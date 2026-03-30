"""
Tests for content_watermarker.py.

Run with:
    python3 -m pytest tests/test_content_watermarker.py -v

All heavy dependencies (videoseal, torch, torchvision) are mocked — no GPU
or installed model is required.
"""

import os
import sys
import types
from dataclasses import fields
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Helpers — build mock videoseal/torch/torchvision stubs
# ---------------------------------------------------------------------------

def _make_torch_mock():
    """Return a minimal torch mock that satisfies the module's needs."""
    mock_torch = MagicMock(name="torch")

    # Tensor-like mock returned by permute/float/clamp/byte
    tensor = MagicMock(name="Tensor")
    tensor.permute.return_value = tensor
    tensor.float.return_value = tensor
    tensor.clamp.return_value = tensor
    tensor.byte.return_value = tensor
    mock_torch.Tensor = MagicMock(return_value=tensor)
    return mock_torch, tensor


def _make_torchvision_mock(frames_tensor=None):
    """Return a minimal torchvision mock."""
    mock_tv = MagicMock(name="torchvision")
    if frames_tensor is None:
        frames_tensor = MagicMock(name="frames")
        frames_tensor.permute.return_value = frames_tensor
        frames_tensor.float.return_value = frames_tensor
        frames_tensor.clamp.return_value = frames_tensor
        frames_tensor.byte.return_value = frames_tensor

    audio = MagicMock(name="audio")
    info = {"video_fps": 30}

    mock_tv.io.read_video.return_value = (frames_tensor, audio, info)
    mock_tv.io.write_video.return_value = None
    return mock_tv, frames_tensor


def _make_videoseal_mock(detected=True, message="MPV2test", confidence=0.95):
    """Return a minimal videoseal mock."""
    mock_vs = MagicMock(name="videoseal")
    model = MagicMock(name="model")

    # embed returns a tensor
    embedded_tensor = MagicMock(name="wm_tensor")
    embedded_tensor.clamp.return_value = embedded_tensor
    embedded_tensor.byte.return_value = embedded_tensor
    embedded_tensor.permute.return_value = embedded_tensor
    model.embed.return_value = embedded_tensor

    # detect returns a dict
    model.detect.return_value = {
        "detected": detected,
        "message": message,
        "confidence": confidence,
    }

    mock_vs.load.return_value = model
    return mock_vs, model


def _dummy_video(path):
    """Write a 100-byte dummy file at *path* to simulate a video file."""
    with open(path, "wb") as fh:
        fh.write(b"\x00" * 100)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_module_cache(monkeypatch):
    """
    Re-import content_watermarker fresh for each test so module-level
    availability flags reflect whatever mocks are active.
    """
    # Remove cached module so each test gets a fresh import
    for mod_name in list(sys.modules.keys()):
        if "content_watermarker" in mod_name:
            del sys.modules[mod_name]
    yield
    for mod_name in list(sys.modules.keys()):
        if "content_watermarker" in mod_name:
            del sys.modules[mod_name]


@pytest.fixture()
def dummy_mp4(tmp_path):
    """A real file on disk with .mp4 extension."""
    p = tmp_path / "clip.mp4"
    _dummy_video(str(p))
    return str(p)


@pytest.fixture()
def mocked_deps(monkeypatch):
    """
    Inject mock videoseal, torch, torchvision into sys.modules so that
    content_watermarker imports them successfully.
    Returns (videoseal_mock, model_mock, torchvision_mock, torch_mock).
    """
    mock_torch, _ = _make_torch_mock()
    mock_tv, frames = _make_torchvision_mock()
    mock_vs, model = _make_videoseal_mock()

    monkeypatch.setitem(sys.modules, "videoseal", mock_vs)
    monkeypatch.setitem(sys.modules, "torch", mock_torch)
    monkeypatch.setitem(sys.modules, "torchvision", mock_tv)

    return mock_vs, model, mock_tv, mock_torch


# ---------------------------------------------------------------------------
# 1. WatermarkResult dataclass
# ---------------------------------------------------------------------------

class TestWatermarkResultDataclass:
    def _import(self):
        import content_watermarker as cw
        return cw.WatermarkResult

    def test_default_values(self):
        WatermarkResult = self._import()
        r = WatermarkResult()
        assert r.embedded is False
        assert r.detected is False
        assert r.message == ""
        assert r.strength == 0.2
        assert r.file_path == ""
        assert r.confidence == 0.0
        assert r.error == ""

    def test_all_fields_settable(self):
        WatermarkResult = self._import()
        r = WatermarkResult(
            embedded=True,
            detected=True,
            message="hello",
            strength=0.5,
            file_path="/tmp/x.mp4",
            confidence=0.99,
            error="",
        )
        assert r.embedded is True
        assert r.detected is True
        assert r.message == "hello"
        assert r.strength == 0.5
        assert r.file_path == "/tmp/x.mp4"
        assert r.confidence == 0.99
        assert r.error == ""

    def test_field_count(self):
        WatermarkResult = self._import()
        assert len(fields(WatermarkResult)) == 7

    def test_error_field_non_empty(self):
        WatermarkResult = self._import()
        r = WatermarkResult(error="something went wrong")
        assert r.error == "something went wrong"

    def test_embedded_false_detected_true(self):
        """detected=True without embedded=True is valid (detect operation)."""
        WatermarkResult = self._import()
        r = WatermarkResult(detected=True, message="MPV2", confidence=0.8)
        assert r.detected is True
        assert r.embedded is False

    def test_confidence_boundary_zero(self):
        WatermarkResult = self._import()
        r = WatermarkResult(confidence=0.0)
        assert r.confidence == 0.0

    def test_confidence_boundary_one(self):
        WatermarkResult = self._import()
        r = WatermarkResult(confidence=1.0)
        assert r.confidence == 1.0

    def test_strength_stored_as_float(self):
        WatermarkResult = self._import()
        r = WatermarkResult(strength=0.3)
        assert isinstance(r.strength, float)


# ---------------------------------------------------------------------------
# 2. ContentWatermarker.__init__
# ---------------------------------------------------------------------------

class TestContentWatermarkerInit:
    def _make(self, **kw):
        import content_watermarker as cw
        return cw.ContentWatermarker(**kw)

    def test_default_strength(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make()
        assert wm.strength == 0.2

    def test_default_prefix(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make()
        assert wm.message_prefix == "MPV2"

    def test_custom_strength_constructor(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make(strength=0.7)
        assert wm.strength == 0.7

    def test_custom_prefix_constructor(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make(message_prefix="TEST")
        assert wm.message_prefix == "TEST"

    def test_config_overrides_strength(self):
        def fake_get(key, default=None):
            if key == "watermark.strength":
                return 0.9
            return default
        with patch("content_watermarker._get", side_effect=fake_get):
            wm = self._make(strength=0.2)
        assert wm.strength == 0.9

    def test_config_overrides_prefix(self):
        def fake_get(key, default=None):
            if key == "watermark.message_prefix":
                return "ACME"
            return default
        with patch("content_watermarker._get", side_effect=fake_get):
            wm = self._make()
        assert wm.message_prefix == "ACME"

    def test_strength_clamped_below_min(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make(strength=0.001)
        assert wm.strength == 0.05

    def test_strength_clamped_above_max(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make(strength=5.0)
        assert wm.strength == 1.0

    def test_strength_at_min_boundary(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make(strength=0.05)
        assert wm.strength == 0.05

    def test_strength_at_max_boundary(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make(strength=1.0)
        assert wm.strength == 1.0

    def test_model_is_none_on_init(self):
        with patch("content_watermarker._get", return_value=None):
            wm = self._make()
        assert wm._model is None

    def test_invalid_config_strength_falls_back(self):
        """Non-numeric config value for strength should log warning and use constructor default."""
        def fake_get(key, default=None):
            if key == "watermark.strength":
                return "not-a-number"
            return default
        with patch("content_watermarker._get", side_effect=fake_get):
            wm = self._make(strength=0.3)
        # Falls back to constructor arg, clamped
        assert wm.strength == 0.3

    def test_non_string_config_prefix_ignored(self):
        """Non-string config prefix should not override constructor value."""
        def fake_get(key, default=None):
            if key == "watermark.message_prefix":
                return 12345
            return default
        with patch("content_watermarker._get", side_effect=fake_get):
            wm = self._make(message_prefix="MPV2")
        assert wm.message_prefix == "MPV2"


# ---------------------------------------------------------------------------
# 3. embed() — happy path
# ---------------------------------------------------------------------------

class TestEmbedHappyPath:
    def _wm(self, deps, **kw):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            return cw.ContentWatermarker(**kw)

    def test_embed_returns_watermark_result(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="test", output_path=out)
        assert isinstance(result, cw.WatermarkResult)

    def test_embed_sets_embedded_true(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="test", output_path=out)
        assert result.embedded is True

    def test_embed_sets_file_path_to_output(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="test", output_path=out)
        assert result.file_path == out

    def test_embed_error_is_empty_on_success(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="test", output_path=out)
        assert result.error == ""

    def test_embed_message_includes_prefix(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker(message_prefix="PFX")
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="batch1", output_path=out)
        assert result.message == "PFXbatch1"

    def test_embed_auto_output_path(self, mocked_deps, dummy_mp4):
        """When output_path is empty, output gets _wm suffix."""
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        result = wm.embed(dummy_mp4, message="x")
        base, ext = os.path.splitext(dummy_mp4)
        assert result.file_path == base + "_wm" + ext

    def test_embed_strength_in_result(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker(strength=0.6)
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="x", output_path=out)
        assert result.strength == 0.6

    def test_embed_calls_read_video(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        wm.embed(dummy_mp4, message="x", output_path=out)
        mock_tv.io.read_video.assert_called_once_with(dummy_mp4, pts_unit="sec")

    def test_embed_calls_write_video(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        wm.embed(dummy_mp4, message="x", output_path=out)
        assert mock_tv.io.write_video.called

    def test_embed_calls_model_embed(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        wm.embed(dummy_mp4, message="x", output_path=out)
        assert model.embed.called

    def test_embed_with_empty_message(self, mocked_deps, dummy_mp4, tmp_path):
        """Empty message string is valid — only prefix is embedded."""
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker(message_prefix="MPV2")
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="", output_path=out)
        assert result.embedded is True
        assert result.message == "MPV2"

    def test_embed_avi_format(self, mocked_deps, tmp_path):
        """AVI files should be supported."""
        import content_watermarker as cw
        p = tmp_path / "clip.avi"
        _dummy_video(str(p))
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.avi")
        result = wm.embed(str(p), message="x", output_path=out)
        assert result.embedded is True


# ---------------------------------------------------------------------------
# 4. embed() — validation errors
# ---------------------------------------------------------------------------

class TestEmbedValidationErrors:
    def _wm(self):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            return cw.ContentWatermarker()

    def test_missing_file(self, mocked_deps, tmp_path):
        wm = self._wm()
        result = wm.embed(str(tmp_path / "nonexistent.mp4"), message="x")
        assert result.embedded is False
        assert "not found" in result.error.lower() or "not exist" in result.error.lower() or result.error != ""

    def test_null_bytes_in_path(self, mocked_deps, tmp_path):
        wm = self._wm()
        result = wm.embed("/tmp/vid\x00.mp4", message="x")
        assert result.embedded is False
        assert result.error != ""

    def test_path_too_long(self, mocked_deps, tmp_path):
        wm = self._wm()
        long_path = "/tmp/" + "a" * 1020 + ".mp4"
        result = wm.embed(long_path, message="x")
        assert result.embedded is False
        assert "length" in result.error.lower() or result.error != ""

    def test_unsupported_format(self, mocked_deps, tmp_path):
        wm = self._wm()
        p = tmp_path / "clip.xyz"
        _dummy_video(str(p))
        result = wm.embed(str(p), message="x")
        assert result.embedded is False
        assert result.error != ""

    def test_oversized_message(self, mocked_deps, dummy_mp4, tmp_path):
        """Message that exceeds 32 bytes after UTF-8 + prefix encoding."""
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            # Use empty prefix so message alone exceeds limit
            wm = cw.ContentWatermarker(message_prefix="")
        # 33 ASCII bytes > 32 limit
        big_msg = "x" * 33
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message=big_msg, output_path=out)
        assert result.embedded is False
        assert "bytes" in result.error.lower() or result.error != ""

    def test_path_exactly_1024_chars_fails_if_no_file(self, mocked_deps, tmp_path):
        """Path at exactly 1024 chars is valid length-wise but file won't exist."""
        wm = self._wm()
        # build a path of exactly 1024 chars ending in .mp4
        path_1024 = "/tmp/" + "a" * (1024 - len("/tmp/") - len(".mp4")) + ".mp4"
        assert len(path_1024) == 1024
        result = wm.embed(path_1024, message="x")
        assert result.embedded is False
        # Should fail on file-not-found, not on length
        assert "length" not in result.error.lower()

    def test_path_over_1024_chars(self, mocked_deps):
        """Path over 1024 chars should fail with length error."""
        wm = self._wm()
        path = "/tmp/" + "a" * 1020 + ".mp4"
        assert len(path) > 1024
        result = wm.embed(path, message="x")
        assert result.embedded is False

    def test_mkv_format_supported(self, mocked_deps, tmp_path):
        """MKV extension is in _SUPPORTED_FORMATS."""
        import content_watermarker as cw
        p = tmp_path / "clip.mkv"
        _dummy_video(str(p))
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        result = wm.embed(str(p), message="x")
        assert result.embedded is True

    def test_webm_format_supported(self, mocked_deps, tmp_path):
        import content_watermarker as cw
        p = tmp_path / "clip.webm"
        _dummy_video(str(p))
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        result = wm.embed(str(p), message="x")
        assert result.embedded is True

    def test_mov_format_supported(self, mocked_deps, tmp_path):
        import content_watermarker as cw
        p = tmp_path / "clip.mov"
        _dummy_video(str(p))
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        result = wm.embed(str(p), message="x")
        assert result.embedded is True


# ---------------------------------------------------------------------------
# 5. embed() — videoseal not installed
# ---------------------------------------------------------------------------

class TestEmbedNoDependency:
    def test_embed_raises_runtime_error_no_videoseal(self, tmp_path):
        """When videoseal is not installed, embed() raises RuntimeError."""
        # Ensure clean import without videoseal
        for mod in list(sys.modules.keys()):
            if "content_watermarker" in mod:
                del sys.modules[mod]

        # Do NOT inject videoseal into sys.modules
        import content_watermarker as cw
        assert not cw._VIDEOSEAL_AVAILABLE

        p = tmp_path / "clip.mp4"
        _dummy_video(str(p))
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        with pytest.raises(RuntimeError, match="videoseal"):
            wm.embed(str(p), message="x")

    def test_detect_raises_runtime_error_no_videoseal(self, tmp_path):
        """When videoseal is not installed, detect() raises RuntimeError."""
        for mod in list(sys.modules.keys()):
            if "content_watermarker" in mod:
                del sys.modules[mod]

        import content_watermarker as cw
        p = tmp_path / "clip.mp4"
        _dummy_video(str(p))
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        with pytest.raises(RuntimeError, match="videoseal"):
            wm.detect(str(p))


# ---------------------------------------------------------------------------
# 6. embed() — model load failure, embed failure
# ---------------------------------------------------------------------------

class TestEmbedFailures:
    def test_model_load_failure_returns_error_result(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        mock_vs.load.side_effect = RuntimeError("model not available")
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="x", output_path=out)
        assert result.embedded is False
        assert result.error != ""

    def test_embed_exception_returns_error_result(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        model.embed.side_effect = RuntimeError("CUDA OOM")
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="x", output_path=out)
        assert result.embedded is False
        assert "Embed failed" in result.error or result.error != ""

    def test_write_video_failure_returns_error_result(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        mock_tv.io.write_video.side_effect = IOError("disk full")
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="x", output_path=out)
        assert result.embedded is False
        assert result.error != ""

    def test_read_video_failure_returns_error_result(self, mocked_deps, dummy_mp4, tmp_path):
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        mock_tv.io.read_video.side_effect = IOError("codec error")
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out = str(tmp_path / "out.mp4")
        result = wm.embed(dummy_mp4, message="x", output_path=out)
        assert result.embedded is False
        assert "Video read failed" in result.error or result.error != ""


# ---------------------------------------------------------------------------
# 7. detect() — happy path, detection failure, no watermark found
# ---------------------------------------------------------------------------

class TestDetectHappyPath:
    def _wm(self):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            return cw.ContentWatermarker()

    def test_detect_returns_watermark_result(self, mocked_deps, dummy_mp4):
        import content_watermarker as cw
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert isinstance(result, cw.WatermarkResult)

    def test_detect_true_when_model_says_detected(self, mocked_deps, dummy_mp4):
        mock_vs, model, mock_tv, _ = mocked_deps
        model.detect.return_value = {"detected": True, "message": "MPV2hello", "confidence": 0.92}
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.detected is True

    def test_detect_message_populated(self, mocked_deps, dummy_mp4):
        mock_vs, model, mock_tv, _ = mocked_deps
        model.detect.return_value = {"detected": True, "message": "MPV2-abc", "confidence": 0.8}
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.message == "MPV2-abc"

    def test_detect_confidence_populated(self, mocked_deps, dummy_mp4):
        mock_vs, model, mock_tv, _ = mocked_deps
        model.detect.return_value = {"detected": True, "message": "X", "confidence": 0.75}
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.confidence == 0.75

    def test_detect_false_when_no_watermark(self, mocked_deps, dummy_mp4):
        mock_vs, model, mock_tv, _ = mocked_deps
        model.detect.return_value = {"detected": False, "message": "", "confidence": 0.0}
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.detected is False

    def test_detect_file_path_preserved(self, mocked_deps, dummy_mp4):
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.file_path == dummy_mp4

    def test_detect_no_error_on_success(self, mocked_deps, dummy_mp4):
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.error == ""

    def test_detect_model_exception_returns_error(self, mocked_deps, dummy_mp4):
        mock_vs, model, mock_tv, _ = mocked_deps
        model.detect.side_effect = RuntimeError("GPU error")
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.detected is False
        assert result.error != ""

    def test_detect_model_load_failure(self, mocked_deps, dummy_mp4):
        mock_vs, model, mock_tv, _ = mocked_deps
        mock_vs.load.side_effect = RuntimeError("weights missing")
        with patch("content_watermarker._get", return_value=None):
            import content_watermarker as cw
            wm = cw.ContentWatermarker()
        result = wm.detect(dummy_mp4)
        assert result.detected is False
        assert result.error != ""

    def test_detect_read_video_failure(self, mocked_deps, dummy_mp4):
        mock_vs, model, mock_tv, _ = mocked_deps
        mock_tv.io.read_video.side_effect = IOError("codec not found")
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.detected is False
        assert result.error != ""

    def test_detect_missing_confidence_key(self, mocked_deps, dummy_mp4):
        """If detect dict lacks 'confidence', defaults correctly."""
        mock_vs, model, mock_tv, _ = mocked_deps
        model.detect.return_value = {"detected": True, "message": "MPV2"}
        wm = self._wm()
        result = wm.detect(dummy_mp4)
        assert result.detected is True
        assert result.confidence == 1.0  # default when detected=True and key missing


# ---------------------------------------------------------------------------
# 8. detect() — validation errors
# ---------------------------------------------------------------------------

class TestDetectValidationErrors:
    def _wm(self):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            return cw.ContentWatermarker()

    def test_missing_file(self, mocked_deps, tmp_path):
        wm = self._wm()
        result = wm.detect(str(tmp_path / "ghost.mp4"))
        assert result.detected is False
        assert result.error != ""

    def test_null_bytes_in_path(self, mocked_deps):
        wm = self._wm()
        result = wm.detect("/tmp/vid\x00.mp4")
        assert result.detected is False
        assert result.error != ""

    def test_unsupported_format(self, mocked_deps, tmp_path):
        wm = self._wm()
        p = tmp_path / "clip.txt"
        _dummy_video(str(p))
        result = wm.detect(str(p))
        assert result.detected is False
        assert result.error != ""

    def test_path_too_long(self, mocked_deps):
        wm = self._wm()
        long_path = "/tmp/" + "b" * 1020 + ".mp4"
        result = wm.detect(long_path)
        assert result.detected is False
        assert result.error != ""


# ---------------------------------------------------------------------------
# 9. _validate_path() — edge cases
# ---------------------------------------------------------------------------

class TestValidatePath:
    def _wm(self):
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            return cw.ContentWatermarker()

    def test_valid_mp4_existing(self, mocked_deps, dummy_mp4):
        wm = self._wm()
        # Should not raise
        wm._validate_path(dummy_mp4)

    def test_raises_for_missing_file(self, mocked_deps, tmp_path):
        wm = self._wm()
        with pytest.raises(FileNotFoundError):
            wm._validate_path(str(tmp_path / "nope.mp4"))

    def test_raises_for_null_bytes(self, mocked_deps):
        wm = self._wm()
        with pytest.raises(ValueError, match="null bytes"):
            wm._validate_path("/tmp/vid\x00.mp4")

    def test_raises_for_unsupported_ext(self, mocked_deps, tmp_path):
        wm = self._wm()
        p = tmp_path / "file.doc"
        _dummy_video(str(p))
        with pytest.raises(ValueError, match="[Uu]nsupported"):
            wm._validate_path(str(p))

    def test_raises_for_path_too_long(self, mocked_deps):
        wm = self._wm()
        long_path = "/tmp/" + "c" * 1020 + ".mp4"
        with pytest.raises(ValueError, match="[Ll]ength"):
            wm._validate_path(long_path)

    def test_no_extension(self, mocked_deps, tmp_path):
        wm = self._wm()
        p = tmp_path / "noext"
        _dummy_video(str(p))
        with pytest.raises(ValueError):
            wm._validate_path(str(p))

    def test_uppercase_extension(self, mocked_deps, tmp_path):
        """Extension matching should be case-insensitive."""
        wm = self._wm()
        p = tmp_path / "clip.MP4"
        _dummy_video(str(p))
        # Should not raise (ext lowercased internally)
        wm._validate_path(str(p))

    def test_raises_for_non_string_path(self, mocked_deps):
        wm = self._wm()
        with pytest.raises((ValueError, AttributeError)):
            wm._validate_path(123)  # type: ignore

    def test_path_exactly_1024_valid_length(self, mocked_deps, tmp_path):
        """Path of exactly 1024 chars passes length check (may fail on OS filename limit)."""
        import content_watermarker as cw
        wm = self._wm()
        # Build a path of exactly 1024 chars.  On macOS the per-component filename
        # limit is 255 bytes so we can't actually create such a file on disk.
        # We verify only that the length check itself doesn't trigger (ValueError
        # about "length" is not raised); the FileNotFoundError from the missing
        # file is acceptable here.
        path_1024 = "/tmp/" + "a" * (1024 - len("/tmp/") - len(".mp4")) + ".mp4"
        assert len(path_1024) == 1024
        try:
            wm._validate_path(path_1024)
        except FileNotFoundError:
            pass  # expected — file doesn't exist, but length check passed
        except ValueError as exc:
            assert "length" not in str(exc).lower(), (
                f"Unexpected length error for 1024-char path: {exc}"
            )


# ---------------------------------------------------------------------------
# 10. _load_model() — singleton behaviour, cache
# ---------------------------------------------------------------------------

class TestLoadModel:
    def test_loads_model_once(self, mocked_deps):
        """_load_model() is called twice but videoseal.load() fires once."""
        import content_watermarker as cw
        mock_vs, model, _, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        wm._load_model()
        wm._load_model()
        mock_vs.load.assert_called_once()

    def test_model_cached_after_first_load(self, mocked_deps):
        import content_watermarker as cw
        mock_vs, model, _, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        assert wm._model is None
        wm._load_model()
        assert wm._model is not None

    def test_model_eval_called(self, mocked_deps):
        """model.eval() must be called after loading."""
        import content_watermarker as cw
        mock_vs, model, _, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        wm._load_model()
        model.eval.assert_called_once()

    def test_load_uses_config_model_name(self, mocked_deps):
        import content_watermarker as cw
        mock_vs, model, _, _ = mocked_deps

        def fake_get(key, default=None):
            if key == "watermark.model":
                return "custom_model"
            return default

        with patch("content_watermarker._get", side_effect=fake_get):
            wm = cw.ContentWatermarker()
            wm._load_model()
        mock_vs.load.assert_called_once_with("custom_model")

    def test_load_model_raises_when_no_videoseal(self, tmp_path):
        """_load_model() raises RuntimeError when videoseal not available."""
        for mod in list(sys.modules.keys()):
            if "content_watermarker" in mod:
                del sys.modules[mod]

        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        with pytest.raises(RuntimeError):
            wm._load_model()

    def test_second_embed_reuses_cached_model(self, mocked_deps, dummy_mp4, tmp_path):
        """Second embed() call reuses the model; load() called only once."""
        import content_watermarker as cw
        mock_vs, model, mock_tv, _ = mocked_deps
        with patch("content_watermarker._get", return_value=None):
            wm = cw.ContentWatermarker()
        out1 = str(tmp_path / "out1.mp4")
        out2 = str(tmp_path / "out2.mp4")
        wm.embed(dummy_mp4, message="a", output_path=out1)
        wm.embed(dummy_mp4, message="b", output_path=out2)
        mock_vs.load.assert_called_once()


# ---------------------------------------------------------------------------
# 11. Config integration
# ---------------------------------------------------------------------------

class TestConfigIntegration:
    def test_reads_watermark_strength_from_config(self, mocked_deps):
        import content_watermarker as cw
        calls = []

        def fake_get(key, default=None):
            calls.append(key)
            if key == "watermark.strength":
                return 0.55
            return default

        with patch("content_watermarker._get", side_effect=fake_get):
            wm = cw.ContentWatermarker()
        assert "watermark.strength" in calls
        assert wm.strength == 0.55

    def test_reads_watermark_prefix_from_config(self, mocked_deps):
        import content_watermarker as cw

        def fake_get(key, default=None):
            if key == "watermark.message_prefix":
                return "CUSTOM"
            return default

        with patch("content_watermarker._get", side_effect=fake_get):
            wm = cw.ContentWatermarker()
        assert wm.message_prefix == "CUSTOM"

    def test_reads_watermark_model_from_config(self, mocked_deps):
        import content_watermarker as cw
        mock_vs, model, _, _ = mocked_deps

        def fake_get(key, default=None):
            if key == "watermark.model":
                return "my_model_v2"
            return default

        with patch("content_watermarker._get", side_effect=fake_get):
            wm = cw.ContentWatermarker()
            wm._load_model()
        mock_vs.load.assert_called_with("my_model_v2")

    def test_watermark_enabled_config_exists(self, mocked_deps):
        """Config key 'watermark.enabled' is accessible (though not enforced in class)."""
        import content_watermarker as cw
        with patch("content_watermarker._get", return_value=None):
            # Just ensuring the module reads config without crashing
            wm = cw.ContentWatermarker()
        assert wm is not None


# ---------------------------------------------------------------------------
# 12. Strength clamping
# ---------------------------------------------------------------------------

class TestStrengthClamping:
    def _clamp(self, v):
        import content_watermarker as cw
        return cw.ContentWatermarker._clamp_strength(v)

    def test_below_min(self):
        assert self._clamp(0.0) == 0.05

    def test_above_max(self):
        assert self._clamp(2.0) == 1.0

    def test_at_min(self):
        assert self._clamp(0.05) == 0.05

    def test_at_max(self):
        assert self._clamp(1.0) == 1.0

    def test_middle(self):
        assert self._clamp(0.5) == 0.5

    def test_just_below_min(self):
        import content_watermarker as cw
        assert cw.ContentWatermarker._clamp_strength(0.04) == 0.05

    def test_just_above_max(self):
        import content_watermarker as cw
        assert cw.ContentWatermarker._clamp_strength(1.001) == 1.0

    def test_negative(self):
        assert self._clamp(-1.0) == 0.05

    def test_exactly_half(self):
        assert self._clamp(0.5) == 0.5


# ---------------------------------------------------------------------------
# 13. Message encoding
# ---------------------------------------------------------------------------

class TestMessageEncoding:
    def _validate(self, msg):
        import content_watermarker as cw
        cw._validate_message(msg)

    def test_ascii_short_ok(self):
        self._validate("hello")  # 5 bytes, fine

    def test_exactly_32_ascii_bytes(self):
        self._validate("a" * 32)  # exactly at limit

    def test_over_32_ascii_bytes_raises(self):
        import content_watermarker as cw
        with pytest.raises(ValueError, match="bytes"):
            cw._validate_message("a" * 33)

    def test_utf8_multibyte_ok(self):
        # "é" = 2 bytes; 15 chars = 30 bytes — under limit
        self._validate("é" * 15)

    def test_utf8_multibyte_over_limit(self):
        import content_watermarker as cw
        # "é" = 2 bytes each; 17 × 2 = 34 bytes > 32
        with pytest.raises(ValueError):
            cw._validate_message("é" * 17)

    def test_empty_string_ok(self):
        self._validate("")  # 0 bytes, fine

    def test_exactly_32_multibyte(self):
        # 16 × "é" = 32 bytes — exactly at limit
        self._validate("é" * 16)

    def test_unicode_emoji_over_limit(self):
        import content_watermarker as cw
        # "😀" = 4 bytes; 9 × 4 = 36 > 32
        with pytest.raises(ValueError):
            cw._validate_message("😀" * 9)

    def test_unicode_emoji_within_limit(self):
        # "😀" = 4 bytes; 8 × 4 = 32 — at limit
        self._validate("😀" * 8)


# ---------------------------------------------------------------------------
# 14. _auto_output_path helper
# ---------------------------------------------------------------------------

class TestAutoOutputPath:
    def _auto(self, path):
        import content_watermarker as cw
        return cw._auto_output_path(path)

    def test_mp4(self):
        assert self._auto("/tmp/clip.mp4") == "/tmp/clip_wm.mp4"

    def test_avi(self):
        assert self._auto("/tmp/video.avi") == "/tmp/video_wm.avi"

    def test_nested_path(self):
        assert self._auto("/a/b/c/d.mov") == "/a/b/c/d_wm.mov"

    def test_no_directory(self):
        assert self._auto("video.mp4") == "video_wm.mp4"

    def test_dot_in_directory_name(self):
        result = self._auto("/path.to/video.mp4")
        assert result == "/path.to/video_wm.mp4"


# ---------------------------------------------------------------------------
# 15. Module-level availability flags
# ---------------------------------------------------------------------------

class TestAvailabilityFlags:
    def test_videoseal_unavailable_when_not_in_sys_modules(self):
        """Without the videoseal mock, _VIDEOSEAL_AVAILABLE should be False."""
        for mod in list(sys.modules.keys()):
            if "content_watermarker" in mod:
                del sys.modules[mod]
        import content_watermarker as cw
        assert cw._VIDEOSEAL_AVAILABLE is False

    def test_videoseal_available_when_mocked(self, mocked_deps):
        """With the videoseal mock injected, _VIDEOSEAL_AVAILABLE should be True."""
        import content_watermarker as cw
        assert cw._VIDEOSEAL_AVAILABLE is True

    def test_torch_unavailable_when_import_blocked(self, monkeypatch):
        """Simulate torch being unavailable by blocking its import."""
        for mod in list(sys.modules.keys()):
            if "content_watermarker" in mod:
                del sys.modules[mod]

        # Block the torch import so content_watermarker treats it as unavailable
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        import builtins
        original_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("torch blocked for test")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        # Also remove from sys.modules so it re-runs the import
        monkeypatch.delitem(sys.modules, "torch", raising=False)

        import content_watermarker as cw
        assert cw._TORCH_AVAILABLE is False

    def test_torch_available_with_mock(self, mocked_deps):
        import content_watermarker as cw
        assert cw._TORCH_AVAILABLE is True

    def test_torchvision_available_with_mock(self, mocked_deps):
        import content_watermarker as cw
        assert cw._TORCHVISION_AVAILABLE is True


# ---------------------------------------------------------------------------
# 16. Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_max_message_bytes(self):
        import content_watermarker as cw
        assert cw._MAX_MESSAGE_BYTES == 32

    def test_min_strength(self):
        import content_watermarker as cw
        assert cw._MIN_STRENGTH == 0.05

    def test_max_strength(self):
        import content_watermarker as cw
        assert cw._MAX_STRENGTH == 1.0

    def test_default_strength(self):
        import content_watermarker as cw
        assert cw._DEFAULT_STRENGTH == 0.2

    def test_max_path_length(self):
        import content_watermarker as cw
        assert cw._MAX_PATH_LENGTH == 1024

    def test_supported_formats_is_frozenset(self):
        import content_watermarker as cw
        assert isinstance(cw._SUPPORTED_FORMATS, frozenset)

    def test_supported_formats_contents(self):
        import content_watermarker as cw
        assert ".mp4" in cw._SUPPORTED_FORMATS
        assert ".avi" in cw._SUPPORTED_FORMATS
        assert ".mov" in cw._SUPPORTED_FORMATS
        assert ".mkv" in cw._SUPPORTED_FORMATS
        assert ".webm" in cw._SUPPORTED_FORMATS

"""
Unit tests for multi_lang_dubbing module.
"""

import os
import sys
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# TranscriptSegment tests
# ---------------------------------------------------------------------------


class TestTranscriptSegment:
    def setup_method(self):
        from multi_lang_dubbing import TranscriptSegment
        self.cls = TranscriptSegment

    def test_basic_creation(self):
        seg = self.cls(start=0.0, end=1.5, text="Hello world")
        assert seg.start == 0.0
        assert seg.end == 1.5
        assert seg.text == "Hello world"

    def test_to_dict(self):
        seg = self.cls(start=1.0, end=2.0, text="test")
        d = seg.to_dict()
        assert d == {"start": 1.0, "end": 2.0, "text": "test"}

    def test_from_dict_valid(self):
        seg = self.cls.from_dict({"start": 1.0, "end": 3.0, "text": "hola"})
        assert seg.start == 1.0
        assert seg.end == 3.0
        assert seg.text == "hola"

    def test_from_dict_missing_fields(self):
        seg = self.cls.from_dict({})
        assert seg.start == 0
        assert seg.end == 0
        assert seg.text == ""

    def test_from_dict_negative_start(self):
        seg = self.cls.from_dict({"start": -5.0, "end": 2.0, "text": "x"})
        assert seg.start == 0  # clamped

    def test_from_dict_end_before_start(self):
        seg = self.cls.from_dict({"start": 5.0, "end": 2.0, "text": "x"})
        assert seg.end == seg.start  # clamped

    def test_from_dict_text_truncation(self):
        long_text = "A" * 6000
        seg = self.cls.from_dict({"start": 0, "end": 1, "text": long_text})
        assert len(seg.text) == 5000


# ---------------------------------------------------------------------------
# DubResult tests
# ---------------------------------------------------------------------------


class TestDubResult:
    def setup_method(self):
        from multi_lang_dubbing import DubResult
        self.cls = DubResult

    def test_basic_creation(self):
        r = self.cls(
            source_path="/video.mp4",
            target_lang="es",
            output_path="/out.mp4",
            success=True,
        )
        assert r.success is True
        assert r.target_lang == "es"
        assert r.created_at  # auto-populated

    def test_to_dict(self):
        r = self.cls(
            source_path="/a.mp4",
            target_lang="fr",
            output_path="/b.mp4",
            success=False,
            error="TestErr",
        )
        d = r.to_dict()
        assert d["source_path"] == "/a.mp4"
        assert d["error"] == "TestErr"

    def test_from_dict_truncation(self):
        r = self.cls.from_dict({
            "source_path": "X" * 1000,
            "target_lang": "es",
            "output_path": "Y" * 1000,
            "success": True,
            "error": "E" * 1000,
        })
        assert len(r.source_path) == 500
        assert len(r.output_path) == 500
        assert len(r.error) == 500

    def test_from_dict_duration_cap(self):
        r = self.cls.from_dict({"duration_seconds": 99999})
        assert r.duration_seconds == 600  # _MAX_VIDEO_DURATION


# ---------------------------------------------------------------------------
# VideoDubber __init__ tests
# ---------------------------------------------------------------------------


class TestVideoDubberInit:
    def test_default_init(self):
        from multi_lang_dubbing import VideoDubber
        d = VideoDubber()
        assert d.stt_backend == "faster_whisper"
        assert d.tts_backend == "kittentts"
        assert d.enable_lip_sync is False

    def test_custom_init(self):
        from multi_lang_dubbing import VideoDubber
        d = VideoDubber(stt_backend="assemblyai", tts_backend="edge_tts", enable_lip_sync=True)
        assert d.stt_backend == "assemblyai"
        assert d.tts_backend == "edge_tts"
        assert d.enable_lip_sync is True

    def test_invalid_stt_backend(self):
        from multi_lang_dubbing import VideoDubber
        with pytest.raises(ValueError, match="Unsupported STT backend"):
            VideoDubber(stt_backend="invalid")

    def test_invalid_tts_backend(self):
        from multi_lang_dubbing import VideoDubber
        with pytest.raises(ValueError, match="Unsupported TTS backend"):
            VideoDubber(tts_backend="invalid")


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    def setup_method(self):
        from multi_lang_dubbing import VideoDubber
        self.dubber = VideoDubber()

    def test_validate_language_valid(self):
        assert self.dubber._validate_language("es") == "es"
        assert self.dubber._validate_language("  FR  ") == "fr"
        assert self.dubber._validate_language("JA") == "ja"

    def test_validate_language_invalid(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            self.dubber._validate_language("xx")

    def test_validate_language_empty(self):
        with pytest.raises(ValueError, match="non-empty string"):
            self.dubber._validate_language("")

    def test_validate_language_none(self):
        with pytest.raises(ValueError, match="non-empty string"):
            self.dubber._validate_language(None)

    def test_validate_video_path_null_bytes(self):
        with pytest.raises(ValueError, match="null bytes"):
            self.dubber._validate_video_path("/video\x00.mp4")

    def test_validate_video_path_empty(self):
        with pytest.raises(ValueError, match="non-empty"):
            self.dubber._validate_video_path("")

    def test_validate_video_path_wrong_ext(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a video")
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported video format"):
                self.dubber._validate_video_path(path)
        finally:
            os.unlink(path)

    def test_validate_video_path_mp4(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake video")
            path = f.name
        try:
            result = self.dubber._validate_video_path(path)
            assert result == os.path.normpath(os.path.abspath(path))
        finally:
            os.unlink(path)

    def test_validate_video_path_mov(self):
        with tempfile.NamedTemporaryFile(suffix=".mov", delete=False) as f:
            f.write(b"fake video")
            path = f.name
        try:
            result = self.dubber._validate_video_path(path)
            assert result.endswith(".mov")
        finally:
            os.unlink(path)

    def test_validate_output_dir_creates_dir(self):
        with tempfile.TemporaryDirectory() as td:
            new_dir = os.path.join(td, "subdir")
            result = self.dubber._validate_output_dir(new_dir)
            assert os.path.isdir(result)

    def test_validate_output_dir_null_bytes(self):
        with pytest.raises(ValueError, match="null bytes"):
            self.dubber._validate_output_dir("/out\x00dir")

    def test_validate_output_dir_empty(self):
        with pytest.raises(ValueError, match="non-empty"):
            self.dubber._validate_output_dir("")

    def test_validate_output_dir_too_long(self):
        with pytest.raises(ValueError, match="too long"):
            self.dubber._validate_output_dir("/" + "a" * 600)


# ---------------------------------------------------------------------------
# get_supported_languages test
# ---------------------------------------------------------------------------


class TestSupportedLanguages:
    def test_returns_dict(self):
        from multi_lang_dubbing import VideoDubber
        d = VideoDubber()
        langs = d.get_supported_languages()
        assert isinstance(langs, dict)
        assert "en" in langs
        assert langs["es"] == "Spanish"
        assert len(langs) == 18


# ---------------------------------------------------------------------------
# _parse_translation_response tests
# ---------------------------------------------------------------------------


class TestParseTranslation:
    def setup_method(self):
        from multi_lang_dubbing import VideoDubber, TranscriptSegment
        self.dubber = VideoDubber()
        self.seg_cls = TranscriptSegment

    def test_valid_response(self):
        originals = [
            self.seg_cls(0, 1, "Hello"),
            self.seg_cls(1, 2, "World"),
        ]
        response = "[0] Hola\n[1] Mundo"
        result = self.dubber._parse_translation_response(response, originals)
        assert result[0].text == "Hola"
        assert result[1].text == "Mundo"
        assert result[0].start == 0
        assert result[1].end == 2

    def test_partial_response_fallback(self):
        originals = [
            self.seg_cls(0, 1, "Hello"),
            self.seg_cls(1, 2, "World"),
        ]
        response = "[0] Hola"
        result = self.dubber._parse_translation_response(response, originals)
        assert result[0].text == "Hola"
        assert result[1].text == "World"  # fallback

    def test_empty_response_fallback(self):
        originals = [self.seg_cls(0, 1, "Hello")]
        result = self.dubber._parse_translation_response("", originals)
        assert result[0].text == "Hello"

    def test_out_of_range_index_ignored(self):
        originals = [self.seg_cls(0, 1, "Hello")]
        response = "[0] Hola\n[5] Extra"
        result = self.dubber._parse_translation_response(response, originals)
        assert len(result) == 1
        assert result[0].text == "Hola"

    def test_translation_text_truncated(self):
        originals = [self.seg_cls(0, 1, "Hello")]
        response = f"[0] {'X' * 6000}"
        result = self.dubber._parse_translation_response(response, originals)
        assert len(result[0].text) == 5000


# ---------------------------------------------------------------------------
# _build_output_filename tests
# ---------------------------------------------------------------------------


class TestBuildOutputFilename:
    def test_basic(self):
        from multi_lang_dubbing import VideoDubber
        name = VideoDubber._build_output_filename("/path/to/video.mp4", "es")
        assert name == "video_es.mp4"

    def test_special_chars_sanitized(self):
        from multi_lang_dubbing import VideoDubber
        name = VideoDubber._build_output_filename("/path/to/my video (1).mp4", "fr")
        assert "my_video__1_" in name
        assert name.endswith("_fr.mp4")

    def test_long_name_truncated(self):
        from multi_lang_dubbing import VideoDubber
        long_name = "A" * 200 + ".mp4"
        name = VideoDubber._build_output_filename(f"/path/{long_name}", "de")
        assert len(name) <= 110  # 100 + _XX.mp4


# ---------------------------------------------------------------------------
# dub() integration tests (mocked pipeline)
# ---------------------------------------------------------------------------


class TestDub:
    def setup_method(self):
        from multi_lang_dubbing import VideoDubber
        self.dubber = VideoDubber()

    def test_same_language_noop(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake")
            path = f.name
        try:
            result = self.dubber.dub(path, "en", tempfile.gettempdir(), source_lang="en")
            assert result.success is True
            assert "same" in result.error.lower()
        finally:
            os.unlink(path)

    @patch("multi_lang_dubbing.VideoDubber._get_duration", return_value=30.0)
    @patch("multi_lang_dubbing.VideoDubber._merge_audio")
    @patch("multi_lang_dubbing.VideoDubber._synthesize_speech", return_value="/tmp/audio.wav")
    @patch("multi_lang_dubbing.VideoDubber._translate_segments")
    @patch("multi_lang_dubbing.VideoDubber._extract_transcript")
    def test_dub_success(self, mock_extract, mock_translate, mock_synth, mock_merge, mock_dur):
        from multi_lang_dubbing import TranscriptSegment
        segs = [TranscriptSegment(0, 1, "Hello")]
        mock_extract.return_value = segs
        mock_translate.return_value = [TranscriptSegment(0, 1, "Hola")]

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake")
            path = f.name
        try:
            result = self.dubber.dub(path, "es", tempfile.gettempdir())
            assert result.success is True
            assert result.target_lang == "es"
            assert result.transcript_segments == 1
            assert result.duration_seconds == 30.0
        finally:
            os.unlink(path)

    @patch("multi_lang_dubbing.VideoDubber._extract_transcript", return_value=[])
    def test_dub_no_speech(self, mock_extract):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake")
            path = f.name
        try:
            result = self.dubber.dub(path, "es", tempfile.gettempdir())
            assert result.success is False
            assert "No speech" in result.error
        finally:
            os.unlink(path)

    @patch("multi_lang_dubbing.VideoDubber._extract_transcript", side_effect=RuntimeError("fail"))
    def test_dub_exception_handled(self, mock_extract):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake")
            path = f.name
        try:
            result = self.dubber.dub(path, "fr", tempfile.gettempdir())
            assert result.success is False
            assert result.error == "RuntimeError"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# batch_dub() tests
# ---------------------------------------------------------------------------


class TestBatchDub:
    def setup_method(self):
        from multi_lang_dubbing import VideoDubber
        self.dubber = VideoDubber()

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="must be a list"):
            self.dubber.batch_dub("/v.mp4", "es", "/out")

    def test_too_many_languages(self):
        from multi_lang_dubbing import _MAX_BATCH_LANGUAGES
        langs = [f"lang{i}" for i in range(_MAX_BATCH_LANGUAGES + 1)]
        with pytest.raises(ValueError, match="Too many languages"):
            self.dubber.batch_dub("/v.mp4", langs, "/out")

    @patch("multi_lang_dubbing.VideoDubber.dub")
    def test_deduplication(self, mock_dub):
        from multi_lang_dubbing import DubResult
        mock_dub.return_value = DubResult(
            source_path="/v.mp4", target_lang="es",
            output_path="/out.mp4", success=True,
        )
        results = self.dubber.batch_dub("/v.mp4", ["es", "es", "ES"], "/out")
        assert len(results) == 1  # deduplicated

    @patch("multi_lang_dubbing.VideoDubber.dub")
    def test_multiple_languages(self, mock_dub):
        from multi_lang_dubbing import DubResult
        mock_dub.return_value = DubResult(
            source_path="/v.mp4", target_lang="es",
            output_path="/out.mp4", success=True,
        )
        results = self.dubber.batch_dub("/v.mp4", ["es", "fr", "de"], "/out")
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Edge TTS voice mapping tests
# ---------------------------------------------------------------------------


class TestEdgeTTSVoice:
    def test_all_supported_languages_have_voice(self):
        from multi_lang_dubbing import _get_edge_tts_voice, _SUPPORTED_LANGUAGES
        for lang in _SUPPORTED_LANGUAGES:
            voice = _get_edge_tts_voice(lang)
            assert voice
            assert "Neural" in voice

    def test_unsupported_language_raises(self):
        from multi_lang_dubbing import _get_edge_tts_voice
        with pytest.raises(ValueError, match="No Edge TTS voice"):
            _get_edge_tts_voice("zz")


# ---------------------------------------------------------------------------
# Config helper tests
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    @patch("multi_lang_dubbing.get_dubbing_config", return_value={})
    def test_enabled_default_false(self, _):
        from multi_lang_dubbing import get_dubbing_enabled
        assert get_dubbing_enabled() is False

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"enabled": True})
    def test_enabled_true(self, _):
        from multi_lang_dubbing import get_dubbing_enabled
        assert get_dubbing_enabled() is True

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={})
    def test_default_languages_fallback(self, _):
        from multi_lang_dubbing import get_dubbing_default_languages
        assert get_dubbing_default_languages() == ["es", "fr", "de"]

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"default_languages": ["ja", "ko"]})
    def test_default_languages_from_config(self, _):
        from multi_lang_dubbing import get_dubbing_default_languages
        assert get_dubbing_default_languages() == ["ja", "ko"]

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"default_languages": ["invalid"]})
    def test_default_languages_invalid_filtered(self, _):
        from multi_lang_dubbing import get_dubbing_default_languages
        result = get_dubbing_default_languages()
        assert result == ["es", "fr", "de"]  # fallback

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"default_languages": "not_a_list"})
    def test_default_languages_wrong_type(self, _):
        from multi_lang_dubbing import get_dubbing_default_languages
        assert get_dubbing_default_languages() == ["es", "fr", "de"]

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={})
    def test_stt_backend_default(self, _):
        from multi_lang_dubbing import get_dubbing_stt_backend
        assert get_dubbing_stt_backend() == "faster_whisper"

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"stt_backend": "assemblyai"})
    def test_stt_backend_assemblyai(self, _):
        from multi_lang_dubbing import get_dubbing_stt_backend
        assert get_dubbing_stt_backend() == "assemblyai"

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"stt_backend": "invalid"})
    def test_stt_backend_invalid_fallback(self, _):
        from multi_lang_dubbing import get_dubbing_stt_backend
        assert get_dubbing_stt_backend() == "faster_whisper"

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={})
    def test_tts_backend_default(self, _):
        from multi_lang_dubbing import get_dubbing_tts_backend
        assert get_dubbing_tts_backend() == "edge_tts"

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"tts_backend": "kittentts"})
    def test_tts_backend_kittentts(self, _):
        from multi_lang_dubbing import get_dubbing_tts_backend
        assert get_dubbing_tts_backend() == "kittentts"

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"tts_backend": "bogus"})
    def test_tts_backend_invalid_fallback(self, _):
        from multi_lang_dubbing import get_dubbing_tts_backend
        assert get_dubbing_tts_backend() == "edge_tts"

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={})
    def test_lip_sync_default_false(self, _):
        from multi_lang_dubbing import get_dubbing_lip_sync_enabled
        assert get_dubbing_lip_sync_enabled() is False

    @patch("multi_lang_dubbing.get_dubbing_config", return_value={"lip_sync": True})
    def test_lip_sync_true(self, _):
        from multi_lang_dubbing import get_dubbing_lip_sync_enabled
        assert get_dubbing_lip_sync_enabled() is True


# ---------------------------------------------------------------------------
# Lip-sync fallback test
# ---------------------------------------------------------------------------


class TestLipSync:
    def test_lip_sync_import_error_fallback(self):
        from multi_lang_dubbing import VideoDubber
        dubber = VideoDubber(enable_lip_sync=True)
        # wav2lip not installed — should warn and return audio_path unchanged
        result = dubber._apply_lip_sync("/video.mp4", "/audio.wav", "/out")
        assert result == "/audio.wav"  # fallback


# ---------------------------------------------------------------------------
# Merge audio test (mocked subprocess)
# ---------------------------------------------------------------------------


class TestMergeAudio:
    @patch("subprocess.run")
    @patch("ffmpeg_utils.check_ffmpeg")
    def test_merge_success(self, mock_ffmpeg, mock_run):
        from multi_lang_dubbing import VideoDubber
        mock_run.return_value = MagicMock(returncode=0)
        VideoDubber._merge_audio("/v.mp4", "/a.wav", "/out.mp4")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "ffmpeg" in args
        assert "-shortest" in args

    @patch("subprocess.run")
    @patch("ffmpeg_utils.check_ffmpeg")
    def test_merge_failure_raises(self, mock_ffmpeg, mock_run):
        from multi_lang_dubbing import VideoDubber
        mock_run.return_value = MagicMock(returncode=1)
        with pytest.raises(RuntimeError, match="merge failed"):
            VideoDubber._merge_audio("/v.mp4", "/a.wav", "/out.mp4")


# ---------------------------------------------------------------------------
# _get_duration test
# ---------------------------------------------------------------------------


class TestGetDuration:
    @patch("ffmpeg_utils.get_video_info")
    def test_returns_duration(self, mock_info):
        from multi_lang_dubbing import VideoDubber
        mock_info.return_value = MagicMock(duration=45.5)
        assert VideoDubber._get_duration("/v.mp4") == 45.5

    @patch("ffmpeg_utils.get_video_info", side_effect=Exception("fail"))
    def test_returns_zero_on_error(self, _):
        from multi_lang_dubbing import VideoDubber
        assert VideoDubber._get_duration("/v.mp4") == 0.0


# ---------------------------------------------------------------------------
# Module constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_supported_languages_count(self):
        from multi_lang_dubbing import _SUPPORTED_LANGUAGES, _LANGUAGE_NAMES
        assert len(_SUPPORTED_LANGUAGES) == 18
        assert len(_LANGUAGE_NAMES) == 18
        assert _SUPPORTED_LANGUAGES == set(_LANGUAGE_NAMES.keys())

    def test_max_constants(self):
        from multi_lang_dubbing import (
            _MAX_TRANSCRIPT_LENGTH,
            _MAX_VIDEO_DURATION,
            _MAX_BATCH_LANGUAGES,
            _MAX_OUTPUT_PATH_LENGTH,
        )
        assert _MAX_TRANSCRIPT_LENGTH == 50_000
        assert _MAX_VIDEO_DURATION == 600
        assert _MAX_BATCH_LANGUAGES == 20
        assert _MAX_OUTPUT_PATH_LENGTH == 500

"""
Tests for export_optimizer.py — Multi-Platform Export Optimizer.

Coverage categories:
  - ExportProfile dataclass: creation, to_dict, from_dict, field defaults
  - ExportOptimizer init and profile management
  - get_profile: all 6 platforms, invalid platform
  - list_profiles: returns all 6 profiles
  - _calculate_crop: mathematical correctness for all aspect ratio conversions
  - optimize_clip: mocked MoviePy, verify crop/resize/write called correctly
  - batch_export: mocked optimize_clip, verify all platforms processed
  - Edge cases: empty platforms list, non-existent source, max_duration trimming
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call, PropertyMock

# ---------------------------------------------------------------------------
# Mock moviepy before importing the module under test so the import-time
# reference inside the lazy-import branches never actually loads MoviePy.
# ---------------------------------------------------------------------------
_mock_moviepy = MagicMock()
sys.modules.setdefault("moviepy", _mock_moviepy)

from export_optimizer import ExportOptimizer, ExportProfile, _SUPPORTED_PLATFORMS


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def optimizer():
    return ExportOptimizer()


# ===========================================================================
# ExportProfile dataclass tests
# ===========================================================================

class TestExportProfileCreation:
    """Tests for ExportProfile dataclass field handling."""

    def test_required_fields(self):
        p = ExportProfile(
            platform="youtube",
            aspect_ratio=(16, 9),
            resolution=(1920, 1080),
            max_duration=None,
        )
        assert p.platform == "youtube"
        assert p.aspect_ratio == (16, 9)
        assert p.resolution == (1920, 1080)
        assert p.max_duration is None

    def test_default_codec(self):
        p = ExportProfile(
            platform="tiktok",
            aspect_ratio=(9, 16),
            resolution=(1080, 1920),
            max_duration=180.0,
        )
        assert p.codec == "libx264"
        assert p.audio_codec == "aac"

    def test_custom_codec(self):
        p = ExportProfile(
            platform="youtube",
            aspect_ratio=(16, 9),
            resolution=(1920, 1080),
            max_duration=None,
            codec="libx265",
            audio_codec="mp3",
        )
        assert p.codec == "libx265"
        assert p.audio_codec == "mp3"

    def test_max_duration_float(self):
        p = ExportProfile(
            platform="youtube_shorts",
            aspect_ratio=(9, 16),
            resolution=(1080, 1920),
            max_duration=60.0,
        )
        assert p.max_duration == 60.0

    def test_square_ratio(self):
        p = ExportProfile(
            platform="instagram_feed",
            aspect_ratio=(1, 1),
            resolution=(1080, 1080),
            max_duration=60.0,
        )
        assert p.aspect_ratio == (1, 1)
        assert p.resolution == (1080, 1080)

    def test_four_five_ratio(self):
        p = ExportProfile(
            platform="instagram_optimized",
            aspect_ratio=(4, 5),
            resolution=(1080, 1350),
            max_duration=60.0,
        )
        assert p.aspect_ratio == (4, 5)


class TestExportProfileToDict:
    """Tests for ExportProfile.to_dict()."""

    def test_to_dict_keys(self):
        p = ExportProfile(
            platform="youtube",
            aspect_ratio=(16, 9),
            resolution=(1920, 1080),
            max_duration=None,
        )
        d = p.to_dict()
        assert set(d.keys()) == {
            "platform", "aspect_ratio", "resolution",
            "max_duration", "codec", "audio_codec",
        }

    def test_to_dict_values(self):
        p = ExportProfile(
            platform="tiktok",
            aspect_ratio=(9, 16),
            resolution=(1080, 1920),
            max_duration=180.0,
        )
        d = p.to_dict()
        assert d["platform"] == "tiktok"
        assert d["aspect_ratio"] == [9, 16]
        assert d["resolution"] == [1080, 1920]
        assert d["max_duration"] == 180.0
        assert d["codec"] == "libx264"
        assert d["audio_codec"] == "aac"

    def test_to_dict_none_max_duration(self):
        p = ExportProfile(
            platform="youtube",
            aspect_ratio=(16, 9),
            resolution=(1920, 1080),
            max_duration=None,
        )
        d = p.to_dict()
        assert d["max_duration"] is None

    def test_to_dict_lists_not_tuples(self):
        p = ExportProfile(
            platform="youtube",
            aspect_ratio=(16, 9),
            resolution=(1920, 1080),
            max_duration=None,
        )
        d = p.to_dict()
        # JSON-serializable: stored as lists
        assert isinstance(d["aspect_ratio"], list)
        assert isinstance(d["resolution"], list)


class TestExportProfileFromDict:
    """Tests for ExportProfile.from_dict() classmethod."""

    def test_from_dict_roundtrip(self):
        p = ExportProfile(
            platform="tiktok",
            aspect_ratio=(9, 16),
            resolution=(1080, 1920),
            max_duration=180.0,
        )
        restored = ExportProfile.from_dict(p.to_dict())
        assert restored.platform == p.platform
        assert restored.aspect_ratio == p.aspect_ratio
        assert restored.resolution == p.resolution
        assert restored.max_duration == p.max_duration
        assert restored.codec == p.codec
        assert restored.audio_codec == p.audio_codec

    def test_from_dict_default_codec(self):
        data = {
            "platform": "youtube",
            "aspect_ratio": [16, 9],
            "resolution": [1920, 1080],
            "max_duration": None,
        }
        p = ExportProfile.from_dict(data)
        assert p.codec == "libx264"
        assert p.audio_codec == "aac"

    def test_from_dict_custom_codec(self):
        data = {
            "platform": "youtube",
            "aspect_ratio": [16, 9],
            "resolution": [1920, 1080],
            "max_duration": None,
            "codec": "libx265",
            "audio_codec": "mp3",
        }
        p = ExportProfile.from_dict(data)
        assert p.codec == "libx265"
        assert p.audio_codec == "mp3"

    def test_from_dict_tuples(self):
        data = {
            "platform": "instagram_feed",
            "aspect_ratio": [1, 1],
            "resolution": [1080, 1080],
            "max_duration": 60.0,
        }
        p = ExportProfile.from_dict(data)
        assert isinstance(p.aspect_ratio, tuple)
        assert isinstance(p.resolution, tuple)


# ===========================================================================
# ExportOptimizer initialization
# ===========================================================================

class TestExportOptimizerInit:
    """Tests for ExportOptimizer constructor."""

    def test_init_creates_instance(self):
        opt = ExportOptimizer()
        assert opt is not None

    def test_init_has_profiles(self):
        opt = ExportOptimizer()
        assert len(opt._profiles) == 6

    def test_init_profiles_independent(self):
        """Two instances should have separate profile dicts (dict-level isolation)."""
        opt1 = ExportOptimizer()
        opt2 = ExportOptimizer()
        # Add a new key to opt1's dict — opt2's dict should be unaffected
        opt1._profiles["__test_key__"] = None
        assert "__test_key__" not in opt2._profiles


# ===========================================================================
# get_profile tests
# ===========================================================================

class TestGetProfile:
    """Tests for ExportOptimizer.get_profile()."""

    def test_youtube(self, optimizer):
        p = optimizer.get_profile("youtube")
        assert p.platform == "youtube"
        assert p.aspect_ratio == (16, 9)
        assert p.resolution == (1920, 1080)
        assert p.max_duration is None

    def test_youtube_shorts(self, optimizer):
        p = optimizer.get_profile("youtube_shorts")
        assert p.platform == "youtube_shorts"
        assert p.aspect_ratio == (9, 16)
        assert p.resolution == (1080, 1920)
        assert p.max_duration == 60.0

    def test_tiktok(self, optimizer):
        p = optimizer.get_profile("tiktok")
        assert p.platform == "tiktok"
        assert p.aspect_ratio == (9, 16)
        assert p.resolution == (1080, 1920)
        assert p.max_duration == 180.0

    def test_instagram_reels(self, optimizer):
        p = optimizer.get_profile("instagram_reels")
        assert p.platform == "instagram_reels"
        assert p.aspect_ratio == (9, 16)
        assert p.resolution == (1080, 1920)
        assert p.max_duration == 90.0

    def test_instagram_feed(self, optimizer):
        p = optimizer.get_profile("instagram_feed")
        assert p.platform == "instagram_feed"
        assert p.aspect_ratio == (1, 1)
        assert p.resolution == (1080, 1080)
        assert p.max_duration == 60.0

    def test_instagram_optimized(self, optimizer):
        p = optimizer.get_profile("instagram_optimized")
        assert p.platform == "instagram_optimized"
        assert p.aspect_ratio == (4, 5)
        assert p.resolution == (1080, 1350)
        assert p.max_duration == 60.0

    def test_invalid_platform_raises(self, optimizer):
        with pytest.raises(ValueError, match="Unsupported platform"):
            optimizer.get_profile("snapchat")

    def test_empty_platform_raises(self, optimizer):
        with pytest.raises(ValueError, match="Unsupported platform"):
            optimizer.get_profile("")

    def test_case_sensitive(self, optimizer):
        with pytest.raises(ValueError):
            optimizer.get_profile("YouTube")


# ===========================================================================
# list_profiles tests
# ===========================================================================

class TestListProfiles:
    """Tests for ExportOptimizer.list_profiles()."""

    def test_returns_list(self, optimizer):
        result = optimizer.list_profiles()
        assert isinstance(result, list)

    def test_returns_six_profiles(self, optimizer):
        result = optimizer.list_profiles()
        assert len(result) == 6

    def test_all_platforms_present(self, optimizer):
        result = optimizer.list_profiles()
        platforms = {p.platform for p in result}
        assert platforms == _SUPPORTED_PLATFORMS

    def test_all_export_profiles(self, optimizer):
        result = optimizer.list_profiles()
        for p in result:
            assert isinstance(p, ExportProfile)

    def test_list_includes_youtube(self, optimizer):
        platforms = [p.platform for p in optimizer.list_profiles()]
        assert "youtube" in platforms

    def test_list_includes_tiktok(self, optimizer):
        platforms = [p.platform for p in optimizer.list_profiles()]
        assert "tiktok" in platforms


# ===========================================================================
# _calculate_crop tests (pure math)
# ===========================================================================

class TestCalculateCrop:
    """Tests for ExportOptimizer._calculate_crop()."""

    # --- landscape → portrait ---

    def test_landscape_to_portrait(self, optimizer):
        """1920×1080 (16:9) source → 9:16 target."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1920, 1080, (9, 16))
        expected_w = int(1080 * 9 / 16)  # 607
        assert new_w == expected_w
        assert new_h == 1080          # height kept
        assert cx == 1920 / 2         # centered horizontally
        assert cy == 1080 / 2

    def test_landscape_to_portrait_crop_dimensions(self, optimizer):
        """Cropped width must be less than source width."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1920, 1080, (9, 16))
        assert new_w < 1920
        assert new_h == 1080

    # --- portrait → landscape ---

    def test_portrait_to_landscape(self, optimizer):
        """1080×1920 (9:16) source → 16:9 target."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1080, 1920, (16, 9))
        expected_h = int(1080 / (16 / 9))  # 607
        assert new_w == 1080          # width kept
        assert new_h == expected_h
        assert cx == 1080 / 2
        assert cy == 1920 / 2

    def test_portrait_to_landscape_crop_height(self, optimizer):
        new_w, new_h, cx, cy = optimizer._calculate_crop(1080, 1920, (16, 9))
        assert new_h < 1920
        assert new_w == 1080

    # --- landscape → square ---

    def test_landscape_to_square(self, optimizer):
        """1920×1080 (16:9) source → 1:1 target."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1920, 1080, (1, 1))
        # Source is wider, so crop width → new_w = src_h * 1 = 1080
        assert new_w == 1080
        assert new_h == 1080

    def test_landscape_to_square_center(self, optimizer):
        new_w, new_h, cx, cy = optimizer._calculate_crop(1920, 1080, (1, 1))
        assert cx == 960.0
        assert cy == 540.0

    # --- portrait → 4:5 ---

    def test_portrait_to_four_five(self, optimizer):
        """1080×1920 (9:16) source → 4:5 target."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1080, 1920, (4, 5))
        # target_ratio = 4/5 = 0.8
        # source_ratio = 1080/1920 = 0.5625
        # source is taller → crop height
        expected_h = int(1080 / (4 / 5))  # int(1080 * 5 / 4) = 1350
        assert new_w == 1080
        assert new_h == expected_h

    # --- same ratio → no meaningful crop ---

    def test_same_ratio_landscape(self, optimizer):
        """Source and target have the same ratio (16:9)."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1920, 1080, (16, 9))
        # source_ratio == target_ratio → goes into the else branch (taller/equal)
        # new_h = int(1920 / (16/9)) = int(1080) = 1080
        assert new_w == 1920
        assert new_h == 1080

    def test_same_ratio_square(self, optimizer):
        """Square source and square target."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1080, 1080, (1, 1))
        assert new_w == 1080
        assert new_h == 1080

    # --- square source to various targets ---

    def test_square_to_portrait(self, optimizer):
        """1080×1080 (1:1) source → 9:16 target."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1080, 1080, (9, 16))
        # target_ratio = 9/16 = 0.5625 < source_ratio = 1.0 (source wider)
        expected_w = int(1080 * 9 / 16)  # 607
        assert new_w == expected_w
        assert new_h == 1080

    def test_square_to_landscape(self, optimizer):
        """1080×1080 (1:1) source → 16:9 target."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(1080, 1080, (16, 9))
        # target_ratio = 16/9 ≈ 1.78 > source_ratio = 1.0 (source taller/equal)
        expected_h = int(1080 / (16 / 9))  # 607
        assert new_w == 1080
        assert new_h == expected_h

    # --- center coordinates are always src/2 ---

    def test_center_always_src_center(self, optimizer):
        new_w, new_h, cx, cy = optimizer._calculate_crop(1280, 720, (9, 16))
        assert cx == 640.0
        assert cy == 360.0

    def test_small_source(self, optimizer):
        """Small source dimensions should still work."""
        new_w, new_h, cx, cy = optimizer._calculate_crop(320, 240, (1, 1))
        assert new_w == 240
        assert new_h == 240

    def test_crop_width_never_exceeds_source(self, optimizer):
        new_w, new_h, cx, cy = optimizer._calculate_crop(1920, 1080, (9, 16))
        assert new_w <= 1920
        assert new_h <= 1080

    def test_crop_height_never_exceeds_source(self, optimizer):
        new_w, new_h, cx, cy = optimizer._calculate_crop(1080, 1920, (16, 9))
        assert new_w <= 1080
        assert new_h <= 1920


# ===========================================================================
# optimize_clip tests (MoviePy mocked)
# ===========================================================================

def _make_moviepy_patch(clip_mock):
    """
    Return a context manager that patches the lazy moviepy imports used inside
    optimize_clip(). Because VideoFileClip and CompositeVideoClip are imported
    *inside* the method body, we patch the moviepy module objects directly.
    """
    mock_vfc = MagicMock(return_value=clip_mock)
    mock_cvr = MagicMock()
    _mock_moviepy.VideoFileClip = mock_vfc
    _mock_moviepy.CompositeVideoClip = mock_cvr
    return mock_vfc, mock_cvr


class TestOptimizeClip:
    """Tests for ExportOptimizer.optimize_clip() with MoviePy mocked."""

    def _make_clip_mock(self, width=1920, height=1080, duration=30.0):
        """Create a mock VideoFileClip with chained method returns."""
        clip = MagicMock()
        clip.size = (width, height)
        clip.duration = duration
        # Methods return new mock clips that also chain
        cropped = MagicMock()
        cropped.size = (width, height)
        cropped.duration = duration
        resized = MagicMock()
        resized.size = (width, height)
        resized.duration = duration
        trimmed = MagicMock()
        trimmed.size = (width, height)
        trimmed.duration = duration

        clip.cropped.return_value = cropped
        cropped.resized.return_value = resized
        resized.subclipped.return_value = trimmed
        return clip, cropped, resized, trimmed

    def test_optimize_calls_write_videofile(self, optimizer, tmp_path):
        clip, cropped, resized, _ = self._make_clip_mock(duration=20.0)
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "youtube", str(tmp_path))

        resized.write_videofile.assert_called_once()

    def test_optimize_returns_output_path(self, optimizer, tmp_path):
        clip, cropped, resized, _ = self._make_clip_mock(duration=20.0)
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        result = optimizer.optimize_clip(source, "youtube", str(tmp_path))

        assert result.endswith(".mp4")
        assert "youtube" in result
        assert str(tmp_path) in result

    def test_optimize_calls_cropped(self, optimizer, tmp_path):
        clip, cropped, resized, _ = self._make_clip_mock(
            width=1920, height=1080, duration=20.0
        )
        source = str(tmp_path / "video.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "youtube_shorts", str(tmp_path))

        clip.cropped.assert_called_once()

    def test_optimize_calls_resized(self, optimizer, tmp_path):
        clip, cropped, resized, _ = self._make_clip_mock(duration=20.0)
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "tiktok", str(tmp_path))

        cropped.resized.assert_called_once_with((1080, 1920))

    def test_optimize_trims_when_over_max_duration(self, optimizer, tmp_path):
        """Clip longer than max_duration should call subclipped."""
        clip, cropped, resized, _ = self._make_clip_mock(duration=120.0)
        resized.duration = 120.0
        source = str(tmp_path / "long_video.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "youtube_shorts", str(tmp_path))  # max 60s

        resized.subclipped.assert_called_once_with(0, 60.0)

    def test_optimize_no_trim_under_max_duration(self, optimizer, tmp_path):
        """Clip shorter than max_duration should NOT call subclipped."""
        clip, cropped, resized, _ = self._make_clip_mock(duration=30.0)
        resized.duration = 30.0
        source = str(tmp_path / "short.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "youtube_shorts", str(tmp_path))  # max 60s

        resized.subclipped.assert_not_called()

    def test_optimize_no_trim_when_no_max_duration(self, optimizer, tmp_path):
        """Platforms with max_duration=None should never trim."""
        clip, cropped, resized, _ = self._make_clip_mock(duration=3600.0)
        resized.duration = 3600.0
        source = str(tmp_path / "long.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "youtube", str(tmp_path))  # no max

        resized.subclipped.assert_not_called()

    def test_optimize_uses_profile_codec(self, optimizer, tmp_path):
        clip, cropped, resized, _ = self._make_clip_mock(duration=20.0)
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "youtube", str(tmp_path))

        call_kwargs = resized.write_videofile.call_args[1]
        assert call_kwargs.get("codec") == "libx264"
        assert call_kwargs.get("audio_codec") == "aac"

    def test_optimize_invalid_platform_raises(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        with pytest.raises(ValueError, match="Unsupported platform"):
            optimizer.optimize_clip(source, "snapchat", str(tmp_path))

    def test_optimize_missing_source_raises(self, optimizer, tmp_path):
        with pytest.raises(ValueError, match="Source file not found"):
            optimizer.optimize_clip("/nonexistent/video.mp4", "youtube", str(tmp_path))

    def test_optimize_missing_output_dir_raises(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        with pytest.raises(ValueError, match="Output directory does not exist"):
            optimizer.optimize_clip(source, "youtube", "/nonexistent/output/dir")

    def test_optimize_closes_clip(self, optimizer, tmp_path):
        """After writing, close() is called on the final clip chain (resized)."""
        clip, cropped, resized, _ = self._make_clip_mock(duration=20.0)
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        optimizer.optimize_clip(source, "youtube", str(tmp_path))

        # The local 'clip' variable in optimize_clip ends up as 'resized'
        # (after clip = clip.cropped(...) then clip = clip.resized(...))
        resized.close.assert_called_once()

    def test_optimize_output_filename_contains_platform(self, optimizer, tmp_path):
        clip, cropped, resized, _ = self._make_clip_mock(duration=20.0)
        source = str(tmp_path / "myvideo.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        result = optimizer.optimize_clip(source, "tiktok", str(tmp_path))

        assert os.path.basename(result).startswith("tiktok_")

    def test_optimize_writes_to_correct_directory(self, optimizer, tmp_path):
        clip, cropped, resized, _ = self._make_clip_mock(duration=20.0)
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()

        _make_moviepy_patch(clip)
        result = optimizer.optimize_clip(source, "youtube", str(tmp_path))

        assert os.path.dirname(result) == str(tmp_path)


# ===========================================================================
# batch_export tests
# ===========================================================================

class TestBatchExport:
    """Tests for ExportOptimizer.batch_export()."""

    def test_empty_platforms_returns_empty(self, optimizer):
        result = optimizer.batch_export("/fake/video.mp4", [], "/tmp")
        assert result == {}

    def test_single_platform(self, optimizer, tmp_path):
        with patch.object(optimizer, "optimize_clip", return_value="/out/tiktok.mp4") as mock_opt:
            result = optimizer.batch_export(
                str(tmp_path / "video.mp4"), ["tiktok"], str(tmp_path)
            )

        assert "tiktok" in result
        assert result["tiktok"] == "/out/tiktok.mp4"
        mock_opt.assert_called_once()

    def test_multiple_platforms(self, optimizer, tmp_path):
        expected = {
            "youtube": "/out/youtube.mp4",
            "tiktok": "/out/tiktok.mp4",
            "instagram_feed": "/out/instagram_feed.mp4",
        }

        def fake_optimize(source, platform, out_dir):
            return expected[platform]

        with patch.object(optimizer, "optimize_clip", side_effect=fake_optimize):
            result = optimizer.batch_export(
                str(tmp_path / "video.mp4"),
                ["youtube", "tiktok", "instagram_feed"],
                str(tmp_path),
            )

        assert result == expected

    def test_all_six_platforms(self, optimizer, tmp_path):
        platforms = list(_SUPPORTED_PLATFORMS)

        def fake_optimize(source, platform, out_dir):
            return f"/out/{platform}.mp4"

        with patch.object(optimizer, "optimize_clip", side_effect=fake_optimize):
            result = optimizer.batch_export(
                str(tmp_path / "video.mp4"), platforms, str(tmp_path)
            )

        assert len(result) == 6
        for p in platforms:
            assert p in result

    def test_failed_platform_captured_in_result(self, optimizer, tmp_path):
        """If optimize_clip raises, the error string is stored — not re-raised."""
        def fail_for_tiktok(source, platform, out_dir):
            if platform == "tiktok":
                raise RuntimeError("ffmpeg missing")
            return f"/out/{platform}.mp4"

        with patch.object(optimizer, "optimize_clip", side_effect=fail_for_tiktok):
            result = optimizer.batch_export(
                str(tmp_path / "video.mp4"),
                ["youtube", "tiktok"],
                str(tmp_path),
            )

        assert result["youtube"] == "/out/youtube.mp4"
        assert "ffmpeg missing" in result["tiktok"]

    def test_batch_passes_correct_args(self, optimizer, tmp_path):
        source = str(tmp_path / "video.mp4")
        out_dir = str(tmp_path)

        with patch.object(optimizer, "optimize_clip", return_value="/out/x.mp4") as mock_opt:
            optimizer.batch_export(source, ["youtube"], out_dir)

        mock_opt.assert_called_once_with(source, "youtube", out_dir)

    def test_returns_dict(self, optimizer, tmp_path):
        with patch.object(optimizer, "optimize_clip", return_value="/out/x.mp4"):
            result = optimizer.batch_export(
                str(tmp_path / "v.mp4"), ["tiktok"], str(tmp_path)
            )
        assert isinstance(result, dict)

    def test_all_fail_returns_error_dict(self, optimizer, tmp_path):
        def always_fail(source, platform, out_dir):
            raise ValueError("bad")

        with patch.object(optimizer, "optimize_clip", side_effect=always_fail):
            result = optimizer.batch_export(
                str(tmp_path / "v.mp4"),
                ["youtube", "tiktok"],
                str(tmp_path),
            )

        assert len(result) == 2
        for v in result.values():
            assert "bad" in v


# ===========================================================================
# Supported platforms constant
# ===========================================================================

class TestSupportedPlatformsConstant:
    """Tests for _SUPPORTED_PLATFORMS module constant."""

    def test_is_frozenset(self):
        assert isinstance(_SUPPORTED_PLATFORMS, frozenset)

    def test_contains_six_platforms(self):
        assert len(_SUPPORTED_PLATFORMS) == 6

    def test_contains_all_expected(self):
        expected = {
            "youtube", "youtube_shorts", "tiktok",
            "instagram_reels", "instagram_feed", "instagram_optimized",
        }
        assert _SUPPORTED_PLATFORMS == expected

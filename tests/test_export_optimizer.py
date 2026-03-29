"""
Tests for export_optimizer.py — Multi-Platform Export Optimizer.

Coverage categories:
  - ExportProfile dataclass: creation, to_dict, from_dict, field defaults
  - ExportOptimizer init and profile management
  - get_profile: all 6 platforms, invalid platform
  - list_profiles: returns all 6 profiles
  - _calculate_crop: mathematical correctness for all aspect ratio conversions
  - optimize_clip: mocked ffmpeg_utils + subprocess, verify command construction
  - batch_export: mocked optimize_clip, verify all platforms processed
  - Edge cases: empty platforms list, non-existent source, max_duration trimming
  - FFmpeg command construction: per-platform, even-pixel enforcement, duration trim
  - subprocess error handling
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call

# ---------------------------------------------------------------------------
# Ensure src/ is on the path before importing module under test.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from export_optimizer import ExportOptimizer, ExportProfile, _SUPPORTED_PLATFORMS


# ===========================================================================
# Helpers
# ===========================================================================

def _make_video_info(width=1920, height=1080, duration=30.0):
    """Create a mock VideoInfo-like object."""
    info = MagicMock()
    info.width = width
    info.height = height
    info.duration = duration
    return info


def _make_subprocess_result(returncode=0, stderr=""):
    """Create a mock subprocess.CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stderr = stderr
    return result


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
# optimize_clip tests (ffmpeg_utils + subprocess mocked)
# ===========================================================================

class TestOptimizeClip:
    """Tests for ExportOptimizer.optimize_clip() with ffmpeg_utils mocked."""

    def test_optimize_returns_output_path(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()):
            result = optimizer.optimize_clip(source, "youtube", str(tmp_path))

        assert result.endswith(".mp4")
        assert "youtube" in result
        assert str(tmp_path) in result

    def test_optimize_calls_subprocess_run(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info) as mock_info, \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        mock_run.assert_called_once()

    def test_optimize_command_contains_ffmpeg(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd

    def test_optimize_command_contains_vf(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-vf" in cmd

    def test_optimize_command_contains_codec_flags(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-c:v" in cmd
        assert "-c:a" in cmd

    def test_optimize_uses_profile_codec_libx264(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        cv_idx = cmd.index("-c:v")
        ca_idx = cmd.index("-c:a")
        assert cmd[cv_idx + 1] == "libx264"
        assert cmd[ca_idx + 1] == "aac"

    def test_optimize_trims_when_over_max_duration(self, optimizer, tmp_path):
        """Clip longer than max_duration should add -t flag."""
        source = str(tmp_path / "long_video.mp4")
        open(source, "w").close()
        info = _make_video_info(1080, 1920, 120.0)  # 120s > 60s limit

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube_shorts", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-t" in cmd
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == "60.0"

    def test_optimize_no_trim_under_max_duration(self, optimizer, tmp_path):
        """Clip shorter than max_duration should NOT add -t flag."""
        source = str(tmp_path / "short.mp4")
        open(source, "w").close()
        info = _make_video_info(1080, 1920, 30.0)  # 30s < 60s limit

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube_shorts", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-t" not in cmd

    def test_optimize_no_trim_when_no_max_duration(self, optimizer, tmp_path):
        """Platforms with max_duration=None should never add -t flag."""
        source = str(tmp_path / "long.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 3600.0)  # 1 hour

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))  # no max

        cmd = mock_run.call_args[0][0]
        assert "-t" not in cmd

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

    def test_optimize_output_filename_contains_platform(self, optimizer, tmp_path):
        source = str(tmp_path / "myvideo.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()):
            result = optimizer.optimize_clip(source, "tiktok", str(tmp_path))

        assert os.path.basename(result).startswith("tiktok_")

    def test_optimize_writes_to_correct_directory(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()):
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


# ===========================================================================
# New integration tests: FFmpeg command construction
# ===========================================================================

class TestFFmpegCommandConstruction:
    """Verify FFmpeg command is correctly built for each platform."""

    def _run_optimize(self, optimizer, tmp_path, platform, width=1920, height=1080, duration=30.0):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(width, height, duration)
        mock_result = _make_subprocess_result(returncode=0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=mock_result) as mock_run:
            path = optimizer.optimize_clip(source, platform, str(tmp_path))
            cmd = mock_run.call_args[0][0]
        return path, cmd

    def test_youtube_command_has_correct_resolution_in_vf(self, optimizer, tmp_path):
        """youtube target is 1920x1080 — scale filter must use those values."""
        _, cmd = self._run_optimize(optimizer, tmp_path, "youtube", 1920, 1080)
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        assert "scale=1920:1080" in vf

    def test_youtube_shorts_command_has_correct_resolution_in_vf(self, optimizer, tmp_path):
        """youtube_shorts target is 1080x1920."""
        _, cmd = self._run_optimize(optimizer, tmp_path, "youtube_shorts", 1920, 1080)
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        assert "scale=1080:1920" in vf

    def test_tiktok_command_has_correct_resolution_in_vf(self, optimizer, tmp_path):
        """tiktok target is 1080x1920."""
        _, cmd = self._run_optimize(optimizer, tmp_path, "tiktok", 1920, 1080)
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        assert "scale=1080:1920" in vf

    def test_instagram_feed_command_square_scale(self, optimizer, tmp_path):
        """instagram_feed target is 1080x1080 square."""
        _, cmd = self._run_optimize(optimizer, tmp_path, "instagram_feed", 1920, 1080)
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        assert "scale=1080:1080" in vf

    def test_instagram_optimized_command_four_five_scale(self, optimizer, tmp_path):
        """instagram_optimized target is 1080x1350."""
        _, cmd = self._run_optimize(optimizer, tmp_path, "instagram_optimized", 1920, 1080)
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        assert "scale=1080:1350" in vf

    def test_vf_filter_contains_crop_and_scale(self, optimizer, tmp_path):
        """The -vf value must chain crop and scale."""
        _, cmd = self._run_optimize(optimizer, tmp_path, "tiktok", 1920, 1080)
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        assert vf.startswith("crop=")
        assert ",scale=" in vf

    def test_command_source_path_present(self, optimizer, tmp_path):
        """The -i flag must reference the source file."""
        source_name = "myvid.mp4"
        source = str(tmp_path / source_name)
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))
        cmd = mock_run.call_args[0][0]

        i_idx = cmd.index("-i")
        assert cmd[i_idx + 1] == source

    def test_command_output_path_is_last_arg(self, optimizer, tmp_path):
        """The last element of the FFmpeg command must be the output path."""
        _, cmd = self._run_optimize(optimizer, tmp_path, "youtube", 1920, 1080)
        assert cmd[-1].endswith(".mp4")
        assert "youtube" in os.path.basename(cmd[-1])

    def test_command_uses_capture_output_text(self, optimizer, tmp_path):
        """subprocess.run must be called with capture_output=True, text=True."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        _, kwargs = mock_run.call_args
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True


class TestEvenPixelEnforcement:
    """Even-pixel enforcement for libx264 compatibility."""

    def test_odd_source_width_becomes_even_in_crop(self, optimizer, tmp_path):
        """Source with odd-width crop result gets rounded down to even."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        # 1921x1080 → crop to 9:16 will produce odd intermediate width
        info = _make_video_info(1921, 1081, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube_shorts", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        # Extract crop dimensions: crop=W:H:x:y
        crop_part = vf.split(",")[0]  # "crop=W:H:x:y"
        parts = crop_part[len("crop="):].split(":")
        crop_w = int(parts[0])
        crop_h = int(parts[1])
        assert crop_w % 2 == 0, f"crop width {crop_w} is not even"
        assert crop_h % 2 == 0, f"crop height {crop_h} is not even"

    def test_scale_target_dimensions_are_even(self, optimizer, tmp_path):
        """All platform target resolutions are even (sanity check via vf filter)."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        for platform in _SUPPORTED_PLATFORMS:
            with patch("export_optimizer.get_video_info", return_value=info), \
                 patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
                optimizer.optimize_clip(source, platform, str(tmp_path))

            cmd = mock_run.call_args[0][0]
            vf_idx = cmd.index("-vf")
            vf = cmd[vf_idx + 1]
            scale_part = vf.split(",scale=")[1]
            scale_w, scale_h = [int(x) for x in scale_part.split(":")]
            assert scale_w % 2 == 0, f"[{platform}] scale width {scale_w} is odd"
            assert scale_h % 2 == 0, f"[{platform}] scale height {scale_h} is odd"


class TestDurationTrimming:
    """Duration trimming logic via -t flag."""

    def test_trim_tiktok_over_180s(self, optimizer, tmp_path):
        """tiktok max is 180s — a 200s clip should be trimmed."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1080, 1920, 200.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "tiktok", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-t" in cmd
        t_idx = cmd.index("-t")
        assert float(cmd[t_idx + 1]) == 180.0

    def test_no_trim_tiktok_exactly_180s(self, optimizer, tmp_path):
        """Clip of exactly max_duration should NOT be trimmed."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1080, 1920, 180.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "tiktok", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-t" not in cmd

    def test_trim_instagram_reels_over_90s(self, optimizer, tmp_path):
        """instagram_reels max is 90s."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1080, 1920, 100.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "instagram_reels", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-t" in cmd
        t_idx = cmd.index("-t")
        assert float(cmd[t_idx + 1]) == 90.0

    def test_trim_instagram_feed_over_60s(self, optimizer, tmp_path):
        """instagram_feed max is 60s."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 90.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "instagram_feed", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-t" in cmd


class TestSubprocessErrorHandling:
    """subprocess.run non-zero returncode raises RuntimeError."""

    def test_nonzero_returncode_raises_runtime_error(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)
        fail_result = _make_subprocess_result(returncode=1, stderr="codec not found")

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=fail_result):
            with pytest.raises(RuntimeError, match="ffmpeg export failed"):
                optimizer.optimize_clip(source, "youtube", str(tmp_path))

    def test_error_message_includes_returncode(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)
        fail_result = _make_subprocess_result(returncode=2, stderr="some error")

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=fail_result):
            with pytest.raises(RuntimeError, match="exit 2"):
                optimizer.optimize_clip(source, "youtube", str(tmp_path))

    def test_error_message_includes_stderr(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)
        fail_result = _make_subprocess_result(returncode=1, stderr="libx264 not found")

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=fail_result):
            with pytest.raises(RuntimeError, match="libx264 not found"):
                optimizer.optimize_clip(source, "youtube", str(tmp_path))

    def test_success_returncode_zero_does_not_raise(self, optimizer, tmp_path):
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result(returncode=0)):
            # Should not raise
            result = optimizer.optimize_clip(source, "youtube", str(tmp_path))
        assert result is not None


class TestVariousSourceDimensions:
    """Test optimize_clip with wide, tall, and square source videos."""

    def test_wide_source_landscape_to_portrait(self, optimizer, tmp_path):
        """2560x1080 ultra-wide to youtube_shorts (9:16)."""
        source = str(tmp_path / "ultra.mp4")
        open(source, "w").close()
        info = _make_video_info(2560, 1080, 30.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube_shorts", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert "-vf" in cmd

    def test_tall_source_portrait_to_landscape(self, optimizer, tmp_path):
        """1080x2340 tall phone video to youtube (16:9)."""
        source = str(tmp_path / "tall.mp4")
        open(source, "w").close()
        info = _make_video_info(1080, 2340, 30.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        # scale must end with 1920:1080
        assert "scale=1920:1080" in vf

    def test_square_source_to_portrait(self, optimizer, tmp_path):
        """1080x1080 square to tiktok (9:16)."""
        source = str(tmp_path / "square.mp4")
        open(source, "w").close()
        info = _make_video_info(1080, 1080, 30.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()) as mock_run:
            optimizer.optimize_clip(source, "tiktok", str(tmp_path))

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"

    def test_batch_export_with_ffmpeg_backend(self, optimizer, tmp_path):
        """batch_export calls optimize_clip for each platform; errors are captured."""
        source = str(tmp_path / "vid.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 30.0)

        with patch("export_optimizer.get_video_info", return_value=info), \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()):
            results = optimizer.batch_export(source, ["youtube", "tiktok"], str(tmp_path))

        assert "youtube" in results
        assert "tiktok" in results
        for v in results.values():
            assert isinstance(v, str)
            assert v.endswith(".mp4")

    def test_get_video_info_called_once_per_optimize(self, optimizer, tmp_path):
        """get_video_info must be called exactly once per optimize_clip call."""
        source = str(tmp_path / "input.mp4")
        open(source, "w").close()
        info = _make_video_info(1920, 1080, 20.0)

        with patch("export_optimizer.get_video_info", return_value=info) as mock_info, \
             patch("export_optimizer.subprocess.run", return_value=_make_subprocess_result()):
            optimizer.optimize_clip(source, "youtube", str(tmp_path))

        mock_info.assert_called_once_with(source)

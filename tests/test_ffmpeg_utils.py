"""
Tests for ffmpeg_utils.py — Direct FFmpeg subprocess wrappers.

Coverage categories:
  1. VideoInfo dataclass validation
  2. check_ffmpeg with/without binaries
  3. get_video_info with valid/invalid/missing ffprobe output
  4. trim_clip with copy mode, re-encode, invalid times, nonexistent paths
  5. concat_clips with 2 files, max files, empty list, single file
  6. transcode with various codec/resolution/preset combos
  7. extract_audio with wav/mp3/aac
  8. Error handling (subprocess returncode != 0, timeout, missing binary)
  9. Edge cases (zero duration, negative start, start >= end)
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call

# ---------------------------------------------------------------------------
# Path setup — makes bare-module imports work the same way src/main.py does
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ---------------------------------------------------------------------------
# We mock validate_path at the module level so it doesn't touch the filesystem
# ---------------------------------------------------------------------------
_real_validate_path = None  # populated after import

from ffmpeg_utils import (
    VideoInfo,
    check_ffmpeg,
    get_video_info,
    trim_clip,
    concat_clips,
    transcode,
    extract_audio,
    _MAX_DURATION,
    _MAX_CONCAT_FILES,
    _SUPPORTED_CODECS,
    _SUPPORTED_PRESETS,
    _SUPPORTED_AUDIO_FORMATS,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_subprocess_ok(stdout="", stderr=""):
    """Return a mock CompletedProcess with returncode=0."""
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


def _make_subprocess_fail(returncode=1, stderr="ffmpeg error"):
    """Return a mock CompletedProcess with non-zero returncode."""
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = ""
    mock.stderr = stderr
    return mock


def _ffprobe_json(
    duration="30.0",
    width=1920,
    height=1080,
    codec_name="h264",
    avg_frame_rate="30/1",
    bit_rate="4000000",
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
    format_bit_rate="4000000",
):
    """Build a minimal valid ffprobe JSON payload."""
    return json.dumps({
        "streams": [
            {
                "codec_type": "video",
                "codec_name": codec_name,
                "width": width,
                "height": height,
                "avg_frame_rate": avg_frame_rate,
                "bit_rate": bit_rate,
                "duration": duration,
            }
        ],
        "format": {
            "format_name": format_name,
            "duration": duration,
            "bit_rate": format_bit_rate,
        },
    })


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def mock_validate_path():
    """
    By default, validate_path is a no-op that returns its first argument.
    Individual tests that want to test validation failure can override it.
    """
    with patch("ffmpeg_utils.validate_path", side_effect=lambda p, must_exist=True: p):
        yield


# ===========================================================================
# 1. VideoInfo dataclass
# ===========================================================================

class TestVideoInfoDataclass:
    """VideoInfo is a simple dataclass — verify all fields."""

    def test_can_construct(self):
        info = VideoInfo(
            duration=30.0,
            width=1920,
            height=1080,
            codec="h264",
            fps=30.0,
            bitrate=4_000_000,
            format="mp4",
        )
        assert info.duration == 30.0

    def test_fields_accessible(self):
        info = VideoInfo(10.5, 1280, 720, "h265", 24.0, 2_000_000, "mkv")
        assert info.duration == 10.5
        assert info.width == 1280
        assert info.height == 720
        assert info.codec == "h265"
        assert info.fps == 24.0
        assert info.bitrate == 2_000_000
        assert info.format == "mkv"

    def test_zero_duration_allowed(self):
        info = VideoInfo(0.0, 640, 480, "mpeg4", 25.0, 500_000, "avi")
        assert info.duration == 0.0

    def test_large_values(self):
        info = VideoInfo(86400.0, 3840, 2160, "h264", 60.0, 50_000_000, "mp4")
        assert info.bitrate == 50_000_000

    def test_equality(self):
        a = VideoInfo(5.0, 640, 480, "h264", 30.0, 1_000_000, "mp4")
        b = VideoInfo(5.0, 640, 480, "h264", 30.0, 1_000_000, "mp4")
        assert a == b

    def test_inequality(self):
        a = VideoInfo(5.0, 640, 480, "h264", 30.0, 1_000_000, "mp4")
        b = VideoInfo(5.0, 640, 480, "h264", 30.0, 999_999, "mp4")
        assert a != b


# ===========================================================================
# 2. check_ffmpeg
# ===========================================================================

class TestCheckFfmpeg:
    """check_ffmpeg: returns True only if both binaries are on PATH."""

    def test_both_present_returns_true(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            assert check_ffmpeg() is True

    def test_ffmpeg_missing_returns_false(self):
        def which_side(name):
            return None if name == "ffmpeg" else "/usr/bin/ffprobe"

        with patch("shutil.which", side_effect=which_side):
            assert check_ffmpeg() is False

    def test_ffprobe_missing_returns_false(self):
        def which_side(name):
            return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

        with patch("shutil.which", side_effect=which_side):
            assert check_ffmpeg() is False

    def test_both_missing_returns_false(self):
        with patch("shutil.which", return_value=None):
            assert check_ffmpeg() is False

    def test_checks_both_binaries(self):
        """which() must be called for 'ffmpeg' and 'ffprobe'."""
        with patch("shutil.which", return_value="/usr/bin/x") as mock_which:
            check_ffmpeg()
        calls = [c.args[0] for c in mock_which.call_args_list]
        assert "ffmpeg" in calls
        assert "ffprobe" in calls


# ===========================================================================
# 3. get_video_info
# ===========================================================================

class TestGetVideoInfo:
    """get_video_info: happy path, missing fields, bad JSON, non-zero exit."""

    def test_returns_video_info(self):
        payload = _ffprobe_json()
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert isinstance(info, VideoInfo)

    def test_correct_duration(self):
        payload = _ffprobe_json(duration="42.5")
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert info.duration == 42.5

    def test_correct_dimensions(self):
        payload = _ffprobe_json(width=1280, height=720)
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert info.width == 1280
        assert info.height == 720

    def test_correct_codec(self):
        payload = _ffprobe_json(codec_name="hevc")
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert info.codec == "hevc"

    def test_fps_calculation(self):
        payload = _ffprobe_json(avg_frame_rate="60/1")
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert info.fps == 60.0

    def test_fps_fractional(self):
        payload = _ffprobe_json(avg_frame_rate="30000/1001")
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert abs(info.fps - 29.97) < 0.01

    def test_bitrate_from_stream(self):
        payload = _ffprobe_json(bit_rate="8000000")
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert info.bitrate == 8_000_000

    def test_format_name(self):
        payload = _ffprobe_json(format_name="matroska,webm")
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert info.format == "matroska,webm"

    def test_ffprobe_nonzero_raises_runtime_error(self):
        with patch("subprocess.run", return_value=_make_subprocess_fail(returncode=1)):
            with pytest.raises(RuntimeError):
                get_video_info("/fake/video.mp4")

    def test_invalid_json_raises_runtime_error(self):
        with patch(
            "subprocess.run",
            return_value=_make_subprocess_ok(stdout="not json {{{"),
        ):
            with pytest.raises(RuntimeError, match="invalid JSON"):
                get_video_info("/fake/video.mp4")

    def test_no_video_stream_raises_value_error(self):
        payload = json.dumps({
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            "format": {"format_name": "mp4", "duration": "10.0"},
        })
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            with pytest.raises(ValueError, match="No video stream"):
                get_video_info("/fake/video.mp4")

    def test_missing_duration_raises_value_error(self):
        payload = json.dumps({
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                    "bit_rate": "4000000",
                    # No 'duration' key
                }
            ],
            "format": {
                "format_name": "mp4",
                # No 'duration' key
            },
        })
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            with pytest.raises(ValueError, match="duration"):
                get_video_info("/fake/video.mp4")

    def test_zero_width_raises_value_error(self):
        payload = json.dumps({
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 0,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                    "bit_rate": "4000000",
                    "duration": "10.0",
                }
            ],
            "format": {"format_name": "mp4"},
        })
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            with pytest.raises(ValueError, match="dimensions"):
                get_video_info("/fake/video.mp4")

    def test_uses_ffprobe_binary(self):
        payload = _ffprobe_json()
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)) as mock_run:
            get_video_info("/fake/video.mp4")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffprobe"

    def test_no_shell_true(self):
        payload = _ffprobe_json()
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)) as mock_run:
            get_video_info("/fake/video.mp4")
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell", False) is False

    def test_validate_path_called(self):
        payload = _ffprobe_json()
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            with patch("ffmpeg_utils.validate_path") as mock_vp:
                mock_vp.return_value = "/fake/video.mp4"
                get_video_info("/fake/video.mp4")
        mock_vp.assert_called_once_with("/fake/video.mp4", must_exist=True)

    def test_fps_zero_denominator(self):
        """avg_frame_rate with 0 denominator should yield fps=0.0 without crash."""
        payload = _ffprobe_json(avg_frame_rate="0/0")
        with patch("subprocess.run", return_value=_make_subprocess_ok(stdout=payload)):
            info = get_video_info("/fake/video.mp4")
        assert info.fps == 0.0


# ===========================================================================
# 4. trim_clip
# ===========================================================================

class TestTrimClip:
    """trim_clip: copy mode, re-encode, validation, error cases."""

    def test_returns_output_path(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = trim_clip("/fake/input.mp4", out, 0, 10)
        assert result == out

    def test_copy_codec_default(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            trim_clip("/fake/input.mp4", out, 0, 10)
        cmd = mock_run.call_args[0][0]
        assert "-c" in cmd
        assert cmd[cmd.index("-c") + 1] == "copy"

    def test_custom_codec(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            trim_clip("/fake/input.mp4", out, 0, 10, codec="libx264")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("-c") + 1] == "libx264"

    def test_start_and_end_in_cmd(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            trim_clip("/fake/input.mp4", out, 5.0, 15.0)
        cmd = mock_run.call_args[0][0]
        assert "-ss" in cmd
        assert "5.0" in cmd
        assert "-to" in cmd
        assert "15.0" in cmd

    def test_negative_start_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="start must be"):
            trim_clip("/fake/input.mp4", out, -1, 10)

    def test_end_equals_start_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="end.*must be greater"):
            trim_clip("/fake/input.mp4", out, 5, 5)

    def test_end_less_than_start_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="end.*must be greater"):
            trim_clip("/fake/input.mp4", out, 10, 5)

    def test_end_exceeds_max_duration_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="exceeds maximum"):
            trim_clip("/fake/input.mp4", out, 0, _MAX_DURATION + 1)

    def test_unsupported_codec_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="Unsupported codec"):
            trim_clip("/fake/input.mp4", out, 0, 10, codec="wmv")

    def test_ffmpeg_failure_raises_runtime_error(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_fail()):
            with pytest.raises(RuntimeError, match="ffmpeg trim failed"):
                trim_clip("/fake/input.mp4", out, 0, 10)

    def test_no_shell_true(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            trim_clip("/fake/input.mp4", out, 0, 10)
        assert mock_run.call_args[1].get("shell", False) is False

    def test_start_zero_allowed(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = trim_clip("/fake/input.mp4", out, 0, 5)
        assert result == out

    def test_validate_path_called_for_input(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            with patch("ffmpeg_utils.validate_path") as mock_vp:
                mock_vp.side_effect = lambda p, must_exist=True: p
                trim_clip("/fake/input.mp4", out, 0, 10)
        calls = [c.args for c in mock_vp.call_args_list]
        assert any(c[0] == "/fake/input.mp4" for c in calls)

    def test_uses_ffmpeg_binary(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            trim_clip("/fake/input.mp4", out, 0, 10)
        assert mock_run.call_args[0][0][0] == "ffmpeg"


# ===========================================================================
# 5. concat_clips
# ===========================================================================

class TestConcatClips:
    """concat_clips: 2 files, max files, single file, empty list, errors."""

    def test_returns_output_path(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = concat_clips(["/fake/a.mp4", "/fake/b.mp4"], out)
        assert result == out

    def test_single_file(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = concat_clips(["/fake/a.mp4"], out)
        assert result == out

    def test_two_files_success(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            concat_clips(["/fake/a.mp4", "/fake/b.mp4"], out)
        assert mock_run.called

    def test_max_files_allowed(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        paths = [f"/fake/clip_{i}.mp4" for i in range(_MAX_CONCAT_FILES)]
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = concat_clips(paths, out)
        assert result == out

    def test_over_max_files_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        paths = [f"/fake/clip_{i}.mp4" for i in range(_MAX_CONCAT_FILES + 1)]
        with pytest.raises(ValueError, match="Too many input files"):
            concat_clips(paths, out)

    def test_empty_list_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="must not be empty"):
            concat_clips([], out)

    def test_uses_concat_demuxer(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            concat_clips(["/fake/a.mp4", "/fake/b.mp4"], out)
        cmd = mock_run.call_args[0][0]
        assert "-f" in cmd
        assert "concat" in cmd

    def test_default_codec_copy(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            concat_clips(["/fake/a.mp4", "/fake/b.mp4"], out)
        cmd = mock_run.call_args[0][0]
        assert "-c" in cmd
        assert cmd[cmd.index("-c") + 1] == "copy"

    def test_custom_codec(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            concat_clips(["/fake/a.mp4"], out, codec="libx264")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("-c") + 1] == "libx264"

    def test_unsupported_codec_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="Unsupported codec"):
            concat_clips(["/fake/a.mp4"], out, codec="wmv")

    def test_ffmpeg_failure_raises_runtime_error(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_fail()):
            with pytest.raises(RuntimeError, match="ffmpeg concat failed"):
                concat_clips(["/fake/a.mp4", "/fake/b.mp4"], out)

    def test_no_shell_true(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            concat_clips(["/fake/a.mp4"], out)
        assert mock_run.call_args[1].get("shell", False) is False

    def test_uses_ffmpeg_binary(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            concat_clips(["/fake/a.mp4"], out)
        assert mock_run.call_args[0][0][0] == "ffmpeg"

    def test_tempfile_filelist_used(self, tmp_path):
        """The concat command must reference a temporary file via -i."""
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            concat_clips(["/fake/a.mp4", "/fake/b.mp4"], out)
        cmd = mock_run.call_args[0][0]
        # -i must appear and the filelist path must be a string path
        assert "-i" in cmd
        filelist_arg = cmd[cmd.index("-i") + 1]
        assert isinstance(filelist_arg, str)


# ===========================================================================
# 6. transcode
# ===========================================================================

class TestTranscode:
    """transcode: codec/resolution/fps/bitrate/preset combos."""

    def test_returns_output_path(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = transcode("/fake/input.mp4", out)
        assert result == out

    def test_default_codec_libx264(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out)
        cmd = mock_run.call_args[0][0]
        assert "libx264" in cmd

    def test_libx265_codec(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out, codec="libx265")
        cmd = mock_run.call_args[0][0]
        assert "libx265" in cmd

    def test_resolution_adds_scale_filter(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out, resolution=(1280, 720))
        cmd = mock_run.call_args[0][0]
        assert "-vf" in cmd
        vf_arg = cmd[cmd.index("-vf") + 1]
        assert "1280" in vf_arg
        assert "720" in vf_arg

    def test_no_resolution_no_scale_filter(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out)
        cmd = mock_run.call_args[0][0]
        assert "-vf" not in cmd

    def test_fps_passed(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out, fps=60.0)
        cmd = mock_run.call_args[0][0]
        assert "-r" in cmd
        assert "60.0" in cmd

    def test_bitrate_passed(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out, bitrate=2_000_000)
        cmd = mock_run.call_args[0][0]
        assert "-b:v" in cmd

    def test_preset_default_medium(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out)
        cmd = mock_run.call_args[0][0]
        assert "-preset" in cmd
        assert cmd[cmd.index("-preset") + 1] == "medium"

    def test_preset_fast(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out, preset="fast")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("-preset") + 1] == "fast"

    def test_unsupported_codec_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="Unsupported codec"):
            transcode("/fake/input.mp4", out, codec="divx")

    def test_unsupported_preset_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="Unsupported preset"):
            transcode("/fake/input.mp4", out, preset="ludicrous_speed")

    def test_invalid_resolution_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="resolution must be"):
            transcode("/fake/input.mp4", out, resolution=(0, 720))

    def test_negative_fps_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="fps must be positive"):
            transcode("/fake/input.mp4", out, fps=-1.0)

    def test_zero_fps_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="fps must be positive"):
            transcode("/fake/input.mp4", out, fps=0)

    def test_negative_bitrate_raises(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with pytest.raises(ValueError, match="bitrate must be positive"):
            transcode("/fake/input.mp4", out, bitrate=-1)

    def test_ffmpeg_failure_raises_runtime_error(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_fail()):
            with pytest.raises(RuntimeError, match="ffmpeg transcode failed"):
                transcode("/fake/input.mp4", out)

    def test_no_shell_true(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out)
        assert mock_run.call_args[1].get("shell", False) is False

    def test_aac_no_preset(self, tmp_path):
        """aac codec does not support -preset; it must not be passed."""
        out = str(tmp_path / "out.aac")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out, codec="aac")
        cmd = mock_run.call_args[0][0]
        assert "-preset" not in cmd

    def test_uses_ffmpeg_binary(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            transcode("/fake/input.mp4", out)
        assert mock_run.call_args[0][0][0] == "ffmpeg"


# ===========================================================================
# 7. extract_audio
# ===========================================================================

class TestExtractAudio:
    """extract_audio: wav/mp3/aac, validation, errors."""

    def test_returns_output_path(self, tmp_path):
        out = str(tmp_path / "audio.wav")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = extract_audio("/fake/video.mp4", out)
        assert result == out

    def test_default_format_wav(self, tmp_path):
        """Default format is wav — no ValueError raised."""
        out = str(tmp_path / "audio.wav")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = extract_audio("/fake/video.mp4", out)
        assert result == out

    def test_mp3_format(self, tmp_path):
        out = str(tmp_path / "audio.mp3")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = extract_audio("/fake/video.mp4", out, format="mp3")
        assert result == out

    def test_aac_format(self, tmp_path):
        out = str(tmp_path / "audio.aac")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            result = extract_audio("/fake/video.mp4", out, format="aac")
        assert result == out

    def test_unsupported_format_raises(self, tmp_path):
        out = str(tmp_path / "audio.flac")
        with pytest.raises(ValueError, match="Unsupported audio format"):
            extract_audio("/fake/video.mp4", out, format="flac")

    def test_cmd_contains_no_video_flag(self, tmp_path):
        out = str(tmp_path / "audio.wav")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            extract_audio("/fake/video.mp4", out)
        cmd = mock_run.call_args[0][0]
        assert "-vn" in cmd

    def test_ffmpeg_failure_raises_runtime_error(self, tmp_path):
        out = str(tmp_path / "audio.wav")
        with patch("subprocess.run", return_value=_make_subprocess_fail()):
            with pytest.raises(RuntimeError, match="audio extraction failed"):
                extract_audio("/fake/video.mp4", out)

    def test_no_shell_true(self, tmp_path):
        out = str(tmp_path / "audio.wav")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            extract_audio("/fake/video.mp4", out)
        assert mock_run.call_args[1].get("shell", False) is False

    def test_uses_ffmpeg_binary(self, tmp_path):
        out = str(tmp_path / "audio.wav")
        with patch("subprocess.run", return_value=_make_subprocess_ok()) as mock_run:
            extract_audio("/fake/video.mp4", out)
        assert mock_run.call_args[0][0][0] == "ffmpeg"

    def test_validate_path_called_for_input(self, tmp_path):
        out = str(tmp_path / "audio.wav")
        with patch("subprocess.run", return_value=_make_subprocess_ok()):
            with patch("ffmpeg_utils.validate_path") as mock_vp:
                mock_vp.side_effect = lambda p, must_exist=True: p
                extract_audio("/fake/video.mp4", out)
        calls = [c.args for c in mock_vp.call_args_list]
        assert any(c[0] == "/fake/video.mp4" for c in calls)


# ===========================================================================
# 8. Error handling — validate_path failures
# ===========================================================================

class TestValidatePathFailures:
    """Verify that validate_path rejections bubble up as ValueError."""

    def test_trim_bad_input_path(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("ffmpeg_utils.validate_path", side_effect=ValueError("Path does not exist.")):
            with pytest.raises(ValueError):
                trim_clip("/nonexistent/input.mp4", out, 0, 5)

    def test_get_video_info_bad_path(self):
        with patch("ffmpeg_utils.validate_path", side_effect=ValueError("Path does not exist.")):
            with pytest.raises(ValueError):
                get_video_info("/nonexistent/video.mp4")

    def test_concat_bad_input_path(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("ffmpeg_utils.validate_path", side_effect=ValueError("Path does not exist.")):
            with pytest.raises(ValueError):
                concat_clips(["/nonexistent/a.mp4"], out)

    def test_transcode_bad_input_path(self, tmp_path):
        out = str(tmp_path / "out.mp4")
        with patch("ffmpeg_utils.validate_path", side_effect=ValueError("Path does not exist.")):
            with pytest.raises(ValueError):
                transcode("/nonexistent/input.mp4", out)

    def test_extract_audio_bad_path(self, tmp_path):
        out = str(tmp_path / "audio.wav")
        with patch("ffmpeg_utils.validate_path", side_effect=ValueError("Path does not exist.")):
            with pytest.raises(ValueError):
                extract_audio("/nonexistent/video.mp4", out)


# ===========================================================================
# 9. Constants
# ===========================================================================

class TestConstants:
    """Verify module constants match the spec."""

    def test_max_duration(self):
        assert _MAX_DURATION == 86400

    def test_max_concat_files(self):
        assert _MAX_CONCAT_FILES == 100

    def test_supported_codecs_is_frozenset(self):
        assert isinstance(_SUPPORTED_CODECS, frozenset)

    def test_supported_codecs_contents(self):
        assert "copy" in _SUPPORTED_CODECS
        assert "libx264" in _SUPPORTED_CODECS
        assert "libx265" in _SUPPORTED_CODECS
        assert "aac" in _SUPPORTED_CODECS
        assert "libmp3lame" in _SUPPORTED_CODECS

    def test_supported_presets_is_frozenset(self):
        assert isinstance(_SUPPORTED_PRESETS, frozenset)

    def test_supported_presets_contents(self):
        for p in ("ultrafast", "superfast", "veryfast", "faster", "fast",
                  "medium", "slow", "slower", "veryslow"):
            assert p in _SUPPORTED_PRESETS

    def test_supported_audio_formats_is_frozenset(self):
        assert isinstance(_SUPPORTED_AUDIO_FORMATS, frozenset)

    def test_supported_audio_formats_contents(self):
        assert "wav" in _SUPPORTED_AUDIO_FORMATS
        assert "mp3" in _SUPPORTED_AUDIO_FORMATS
        assert "aac" in _SUPPORTED_AUDIO_FORMATS

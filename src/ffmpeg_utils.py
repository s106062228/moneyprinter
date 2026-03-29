"""
Direct FFmpeg subprocess wrappers for non-compositing video operations.

Uses subprocess.run() with proper error capture and no shell=True.

Functions:
  - check_ffmpeg()       — validates ffmpeg and ffprobe on PATH
  - get_video_info()     — extracts metadata via ffprobe JSON output
  - trim_clip()          — lossless or re-encoded trim using -ss/-to
  - concat_clips()       — concatenates clips via concat demuxer
  - transcode()          — re-encodes with configurable parameters
  - extract_audio()      — extracts the audio track from a video

Usage:
    from ffmpeg_utils import check_ffmpeg, get_video_info, trim_clip

    if not check_ffmpeg():
        raise RuntimeError("ffmpeg is not installed")

    info = get_video_info("video.mp4")
    trim_clip("video.mp4", "clip.mp4", 0, 10)
"""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from mp_logger import get_logger
from validation import validate_path

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MAX_DURATION = 86400          # 24 hours, max accepted duration in seconds
_MAX_CONCAT_FILES = 100        # hard cap for concat_clips input list
_SUPPORTED_CODECS = frozenset({
    "copy",
    "libx264",
    "libx265",
    "aac",
    "libmp3lame",
})
_SUPPORTED_PRESETS = frozenset({
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
})
_SUPPORTED_AUDIO_FORMATS = frozenset({"wav", "mp3", "aac"})


# ---------------------------------------------------------------------------
# VideoInfo dataclass
# ---------------------------------------------------------------------------

@dataclass
class VideoInfo:
    """Metadata extracted from a video file via ffprobe."""

    duration: float
    width: int
    height: int
    codec: str
    fps: float
    bitrate: int
    format: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_ffmpeg() -> bool:
    """
    Validate that both *ffmpeg* and *ffprobe* are on PATH.

    Returns:
        True if both binaries are found, False otherwise.
    """
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    if not ffmpeg_ok:
        logger.warning("ffmpeg binary not found on PATH.")
    if not ffprobe_ok:
        logger.warning("ffprobe binary not found on PATH.")
    return ffmpeg_ok and ffprobe_ok


def get_video_info(video_path: str) -> VideoInfo:
    """
    Extract metadata from *video_path* using ffprobe.

    Args:
        video_path: Path to an existing video file.

    Returns:
        A populated VideoInfo dataclass.

    Raises:
        ValueError: If the path is invalid or the ffprobe output is missing
                    required fields.
        RuntimeError: If ffprobe exits with a non-zero return code.
    """
    validated = validate_path(video_path, must_exist=True)

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        validated,
    ]
    logger.debug("Running ffprobe to extract video info.")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("ffprobe failed with non-zero exit code.")
        raise RuntimeError(
            f"ffprobe failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON: {exc}") from exc

    # Extract from streams
    streams = data.get("streams", [])
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"), None
    )
    fmt = data.get("format", {})

    if video_stream is None:
        raise ValueError("No video stream found in ffprobe output.")

    # duration: prefer stream-level, fall back to format-level
    raw_duration = video_stream.get("duration") or fmt.get("duration")
    if raw_duration is None:
        raise ValueError("Could not determine video duration from ffprobe output.")
    duration = float(raw_duration)

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    if width == 0 or height == 0:
        raise ValueError("Could not determine video dimensions from ffprobe output.")

    codec = video_stream.get("codec_name", "unknown")

    # fps: expressed as "num/den" string in avg_frame_rate
    fps_raw = video_stream.get("avg_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    # bitrate: prefer stream-level, fall back to format-level
    raw_bitrate = video_stream.get("bit_rate") or fmt.get("bit_rate", "0")
    try:
        bitrate = int(raw_bitrate)
    except (ValueError, TypeError):
        bitrate = 0

    format_name = fmt.get("format_name", "unknown")

    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        codec=codec,
        fps=fps,
        bitrate=bitrate,
        format=format_name,
    )


def trim_clip(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
    *,
    codec: str = "copy",
) -> str:
    """
    Trim a video clip from *start* to *end* seconds.

    Uses ``-ss``/``-to`` flags. Default codec is ``'copy'`` for instant
    lossless trimming.

    Args:
        input_path:  Path to the source video.
        output_path: Path for the trimmed output file.
        start:       Start time in seconds (>= 0).
        end:         End time in seconds (> start, <= _MAX_DURATION).
        codec:       FFmpeg video codec. Must be in _SUPPORTED_CODECS.

    Returns:
        The *output_path* on success.

    Raises:
        ValueError: On invalid paths or time parameters.
        RuntimeError: If FFmpeg exits with a non-zero return code.
    """
    if codec not in _SUPPORTED_CODECS:
        raise ValueError(
            f"Unsupported codec '{codec}'. Choose from: {sorted(_SUPPORTED_CODECS)}"
        )
    if start < 0:
        raise ValueError(f"start must be >= 0, got {start}.")
    if end <= start:
        raise ValueError(f"end ({end}) must be greater than start ({start}).")
    if end > _MAX_DURATION:
        raise ValueError(
            f"end ({end}) exceeds maximum allowed duration ({_MAX_DURATION}s)."
        )

    validated_in = validate_path(input_path, must_exist=True)
    validate_path(output_path, must_exist=False)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", validated_in,
        "-ss", str(start),
        "-to", str(end),
        "-c", codec,
        output_path,
    ]
    logger.info("Trimming clip (codec=%s, start=%s, end=%s).", codec, start, end)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("ffmpeg trim failed.")
        raise RuntimeError(
            f"ffmpeg trim failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    logger.info("Trim complete.")
    return output_path


def concat_clips(
    input_paths: list,
    output_path: str,
    *,
    codec: str = "copy",
) -> str:
    """
    Concatenate a list of video clips into a single output file.

    Uses the FFmpeg concat demuxer (no re-encoding when codec='copy').

    Args:
        input_paths:  Non-empty list of existing video paths (max 100).
        output_path:  Destination path for the concatenated video.
        codec:        FFmpeg video codec. Must be in _SUPPORTED_CODECS.

    Returns:
        The *output_path* on success.

    Raises:
        ValueError: On invalid inputs (empty list, too many files, bad paths).
        RuntimeError: If FFmpeg exits with a non-zero return code.
    """
    if codec not in _SUPPORTED_CODECS:
        raise ValueError(
            f"Unsupported codec '{codec}'. Choose from: {sorted(_SUPPORTED_CODECS)}"
        )
    if not input_paths:
        raise ValueError("input_paths must not be empty.")
    if len(input_paths) > _MAX_CONCAT_FILES:
        raise ValueError(
            f"Too many input files ({len(input_paths)}); "
            f"maximum is {_MAX_CONCAT_FILES}."
        )

    # Validate all inputs exist
    validated_inputs = [validate_path(p, must_exist=True) for p in input_paths]
    validate_path(output_path, must_exist=False)

    # Write concat filelist to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as filelist:
        for path in validated_inputs:
            # ffmpeg concat demuxer requires 'file' lines with escaped paths
            escaped = path.replace("'", "'\\''")
            filelist.write(f"file '{escaped}'\n")
        filelist_path = filelist.name

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", filelist_path,
        "-c", codec,
        output_path,
    ]
    logger.info(
        "Concatenating %d clips (codec=%s).", len(input_paths), codec
    )
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up temp filelist regardless of outcome
    import os
    try:
        os.unlink(filelist_path)
    except OSError:
        pass

    if result.returncode != 0:
        logger.error("ffmpeg concat failed.")
        raise RuntimeError(
            f"ffmpeg concat failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    logger.info("Concat complete.")
    return output_path


def transcode(
    input_path: str,
    output_path: str,
    *,
    codec: str = "libx264",
    resolution: Optional[tuple] = None,
    fps: Optional[float] = None,
    bitrate: Optional[int] = None,
    preset: str = "medium",
) -> str:
    """
    Re-encode a video with configurable parameters.

    Args:
        input_path:  Path to the source video.
        output_path: Path for the transcoded output file.
        codec:       Video codec (must be in _SUPPORTED_CODECS, not 'copy').
        resolution:  Optional (width, height) tuple, e.g. (1920, 1080).
        fps:         Optional target frame rate.
        bitrate:     Optional target video bitrate in bits/s.
        preset:      Encoding speed preset (libx264/libx265 only).
                     Must be in _SUPPORTED_PRESETS.

    Returns:
        The *output_path* on success.

    Raises:
        ValueError: On invalid parameters or paths.
        RuntimeError: If FFmpeg exits with a non-zero return code.
    """
    if codec not in _SUPPORTED_CODECS:
        raise ValueError(
            f"Unsupported codec '{codec}'. Choose from: {sorted(_SUPPORTED_CODECS)}"
        )
    if preset not in _SUPPORTED_PRESETS:
        raise ValueError(
            f"Unsupported preset '{preset}'. Choose from: {sorted(_SUPPORTED_PRESETS)}"
        )
    if resolution is not None:
        if (
            not isinstance(resolution, (tuple, list))
            or len(resolution) != 2
            or resolution[0] <= 0
            or resolution[1] <= 0
        ):
            raise ValueError(
                "resolution must be a (width, height) tuple with positive values."
            )
    if fps is not None and fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}.")
    if bitrate is not None and bitrate <= 0:
        raise ValueError(f"bitrate must be positive, got {bitrate}.")

    validated_in = validate_path(input_path, must_exist=True)
    validate_path(output_path, must_exist=False)

    cmd = ["ffmpeg", "-y", "-i", validated_in]

    cmd += ["-c:v", codec]

    if resolution is not None:
        cmd += ["-vf", f"scale={resolution[0]}:{resolution[1]}"]

    if fps is not None:
        cmd += ["-r", str(fps)]

    if bitrate is not None:
        cmd += ["-b:v", str(bitrate)]

    # Only pass -preset for codecs that support it
    if codec in {"libx264", "libx265"}:
        cmd += ["-preset", preset]

    cmd.append(output_path)

    logger.info(
        "Transcoding (codec=%s, resolution=%s, fps=%s, bitrate=%s, preset=%s).",
        codec, resolution, fps, bitrate, preset,
    )
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("ffmpeg transcode failed.")
        raise RuntimeError(
            f"ffmpeg transcode failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    logger.info("Transcode complete.")
    return output_path


def extract_audio(
    video_path: str,
    output_path: str,
    *,
    format: str = "wav",
) -> str:
    """
    Extract the audio track from a video file.

    Args:
        video_path:  Path to the source video.
        output_path: Destination path for the audio file.
        format:      Output audio format — 'wav', 'mp3', or 'aac'.

    Returns:
        The *output_path* on success.

    Raises:
        ValueError: If the format is unsupported or paths are invalid.
        RuntimeError: If FFmpeg exits with a non-zero return code.
    """
    if format not in _SUPPORTED_AUDIO_FORMATS:
        raise ValueError(
            f"Unsupported audio format '{format}'. "
            f"Choose from: {sorted(_SUPPORTED_AUDIO_FORMATS)}"
        )

    validated_in = validate_path(video_path, must_exist=True)
    validate_path(output_path, must_exist=False)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", validated_in,
        "-vn",          # drop video stream
        output_path,
    ]
    logger.info("Extracting audio (format=%s).", format)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("ffmpeg audio extraction failed.")
        raise RuntimeError(
            f"ffmpeg audio extraction failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )

    logger.info("Audio extraction complete.")
    return output_path

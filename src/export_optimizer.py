"""
Multi-Platform Export Optimizer for MoneyPrinter.

Takes a source video path and produces platform-optimized variants using
smart aspect ratio conversion, cropping, resizing, and duration trimming.

Supported platforms:
  - youtube: 16:9, 1920x1080, no duration limit
  - youtube_shorts: 9:16, 1080x1920, max 60s
  - tiktok: 9:16, 1080x1920, max 180s
  - instagram_reels: 9:16, 1080x1920, max 90s
  - instagram_feed: 1:1, 1080x1080, max 60s
  - instagram_optimized: 4:5, 1080x1350, max 60s

Usage:
    optimizer = ExportOptimizer()
    path = optimizer.optimize_clip("video.mp4", "tiktok", "/tmp/exports")
    results = optimizer.batch_export("video.mp4", ["tiktok", "youtube"], "/tmp")
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from typing import Optional

from ffmpeg_utils import get_video_info, check_ffmpeg
from mp_logger import get_logger
from validation import validate_path, sanitize_filename

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_SUPPORTED_PLATFORMS = frozenset({
    "youtube",
    "youtube_shorts",
    "tiktok",
    "instagram_reels",
    "instagram_feed",
    "instagram_optimized",
})

_MAX_RESOLUTION = 3840
_MIN_RESOLUTION = 100


# ---------------------------------------------------------------------------
# ExportProfile dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExportProfile:
    """Describes video export parameters for a single platform."""

    platform: str
    aspect_ratio: tuple  # (width_ratio, height_ratio) e.g. (9, 16)
    resolution: tuple    # (width_px, height_px) e.g. (1080, 1920)
    max_duration: Optional[float]  # seconds; None means no limit
    codec: str = "libx264"
    audio_codec: str = "aac"

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary."""
        return {
            "platform": self.platform,
            "aspect_ratio": list(self.aspect_ratio),
            "resolution": list(self.resolution),
            "max_duration": self.max_duration,
            "codec": self.codec,
            "audio_codec": self.audio_codec,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExportProfile":
        """Deserialize from a dictionary (e.g. from JSON)."""
        return cls(
            platform=data["platform"],
            aspect_ratio=tuple(data["aspect_ratio"]),
            resolution=tuple(data["resolution"]),
            max_duration=data.get("max_duration"),
            codec=data.get("codec", "libx264"),
            audio_codec=data.get("audio_codec", "aac"),
        )


# ---------------------------------------------------------------------------
# Built-in platform profiles
# ---------------------------------------------------------------------------

_PROFILES: dict[str, ExportProfile] = {
    "youtube": ExportProfile(
        platform="youtube",
        aspect_ratio=(16, 9),
        resolution=(1920, 1080),
        max_duration=None,
    ),
    "youtube_shorts": ExportProfile(
        platform="youtube_shorts",
        aspect_ratio=(9, 16),
        resolution=(1080, 1920),
        max_duration=60.0,
    ),
    "tiktok": ExportProfile(
        platform="tiktok",
        aspect_ratio=(9, 16),
        resolution=(1080, 1920),
        max_duration=180.0,
    ),
    "instagram_reels": ExportProfile(
        platform="instagram_reels",
        aspect_ratio=(9, 16),
        resolution=(1080, 1920),
        max_duration=90.0,
    ),
    "instagram_feed": ExportProfile(
        platform="instagram_feed",
        aspect_ratio=(1, 1),
        resolution=(1080, 1080),
        max_duration=60.0,
    ),
    "instagram_optimized": ExportProfile(
        platform="instagram_optimized",
        aspect_ratio=(4, 5),
        resolution=(1080, 1350),
        max_duration=60.0,
    ),
}


# ---------------------------------------------------------------------------
# ExportOptimizer class
# ---------------------------------------------------------------------------

class ExportOptimizer:
    """
    Produces platform-optimized video exports from a source video.

    Handles aspect ratio conversion via center-crop, then resizes to the
    target platform resolution, and trims to the platform's max duration.
    """

    def __init__(self) -> None:
        # Make a private copy so callers cannot mutate the module-level dict
        self._profiles: dict[str, ExportProfile] = dict(_PROFILES)

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def get_profile(self, platform: str) -> ExportProfile:
        """
        Return the ExportProfile for *platform*.

        Raises:
            ValueError: If *platform* is not in the supported set.
        """
        if platform not in self._profiles:
            raise ValueError(
                f"Unsupported platform '{platform}'. "
                f"Choose from: {sorted(_SUPPORTED_PLATFORMS)}"
            )
        return self._profiles[platform]

    def list_profiles(self) -> list[ExportProfile]:
        """Return all built-in platform profiles."""
        return list(self._profiles.values())

    # ------------------------------------------------------------------
    # Crop calculation (pure math — no MoviePy dependency)
    # ------------------------------------------------------------------

    def _calculate_crop(
        self,
        src_w: int,
        src_h: int,
        target_ratio: tuple,
    ) -> tuple:
        """
        Calculate center-crop parameters for converting *src_w x src_h* to
        the given *target_ratio* (rw, rh).

        Returns:
            (new_w, new_h, x_center, y_center) where new_w/new_h are the
            crop dimensions and x_center/y_center are the center of the crop
            region in the original coordinate system.
        """
        rw, rh = target_ratio
        target_ratio_value = rw / rh
        source_ratio_value = src_w / src_h

        x_center = src_w / 2
        y_center = src_h / 2

        if source_ratio_value > target_ratio_value:
            # Source is wider than target — crop the width, keep the height
            new_w = int(src_h * target_ratio_value)
            new_h = src_h
        else:
            # Source is taller (or equal) — crop the height, keep the width
            new_w = src_w
            new_h = int(src_w / target_ratio_value)

        return new_w, new_h, x_center, y_center

    # ------------------------------------------------------------------
    # Single-platform export
    # ------------------------------------------------------------------

    def optimize_clip(
        self,
        source_path: str,
        platform: str,
        output_dir: str,
    ) -> str:
        """
        Export *source_path* optimized for *platform* into *output_dir*.

        Args:
            source_path: Absolute or relative path to the source video file.
            platform: Target platform name (must be in _SUPPORTED_PLATFORMS).
            output_dir: Directory where the output file will be written.

        Returns:
            Absolute path to the written output file.

        Raises:
            ValueError: For unsupported platform, missing source, or bad dir.
        """
        # ---- validation ------------------------------------------------
        if platform not in self._profiles:
            raise ValueError(
                f"Unsupported platform '{platform}'. "
                f"Choose from: {sorted(_SUPPORTED_PLATFORMS)}"
            )

        if not os.path.isfile(source_path):
            raise ValueError(f"Source file not found: {source_path}")

        if not os.path.isdir(output_dir):
            raise ValueError(f"Output directory does not exist: {output_dir}")

        # ---- profile ---------------------------------------------------
        profile = self._profiles[platform]
        target_w, target_h = profile.resolution

        # ---- get source video info -------------------------------------
        info = get_video_info(source_path)
        src_w, src_h = info.width, info.height

        # ---- crop to target aspect ratio --------------------------------
        new_w, new_h, cx, cy = self._calculate_crop(src_w, src_h, profile.aspect_ratio)

        x_offset = int(cx - new_w / 2)
        y_offset = int(cy - new_h / 2)

        # Ensure even pixel dimensions (libx264 requires even w/h)
        new_w &= ~1
        new_h &= ~1
        target_w &= ~1
        target_h &= ~1

        # ---- build output path -----------------------------------------
        source_filename = os.path.basename(source_path)
        try:
            safe_name = sanitize_filename(source_filename)
        except ValueError:
            safe_name = "video.mp4"

        output_filename = f"{platform}_{safe_name}"
        output_path = os.path.join(output_dir, output_filename)

        # ---- build FFmpeg command with crop+scale filter ----------------
        vf = f"crop={new_w}:{new_h}:{x_offset}:{y_offset},scale={target_w}:{target_h}"
        cmd = ["ffmpeg", "-y", "-i", source_path]
        cmd += ["-vf", vf]
        if profile.max_duration is not None:
            if info.duration > profile.max_duration:
                cmd += ["-t", str(profile.max_duration)]
        cmd += ["-c:v", profile.codec, "-c:a", profile.audio_codec]
        cmd.append(output_path)

        # ---- write ---------------------------------------------------------
        logger.info(
            f"Exporting '{source_path}' → '{output_path}' "
            f"({profile.resolution[0]}x{profile.resolution[1]}, "
            f"codec={profile.codec})"
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg export failed (exit {result.returncode}): {result.stderr.strip()}"
            )

        logger.info(f"Export complete: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Batch export
    # ------------------------------------------------------------------

    def batch_export(
        self,
        source_path: str,
        platforms: list,
        output_dir: str,
    ) -> dict:
        """
        Export *source_path* for each platform in *platforms*.

        Args:
            source_path: Path to the source video file.
            platforms: List of platform name strings.
            output_dir: Directory where output files are written.

        Returns:
            Dict mapping platform name → output file path.
            Platforms that fail are mapped to the error message string.
        """
        if not platforms:
            logger.info("batch_export called with empty platforms list.")
            return {}

        results: dict[str, str] = {}
        for platform in platforms:
            try:
                path = self.optimize_clip(source_path, platform, output_dir)
                results[platform] = path
            except Exception as exc:
                logger.error(f"Export failed for '{platform}': {exc}")
                results[platform] = str(exc)

        return results

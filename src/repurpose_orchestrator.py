"""
Repurposing Orchestrator for MoneyPrinter.

Chains clip extraction → platform optimization → publishing into a single
"Capture Once, Ship Everywhere" pipeline.

Pipeline:
    1. smart_clipper.SmartClipper.detect_scenes() + split_clips()
    2. export_optimizer.ExportOptimizer.optimize_clip() per platform
    3. publisher.ContentPublisher.publish() (optional, auto_publish flag)

Usage:
    from repurpose_orchestrator import RepurposeOrchestrator, RepurposeConfig

    cfg = RepurposeConfig(
        source_video="/path/to/video.mp4",
        platforms=["youtube", "tiktok"],
        auto_publish=True,
    )
    orchestrator = RepurposeOrchestrator()
    result = orchestrator.run(cfg)
    print(f"Created {result.total_clips_created} clips, "
          f"published {result.total_clips_published}")
"""

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MAX_CLIPS = 20
_MIN_CLIP_DURATION = 1.0
_MAX_CLIP_DURATION = 300.0
_MAX_PATH_LENGTH = 1024
_SUPPORTED_FORMATS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})
_ALLOWED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})
_MAX_TITLE_LENGTH = 500
_MAX_DESCRIPTION_LENGTH = 5000
_MAX_TAGS = 50

# ---------------------------------------------------------------------------
# Lazy imports — heavy dependencies imported at module level with try/except.
# Each name is set to None on failure; methods raise RuntimeError if missing.
# ---------------------------------------------------------------------------

try:
    from smart_clipper import SmartClipper, ClipCandidate  # type: ignore[import]
except Exception:  # pragma: no cover
    SmartClipper = None  # type: ignore[assignment,misc]
    ClipCandidate = None  # type: ignore[assignment,misc]

try:
    from export_optimizer import ExportOptimizer  # type: ignore[import]
except Exception:  # pragma: no cover
    ExportOptimizer = None  # type: ignore[assignment,misc]

try:
    from publisher import ContentPublisher, PublishJob, PublishResult  # type: ignore[import]
except Exception:  # pragma: no cover
    ContentPublisher = None  # type: ignore[assignment,misc]
    PublishJob = None  # type: ignore[assignment,misc]
    PublishResult = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RepurposeConfig:
    """Configuration for a single repurposing run."""

    source_video: str
    platforms: list = field(default_factory=lambda: ["youtube", "tiktok", "instagram"])
    max_clips: int = 10
    min_clip_duration: float = 15.0
    max_clip_duration: float = 60.0
    auto_publish: bool = False
    title_template: str = "Clip {index}"
    description: str = ""
    tags: list = field(default_factory=list)
    output_dir: str = ""

    def validate(self) -> None:
        """
        Validate all fields.

        Raises:
            ValueError: on any invalid field.
        """
        # --- source_video ---
        if not self.source_video or not isinstance(self.source_video, str):
            raise ValueError("source_video must be a non-empty string.")
        if "\x00" in self.source_video:
            raise ValueError("source_video contains null bytes.")
        if len(self.source_video) > _MAX_PATH_LENGTH:
            raise ValueError(
                f"source_video path exceeds maximum length of {_MAX_PATH_LENGTH}."
            )
        _, ext = os.path.splitext(self.source_video)
        if ext.lower() not in _SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported video format '{ext}'. "
                f"Supported: {sorted(_SUPPORTED_FORMATS)}"
            )
        if not os.path.isfile(self.source_video):
            raise FileNotFoundError(
                f"source_video does not exist: {self.source_video}"
            )

        # --- max_clips ---
        if not isinstance(self.max_clips, int) or self.max_clips < 1 or self.max_clips > _MAX_CLIPS:
            raise ValueError(
                f"max_clips must be an integer between 1 and {_MAX_CLIPS}, "
                f"got {self.max_clips!r}."
            )

        # --- durations ---
        if not isinstance(self.min_clip_duration, (int, float)) or self.min_clip_duration <= 0:
            raise ValueError("min_clip_duration must be a positive number.")
        if not isinstance(self.max_clip_duration, (int, float)) or self.max_clip_duration <= self.min_clip_duration:
            raise ValueError(
                "max_clip_duration must be greater than min_clip_duration."
            )

        # --- platforms ---
        if not isinstance(self.platforms, list) or not self.platforms:
            raise ValueError("platforms must be a non-empty list.")
        for p in self.platforms:
            if not isinstance(p, str) or p.lower() not in _ALLOWED_PLATFORMS:
                raise ValueError(
                    f"Unknown platform: {p!r}. "
                    f"Allowed: {sorted(_ALLOWED_PLATFORMS)}"
                )

        # --- title_template ---
        if not isinstance(self.title_template, str):
            raise ValueError("title_template must be a string.")
        if len(self.title_template) > _MAX_TITLE_LENGTH:
            raise ValueError(
                f"title_template exceeds maximum length of {_MAX_TITLE_LENGTH}."
            )

        # --- description ---
        if self.description and len(self.description) > _MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"description exceeds maximum length of {_MAX_DESCRIPTION_LENGTH}."
            )

        # --- output_dir ---
        if self.output_dir and not os.path.isdir(self.output_dir):
            raise ValueError(
                f"output_dir does not exist: {self.output_dir}"
            )


@dataclass
class ClipInfo:
    """Audit record for a single extracted clip."""

    index: int
    source_path: str
    duration: float
    optimized_paths: dict = field(default_factory=dict)  # platform -> file path
    published: bool = False
    errors: list = field(default_factory=list)


@dataclass
class RepurposeResult:
    """Summary of a complete repurposing run."""

    source_video: str
    clips: list = field(default_factory=list)          # list[ClipInfo]
    total_clips_created: int = 0
    total_clips_exported: int = 0
    total_clips_published: int = 0
    errors: list = field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class RepurposeOrchestrator:
    """
    Orchestrates clip extraction → optimization → publishing.

    Reads defaults from config.json under the "repurpose" key.
    """

    def __init__(self) -> None:
        try:
            from config import _get  # type: ignore[import]
            cfg = _get("repurpose", {})
        except Exception:
            cfg = {}

        self._default_max_clips: int = int(cfg.get("max_clips", 10))
        self._default_min_clip_duration: float = float(cfg.get("min_clip_duration", 15.0))
        self._default_max_clip_duration: float = float(cfg.get("max_clip_duration", 60.0))
        self._default_auto_publish: bool = bool(cfg.get("auto_publish", False))
        self._default_platforms: list = list(cfg.get("platforms", ["youtube", "tiktok", "instagram"]))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, config: RepurposeConfig) -> RepurposeResult:
        """
        Execute the full repurposing pipeline.

        Args:
            config: RepurposeConfig describing the job.

        Returns:
            RepurposeResult with full audit trail.

        Raises:
            RuntimeError: If a required module is not available.
            ValueError / FileNotFoundError: If config validation fails.
        """
        t0 = time.monotonic()
        result = RepurposeResult(source_video=config.source_video)

        # Validate before touching any I/O
        config.validate()

        # --- Step 1: Clip extraction ---
        clip_paths: list[str] = []
        try:
            clip_paths = self._clip(
                config.source_video,
                config.max_clips,
                config.min_clip_duration,
                config.max_clip_duration,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            msg = f"Clip extraction failed: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            result.duration_seconds = time.monotonic() - t0
            return result

        result.total_clips_created = len(clip_paths)
        logger.info("Extracted %d clip(s).", len(clip_paths))

        if not clip_paths:
            logger.warning("No clips extracted; returning early.")
            result.duration_seconds = time.monotonic() - t0
            return result

        # Resolve output_dir
        output_dir = config.output_dir or os.path.dirname(config.source_video) or "."

        # --- Step 2: Platform optimization ---
        clips: list[ClipInfo] = []
        try:
            clips = self._optimize(clip_paths, config.platforms, output_dir)
        except RuntimeError:
            raise
        except Exception as exc:
            msg = f"Optimization failed: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            result.clips = [
                ClipInfo(index=i + 1, source_path=p, duration=0.0, errors=[msg])
                for i, p in enumerate(clip_paths)
            ]
            result.duration_seconds = time.monotonic() - t0
            return result

        result.clips = clips
        result.total_clips_exported = sum(
            1 for c in clips if c.optimized_paths
        )

        # Collect optimization-level errors into global list
        for c in clips:
            result.errors.extend(c.errors)

        # --- Step 3: Publishing (optional) ---
        if config.auto_publish:
            try:
                clips = self._publish(
                    clips,
                    config.title_template,
                    config.description,
                    config.tags,
                    config.platforms,
                )
            except RuntimeError:
                raise
            except Exception as exc:
                msg = f"Publishing failed: {exc}"
                logger.error(msg)
                result.errors.append(msg)

            result.clips = clips
            result.total_clips_published = sum(1 for c in clips if c.published)

            # Collect publish-level errors
            for c in clips:
                for err in c.errors:
                    if err not in result.errors:
                        result.errors.append(err)

        result.duration_seconds = time.monotonic() - t0
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _clip(
        self,
        source_video: str,
        max_clips: int,
        min_dur: float,
        max_dur: float,
    ) -> list[str]:
        """
        Extract clips from source_video using SmartClipper.

        Returns list of clip file paths.
        """
        if SmartClipper is None:
            raise RuntimeError(
                "smart_clipper module is not available. "
                "Install required dependencies to use clip extraction."
            )

        clipper = SmartClipper(
            min_clip_duration=min_dur,
            max_clip_duration=max_dur,
        )

        # Detect scene boundaries → list of (start, end) tuples
        scenes: list[tuple[float, float]] = clipper.detect_scenes(source_video)
        logger.info("detect_scenes returned %d scene(s).", len(scenes))

        if not scenes:
            return []

        # Filter scenes by duration
        filtered = [
            (s, e) for (s, e) in scenes
            if min_dur <= (e - s) <= max_dur
        ]

        # Limit to max_clips
        filtered = filtered[:max_clips]

        if not filtered:
            logger.warning(
                "No scenes match duration range [%.1f, %.1f]s after filtering.",
                min_dur, max_dur,
            )
            return []

        # Build ClipCandidates for split_clips
        candidates = [
            ClipCandidate(
                start_time=s,
                end_time=e,
                duration=e - s,
                score=0.0,
                transcript="",
                reason="",
            )
            for s, e in filtered
        ]

        # Determine output dir adjacent to the source video
        output_dir = os.path.join(
            os.path.dirname(source_video) or ".", "_clips"
        )

        paths = clipper.split_clips(source_video, candidates, output_dir=output_dir)
        logger.info("split_clips returned %d path(s).", len(paths))
        return paths

    def _optimize(
        self,
        clip_paths: list[str],
        platforms: list[str],
        output_dir: str,
    ) -> list[ClipInfo]:
        """
        Optimize each clip for each platform using ExportOptimizer.

        Returns list of ClipInfo objects.
        """
        if ExportOptimizer is None:
            raise RuntimeError(
                "export_optimizer module is not available. "
                "Install required dependencies to use platform optimization."
            )

        optimizer = ExportOptimizer()
        clips: list[ClipInfo] = []

        for idx, clip_path in enumerate(clip_paths, start=1):
            clip_info = ClipInfo(
                index=idx,
                source_path=clip_path,
                duration=0.0,
            )

            for platform in platforms:
                try:
                    out_path = optimizer.optimize_clip(clip_path, platform, output_dir)
                    clip_info.optimized_paths[platform] = out_path
                    logger.info(
                        "Clip %d optimized for %s → %s", idx, platform, out_path
                    )
                except Exception as exc:
                    msg = f"Clip {idx}: optimization failed for {platform}: {exc}"
                    logger.warning(msg)
                    clip_info.errors.append(msg)

            clips.append(clip_info)

        return clips

    def _publish(
        self,
        clips: list[ClipInfo],
        title_template: str,
        description: str,
        tags: list,
        platforms: list[str],
    ) -> list[ClipInfo]:
        """
        Publish optimized clips via ContentPublisher.

        Returns updated clips list.
        """
        if ContentPublisher is None:
            raise RuntimeError(
                "publisher module is not available. "
                "Install required dependencies to use publishing."
            )

        pub = ContentPublisher()

        for clip in clips:
            if not clip.optimized_paths:
                continue

            title = title_template.format(index=clip.index)

            all_succeeded = True
            for platform, video_path in clip.optimized_paths.items():
                if platform not in platforms:
                    continue

                try:
                    job = PublishJob(
                        video_path=video_path,
                        title=title,
                        description=description,
                        platforms=[platform],
                        tags=list(tags),
                    )
                    results = pub.publish(job)

                    # Check if this platform succeeded
                    for res in results:
                        if not res.success:
                            all_succeeded = False
                            msg = (
                                f"Clip {clip.index}: publish to {platform} failed"
                                + (f": {res.error_type}" if res.error_type else "")
                            )
                            clip.errors.append(msg)
                            logger.warning(msg)

                except Exception as exc:
                    all_succeeded = False
                    msg = f"Clip {clip.index}: publish to {platform} raised: {exc}"
                    clip.errors.append(msg)
                    logger.warning(msg)

            if all_succeeded and clip.optimized_paths:
                clip.published = True

        return clips

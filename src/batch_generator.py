"""
Batch Video Generation for MoneyPrinter.

Enables automated generation of multiple videos in sequence from a list of
topics or niches. Supports configurable concurrency limits, inter-generation
delays, and integration with the publisher module for automatic distribution.

Usage:
    from batch_generator import BatchGenerator, BatchJob

    # Generate multiple videos from a topic list
    job = BatchJob(
        topics=["AI side hustles", "Passive income 2026", "Crypto for beginners"],
        niche="finance",
        language="en",
        auto_publish=True,
        publish_platforms=["youtube", "tiktok"],
    )

    generator = BatchGenerator()
    results = generator.run(job)
    print(f"Generated {results.succeeded}/{results.total} videos")

Configuration (config.json):
    "batch": {
        "max_videos_per_run": 10,
        "delay_between_videos": 30,
        "auto_publish": false,
        "publish_platforms": ["youtube"]
    }

Security:
    - Topic count capped to prevent resource exhaustion
    - Inter-generation delay enforced to prevent API abuse
    - All topic strings validated (length, null bytes)
    - No topic content included in error messages
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import _get
from mp_logger import get_logger
from status import success, error, warning, info

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants and limits
# ---------------------------------------------------------------------------

_MAX_TOPICS = 50
_MAX_TOPIC_LENGTH = 500
_MIN_DELAY_SECONDS = 10
_MAX_DELAY_SECONDS = 600
_DEFAULT_DELAY_SECONDS = 30
_MAX_VIDEOS_PER_RUN = 50


def _get_health_monitor():
    """Lazy singleton for PipelineHealthMonitor."""
    if _get_health_monitor._instance is None:
        try:
            from pipeline_health import PipelineHealthMonitor
            _get_health_monitor._instance = PipelineHealthMonitor()
        except Exception:
            return None
    return _get_health_monitor._instance

_get_health_monitor._instance = None


def _get_plugin_manager():
    """Lazy singleton for PluginManager."""
    if _get_plugin_manager._instance is None:
        try:
            from plugin_manager import PluginManager
            _get_plugin_manager._instance = PluginManager()
        except Exception:
            return None
    return _get_plugin_manager._instance

_get_plugin_manager._instance = None


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_batch_config() -> dict:
    """Returns the batch generation configuration block."""
    return _get("batch", {})


def get_max_videos_per_run() -> int:
    """Returns the max videos per batch run. Clamped 1-50."""
    val = _get_batch_config().get("max_videos_per_run", 10)
    return min(max(int(val), 1), _MAX_VIDEOS_PER_RUN)


def get_delay_between_videos() -> int:
    """Returns the delay between video generations in seconds. Clamped 10-600."""
    val = _get_batch_config().get("delay_between_videos", _DEFAULT_DELAY_SECONDS)
    return min(max(int(val), _MIN_DELAY_SECONDS), _MAX_DELAY_SECONDS)


def get_auto_publish() -> bool:
    """Returns whether videos should be auto-published after generation."""
    return bool(_get_batch_config().get("auto_publish", False))


def get_publish_platforms() -> list:
    """Returns the default platforms for auto-publishing batch videos."""
    return _get_batch_config().get("publish_platforms", ["youtube"])


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BatchVideoResult:
    """Result of generating a single video in a batch."""

    topic: str
    success: bool
    video_path: str = ""
    error_type: str = ""
    duration_seconds: float = 0.0
    published: bool = False
    publish_results: list = field(default_factory=list)


@dataclass
class BatchResult:
    """Aggregated result of a batch generation run."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    published: int = 0
    videos: list = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Serializes the batch result to a dictionary."""
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "published": self.published,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "videos": [
                {
                    "topic": v.topic[:100],
                    "success": v.success,
                    "error_type": v.error_type,
                    "duration_seconds": round(v.duration_seconds, 2),
                    "published": v.published,
                }
                for v in self.videos
            ],
        }

    def to_text(self) -> str:
        """Returns a human-readable summary of the batch run."""
        lines = [
            "Batch Generation Report",
            f"  Started: {self.started_at}",
            f"  Completed: {self.completed_at}",
            f"  Duration: {self.duration_seconds:.1f}s",
            f"  Total: {self.total}",
            f"  Succeeded: {self.succeeded}",
            f"  Failed: {self.failed}",
            f"  Published: {self.published}",
        ]
        return "\n".join(lines)


@dataclass
class BatchJob:
    """Describes a batch video generation job."""

    topics: list = field(default_factory=list)
    niche: str = "general"
    language: str = "en"
    auto_publish: bool = False
    publish_platforms: list = field(default_factory=list)

    def validate(self) -> None:
        """
        Validates the batch job fields.

        Raises:
            ValueError: If any field is invalid.
        """
        if not isinstance(self.topics, list):
            raise ValueError("topics must be a list.")
        if len(self.topics) == 0:
            raise ValueError("topics list must not be empty.")
        if len(self.topics) > _MAX_TOPICS:
            raise ValueError(
                f"Too many topics (max {_MAX_TOPICS}). "
                f"Got {len(self.topics)}."
            )

        for i, topic in enumerate(self.topics):
            if not isinstance(topic, str) or not topic.strip():
                raise ValueError(
                    f"Topic at index {i} must be a non-empty string."
                )
            if "\x00" in topic:
                raise ValueError(
                    f"Topic at index {i} contains null bytes."
                )
            if len(topic) > _MAX_TOPIC_LENGTH:
                raise ValueError(
                    f"Topic at index {i} exceeds maximum length of "
                    f"{_MAX_TOPIC_LENGTH}."
                )

        if not isinstance(self.niche, str):
            raise ValueError("niche must be a string.")
        if len(self.niche) > 200:
            raise ValueError("niche exceeds maximum length of 200.")

        if not isinstance(self.language, str):
            raise ValueError("language must be a string.")
        if len(self.language) > 10:
            raise ValueError("language code exceeds maximum length of 10.")

        allowed_platforms = {"youtube", "tiktok", "twitter", "instagram"}
        for p in self.publish_platforms:
            if not isinstance(p, str) or p.lower() not in allowed_platforms:
                raise ValueError(
                    f"Unknown publish platform: {p}. "
                    f"Allowed: {', '.join(sorted(allowed_platforms))}"
                )


# ---------------------------------------------------------------------------
# Batch Generator
# ---------------------------------------------------------------------------

class BatchGenerator:
    """
    Orchestrates batch video generation across multiple topics.

    For each topic, generates a complete video using the YouTube pipeline
    (topic → script → images → audio → subtitles → composite), then
    optionally publishes to configured platforms.
    """

    def __init__(self):
        self._max_per_run = get_max_videos_per_run()
        self._delay = get_delay_between_videos()
        self._auto_publish = get_auto_publish()
        self._publish_platforms = get_publish_platforms()

    def run(self, job: BatchJob) -> BatchResult:
        """
        Executes a batch video generation job.

        Args:
            job: A BatchJob describing the topics and settings.

        Returns:
            BatchResult with per-video outcomes and aggregate stats.
        """
        # Validate input
        job.validate()

        # Plugin lifecycle: batch start
        try:
            pm = _get_plugin_manager()
            if pm:
                pm.hook.on_batch_start(job={
                    "topics_count": len(job.topics),
                    "niche": job.niche,
                    "language": job.language,
                    "auto_publish": job.auto_publish,
                })
        except Exception:
            pass

        # Apply per-run cap
        topics = job.topics[:self._max_per_run]

        result = BatchResult(
            total=len(topics),
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        info(f" => Starting batch generation: {len(topics)} video(s)")

        batch_start = time.monotonic()

        for idx, topic in enumerate(topics):
            info(
                f" => [{idx + 1}/{len(topics)}] Generating video..."
            )

            video_result = self._generate_single(
                topic=topic.strip(),
                niche=job.niche,
                language=job.language,
            )

            # Auto-publish if configured and generation succeeded
            if video_result.success and (
                job.auto_publish or self._auto_publish
            ):
                platforms = job.publish_platforms or self._publish_platforms
                if platforms and video_result.video_path:
                    video_result = self._auto_publish_video(
                        video_result, topic, platforms
                    )

            result.videos.append(video_result)

            if video_result.success:
                result.succeeded += 1
                if video_result.published:
                    result.published += 1
            else:
                result.failed += 1

            # Delay between generations (skip after last)
            if idx < len(topics) - 1:
                time.sleep(self._delay)

        batch_duration = time.monotonic() - batch_start
        result.completed_at = datetime.now(timezone.utc).isoformat()
        result.duration_seconds = batch_duration

        # Summary
        if result.failed == 0:
            success(
                f" => Batch complete: {result.succeeded}/{result.total} "
                f"videos generated successfully!"
            )
        else:
            warning(
                f" => Batch complete: {result.succeeded}/{result.total} "
                f"succeeded, {result.failed} failed."
            )

        # Track analytics
        self._track_batch_analytics(result)

        # Pipeline health reporting
        try:
            monitor = _get_health_monitor()
            if monitor:
                health_status = "ok" if result.failed == 0 else (
                    "degraded" if result.succeeded > 0 else "error"
                )
                monitor.report_health(
                    "batch_generator",
                    health_status,
                    error_msg="" if health_status == "ok" else f"{result.failed} video(s) failed",
                    metadata={
                        "total": result.total,
                        "succeeded": result.succeeded,
                        "failed": result.failed,
                        "duration_seconds": round(result.duration_seconds, 2),
                    },
                )
        except Exception:
            pass

        # Plugin lifecycle: batch complete
        try:
            pm = _get_plugin_manager()
            if pm:
                pm.hook.on_batch_complete(
                    job={"niche": job.niche, "language": job.language},
                    result=result.to_dict(),
                )
        except Exception:
            pass

        return result

    def _generate_single(
        self,
        topic: str,
        niche: str,
        language: str,
    ) -> BatchVideoResult:
        """
        Generates a single video for the given topic.

        Uses the YouTube video generation pipeline (without upload).

        Returns:
            BatchVideoResult with generation outcome.
        """
        start_time = time.monotonic()

        try:
            from classes.YouTube import YouTube
            from classes.Tts import TTS
            from cache import get_accounts

            accounts = get_accounts("youtube")
            if not accounts:
                return BatchVideoResult(
                    topic=topic[:100],
                    success=False,
                    error_type="NoYouTubeAccountConfigured",
                    duration_seconds=time.monotonic() - start_time,
                )

            account = accounts[0]
            yt = YouTube(
                account["id"],
                account["nickname"],
                account["firefox_profile"],
                niche or account.get("niche", "general"),
                language or account.get("language", "en"),
            )

            tts = TTS()

            try:
                # Override the topic for this generation
                yt.subject = topic
                yt.generate_video(tts)

                duration = time.monotonic() - start_time
                video_path = getattr(yt, "video_path", "")

                return BatchVideoResult(
                    topic=topic[:100],
                    success=True,
                    video_path=video_path or "",
                    duration_seconds=duration,
                )
            finally:
                try:
                    if hasattr(yt, "browser") and yt.browser:
                        yt.browser.quit()
                except Exception:
                    pass

        except Exception as e:
            duration = time.monotonic() - start_time
            logger.warning(
                "Batch video generation failed: %s", type(e).__name__
            )
            return BatchVideoResult(
                topic=topic[:100],
                success=False,
                error_type=type(e).__name__,
                duration_seconds=duration,
            )

    def _auto_publish_video(
        self,
        video_result: BatchVideoResult,
        topic: str,
        platforms: list,
    ) -> BatchVideoResult:
        """Publishes a generated video to the configured platforms."""
        try:
            from publisher import ContentPublisher, PublishJob

            pub_job = PublishJob(
                video_path=video_result.video_path,
                title=topic[:200],
                description=f"Auto-generated video about {topic[:100]}",
                platforms=platforms,
            )

            publisher = ContentPublisher()
            pub_results = publisher.publish(pub_job)

            video_result.published = any(r.success for r in pub_results)
            video_result.publish_results = [
                {"platform": r.platform, "success": r.success}
                for r in pub_results
            ]

        except Exception as e:
            logger.warning(
                "Auto-publish failed: %s", type(e).__name__
            )

        return video_result

    def _track_batch_analytics(self, result: BatchResult) -> None:
        """Tracks the batch generation in analytics."""
        try:
            from analytics import track_event

            track_event(
                event_type="batch_generated",
                platform="system",
                details={
                    "total": result.total,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "published": result.published,
                    "duration_seconds": round(result.duration_seconds, 2),
                },
            )
        except Exception as e:
            logger.debug(
                "Failed to track batch analytics: %s", type(e).__name__
            )

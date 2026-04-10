"""
Multi-platform content publisher for MoneyPrinter.

Orchestrates simultaneous publishing of generated content across multiple
platforms (YouTube, TikTok, Twitter). Supports configurable platform lists,
retry logic, analytics tracking, and webhook notifications.

Usage:
    from publisher import ContentPublisher, PublishJob

    job = PublishJob(
        video_path="/path/to/video.mp4",
        title="My Video Title",
        description="Video description",
        platforms=["youtube", "tiktok", "twitter"],
    )
    publisher = ContentPublisher()
    results = publisher.publish(job)

Configuration (config.json):
    "publisher": {
        "platforms": ["youtube", "tiktok"],
        "retry_failed": true,
        "max_retries": 2
    }
"""

import time
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import _get, get_verbose
from mp_logger import get_logger
from status import success, error, warning, info
from virality import score_content, SCORE_FAIR

logger = get_logger(__name__)

# Maximum allowed platforms to prevent abuse
_MAX_PLATFORMS = 10
# Maximum lengths for text fields
_MAX_TITLE_LENGTH = 500
_MAX_DESCRIPTION_LENGTH = 5000
_MAX_VIDEO_PATH_LENGTH = 1024


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PublishResult:
    """Result of publishing to a single platform."""

    platform: str
    success: bool
    timestamp: str = ""
    error_type: str = ""
    duration_seconds: float = 0.0
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class PublishJob:
    """Describes content to be published across platforms."""

    video_path: str
    title: str
    description: str = ""
    platforms: list = field(default_factory=list)
    twitter_text: Optional[str] = None
    tags: list = field(default_factory=list)

    def validate(self) -> None:
        """
        Validates the publish job fields.

        Raises:
            ValueError: If any field is invalid.
        """
        if not self.video_path or not isinstance(self.video_path, str):
            raise ValueError("video_path must be a non-empty string.")
        if len(self.video_path) > _MAX_VIDEO_PATH_LENGTH:
            raise ValueError(
                f"video_path exceeds maximum length of {_MAX_VIDEO_PATH_LENGTH}."
            )
        if "\x00" in self.video_path:
            raise ValueError("video_path contains null bytes.")
        if not os.path.isfile(self.video_path):
            raise ValueError(f"Video file does not exist: {self.video_path}")

        if not self.title or not isinstance(self.title, str):
            raise ValueError("title must be a non-empty string.")
        if len(self.title) > _MAX_TITLE_LENGTH:
            raise ValueError(
                f"title exceeds maximum length of {_MAX_TITLE_LENGTH}."
            )

        if self.description and len(self.description) > _MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"description exceeds maximum length of {_MAX_DESCRIPTION_LENGTH}."
            )

        if not isinstance(self.platforms, list):
            raise ValueError("platforms must be a list.")
        if len(self.platforms) > _MAX_PLATFORMS:
            raise ValueError(
                f"Too many platforms specified (max {_MAX_PLATFORMS})."
            )

        allowed_platforms = {"youtube", "tiktok", "twitter"}
        for p in self.platforms:
            if not isinstance(p, str) or p.lower() not in allowed_platforms:
                raise ValueError(
                    f"Unknown platform: {p}. "
                    f"Allowed: {', '.join(sorted(allowed_platforms))}"
                )


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_publisher_config() -> dict:
    """Returns the publisher configuration block."""
    return _get("publisher", {})


def get_default_platforms() -> list:
    """Returns the default platform list from config."""
    return _get_publisher_config().get("platforms", ["youtube"])


def get_retry_failed() -> bool:
    """Returns whether failed publishes should be retried."""
    return bool(_get_publisher_config().get("retry_failed", True))


def get_max_retries() -> int:
    """Returns the max retry count for failed publishes."""
    val = _get_publisher_config().get("max_retries", 2)
    # Cap retries to prevent abuse
    return min(int(val), 10)


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

class ContentPublisher:
    """
    Orchestrates content publishing across multiple platforms.

    Publishes a video/content to each configured platform sequentially,
    with error handling, retry logic, analytics tracking, and webhook
    notifications for each platform result.
    """

    def __init__(self):
        self._retry_failed = get_retry_failed()
        self._max_retries = get_max_retries()

    def publish(self, job: PublishJob) -> list:
        """
        Publishes content across all platforms in the job.

        Args:
            job: A PublishJob describing the content and target platforms.

        Returns:
            List of PublishResult objects, one per platform.
        """
        # Use configured defaults if no platforms specified
        if not job.platforms:
            job.platforms = get_default_platforms()

        # Validate the job
        job.validate()

        verbose = get_verbose()
        results = []

        # Virality pre-check: warn when content score is below threshold
        self._check_virality(job)

        if verbose:
            info(
                f" => Publishing to {len(job.platforms)} platform(s): "
                f"{', '.join(job.platforms)}"
            )

        for platform_name in job.platforms:
            platform = platform_name.lower().strip()
            result = self._publish_to_platform(job, platform)

            # Retry on failure if configured
            if not result.success and self._retry_failed:
                for attempt in range(1, self._max_retries + 1):
                    if verbose:
                        warning(
                            f" => Retry {attempt}/{self._max_retries} "
                            f"for {platform}..."
                        )
                    # Exponential backoff: 2s, 4s, 8s...
                    time.sleep(min(2 ** attempt, 30))
                    result = self._publish_to_platform(job, platform)
                    if result.success:
                        break

            results.append(result)

            # Track analytics
            self._track_analytics(result, job)

            # Send webhook notification
            self._send_notification(result, job)

        # Summary
        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded
        if failed == 0:
            success(
                f" => Published to all {succeeded} platform(s) successfully!"
            )
        else:
            warning(
                f" => Published to {succeeded}/{len(results)} platforms. "
                f"{failed} failed."
            )

        return results

    def _check_virality(self, job: PublishJob) -> None:
        """
        Scores content virality before publishing and logs a warning
        if the score falls below the SCORE_FAIR threshold (40).

        This does not block publishing — it surfaces improvement suggestions
        so the user can iterate before the next content cycle.
        """
        try:
            result = score_content(
                script=job.description or job.title,
                title=job.title,
            )
            info(
                f" => Virality score: {result.overall}/100 "
                f"({result.label}, Grade {result.grade})"
            )
            if result.overall < SCORE_FAIR and result.suggestions:
                warning(
                    " => Low virality score. Top suggestion: "
                    + result.suggestions[0]
                )
        except Exception:
            # Virality check is non-critical — never block publishing
            pass

    def _publish_to_platform(
        self, job: PublishJob, platform: str
    ) -> PublishResult:
        """
        Publishes to a single platform.

        Args:
            job: The publish job.
            platform: Target platform name.

        Returns:
            PublishResult with success/failure details.
        """
        start_time = time.monotonic()

        try:
            if platform == "youtube":
                return self._publish_youtube(job, start_time)
            elif platform == "tiktok":
                return self._publish_tiktok(job, start_time)
            elif platform == "twitter":
                return self._publish_twitter(job, start_time)
            else:
                return PublishResult(
                    platform=platform,
                    success=False,
                    error_type="UnsupportedPlatform",
                    duration_seconds=time.monotonic() - start_time,
                )
        except Exception as e:
            duration = time.monotonic() - start_time
            logger.warning(
                f"Publish to {platform} failed: {type(e).__name__}"
            )
            return PublishResult(
                platform=platform,
                success=False,
                error_type=type(e).__name__,
                duration_seconds=duration,
            )

    def _publish_youtube(
        self, job: PublishJob, start_time: float
    ) -> PublishResult:
        """Publishes video to YouTube."""
        from classes.YouTube import YouTube
        from cache import get_accounts

        accounts = get_accounts("youtube")
        if not accounts:
            return PublishResult(
                platform="youtube",
                success=False,
                error_type="NoAccountConfigured",
                duration_seconds=time.monotonic() - start_time,
            )

        account = accounts[0]  # Use first configured account
        yt = YouTube(
            account["id"],
            account["nickname"],
            account["firefox_profile"],
            account["niche"],
            account["language"],
        )

        try:
            # Set metadata directly since video is already generated
            yt.video_path = os.path.abspath(job.video_path)
            yt.metadata = {
                "title": job.title,
                "description": job.description,
            }

            upload_success = yt.upload_video()
            duration = time.monotonic() - start_time

            return PublishResult(
                platform="youtube",
                success=upload_success,
                error_type="" if upload_success else "UploadFailed",
                duration_seconds=duration,
                details={
                    "title": job.title,
                    "account": account.get("nickname", ""),
                },
            )
        finally:
            try:
                yt.browser.quit()
            except Exception:
                pass

    def _publish_tiktok(
        self, job: PublishJob, start_time: float
    ) -> PublishResult:
        """Publishes video to TikTok."""
        from classes.TikTok import TikTok
        from cache import get_accounts

        # TikTok uses YouTube accounts' Firefox profiles for now
        accounts = get_accounts("youtube")
        if not accounts:
            return PublishResult(
                platform="tiktok",
                success=False,
                error_type="NoAccountConfigured",
                duration_seconds=time.monotonic() - start_time,
            )

        account = accounts[0]
        tiktok = TikTok(
            account["id"],
            account["nickname"],
            account["firefox_profile"],
            account.get("niche", ""),
        )

        try:
            upload_success = tiktok.upload_video(
                video_path=job.video_path,
                title=job.title,
                description=job.description,
            )
            duration = time.monotonic() - start_time

            return PublishResult(
                platform="tiktok",
                success=upload_success,
                error_type="" if upload_success else "UploadFailed",
                duration_seconds=duration,
                details={"title": job.title},
            )
        finally:
            try:
                tiktok.browser.quit()
            except Exception:
                pass

    def _publish_twitter(
        self, job: PublishJob, start_time: float
    ) -> PublishResult:
        """Posts content to Twitter/X."""
        from classes.Twitter import Twitter
        from cache import get_accounts

        accounts = get_accounts("twitter")
        if not accounts:
            return PublishResult(
                platform="twitter",
                success=False,
                error_type="NoAccountConfigured",
                duration_seconds=time.monotonic() - start_time,
            )

        account = accounts[0]
        twitter = Twitter(
            account["id"],
            account["nickname"],
            account["firefox_profile"],
            account.get("topic", ""),
        )

        try:
            # Use custom twitter text or generate from title
            text = job.twitter_text or f"{job.title}\n\n{job.description}"
            # Truncate to Twitter limit
            if len(text) > 280:
                text = text[:277].rsplit(" ", 1)[0] + "..."

            twitter.post(text)
            duration = time.monotonic() - start_time

            return PublishResult(
                platform="twitter",
                success=True,
                duration_seconds=duration,
                details={"text_length": len(text)},
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return PublishResult(
                platform="twitter",
                success=False,
                error_type=type(e).__name__,
                duration_seconds=duration,
            )
        finally:
            try:
                twitter.browser.quit()
            except Exception:
                pass

    def _track_analytics(
        self, result: PublishResult, job: PublishJob
    ) -> None:
        """Tracks a publish result in analytics."""
        try:
            from analytics import track_event

            event_type = (
                "video_uploaded" if result.success else "publish_failed"
            )
            track_event(
                event_type=event_type,
                platform=result.platform,
                details={
                    "title": job.title,
                    "duration_seconds": round(result.duration_seconds, 2),
                    "error_type": result.error_type,
                },
            )
        except Exception as e:
            logger.debug(
                f"Failed to track analytics: {type(e).__name__}"
            )

    def _send_notification(
        self, result: PublishResult, job: PublishJob
    ) -> None:
        """Sends webhook notification for a publish result."""
        try:
            from webhooks import notify, notify_error

            if result.success:
                notify(
                    event_type="video_uploaded",
                    platform=result.platform,
                    message=f"Successfully published to {result.platform}",
                    details={
                        "title": job.title,
                        "duration": f"{result.duration_seconds:.1f}s",
                    },
                )
            else:
                notify_error(
                    error_message=(
                        f"Failed to publish to {result.platform}: "
                        f"{result.error_type}"
                    ),
                    platform=result.platform,
                    details={"title": job.title},
                )
        except Exception as e:
            logger.debug(
                f"Failed to send webhook notification: {type(e).__name__}"
            )

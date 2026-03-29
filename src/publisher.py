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

logger = get_logger(__name__)

# Maximum allowed platforms to prevent abuse
_MAX_PLATFORMS = 10
# Maximum lengths for text fields
_MAX_TITLE_LENGTH = 500
_MAX_DESCRIPTION_LENGTH = 5000
_MAX_VIDEO_PATH_LENGTH = 1024
_MAX_AFFILIATE_LINKS = 10
_MAX_AFFILIATE_LABEL_LENGTH = 200
_MAX_AFFILIATE_URL_LENGTH = 2048


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
    script: str = ""  # for uniqueness scoring
    affiliate_links: list = field(default_factory=list)  # list of {"url": str, "label": str}

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
            raise ValueError("Video file does not exist at the specified path.")

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

        allowed_platforms = {"youtube", "tiktok", "twitter", "instagram"}
        for p in self.platforms:
            if not isinstance(p, str) or p.lower() not in allowed_platforms:
                raise ValueError(
                    f"Unknown platform: {p}. "
                    f"Allowed: {', '.join(sorted(allowed_platforms))}"
                )

        # Validate affiliate links
        if len(self.affiliate_links) > _MAX_AFFILIATE_LINKS:
            raise ValueError(f"Too many affiliate links: {len(self.affiliate_links)} (max {_MAX_AFFILIATE_LINKS})")
        for i, link in enumerate(self.affiliate_links):
            if not isinstance(link, dict):
                raise ValueError(f"Affiliate link {i} must be a dict")
            url = link.get("url", "")
            label = link.get("label", "")
            if not url:
                raise ValueError(f"Affiliate link {i} missing 'url'")
            if not isinstance(url, str) or len(url) > _MAX_AFFILIATE_URL_LENGTH:
                raise ValueError(f"Affiliate link {i} URL too long or invalid")
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"Affiliate link {i} URL must start with http:// or https://")
            if label and len(str(label)) > _MAX_AFFILIATE_LABEL_LENGTH:
                raise ValueError(f"Affiliate link {i} label too long (max {_MAX_AFFILIATE_LABEL_LENGTH})")


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


def get_uniqueness_mode() -> str:
    """Returns the uniqueness check mode: 'block', 'warn', or 'off'."""
    mode = _get_publisher_config().get("uniqueness_mode", "warn")
    if mode not in ("block", "warn", "off"):
        logger.warning(f"Invalid uniqueness_mode '{mode}', defaulting to 'warn'")
        return "warn"
    return mode


def _format_affiliate_links(links: list, platform: str) -> str:
    """Format affiliate links for a specific platform.

    Args:
        links: List of dicts with 'url' and 'label' keys.
        platform: Target platform (youtube, tiktok, twitter, instagram).

    Returns:
        Formatted string to append to description. Empty string if no links.
    """
    if not links:
        return ""

    valid_links = [
        lnk for lnk in links
        if isinstance(lnk, dict) and lnk.get("url")
    ]
    if not valid_links:
        return ""

    if platform == "twitter":
        # Compact format for Twitter's character limit
        parts = []
        for lnk in valid_links:
            label = lnk.get("label", "Link")
            parts.append(f"{label}: {lnk['url']}")
        return " | " + " | ".join(parts)

    if platform == "instagram":
        # Instagram doesn't support clickable links in descriptions
        parts = []
        for lnk in valid_links:
            label = lnk.get("label", "Product")
            parts.append(f"  {label} (link in bio)")
        return "\n\n" + "\n".join(parts)

    if platform == "tiktok":
        parts = []
        for lnk in valid_links:
            label = lnk.get("label", "Link")
            parts.append(f"  {label} -> {lnk['url']}")
        return "\n\nLinks:\n" + "\n".join(parts)

    # YouTube and others: full format
    parts = []
    for lnk in valid_links:
        label = lnk.get("label", "Link")
        parts.append(f"  {label}: {lnk['url']}")
    return "\n\nShop:\n" + "\n".join(parts)


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
        self._uniqueness_mode = get_uniqueness_mode()

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

        # Pre-publish uniqueness check
        blocked = self._check_uniqueness(job)
        if blocked is not None:
            return blocked

        results = []

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

        # Post-publish: update uniqueness history
        if any(r.success for r in results):
            self._update_uniqueness_history(job)

        return results

    def _check_uniqueness(self, job: PublishJob) -> Optional[list]:
        """Run uniqueness check before publishing.

        Returns None if publishing should proceed.
        Returns list of PublishResult if publishing should be blocked.
        """
        if self._uniqueness_mode == "off":
            return None

        try:
            from uniqueness_scorer import UniquenessScorer
            scorer = UniquenessScorer()

            # Use script if available, fallback to description
            script_text = job.script if job.script else job.description

            result = scorer.score_content(
                title=job.title,
                script=script_text,
                tags=job.tags,
                description=job.description,
            )

            if result.flagged:
                if self._uniqueness_mode == "block":
                    warning(
                        f" => Content flagged as non-unique (score={result.overall:.2f}). "
                        f"Publishing blocked."
                    )
                    logger.warning(
                        f"Uniqueness check BLOCKED publish: score={result.overall:.3f}"
                    )
                    return [
                        PublishResult(
                            platform=p,
                            success=False,
                            error_type="UniquenessBlocked",
                            details={
                                "uniqueness_score": result.overall,
                                "uniqueness_flagged": True,
                            },
                        )
                        for p in (job.platforms or get_default_platforms())
                    ]
                else:  # warn mode
                    warning(
                        f" => Content uniqueness warning (score={result.overall:.2f}). "
                        f"Publishing anyway."
                    )
                    logger.warning(
                        f"Uniqueness check WARNING: score={result.overall:.3f}"
                    )
        except Exception as e:
            # Don't block publishing if uniqueness scorer fails
            logger.warning(f"Uniqueness check failed: {type(e).__name__}: {e}")

        return None

    def _update_uniqueness_history(self, job: PublishJob) -> None:
        """Add published content to uniqueness history."""
        if self._uniqueness_mode == "off":
            return

        try:
            from uniqueness_scorer import UniquenessScorer
            scorer = UniquenessScorer()
            script_text = job.script if job.script else job.description
            scorer.add_to_history(
                title=job.title,
                script=script_text,
                tags=job.tags,
                description=job.description,
            )
        except Exception as e:
            logger.warning(f"Failed to update uniqueness history: {type(e).__name__}: {e}")

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

        # Inject affiliate links into description for this platform
        enriched_description = job.description
        if job.affiliate_links:
            enriched_description += _format_affiliate_links(
                job.affiliate_links, platform
            )

        try:
            if platform == "youtube":
                return self._publish_youtube(job, start_time, enriched_description)
            elif platform == "tiktok":
                return self._publish_tiktok(job, start_time, enriched_description)
            elif platform == "twitter":
                return self._publish_twitter(job, start_time, enriched_description)
            elif platform == "instagram":
                return self._publish_instagram(job, start_time, enriched_description)
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
        self, job: PublishJob, start_time: float, description: str = None
    ) -> PublishResult:
        """Publishes video to YouTube."""
        from classes.YouTube import YouTube
        from cache import get_accounts

        if description is None:
            description = job.description

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
                "description": description,
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
                if hasattr(yt, "browser") and yt.browser:
                    yt.browser.quit()
            except Exception:
                pass

    def _publish_tiktok(
        self, job: PublishJob, start_time: float, description: str = None
    ) -> PublishResult:
        """Publishes video to TikTok."""
        from classes.TikTok import TikTok
        from cache import get_accounts

        if description is None:
            description = job.description

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
                description=description,
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
                if hasattr(tiktok, "browser") and tiktok.browser:
                    tiktok.browser.quit()
            except Exception:
                pass

    def _publish_twitter(
        self, job: PublishJob, start_time: float, description: str = None
    ) -> PublishResult:
        """Posts content to Twitter/X."""
        from classes.Twitter import Twitter
        from cache import get_accounts

        if description is None:
            description = job.description

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
            text = job.twitter_text or f"{job.title}\n\n{description}"
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
                if hasattr(twitter, "browser") and twitter.browser:
                    twitter.browser.quit()
            except Exception:
                pass

    def _publish_instagram(
        self, job: PublishJob, start_time: float, description: str = None
    ) -> PublishResult:
        """Publishes video to Instagram Reels."""
        from classes.Instagram import Instagram
        from cache import get_accounts

        if description is None:
            description = job.description

        accounts = get_accounts("instagram")
        if not accounts:
            return PublishResult(
                platform="instagram",
                success=False,
                error_type="NoAccountConfigured",
                duration_seconds=time.monotonic() - start_time,
            )

        account = accounts[0]

        try:
            ig = Instagram(
                account_id=account["id"],
                nickname=account["nickname"],
                username=account.get("username", ""),
                password=account.get("password", ""),
            )

            caption = job.title
            if description:
                caption += "\n\n" + description
            if job.tags:
                caption += "\n\n" + " ".join(
                    f"#{t}" if not t.startswith("#") else t
                    for t in job.tags[:30]
                )

            upload_success = ig.upload_reel(
                video_path=job.video_path,
                caption=caption,
            )
            duration = time.monotonic() - start_time

            return PublishResult(
                platform="instagram",
                success=upload_success,
                error_type="" if upload_success else "UploadFailed",
                duration_seconds=duration,
                details={
                    "title": job.title,
                    "account": account.get("nickname", ""),
                },
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return PublishResult(
                platform="instagram",
                success=False,
                error_type=type(e).__name__,
                duration_seconds=duration,
            )

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

"""
Per-video engagement metrics tracker for MoneyPrinter.

Stores views, likes, comments, and shares per video per platform with
atomic JSON persistence, trend computation, and top-performers queries.

Usage:
    from video_analytics import VideoAnalyticsTracker

    tracker = VideoAnalyticsTracker()
    tracker.record_metrics("vid_abc", "youtube", views=1200, likes=88)
    latest = tracker.get_latest_metrics("vid_abc", "youtube")
    trend  = tracker.get_trend("vid_abc", "youtube", metric="views", days=7)
"""

import os
import json
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import ROOT_DIR
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MAX_RECORDS_PER_VIDEO = 1000
_MAX_TOTAL_RECORDS = 100_000
_SUPPORTED_PLATFORMS = {"youtube", "tiktok", "twitter", "instagram"}
_VALID_METRICS = {"views", "likes", "comments", "shares"}
_ANALYTICS_FILE = os.path.join(ROOT_DIR, ".mp", "video_analytics.json")


# ---------------------------------------------------------------------------
# VideoMetrics dataclass
# ---------------------------------------------------------------------------


@dataclass
class VideoMetrics:
    """Snapshot of engagement metrics for a single video on a single platform."""

    video_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.recorded_at:
            self.recorded_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Serialise to a plain dict (suitable for JSON storage)."""
        return {
            "video_id": self.video_id,
            "platform": self.platform,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoMetrics":
        """Deserialise from a plain dict."""
        return cls(
            video_id=d.get("video_id", ""),
            platform=d.get("platform", ""),
            views=int(d.get("views", 0)),
            likes=int(d.get("likes", 0)),
            comments=int(d.get("comments", 0)),
            shares=int(d.get("shares", 0)),
            recorded_at=d.get("recorded_at", ""),
        )


# ---------------------------------------------------------------------------
# VideoAnalyticsTracker
# ---------------------------------------------------------------------------


class VideoAnalyticsTracker:
    """
    Thread-safe tracker for per-video engagement metrics.

    Data is persisted atomically to a JSON file under `.mp/`.  Each
    `record_metrics()` call appends a new :class:`VideoMetrics` snapshot;
    old entries are rotated when per-video or global caps are exceeded.
    """

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self._path = storage_path or _ANALYTICS_FILE
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_metrics(
        self,
        video_id: str,
        platform: str,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
    ) -> VideoMetrics:
        """
        Record a new engagement-metrics snapshot for *video_id* on *platform*.

        Args:
            video_id: Opaque string that uniquely identifies the video.
            platform: One of the supported platform names.
            views: Current view count.
            likes: Current like count.
            comments: Current comment count.
            shares: Current share count.

        Returns:
            The newly created :class:`VideoMetrics` instance.

        Raises:
            ValueError: If *platform* is not in ``_SUPPORTED_PLATFORMS``.
        """
        _validate_platform(platform)

        metrics = VideoMetrics(
            video_id=video_id,
            platform=platform,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
        )

        with self._lock:
            data = self._load()
            records: list[dict] = data.setdefault("records", [])
            records.append(metrics.to_dict())

            # --- per-(video_id, platform) cap ---
            key_records = [
                r for r in records
                if r["video_id"] == video_id and r["platform"] == platform
            ]
            if len(key_records) > _MAX_RECORDS_PER_VIDEO:
                # Identify oldest records for this key and drop them
                excess = len(key_records) - _MAX_RECORDS_PER_VIDEO
                removed = 0
                kept: list[dict] = []
                for r in records:
                    if (
                        r["video_id"] == video_id
                        and r["platform"] == platform
                        and removed < excess
                    ):
                        removed += 1
                    else:
                        kept.append(r)
                records = kept

            # --- global cap ---
            if len(records) > _MAX_TOTAL_RECORDS:
                records = records[-_MAX_TOTAL_RECORDS:]

            data["records"] = records
            self._save(data)

        logger.debug(
            "Recorded metrics for video_id=%s platform=%s views=%d",
            video_id,
            platform,
            views,
        )
        return metrics

    def get_metrics(
        self,
        video_id: str,
        platform: Optional[str] = None,
    ) -> list:
        """
        Return all recorded snapshots for *video_id*, optionally filtered by
        *platform*, in chronological order.

        Args:
            video_id: Video to look up.
            platform: If given, restrict to this platform.

        Returns:
            List of :class:`VideoMetrics` objects (oldest first).
        """
        if platform is not None:
            _validate_platform(platform)

        with self._lock:
            data = self._load()

        records = data.get("records", [])
        result = []
        for r in records:
            if r.get("video_id") != video_id:
                continue
            if platform is not None and r.get("platform") != platform:
                continue
            result.append(VideoMetrics.from_dict(r))
        return result

    def get_latest_metrics(
        self,
        video_id: str,
        platform: str,
    ) -> Optional[VideoMetrics]:
        """
        Return the most recently recorded snapshot for *(video_id, platform)*.

        Args:
            video_id: Video to look up.
            platform: Platform to look up.

        Returns:
            :class:`VideoMetrics` or ``None`` if no records exist.

        Raises:
            ValueError: If *platform* is not supported.
        """
        _validate_platform(platform)
        snapshots = self.get_metrics(video_id, platform)
        return snapshots[-1] if snapshots else None

    def get_top_videos(
        self,
        platform: Optional[str] = None,
        metric: str = "views",
        limit: int = 10,
    ) -> list:
        """
        Return the top *limit* videos ranked by *metric* (descending).

        One entry per *(video_id, platform)* pair — the latest snapshot is
        used for the ranking value.

        Args:
            platform: Restrict to this platform; ``None`` means all platforms.
            metric: One of ``_VALID_METRICS``.
            limit: Maximum number of results.

        Returns:
            List of :class:`VideoMetrics` objects.

        Raises:
            ValueError: If *platform* or *metric* is invalid.
        """
        if platform is not None:
            _validate_platform(platform)
        _validate_metric(metric)

        with self._lock:
            data = self._load()

        records = data.get("records", [])

        # Build a dict keyed by (video_id, platform) keeping the latest record
        # (records are stored in append order, so a simple pass retaining last
        # occurrence is enough — a second pass preserving insertion order for
        # determinism is not needed here).
        latest: dict[tuple, dict] = {}
        for r in records:
            plat = r.get("platform", "")
            if platform is not None and plat != platform:
                continue
            key = (r.get("video_id", ""), plat)
            latest[key] = r  # later records overwrite earlier ones

        ranked = sorted(
            latest.values(),
            key=lambda r: r.get(metric, 0),
            reverse=True,
        )
        return [VideoMetrics.from_dict(r) for r in ranked[:limit]]

    def get_trend(
        self,
        video_id: str,
        platform: str,
        metric: str = "views",
        days: int = 7,
    ) -> dict:
        """
        Compare the most recent *days*-day window against the previous one.

        The "current" window covers the last *days* days; the "previous"
        window covers the *days* days immediately before that.  Each window
        value is the **maximum** of *metric* observed within that window
        (reflecting peak engagement rather than an average).

        Args:
            video_id: Video to analyse.
            platform: Platform to analyse.
            metric: Engagement dimension to compare.
            days: Window length in days (must be > 0).

        Returns:
            Dict with keys: ``current``, ``previous``, ``change``,
            ``change_pct``.

        Raises:
            ValueError: If *platform*, *metric*, or *days* is invalid.
        """
        _validate_platform(platform)
        _validate_metric(metric)
        if days <= 0:
            raise ValueError(f"days must be a positive integer, got {days!r}")

        snapshots = self.get_metrics(video_id, platform)

        now = datetime.now(timezone.utc)
        current_start = now - timedelta(days=days)
        previous_start = current_start - timedelta(days=days)

        current_vals: list[int] = []
        previous_vals: list[int] = []

        for snap in snapshots:
            try:
                ts = datetime.fromisoformat(snap.recorded_at)
                # Ensure tz-aware for comparison
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            val = getattr(snap, metric, 0)
            if ts >= current_start:
                current_vals.append(val)
            elif ts >= previous_start:
                previous_vals.append(val)

        current = max(current_vals) if current_vals else 0
        previous = max(previous_vals) if previous_vals else 0
        change = current - previous
        change_pct = (change / previous * 100.0) if previous else 0.0

        return {
            "current": current,
            "previous": previous,
            "change": change,
            "change_pct": round(change_pct, 2),
        }

    def get_platform_summary(self, platform: str) -> dict:
        """
        Aggregate engagement totals and averages across all videos on
        *platform*.

        Only the **latest** snapshot per *(video_id, platform)* pair
        contributes to the aggregation — this avoids double-counting
        historical snapshots.

        Args:
            platform: Platform to summarise.

        Returns:
            Dict with keys: ``total_videos``, ``total_views``,
            ``total_likes``, ``total_comments``, ``total_shares``,
            ``avg_views``.

        Raises:
            ValueError: If *platform* is not supported.
        """
        _validate_platform(platform)

        with self._lock:
            data = self._load()

        records = data.get("records", [])

        # Keep only latest record per video_id for this platform
        latest: dict[str, dict] = {}
        for r in records:
            if r.get("platform") != platform:
                continue
            vid = r.get("video_id", "")
            latest[vid] = r

        total_videos = len(latest)
        total_views = sum(r.get("views", 0) for r in latest.values())
        total_likes = sum(r.get("likes", 0) for r in latest.values())
        total_comments = sum(r.get("comments", 0) for r in latest.values())
        total_shares = sum(r.get("shares", 0) for r in latest.values())
        avg_views = (total_views / total_videos) if total_videos else 0.0

        return {
            "total_videos": total_videos,
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "avg_views": round(avg_views, 2),
        }

    def delete_metrics(self, video_id: str) -> int:
        """
        Remove all records for *video_id* regardless of platform.

        Args:
            video_id: Video whose records should be deleted.

        Returns:
            The number of records deleted.
        """
        with self._lock:
            data = self._load()
            before = len(data.get("records", []))
            data["records"] = [
                r for r in data.get("records", [])
                if r.get("video_id") != video_id
            ]
            after = len(data["records"])
            deleted = before - after
            if deleted:
                self._save(data)

        logger.debug("Deleted %d record(s) for video_id=%s", deleted, video_id)
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        """Load records from disk; return empty structure on any error."""
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if not isinstance(data, dict):
                    return {"records": []}
                if "records" not in data or not isinstance(data["records"], list):
                    data["records"] = []
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"records": []}

    def _save(self, data: dict) -> None:
        """Atomically persist *data* to disk via tempfile + os.replace."""
        dir_name = os.path.dirname(self._path)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Private validators
# ---------------------------------------------------------------------------


def _validate_platform(platform: str) -> None:
    """Raise ValueError if *platform* is not in ``_SUPPORTED_PLATFORMS``."""
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(
            f"Unsupported platform {platform!r}. "
            f"Expected one of: {sorted(_SUPPORTED_PLATFORMS)}"
        )


def _validate_metric(metric: str) -> None:
    """Raise ValueError if *metric* is not in ``_VALID_METRICS``."""
    if metric not in _VALID_METRICS:
        raise ValueError(
            f"Invalid metric {metric!r}. "
            f"Expected one of: {sorted(_VALID_METRICS)}"
        )

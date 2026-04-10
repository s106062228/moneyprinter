"""
Revenue estimation and tracking for MoneyPrinter.

Estimates earnings from view counts using platform-specific CPM/RPM tables,
tracks cumulative revenue across platforms, computes ROI, and forecasts
monthly income based on recent trends.

Usage:
    from revenue_tracker import RevenueTracker, RevenueEntry

    tracker = RevenueTracker()
    tracker.record_revenue("vid_abc", "youtube", views=12000, niche="finance")
    summary = tracker.get_summary(days=30)
    forecast = tracker.forecast_monthly()

Configuration (config.json):
    "revenue": {
        "default_niche": "general",
        "currency": "USD",
        "custom_cpm": {"youtube": 8.0}
    }
"""

import os
import json
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import ROOT_DIR, _get
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MAX_ENTRIES = 50_000
_MAX_VIDEO_ID_LENGTH = 256
_MAX_NICHE_LENGTH = 100
_SUPPORTED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})
_REVENUE_FILE = os.path.join(ROOT_DIR, ".mp", "revenue_tracker.json")

# CPM rates (USD per 1,000 views) by niche — 2026 industry averages.
# Sources: OutlierKit, vidIQ, MilX, Miraflow aggregated data.
_CPM_BY_NICHE: dict[str, dict[str, float]] = {
    "finance": {"youtube": 12.0, "tiktok": 1.5, "twitter": 2.0, "instagram": 3.0},
    "technology": {"youtube": 9.5, "tiktok": 1.2, "twitter": 1.8, "instagram": 2.5},
    "health": {"youtube": 8.0, "tiktok": 1.0, "twitter": 1.5, "instagram": 2.2},
    "education": {"youtube": 7.5, "tiktok": 0.9, "twitter": 1.3, "instagram": 2.0},
    "gaming": {"youtube": 5.0, "tiktok": 0.8, "twitter": 1.0, "instagram": 1.5},
    "entertainment": {"youtube": 4.0, "tiktok": 0.7, "twitter": 0.8, "instagram": 1.2},
    "lifestyle": {"youtube": 5.5, "tiktok": 0.9, "twitter": 1.2, "instagram": 2.0},
    "cooking": {"youtube": 6.0, "tiktok": 0.8, "twitter": 1.0, "instagram": 1.8},
    "travel": {"youtube": 7.0, "tiktok": 1.0, "twitter": 1.4, "instagram": 2.5},
    "business": {"youtube": 11.0, "tiktok": 1.4, "twitter": 2.0, "instagram": 2.8},
    "general": {"youtube": 5.0, "tiktok": 0.8, "twitter": 1.0, "instagram": 1.5},
}

# Platform revenue share — the fraction creators actually keep.
_PLATFORM_REVENUE_SHARE: dict[str, float] = {
    "youtube": 0.45,   # YouTube Shorts 45% creator share
    "tiktok": 0.50,    # TikTok Creator Rewards ~50%
    "twitter": 1.0,    # Twitter/X creator payouts (direct)
    "instagram": 0.55, # Instagram Reels bonus program ~55%
}

_VALID_NICHES = frozenset(_CPM_BY_NICHE.keys())
_MAX_VIEWS = 10_000_000_000  # 10 billion, safety cap


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def get_revenue_default_niche() -> str:
    """Return the configured default niche, falling back to 'general'."""
    cfg = _get("revenue", {})
    if not isinstance(cfg, dict):
        return "general"
    niche = cfg.get("default_niche", "general")
    if not isinstance(niche, str) or niche not in _VALID_NICHES:
        return "general"
    return niche


def get_revenue_currency() -> str:
    """Return the configured currency label (display only)."""
    cfg = _get("revenue", {})
    if not isinstance(cfg, dict):
        return "USD"
    currency = cfg.get("currency", "USD")
    if not isinstance(currency, str):
        return "USD"
    return currency[:10]


def get_custom_cpm() -> dict[str, float]:
    """Return user-overridden CPM rates from config (platform -> float)."""
    cfg = _get("revenue", {})
    if not isinstance(cfg, dict):
        return {}
    custom = cfg.get("custom_cpm", {})
    if not isinstance(custom, dict):
        return {}
    result: dict[str, float] = {}
    for platform, rate in custom.items():
        if platform in _SUPPORTED_PLATFORMS:
            try:
                val = float(rate)
                if 0 < val <= 1000:
                    result[platform] = val
            except (TypeError, ValueError):
                pass
    return result


# ---------------------------------------------------------------------------
# RevenueEntry dataclass
# ---------------------------------------------------------------------------


@dataclass
class RevenueEntry:
    """A single revenue estimation record for a video on a platform."""

    video_id: str
    platform: str
    views: int = 0
    estimated_cpm: float = 0.0
    estimated_gross: float = 0.0
    estimated_net: float = 0.0
    niche: str = "general"
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.recorded_at:
            self.recorded_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON storage."""
        return {
            "video_id": self.video_id,
            "platform": self.platform,
            "views": self.views,
            "estimated_cpm": round(self.estimated_cpm, 4),
            "estimated_gross": round(self.estimated_gross, 4),
            "estimated_net": round(self.estimated_net, 4),
            "niche": self.niche,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RevenueEntry":
        """Deserialise from a plain dict with defensive validation."""
        if not isinstance(d, dict):
            raise TypeError("RevenueEntry.from_dict requires a dict")

        video_id = str(d.get("video_id", ""))[:_MAX_VIDEO_ID_LENGTH]
        platform = str(d.get("platform", ""))
        if platform not in _SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported platform: must be one of {sorted(_SUPPORTED_PLATFORMS)}")

        niche = str(d.get("niche", "general"))[:_MAX_NICHE_LENGTH]
        if niche not in _VALID_NICHES:
            niche = "general"

        views = int(d.get("views", 0))
        if views < 0:
            views = 0
        if views > _MAX_VIEWS:
            views = _MAX_VIEWS

        return cls(
            video_id=video_id,
            platform=platform,
            views=views,
            estimated_cpm=float(d.get("estimated_cpm", 0.0)),
            estimated_gross=float(d.get("estimated_gross", 0.0)),
            estimated_net=float(d.get("estimated_net", 0.0)),
            niche=niche,
            recorded_at=str(d.get("recorded_at", "")),
        )


# ---------------------------------------------------------------------------
# RevenueSummary dataclass
# ---------------------------------------------------------------------------


@dataclass
class RevenueSummary:
    """Aggregated revenue summary for a time period."""

    period_days: int = 30
    total_views: int = 0
    total_gross: float = 0.0
    total_net: float = 0.0
    by_platform: dict = field(default_factory=dict)
    by_niche: dict = field(default_factory=dict)
    entry_count: int = 0
    avg_cpm: float = 0.0
    currency: str = "USD"

    def to_dict(self) -> dict:
        return {
            "period_days": self.period_days,
            "total_views": self.total_views,
            "total_gross": round(self.total_gross, 2),
            "total_net": round(self.total_net, 2),
            "by_platform": {
                k: {kk: round(vv, 2) for kk, vv in v.items()}
                for k, v in self.by_platform.items()
            },
            "by_niche": {
                k: {kk: round(vv, 2) for kk, vv in v.items()}
                for k, v in self.by_niche.items()
            },
            "entry_count": self.entry_count,
            "avg_cpm": round(self.avg_cpm, 4),
            "currency": self.currency,
        }


# ---------------------------------------------------------------------------
# RevenueTracker class
# ---------------------------------------------------------------------------


class RevenueTracker:
    """Tracks estimated revenue across platforms and niches.

    Thread-safe via a reentrant lock. Data persisted atomically to JSON.
    """

    def __init__(self, data_file: Optional[str] = None) -> None:
        self._data_file = data_file or _REVENUE_FILE
        self._lock = threading.RLock()
        self._entries: list[dict] = []
        self._loaded = False

    # -- persistence --------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Lazy-load entries from disk on first access."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._entries = self._read_file()
            self._loaded = True

    def _read_file(self) -> list[dict]:
        """Read entries from JSON (TOCTOU-safe)."""
        try:
            with open(self._data_file, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                return data["entries"][-_MAX_ENTRIES:]
            return []
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            return []

    def _save_file(self) -> None:
        """Atomically persist entries to disk."""
        dir_name = os.path.dirname(self._data_file)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"entries": self._entries[-_MAX_ENTRIES:]}, f, indent=2)
            os.replace(tmp_path, self._data_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # -- CPM lookup ---------------------------------------------------------

    @staticmethod
    def get_cpm(platform: str, niche: str = "general") -> float:
        """Look up CPM rate for a platform + niche combination.

        Checks user-configured custom_cpm overrides first, then falls back
        to the built-in CPM table.
        """
        custom = get_custom_cpm()
        if platform in custom:
            return custom[platform]

        niche_rates = _CPM_BY_NICHE.get(niche, _CPM_BY_NICHE["general"])
        return niche_rates.get(platform, 1.0)

    @staticmethod
    def get_revenue_share(platform: str) -> float:
        """Return the creator revenue share fraction for a platform."""
        return _PLATFORM_REVENUE_SHARE.get(platform, 0.5)

    @staticmethod
    def estimate_revenue(
        views: int,
        platform: str,
        niche: str = "general",
    ) -> tuple[float, float, float]:
        """Estimate gross and net revenue for a given view count.

        Returns:
            (cpm, gross_revenue, net_revenue)
        """
        if views < 0:
            views = 0
        if views > _MAX_VIEWS:
            views = _MAX_VIEWS
        cpm = RevenueTracker.get_cpm(platform, niche)
        gross = (views / 1000.0) * cpm
        share = RevenueTracker.get_revenue_share(platform)
        net = gross * share
        return cpm, gross, net

    # -- recording ----------------------------------------------------------

    def record_revenue(
        self,
        video_id: str,
        platform: str,
        views: int,
        niche: Optional[str] = None,
    ) -> RevenueEntry:
        """Record a revenue estimation entry.

        Args:
            video_id: Unique video identifier.
            platform: Target platform (youtube, tiktok, twitter, instagram).
            views: Current view count.
            niche: Content niche for CPM lookup (defaults to config value).

        Returns:
            The created RevenueEntry.

        Raises:
            ValueError: If platform or video_id is invalid.
        """
        # -- input validation --
        if not isinstance(video_id, str) or not video_id.strip():
            raise ValueError("video_id must be a non-empty string")
        video_id = video_id.strip()[:_MAX_VIDEO_ID_LENGTH]

        if "\x00" in video_id:
            raise ValueError("video_id must not contain null bytes")

        if not isinstance(platform, str) or platform not in _SUPPORTED_PLATFORMS:
            raise ValueError(
                f"platform must be one of {sorted(_SUPPORTED_PLATFORMS)}"
            )

        if not isinstance(views, (int, float)):
            raise TypeError("views must be a number")
        views = int(views)
        if views < 0:
            views = 0
        if views > _MAX_VIEWS:
            views = _MAX_VIEWS

        if niche is None:
            niche = get_revenue_default_niche()
        if not isinstance(niche, str):
            niche = "general"
        niche = niche.strip()[:_MAX_NICHE_LENGTH]
        if niche not in _VALID_NICHES:
            niche = "general"

        cpm, gross, net = self.estimate_revenue(views, platform, niche)

        entry = RevenueEntry(
            video_id=video_id,
            platform=platform,
            views=views,
            estimated_cpm=cpm,
            estimated_gross=gross,
            estimated_net=net,
            niche=niche,
        )

        with self._lock:
            self._ensure_loaded()
            self._entries.append(entry.to_dict())
            # Rotate if over limit
            if len(self._entries) > _MAX_ENTRIES:
                self._entries = self._entries[-_MAX_ENTRIES:]
            self._save_file()

        logger.info(
            "Revenue recorded: video=%s platform=%s views=%d net=$%.2f",
            video_id[:32],
            platform,
            views,
            net,
        )
        return entry

    # -- queries ------------------------------------------------------------

    def get_entries(
        self,
        days: Optional[int] = None,
        platform: Optional[str] = None,
        niche: Optional[str] = None,
    ) -> list[RevenueEntry]:
        """Retrieve revenue entries with optional filters.

        Args:
            days: Only return entries from the last N days.
            platform: Filter by platform.
            niche: Filter by niche.

        Returns:
            List of matching RevenueEntry objects.
        """
        with self._lock:
            self._ensure_loaded()
            results: list[RevenueEntry] = []
            cutoff = None
            if days is not None:
                if not isinstance(days, int) or days < 1:
                    days = 1
                if days > 3650:
                    days = 3650
                cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=days)
                ).isoformat()

            for raw in self._entries:
                if not isinstance(raw, dict):
                    continue
                if platform and raw.get("platform") != platform:
                    continue
                if niche and raw.get("niche") != niche:
                    continue
                if cutoff and raw.get("recorded_at", "") < cutoff:
                    continue
                try:
                    results.append(RevenueEntry.from_dict(raw))
                except (TypeError, ValueError):
                    continue
            return results

    def get_summary(self, days: int = 30) -> RevenueSummary:
        """Compute an aggregated revenue summary for the last N days.

        Args:
            days: Time window in days (default 30).

        Returns:
            RevenueSummary with totals broken down by platform and niche.
        """
        entries = self.get_entries(days=days)
        summary = RevenueSummary(
            period_days=days,
            currency=get_revenue_currency(),
        )

        total_cpm_weighted = 0.0
        total_views_for_avg = 0

        for entry in entries:
            summary.total_views += entry.views
            summary.total_gross += entry.estimated_gross
            summary.total_net += entry.estimated_net
            summary.entry_count += 1

            total_cpm_weighted += entry.estimated_cpm * entry.views
            total_views_for_avg += entry.views

            # By platform
            if entry.platform not in summary.by_platform:
                summary.by_platform[entry.platform] = {
                    "views": 0,
                    "gross": 0.0,
                    "net": 0.0,
                }
            summary.by_platform[entry.platform]["views"] += entry.views
            summary.by_platform[entry.platform]["gross"] += entry.estimated_gross
            summary.by_platform[entry.platform]["net"] += entry.estimated_net

            # By niche
            if entry.niche not in summary.by_niche:
                summary.by_niche[entry.niche] = {
                    "views": 0,
                    "gross": 0.0,
                    "net": 0.0,
                }
            summary.by_niche[entry.niche]["views"] += entry.views
            summary.by_niche[entry.niche]["gross"] += entry.estimated_gross
            summary.by_niche[entry.niche]["net"] += entry.estimated_net

        if total_views_for_avg > 0:
            summary.avg_cpm = total_cpm_weighted / total_views_for_avg

        return summary

    def forecast_monthly(self, lookback_days: int = 7) -> dict:
        """Forecast monthly revenue based on recent daily averages.

        Args:
            lookback_days: Number of recent days to use as a baseline.

        Returns:
            Dict with projected monthly views, gross, and net revenue.
        """
        if not isinstance(lookback_days, int) or lookback_days < 1:
            lookback_days = 1
        if lookback_days > 365:
            lookback_days = 365

        recent = self.get_summary(days=lookback_days)
        if recent.entry_count == 0 or lookback_days == 0:
            return {
                "projected_monthly_views": 0,
                "projected_monthly_gross": 0.0,
                "projected_monthly_net": 0.0,
                "daily_avg_net": 0.0,
                "lookback_days": lookback_days,
                "currency": get_revenue_currency(),
            }

        daily_views = recent.total_views / lookback_days
        daily_gross = recent.total_gross / lookback_days
        daily_net = recent.total_net / lookback_days

        return {
            "projected_monthly_views": int(daily_views * 30),
            "projected_monthly_gross": round(daily_gross * 30, 2),
            "projected_monthly_net": round(daily_net * 30, 2),
            "daily_avg_net": round(daily_net, 2),
            "lookback_days": lookback_days,
            "currency": get_revenue_currency(),
        }

    def get_top_earners(
        self,
        days: int = 30,
        limit: int = 10,
    ) -> list[dict]:
        """Return top-earning videos by net revenue in the last N days.

        Args:
            days: Time window in days.
            limit: Maximum videos to return.

        Returns:
            List of dicts with video_id, platform, total_net, total_views.
        """
        if not isinstance(limit, int) or limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

        entries = self.get_entries(days=days)

        # Aggregate by (video_id, platform)
        agg: dict[tuple[str, str], dict] = {}
        for entry in entries:
            key = (entry.video_id, entry.platform)
            if key not in agg:
                agg[key] = {
                    "video_id": entry.video_id,
                    "platform": entry.platform,
                    "total_net": 0.0,
                    "total_views": 0,
                    "niche": entry.niche,
                }
            agg[key]["total_net"] += entry.estimated_net
            agg[key]["total_views"] += entry.views

        ranked = sorted(agg.values(), key=lambda x: x["total_net"], reverse=True)
        return [
            {
                "video_id": r["video_id"][:64],
                "platform": r["platform"],
                "total_net": round(r["total_net"], 2),
                "total_views": r["total_views"],
                "niche": r["niche"],
            }
            for r in ranked[:limit]
        ]

    def get_niche_comparison(self) -> list[dict]:
        """Compare revenue performance across niches.

        Returns:
            List of dicts sorted by estimated net CPM (highest first).
        """
        result = []
        for niche in sorted(_VALID_NICHES):
            platforms = {}
            for platform in sorted(_SUPPORTED_PLATFORMS):
                cpm = self.get_cpm(platform, niche)
                share = self.get_revenue_share(platform)
                platforms[platform] = {
                    "cpm": round(cpm, 2),
                    "net_per_1k": round(cpm * share, 2),
                }
            # Average net per 1k across platforms
            avg_net = sum(p["net_per_1k"] for p in platforms.values()) / len(platforms)
            result.append({
                "niche": niche,
                "platforms": platforms,
                "avg_net_per_1k": round(avg_net, 2),
            })
        result.sort(key=lambda x: x["avg_net_per_1k"], reverse=True)
        return result

    def clear(self) -> None:
        """Clear all revenue entries (for testing or reset)."""
        with self._lock:
            self._entries = []
            self._loaded = True
            self._save_file()

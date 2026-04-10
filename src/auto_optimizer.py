"""
Auto-Optimization Engine for MoneyPrinter.

Analyzes historical analytics and revenue data to recommend optimal content
strategies: best niches, platforms, posting times, content frequency, and
resource allocation. Generates actionable optimization reports and can
auto-adjust scheduler settings based on performance feedback.

Usage:
    from auto_optimizer import AutoOptimizer, OptimizationReport

    optimizer = AutoOptimizer()
    report = optimizer.generate_recommendations()
    print(report.to_text())

    # Auto-adjust scheduler optimal times based on performance
    optimizer.auto_tune_schedule()

Configuration (config.json):
    "optimizer": {
        "enabled": true,
        "lookback_days": 30,
        "min_data_points": 5,
        "auto_tune": false
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

_OPTIMIZER_FILE = os.path.join(ROOT_DIR, ".mp", "optimizer_history.json")
_MAX_HISTORY_ENTRIES = 500
_MAX_LOOKBACK_DAYS = 365
_MIN_LOOKBACK_DAYS = 1
_DEFAULT_LOOKBACK_DAYS = 30
_MIN_DATA_POINTS = 3
_DEFAULT_MIN_DATA_POINTS = 5
_SUPPORTED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})
_SUPPORTED_NICHES = frozenset({
    "finance", "technology", "health", "education", "gaming",
    "entertainment", "lifestyle", "cooking", "travel", "business", "general",
})
_MAX_RECOMMENDATIONS = 20
_MAX_TEXT_LENGTH = 50000

# Time slot buckets for posting time analysis (UTC hours)
_TIME_SLOTS = {
    "early_morning": (5, 8),
    "morning": (8, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 24),
    "late_night": (0, 5),
}

# Platform-specific weight multipliers for scoring
_PLATFORM_WEIGHTS = {
    "youtube": 1.0,
    "tiktok": 0.8,
    "twitter": 0.6,
    "instagram": 0.9,
}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def get_optimizer_enabled() -> bool:
    """Returns whether the auto-optimizer is enabled."""
    val = _get("optimizer", {})
    if isinstance(val, dict):
        return bool(val.get("enabled", False))
    return False


def get_optimizer_lookback_days() -> int:
    """Returns the lookback period in days for analysis."""
    val = _get("optimizer", {})
    if isinstance(val, dict):
        raw = val.get("lookback_days", _DEFAULT_LOOKBACK_DAYS)
    else:
        raw = _DEFAULT_LOOKBACK_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LOOKBACK_DAYS
    return max(_MIN_LOOKBACK_DAYS, min(days, _MAX_LOOKBACK_DAYS))


def get_optimizer_min_data_points() -> int:
    """Minimum data points required before generating recommendations."""
    val = _get("optimizer", {})
    if isinstance(val, dict):
        raw = val.get("min_data_points", _DEFAULT_MIN_DATA_POINTS)
    else:
        raw = _DEFAULT_MIN_DATA_POINTS
    try:
        points = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MIN_DATA_POINTS
    return max(_MIN_DATA_POINTS, min(points, 1000))


def get_auto_tune_enabled() -> bool:
    """Returns whether automatic schedule tuning is enabled."""
    val = _get("optimizer", {})
    if isinstance(val, dict):
        return bool(val.get("auto_tune", False))
    return False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlatformInsight:
    """Performance insight for a single platform."""

    platform: str
    total_events: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    estimated_revenue: float = 0.0
    best_time_slot: str = ""
    avg_events_per_day: float = 0.0
    trend: str = "stable"  # "growing", "declining", "stable"
    score: float = 0.0

    def to_dict(self) -> dict:
        """Serializes to a dictionary."""
        return {
            "platform": str(self.platform)[:50],
            "total_events": int(self.total_events),
            "success_count": int(self.success_count),
            "failure_count": int(self.failure_count),
            "success_rate": round(float(self.success_rate), 2),
            "estimated_revenue": round(float(self.estimated_revenue), 2),
            "best_time_slot": str(self.best_time_slot)[:50],
            "avg_events_per_day": round(float(self.avg_events_per_day), 2),
            "trend": str(self.trend)[:20],
            "score": round(float(self.score), 2),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlatformInsight":
        """Deserializes from a dictionary with validation."""
        if not isinstance(data, dict):
            raise ValueError("PlatformInsight data must be a dict")

        platform = str(data.get("platform", ""))[:50].strip().lower()
        if not platform or platform not in _SUPPORTED_PLATFORMS:
            raise ValueError("Invalid platform")

        return cls(
            platform=platform,
            total_events=max(0, int(data.get("total_events", 0))),
            success_count=max(0, int(data.get("success_count", 0))),
            failure_count=max(0, int(data.get("failure_count", 0))),
            success_rate=max(0.0, min(100.0, float(data.get("success_rate", 0.0)))),
            estimated_revenue=max(0.0, float(data.get("estimated_revenue", 0.0))),
            best_time_slot=str(data.get("best_time_slot", ""))[:50],
            avg_events_per_day=max(0.0, float(data.get("avg_events_per_day", 0.0))),
            trend=str(data.get("trend", "stable"))[:20],
            score=max(0.0, min(100.0, float(data.get("score", 0.0)))),
        )


@dataclass
class NicheInsight:
    """Performance insight for a content niche."""

    niche: str
    total_videos: int = 0
    total_revenue: float = 0.0
    avg_revenue_per_video: float = 0.0
    best_platform: str = ""
    growth_potential: str = "medium"  # "high", "medium", "low"
    score: float = 0.0

    def to_dict(self) -> dict:
        """Serializes to a dictionary."""
        return {
            "niche": str(self.niche)[:100],
            "total_videos": int(self.total_videos),
            "total_revenue": round(float(self.total_revenue), 2),
            "avg_revenue_per_video": round(float(self.avg_revenue_per_video), 2),
            "best_platform": str(self.best_platform)[:50],
            "growth_potential": str(self.growth_potential)[:20],
            "score": round(float(self.score), 2),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NicheInsight":
        """Deserializes from a dictionary with validation."""
        if not isinstance(data, dict):
            raise ValueError("NicheInsight data must be a dict")

        niche = str(data.get("niche", ""))[:100].strip().lower()
        if not niche or niche not in _SUPPORTED_NICHES:
            raise ValueError("Invalid niche")

        return cls(
            niche=niche,
            total_videos=max(0, int(data.get("total_videos", 0))),
            total_revenue=max(0.0, float(data.get("total_revenue", 0.0))),
            avg_revenue_per_video=max(0.0, float(data.get("avg_revenue_per_video", 0.0))),
            best_platform=str(data.get("best_platform", ""))[:50],
            growth_potential=str(data.get("growth_potential", "medium"))[:20],
            score=max(0.0, min(100.0, float(data.get("score", 0.0)))),
        )


@dataclass
class Recommendation:
    """A single actionable recommendation."""

    category: str  # "platform", "niche", "timing", "frequency", "general"
    priority: str  # "high", "medium", "low"
    title: str
    description: str
    expected_impact: str  # "high", "medium", "low"

    def to_dict(self) -> dict:
        return {
            "category": str(self.category)[:50],
            "priority": str(self.priority)[:20],
            "title": str(self.title)[:200],
            "description": str(self.description)[:1000],
            "expected_impact": str(self.expected_impact)[:20],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Recommendation":
        if not isinstance(data, dict):
            raise ValueError("Recommendation data must be a dict")
        return cls(
            category=str(data.get("category", "general"))[:50],
            priority=str(data.get("priority", "medium"))[:20],
            title=str(data.get("title", ""))[:200],
            description=str(data.get("description", ""))[:1000],
            expected_impact=str(data.get("expected_impact", "medium"))[:20],
        )


@dataclass
class OptimizationReport:
    """Complete optimization report with insights and recommendations."""

    generated_at: str = ""
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS
    total_events_analyzed: int = 0
    platform_insights: list = field(default_factory=list)
    niche_insights: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    top_platform: str = ""
    top_niche: str = ""
    overall_health: str = "unknown"  # "excellent", "good", "fair", "poor", "unknown"

    def to_dict(self) -> dict:
        return {
            "generated_at": str(self.generated_at)[:50],
            "lookback_days": int(self.lookback_days),
            "total_events_analyzed": int(self.total_events_analyzed),
            "platform_insights": [
                pi.to_dict() if isinstance(pi, PlatformInsight) else pi
                for pi in self.platform_insights[:len(_SUPPORTED_PLATFORMS)]
            ],
            "niche_insights": [
                ni.to_dict() if isinstance(ni, NicheInsight) else ni
                for ni in self.niche_insights[:len(_SUPPORTED_NICHES)]
            ],
            "recommendations": [
                r.to_dict() if isinstance(r, Recommendation) else r
                for r in self.recommendations[:_MAX_RECOMMENDATIONS]
            ],
            "top_platform": str(self.top_platform)[:50],
            "top_niche": str(self.top_niche)[:100],
            "overall_health": str(self.overall_health)[:20],
        }

    def to_text(self) -> str:
        """Generates a human-readable text report."""
        lines = []
        lines.append("=" * 60)
        lines.append("MoneyPrinter Auto-Optimization Report")
        lines.append("=" * 60)
        lines.append(f"Generated: {self.generated_at}")
        lines.append(f"Lookback: {self.lookback_days} days")
        lines.append(f"Events analyzed: {self.total_events_analyzed}")
        lines.append(f"Overall health: {self.overall_health}")
        lines.append("")

        if self.top_platform:
            lines.append(f"Top platform: {self.top_platform}")
        if self.top_niche:
            lines.append(f"Top niche: {self.top_niche}")
        lines.append("")

        if self.platform_insights:
            lines.append("-" * 40)
            lines.append("Platform Insights")
            lines.append("-" * 40)
            for pi in self.platform_insights:
                if isinstance(pi, PlatformInsight):
                    lines.append(
                        f"  {pi.platform}: {pi.success_rate}% success, "
                        f"${pi.estimated_revenue:.2f} revenue, "
                        f"trend={pi.trend}, score={pi.score:.1f}"
                    )
            lines.append("")

        if self.niche_insights:
            lines.append("-" * 40)
            lines.append("Niche Insights")
            lines.append("-" * 40)
            for ni in self.niche_insights:
                if isinstance(ni, NicheInsight):
                    lines.append(
                        f"  {ni.niche}: {ni.total_videos} videos, "
                        f"${ni.total_revenue:.2f} revenue, "
                        f"avg=${ni.avg_revenue_per_video:.2f}/video, "
                        f"growth={ni.growth_potential}"
                    )
            lines.append("")

        if self.recommendations:
            lines.append("-" * 40)
            lines.append("Recommendations")
            lines.append("-" * 40)
            for i, rec in enumerate(self.recommendations, 1):
                if isinstance(rec, Recommendation):
                    lines.append(f"  {i}. [{rec.priority.upper()}] {rec.title}")
                    lines.append(f"     {rec.description}")
            lines.append("")

        text = "\n".join(lines)
        return text[:_MAX_TEXT_LENGTH]

    @classmethod
    def from_dict(cls, data: dict) -> "OptimizationReport":
        if not isinstance(data, dict):
            raise ValueError("OptimizationReport data must be a dict")

        platform_insights = []
        for pi_data in data.get("platform_insights", [])[:len(_SUPPORTED_PLATFORMS)]:
            try:
                platform_insights.append(PlatformInsight.from_dict(pi_data))
            except (ValueError, TypeError, KeyError):
                continue

        niche_insights = []
        for ni_data in data.get("niche_insights", [])[:len(_SUPPORTED_NICHES)]:
            try:
                niche_insights.append(NicheInsight.from_dict(ni_data))
            except (ValueError, TypeError, KeyError):
                continue

        recommendations = []
        for r_data in data.get("recommendations", [])[:_MAX_RECOMMENDATIONS]:
            try:
                recommendations.append(Recommendation.from_dict(r_data))
            except (ValueError, TypeError, KeyError):
                continue

        return cls(
            generated_at=str(data.get("generated_at", ""))[:50],
            lookback_days=max(
                _MIN_LOOKBACK_DAYS,
                min(int(data.get("lookback_days", _DEFAULT_LOOKBACK_DAYS)), _MAX_LOOKBACK_DAYS),
            ),
            total_events_analyzed=max(0, int(data.get("total_events_analyzed", 0))),
            platform_insights=platform_insights,
            niche_insights=niche_insights,
            recommendations=recommendations,
            top_platform=str(data.get("top_platform", ""))[:50],
            top_niche=str(data.get("top_niche", ""))[:100],
            overall_health=str(data.get("overall_health", "unknown"))[:20],
        )


# ---------------------------------------------------------------------------
# AutoOptimizer
# ---------------------------------------------------------------------------


class AutoOptimizer:
    """
    Analyzes historical performance data and generates optimization
    recommendations for the MoneyPrinter content pipeline.
    """

    def __init__(
        self,
        lookback_days: Optional[int] = None,
        min_data_points: Optional[int] = None,
    ):
        self._lock = threading.RLock()
        self._lookback_days = lookback_days if lookback_days is not None else get_optimizer_lookback_days()
        self._lookback_days = max(
            _MIN_LOOKBACK_DAYS, min(self._lookback_days, _MAX_LOOKBACK_DAYS)
        )
        self._min_data_points = min_data_points if min_data_points is not None else get_optimizer_min_data_points()
        self._min_data_points = max(_MIN_DATA_POINTS, min(self._min_data_points, 1000))

    # ------------------------------------------------------------------
    # Data loading helpers
    # ------------------------------------------------------------------

    def _load_analytics_events(self) -> list[dict]:
        """Loads analytics events from the analytics module's JSON file."""
        analytics_file = os.path.join(ROOT_DIR, ".mp", "analytics.json")
        try:
            with open(analytics_file, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    events = data.get("events", [])
                    if isinstance(events, list):
                        return events[-10000:]  # Cap at 10k events
                return []
        except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
            return []

    def _load_revenue_entries(self) -> list[dict]:
        """Loads revenue entries from the revenue tracker's JSON file."""
        revenue_file = os.path.join(ROOT_DIR, ".mp", "revenue_tracker.json")
        try:
            with open(revenue_file, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data[-50000:]  # Cap at 50k entries
                return []
        except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
            return []

    def _filter_by_lookback(self, events: list[dict], timestamp_key: str = "timestamp") -> list[dict]:
        """Filters events to those within the lookback window."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._lookback_days)
        cutoff_iso = cutoff.isoformat()
        filtered = []
        for event in events:
            if not isinstance(event, dict):
                continue
            ts = event.get(timestamp_key, "")
            if not isinstance(ts, str) or len(ts) > 100:
                continue
            if "\x00" in ts:
                continue
            # Simple string comparison works for ISO format
            if ts >= cutoff_iso:
                filtered.append(event)
        return filtered

    # ------------------------------------------------------------------
    # Analysis methods
    # ------------------------------------------------------------------

    def _analyze_platform_performance(self, events: list[dict]) -> list[PlatformInsight]:
        """Analyzes per-platform performance from analytics events."""
        platform_data: dict[str, dict] = {}
        for p in _SUPPORTED_PLATFORMS:
            platform_data[p] = {
                "total": 0, "success": 0, "failure": 0,
                "time_slots": {slot: 0 for slot in _TIME_SLOTS},
                "daily_counts": {},
            }

        for event in events:
            if not isinstance(event, dict):
                continue
            platform = str(event.get("platform", "")).lower()[:50]
            if platform not in _SUPPORTED_PLATFORMS:
                continue
            event_type = str(event.get("type", ""))[:100]
            timestamp = str(event.get("timestamp", ""))[:100]

            pd = platform_data[platform]
            pd["total"] += 1

            if "uploaded" in event_type or "posted" in event_type or "published" in event_type:
                pd["success"] += 1
            elif "error" in event_type or "failed" in event_type:
                pd["failure"] += 1

            # Classify time slot
            try:
                if "T" in timestamp:
                    hour = int(timestamp.split("T")[1][:2])
                    if 0 <= hour < 24:
                        for slot_name, (start, end) in _TIME_SLOTS.items():
                            if start <= hour < end:
                                pd["time_slots"][slot_name] += 1
                                break
            except (ValueError, IndexError):
                pass

            # Track daily counts for trend analysis
            day = timestamp[:10] if len(timestamp) >= 10 else ""
            if day:
                pd["daily_counts"][day] = pd["daily_counts"].get(day, 0) + 1

        insights = []
        for platform in sorted(_SUPPORTED_PLATFORMS):
            pd = platform_data[platform]
            if pd["total"] == 0:
                continue

            total = pd["total"]
            success_rate = (pd["success"] / total * 100) if total > 0 else 0.0

            # Find best time slot
            best_slot = max(pd["time_slots"], key=pd["time_slots"].get) if pd["time_slots"] else ""

            # Calculate trend from daily counts
            daily = sorted(pd["daily_counts"].items())
            trend = "stable"
            if len(daily) >= 7:
                first_half = sum(v for _, v in daily[: len(daily) // 2])
                second_half = sum(v for _, v in daily[len(daily) // 2:])
                if second_half > first_half * 1.2:
                    trend = "growing"
                elif second_half < first_half * 0.8:
                    trend = "declining"

            # Average events per day
            num_days = max(1, len(daily))
            avg_per_day = total / num_days

            # Composite score: weighted sum of success rate, volume, and trend
            weight = _PLATFORM_WEIGHTS.get(platform, 0.5)
            trend_bonus = {"growing": 10, "stable": 0, "declining": -10}.get(trend, 0)
            score = min(100.0, (success_rate * 0.5) + (min(avg_per_day, 10) * 3) + trend_bonus) * weight

            insights.append(PlatformInsight(
                platform=platform,
                total_events=total,
                success_count=pd["success"],
                failure_count=pd["failure"],
                success_rate=round(success_rate, 2),
                best_time_slot=best_slot,
                avg_events_per_day=round(avg_per_day, 2),
                trend=trend,
                score=round(max(0.0, score), 2),
            ))

        # Sort by score descending
        insights.sort(key=lambda x: x.score, reverse=True)
        return insights

    def _analyze_niche_performance(self, revenue_entries: list[dict]) -> list[NicheInsight]:
        """Analyzes per-niche performance from revenue entries."""
        niche_data: dict[str, dict] = {}

        for entry in revenue_entries:
            if not isinstance(entry, dict):
                continue
            niche = str(entry.get("niche", "general")).lower()[:100]
            if niche not in _SUPPORTED_NICHES:
                niche = "general"
            platform = str(entry.get("platform", "")).lower()[:50]
            net = float(entry.get("net_revenue", 0.0))

            if niche not in niche_data:
                niche_data[niche] = {
                    "videos": 0,
                    "total_revenue": 0.0,
                    "platform_revenue": {},
                }

            nd = niche_data[niche]
            nd["videos"] += 1
            nd["total_revenue"] += max(0.0, net)
            if platform in _SUPPORTED_PLATFORMS:
                nd["platform_revenue"][platform] = (
                    nd["platform_revenue"].get(platform, 0.0) + max(0.0, net)
                )

        insights = []
        for niche, nd in niche_data.items():
            if nd["videos"] == 0:
                continue

            avg_rev = nd["total_revenue"] / nd["videos"] if nd["videos"] > 0 else 0.0
            best_platform = ""
            if nd["platform_revenue"]:
                best_platform = max(nd["platform_revenue"], key=nd["platform_revenue"].get)

            # Growth potential based on avg revenue
            if avg_rev >= 5.0:
                growth = "high"
            elif avg_rev >= 1.0:
                growth = "medium"
            else:
                growth = "low"

            # Score: revenue-weighted with volume consideration
            score = min(100.0, (avg_rev * 10) + (min(nd["videos"], 50) * 0.5))

            insights.append(NicheInsight(
                niche=niche,
                total_videos=nd["videos"],
                total_revenue=round(nd["total_revenue"], 2),
                avg_revenue_per_video=round(avg_rev, 2),
                best_platform=best_platform,
                growth_potential=growth,
                score=round(max(0.0, min(100.0, score)), 2),
            ))

        insights.sort(key=lambda x: x.score, reverse=True)
        return insights

    def _enrich_with_revenue(
        self, platform_insights: list[PlatformInsight], revenue_entries: list[dict]
    ) -> None:
        """Enriches platform insights with revenue data."""
        platform_revenue: dict[str, float] = {}
        for entry in revenue_entries:
            if not isinstance(entry, dict):
                continue
            platform = str(entry.get("platform", "")).lower()[:50]
            net = float(entry.get("net_revenue", 0.0))
            if platform in _SUPPORTED_PLATFORMS:
                platform_revenue[platform] = platform_revenue.get(platform, 0.0) + max(0.0, net)

        for pi in platform_insights:
            pi.estimated_revenue = round(platform_revenue.get(pi.platform, 0.0), 2)

    def _generate_recommendations(
        self,
        platform_insights: list[PlatformInsight],
        niche_insights: list[NicheInsight],
        total_events: int,
    ) -> list[Recommendation]:
        """Generates actionable recommendations from insights."""
        recs = []

        # --- Volume recommendations ---
        if total_events < 10:
            recs.append(Recommendation(
                category="frequency",
                priority="high",
                title="Increase content output",
                description=(
                    "Only {0} events in the lookback period. Aim for at least "
                    "1 piece of content per day across platforms to build momentum."
                ).format(total_events),
                expected_impact="high",
            ))

        # --- Platform recommendations ---
        active_platforms = [pi for pi in platform_insights if pi.total_events > 0]
        if len(active_platforms) < 3:
            missing = _SUPPORTED_PLATFORMS - {pi.platform for pi in active_platforms}
            if missing:
                recs.append(Recommendation(
                    category="platform",
                    priority="high",
                    title="Expand to more platforms",
                    description=(
                        "Currently active on {0} platform(s). Add {1} for 2-3x "
                        "reach multiplier. Multi-platform creators outperform "
                        "single-platform creators consistently."
                    ).format(len(active_platforms), ", ".join(sorted(missing)[:3])),
                    expected_impact="high",
                ))

        for pi in platform_insights:
            if pi.success_rate < 50 and pi.total_events >= 5:
                recs.append(Recommendation(
                    category="platform",
                    priority="high",
                    title=f"Fix {pi.platform} reliability",
                    description=(
                        f"{pi.platform} has only {pi.success_rate}% success rate "
                        f"({min(pi.failure_count, 999999)} failures). Review your "
                        f"{pi.platform} configuration and retry settings."
                    ),
                    expected_impact="high",
                ))

            if pi.trend == "declining" and pi.total_events >= 10:
                recs.append(Recommendation(
                    category="platform",
                    priority="medium",
                    title=f"Reverse {pi.platform} decline",
                    description=(
                        f"{pi.platform} activity is declining. Consider refreshing "
                        f"content strategy, updating SEO metadata, or increasing "
                        f"posting frequency."
                    ),
                    expected_impact="medium",
                ))

        # --- Time slot recommendations ---
        for pi in platform_insights:
            if pi.best_time_slot and pi.total_events >= 5:
                recs.append(Recommendation(
                    category="timing",
                    priority="medium",
                    title=f"Optimize {pi.platform} posting time",
                    description=(
                        f"Best performance on {pi.platform} is during "
                        f"{pi.best_time_slot} (UTC). Schedule content for "
                        f"this window to maximize engagement."
                    ),
                    expected_impact="medium",
                ))

        # --- Niche recommendations ---
        if niche_insights:
            top_niche = niche_insights[0]
            if top_niche.avg_revenue_per_video > 0:
                recs.append(Recommendation(
                    category="niche",
                    priority="high",
                    title=f"Double down on {top_niche.niche} content",
                    description=(
                        f"{top_niche.niche} generates ${top_niche.avg_revenue_per_video:.2f} "
                        f"per video on average. Increase content volume in this "
                        f"niche for maximum revenue."
                    ),
                    expected_impact="high",
                ))

            # Suggest high-CPM niches not yet explored
            explored = {ni.niche for ni in niche_insights}
            high_value_niches = {"finance", "technology", "business", "health"}
            unexplored_high = high_value_niches - explored
            if unexplored_high:
                recs.append(Recommendation(
                    category="niche",
                    priority="medium",
                    title="Explore high-CPM niches",
                    description=(
                        f"Unexplored high-value niches: {', '.join(sorted(unexplored_high)[:3])}. "
                        f"Finance has up to 12x higher CPM than entertainment on YouTube."
                    ),
                    expected_impact="high",
                ))

        # --- General recommendations ---
        if platform_insights:
            top = platform_insights[0]
            if top.estimated_revenue > 0:
                recs.append(Recommendation(
                    category="general",
                    priority="medium",
                    title=f"Scale {top.platform} — your top earner",
                    description=(
                        f"{top.platform} has earned ${top.estimated_revenue:.2f}. "
                        f"Consider increasing frequency and using multi-language "
                        f"dubbing to reach global audiences."
                    ),
                    expected_impact="high",
                ))

        # Cap recommendations
        return recs[:_MAX_RECOMMENDATIONS]

    def _assess_overall_health(
        self, platform_insights: list[PlatformInsight], total_events: int
    ) -> str:
        """Assigns an overall health rating."""
        if total_events == 0:
            return "unknown"

        avg_success = 0.0
        if platform_insights:
            rates = [pi.success_rate for pi in platform_insights if pi.total_events > 0]
            avg_success = sum(rates) / len(rates) if rates else 0.0

        active = len([pi for pi in platform_insights if pi.total_events > 0])

        if avg_success >= 80 and active >= 3:
            return "excellent"
        elif avg_success >= 60 and active >= 2:
            return "good"
        elif avg_success >= 40:
            return "fair"
        else:
            return "poor"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_recommendations(self) -> OptimizationReport:
        """
        Generates a complete optimization report with platform insights,
        niche insights, and actionable recommendations.

        Returns:
            OptimizationReport with analysis results and recommendations.
        """
        with self._lock:
            logger.info("Generating optimization report (lookback=%dd)", self._lookback_days)

            # Load data
            analytics_events = self._load_analytics_events()
            revenue_entries = self._load_revenue_entries()

            # Filter to lookback window
            events = self._filter_by_lookback(analytics_events, "timestamp")
            revenue = self._filter_by_lookback(revenue_entries, "timestamp")

            total_events = len(events)

            # Analyze
            platform_insights = self._analyze_platform_performance(events)
            niche_insights = self._analyze_niche_performance(revenue)

            # Enrich platform insights with revenue
            self._enrich_with_revenue(platform_insights, revenue)

            # Generate recommendations
            recommendations = self._generate_recommendations(
                platform_insights, niche_insights, total_events
            )

            # Assess health
            health = self._assess_overall_health(platform_insights, total_events)

            # Build report
            report = OptimizationReport(
                generated_at=datetime.now(timezone.utc).isoformat(),
                lookback_days=self._lookback_days,
                total_events_analyzed=total_events,
                platform_insights=platform_insights,
                niche_insights=niche_insights,
                recommendations=recommendations,
                top_platform=platform_insights[0].platform if platform_insights else "",
                top_niche=niche_insights[0].niche if niche_insights else "",
                overall_health=health,
            )

            # Persist report to history
            self._save_report(report)

            logger.info(
                "Optimization report generated: %d events, %d platform insights, "
                "%d niche insights, %d recommendations, health=%s",
                total_events, len(platform_insights), len(niche_insights),
                len(recommendations), health,
            )

            return report

    def get_history(self, limit: int = 10) -> list[dict]:
        """
        Returns recent optimization report history.

        Args:
            limit: Max reports to return (1-100).

        Returns:
            List of report dicts, most recent first.
        """
        limit = max(1, min(limit, 100))
        with self._lock:
            history = self._load_history()
            return history[-limit:][::-1]

    def auto_tune_schedule(self) -> dict:
        """
        Analyzes performance data and returns recommended optimal posting
        times for each platform based on historical success patterns.

        Returns:
            Dict mapping platform → list of recommended UTC time strings.
        """
        with self._lock:
            if not get_auto_tune_enabled():
                logger.info("Auto-tune is disabled in config")
                return {}

            events = self._load_analytics_events()
            events = self._filter_by_lookback(events, "timestamp")

            # Analyze success by hour for each platform
            recommendations: dict[str, list[str]] = {}
            for platform in _SUPPORTED_PLATFORMS:
                hour_success: dict[int, int] = {}
                hour_total: dict[int, int] = {}

                for event in events:
                    if not isinstance(event, dict):
                        continue
                    if str(event.get("platform", "")).lower() != platform:
                        continue

                    ts = str(event.get("timestamp", ""))
                    event_type = str(event.get("type", ""))
                    try:
                        if "T" in ts:
                            hour = int(ts.split("T")[1][:2])
                            if not (0 <= hour < 24):
                                continue
                        else:
                            continue
                    except (ValueError, IndexError):
                        continue

                    hour_total[hour] = hour_total.get(hour, 0) + 1
                    if "uploaded" in event_type or "posted" in event_type or "published" in event_type:
                        hour_success[hour] = hour_success.get(hour, 0) + 1

                if not hour_total:
                    continue

                # Rank hours by success rate (minimum 2 events in that hour)
                scored_hours = []
                for h, total in hour_total.items():
                    if total >= 2:
                        rate = hour_success.get(h, 0) / total
                        scored_hours.append((h, rate, total))

                scored_hours.sort(key=lambda x: (x[1], x[2]), reverse=True)

                # Take top 3 hours
                top_hours = sorted([h for h, _, _ in scored_hours[:3]])
                if top_hours:
                    recommendations[platform] = [f"{h:02d}:00" for h in top_hours]

            logger.info("Auto-tune recommendations: %s", {k: v for k, v in recommendations.items()})
            return recommendations

    def clear_history(self) -> None:
        """Clears the optimizer history file."""
        with self._lock:
            self._save_history([])
            logger.info("Optimizer history cleared")

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_history(self) -> list[dict]:
        """Loads optimizer report history from disk."""
        try:
            with open(_OPTIMIZER_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data[-_MAX_HISTORY_ENTRIES:]
                return []
        except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
            return []

    def _save_history(self, history: list[dict]) -> None:
        """Atomically saves optimizer history to disk."""
        dir_name = os.path.dirname(_OPTIMIZER_FILE)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(history[-_MAX_HISTORY_ENTRIES:], f, indent=2)
            os.replace(tmp_path, _OPTIMIZER_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _save_report(self, report: OptimizationReport) -> None:
        """Appends a report to the history file."""
        history = self._load_history()
        history.append(report.to_dict())
        if len(history) > _MAX_HISTORY_ENTRIES:
            history = history[-_MAX_HISTORY_ENTRIES:]
        self._save_history(history)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def generate_recommendations(
    lookback_days: Optional[int] = None,
) -> OptimizationReport:
    """
    Convenience function to generate an optimization report.

    Args:
        lookback_days: Analysis window in days (default: config value).

    Returns:
        OptimizationReport with insights and recommendations.
    """
    optimizer = AutoOptimizer(lookback_days=lookback_days)
    return optimizer.generate_recommendations()


def auto_tune_schedule() -> dict:
    """
    Convenience function to generate schedule tuning recommendations.

    Returns:
        Dict mapping platform to recommended posting times.
    """
    optimizer = AutoOptimizer()
    return optimizer.auto_tune_schedule()

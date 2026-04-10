"""
Analytics Report Generator for MoneyPrinter.

Generates actionable performance reports from tracked analytics data.
Provides platform-specific insights, trend analysis, success rates,
and content strategy recommendations.

Usage:
    from analytics_report import generate_report, get_platform_report

    # Full cross-platform report
    report = generate_report()
    print(report.to_text())

    # Platform-specific report
    yt_report = get_platform_report("youtube")
    print(yt_report.to_text())

Configuration (config.json):
    "analytics": {
        "report_max_events": 5000,
        "report_top_n": 10
    }
"""

import os
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from config import _get
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_REPORT_EVENTS = 10000  # Max events to process in a single report
_DEFAULT_TOP_N = 10
_SUPPORTED_PLATFORMS = {"youtube", "tiktok", "twitter", "instagram"}
_REPORT_MAX_LENGTH = 50000  # Cap text report length


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_analytics_config() -> dict:
    """Returns the analytics configuration block."""
    return _get("analytics", {})


def get_report_max_events() -> int:
    """Max events to include in report generation."""
    val = _get_analytics_config().get("report_max_events", _MAX_REPORT_EVENTS)
    return min(int(val), _MAX_REPORT_EVENTS)


def get_report_top_n() -> int:
    """Number of top items to include in rankings."""
    val = _get_analytics_config().get("report_top_n", _DEFAULT_TOP_N)
    return min(max(int(val), 1), 50)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PlatformStats:
    """Statistics for a single platform."""

    platform: str = ""
    total_events: int = 0
    successful_uploads: int = 0
    failed_uploads: int = 0
    success_rate: float = 0.0
    events_by_type: dict = field(default_factory=dict)
    events_by_day: dict = field(default_factory=dict)
    avg_events_per_day: float = 0.0
    peak_day: str = ""
    peak_day_count: int = 0
    most_common_error: str = ""
    recent_trend: str = ""  # "up", "down", "stable"

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "platform": self.platform,
            "total_events": self.total_events,
            "successful_uploads": self.successful_uploads,
            "failed_uploads": self.failed_uploads,
            "success_rate": round(self.success_rate, 2),
            "events_by_type": self.events_by_type,
            "avg_events_per_day": round(self.avg_events_per_day, 2),
            "peak_day": self.peak_day,
            "peak_day_count": self.peak_day_count,
            "most_common_error": self.most_common_error,
            "recent_trend": self.recent_trend,
        }


@dataclass
class AnalyticsReport:
    """Full analytics report across all platforms."""

    generated_at: str = ""
    total_events: int = 0
    platforms: dict = field(default_factory=dict)  # platform -> PlatformStats
    overall_success_rate: float = 0.0
    busiest_platform: str = ""
    most_active_day: str = ""
    event_type_distribution: dict = field(default_factory=dict)
    daily_trend: list = field(default_factory=list)  # last 7 days counts
    recommendations: list = field(default_factory=list)

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Serialize the full report to a dictionary."""
        return {
            "generated_at": self.generated_at,
            "total_events": self.total_events,
            "platforms": {
                k: v.to_dict() if isinstance(v, PlatformStats) else v
                for k, v in self.platforms.items()
            },
            "overall_success_rate": round(self.overall_success_rate, 2),
            "busiest_platform": self.busiest_platform,
            "most_active_day": self.most_active_day,
            "event_type_distribution": self.event_type_distribution,
            "daily_trend": self.daily_trend,
            "recommendations": self.recommendations,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_text(self) -> str:
        """Generate a human-readable text report."""
        lines = []
        lines.append("=" * 60)
        lines.append("  MONEYPRINTER ANALYTICS REPORT")
        lines.append(f"  Generated: {self.generated_at[:19]}")
        lines.append("=" * 60)
        lines.append("")

        # Overall summary
        lines.append("OVERALL SUMMARY")
        lines.append("-" * 40)
        lines.append(f"  Total events tracked:  {self.total_events}")
        lines.append(f"  Overall success rate:  {self.overall_success_rate:.1f}%")
        lines.append(f"  Busiest platform:      {self.busiest_platform or 'N/A'}")
        lines.append(f"  Most active day:       {self.most_active_day or 'N/A'}")
        lines.append("")

        # Event type breakdown
        if self.event_type_distribution:
            lines.append("EVENT DISTRIBUTION")
            lines.append("-" * 40)
            for event_type, count in sorted(
                self.event_type_distribution.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                lines.append(f"  {event_type:<25} {count:>6}")
            lines.append("")

        # Per-platform stats
        for platform_name, stats in self.platforms.items():
            if not isinstance(stats, PlatformStats):
                continue
            lines.append(f"PLATFORM: {platform_name.upper()}")
            lines.append("-" * 40)
            lines.append(f"  Total events:      {stats.total_events}")
            lines.append(f"  Successful:        {stats.successful_uploads}")
            lines.append(f"  Failed:            {stats.failed_uploads}")
            lines.append(f"  Success rate:      {stats.success_rate:.1f}%")
            lines.append(f"  Avg events/day:    {stats.avg_events_per_day:.1f}")
            lines.append(f"  Peak day:          {stats.peak_day or 'N/A'} ({stats.peak_day_count} events)")
            lines.append(f"  Trend (7-day):     {stats.recent_trend or 'N/A'}")
            if stats.most_common_error:
                lines.append(f"  Most common error: {stats.most_common_error}")
            lines.append("")

        # 7-day trend
        if self.daily_trend:
            lines.append("7-DAY ACTIVITY TREND")
            lines.append("-" * 40)
            max_count = max(self.daily_trend, key=lambda x: x[1])[1] if self.daily_trend else 1
            for date_str, count in self.daily_trend:
                bar_len = int((count / max(max_count, 1)) * 20)
                bar = "#" * bar_len
                lines.append(f"  {date_str}  {bar:<20} {count}")
            lines.append("")

        # Recommendations
        if self.recommendations:
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 40)
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"  {i}. {rec}")
            lines.append("")

        lines.append("=" * 60)

        text = "\n".join(lines)
        return text[:_REPORT_MAX_LENGTH]


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _load_events(max_events: int = _MAX_REPORT_EVENTS) -> list:
    """Load analytics events from disk."""
    from analytics import _load_analytics
    data = _load_analytics()
    events = data.get("events", [])
    # Only process the most recent events
    return events[-max_events:]


def _parse_event_date(event: dict) -> Optional[str]:
    """Extract the date (YYYY-MM-DD) from an event timestamp."""
    ts = event.get("timestamp", "")
    if not ts or not isinstance(ts, str):
        return None
    try:
        return ts[:10]  # ISO format: YYYY-MM-DD
    except (IndexError, ValueError):
        return None


def _compute_platform_stats(events: list, platform: str) -> PlatformStats:
    """Compute statistics for a single platform."""
    stats = PlatformStats(platform=platform)

    platform_events = [
        e for e in events if e.get("platform") == platform
    ]
    stats.total_events = len(platform_events)

    if not platform_events:
        return stats

    # Count by event type
    type_counter = Counter()
    error_counter = Counter()
    day_counter = Counter()

    for event in platform_events:
        event_type = event.get("type", "unknown")
        type_counter[event_type] += 1

        date = _parse_event_date(event)
        if date:
            day_counter[date] += 1

        # Track successes and failures
        if event_type in ("video_uploaded", "tweet_posted", "pitch_shared", "tiktok_uploaded"):
            stats.successful_uploads += 1
        elif event_type == "publish_failed":
            stats.failed_uploads += 1
            # Track error types from details
            details = event.get("details", {})
            error_type = details.get("error_type", "Unknown")
            if error_type:
                error_counter[error_type] += 1

    stats.events_by_type = dict(type_counter)
    stats.events_by_day = dict(day_counter)

    # Success rate
    total_publish_attempts = stats.successful_uploads + stats.failed_uploads
    if total_publish_attempts > 0:
        stats.success_rate = (stats.successful_uploads / total_publish_attempts) * 100

    # Average events per day
    if day_counter:
        stats.avg_events_per_day = stats.total_events / len(day_counter)

    # Peak day
    if day_counter:
        peak = day_counter.most_common(1)[0]
        stats.peak_day = peak[0]
        stats.peak_day_count = peak[1]

    # Most common error
    if error_counter:
        stats.most_common_error = error_counter.most_common(1)[0][0]

    # 7-day trend analysis
    stats.recent_trend = _compute_trend(day_counter)

    return stats


def _compute_trend(day_counter: Counter) -> str:
    """Compute trend direction from day counts over last 7 days."""
    if len(day_counter) < 2:
        return "stable"

    today = datetime.now().date()
    recent_days = []
    for i in range(7):
        day = (today - timedelta(days=i)).isoformat()
        recent_days.append(day_counter.get(day, 0))

    # Compare first half (recent) vs second half (older)
    if len(recent_days) >= 4:
        recent_avg = sum(recent_days[:3]) / 3
        older_avg = sum(recent_days[3:]) / max(len(recent_days[3:]), 1)

        if recent_avg > older_avg * 1.2:
            return "up"
        elif recent_avg < older_avg * 0.8:
            return "down"

    return "stable"


def _compute_daily_trend(events: list, days: int = 7) -> list:
    """Compute daily event counts for the last N days."""
    today = datetime.now().date()
    day_counts = Counter()

    for event in events:
        date = _parse_event_date(event)
        if date:
            day_counts[date] += 1

    trend = []
    for i in range(days - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        trend.append((day, day_counts.get(day, 0)))

    return trend


def _generate_recommendations(report: AnalyticsReport) -> list:
    """Generate actionable recommendations based on analytics data."""
    recommendations = []

    # No data recommendation
    if report.total_events == 0:
        recommendations.append(
            "No analytics data found. Start creating and publishing content "
            "to build up performance data."
        )
        return recommendations

    # Low activity
    if report.total_events < 10:
        recommendations.append(
            "Activity is very low. Consider setting up automated scheduling "
            "with the content scheduler to maintain consistent output."
        )

    # Platform-specific recommendations
    for platform_name, stats in report.platforms.items():
        if not isinstance(stats, PlatformStats):
            continue

        if stats.total_events == 0:
            recommendations.append(
                f"No activity on {platform_name}. Consider adding it to your "
                f"publishing pipeline for broader reach."
            )
            continue

        # Low success rate
        if stats.success_rate < 70 and (stats.successful_uploads + stats.failed_uploads) > 3:
            recommendations.append(
                f"{platform_name} has a {stats.success_rate:.0f}% success rate. "
                f"Check account credentials and network connectivity. "
                f"Most common error: {stats.most_common_error or 'Unknown'}."
            )

        # Declining trend
        if stats.recent_trend == "down":
            recommendations.append(
                f"{platform_name} activity is trending down over the last 7 days. "
                f"Consider increasing posting frequency or exploring new niches."
            )

        # No failures (good!)
        if stats.failed_uploads == 0 and stats.successful_uploads > 5:
            recommendations.append(
                f"{platform_name} has a perfect success rate across "
                f"{stats.successful_uploads} uploads. Great reliability!"
            )

    # Multi-platform check
    active_platforms = [
        k for k, v in report.platforms.items()
        if isinstance(v, PlatformStats) and v.total_events > 0
    ]
    if len(active_platforms) == 1:
        inactive = _SUPPORTED_PLATFORMS - set(active_platforms)
        if inactive:
            recommendations.append(
                f"Only active on {active_platforms[0]}. Cross-posting to "
                f"{', '.join(sorted(inactive))} can increase reach by 2-3x."
            )

    # Limit recommendations
    return recommendations[:8]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(max_events: int = 0) -> AnalyticsReport:
    """
    Generate a comprehensive analytics report across all platforms.

    Args:
        max_events: Maximum events to analyze (0 = use config default).

    Returns:
        AnalyticsReport with cross-platform insights.
    """
    if max_events <= 0:
        max_events = get_report_max_events()

    events = _load_events(max_events)
    report = AnalyticsReport(total_events=len(events))

    if not events:
        report.recommendations = _generate_recommendations(report)
        return report

    # Compute per-platform stats
    all_platforms = set()
    for event in events:
        p = event.get("platform", "")
        if p:
            all_platforms.add(p)

    for platform in all_platforms:
        report.platforms[platform] = _compute_platform_stats(events, platform)

    # Overall success rate
    total_success = sum(
        s.successful_uploads for s in report.platforms.values()
        if isinstance(s, PlatformStats)
    )
    total_fail = sum(
        s.failed_uploads for s in report.platforms.values()
        if isinstance(s, PlatformStats)
    )
    total_attempts = total_success + total_fail
    if total_attempts > 0:
        report.overall_success_rate = (total_success / total_attempts) * 100

    # Busiest platform
    if report.platforms:
        busiest = max(
            report.platforms.items(),
            key=lambda x: x[1].total_events if isinstance(x[1], PlatformStats) else 0,
        )
        report.busiest_platform = busiest[0]

    # Event type distribution
    type_counter = Counter()
    day_counter = Counter()
    for event in events:
        type_counter[event.get("type", "unknown")] += 1
        date = _parse_event_date(event)
        if date:
            day_counter[date] += 1

    report.event_type_distribution = dict(type_counter)

    # Most active day
    if day_counter:
        report.most_active_day = day_counter.most_common(1)[0][0]

    # 7-day trend
    report.daily_trend = _compute_daily_trend(events)

    # Generate recommendations
    report.recommendations = _generate_recommendations(report)

    logger.info(
        "Analytics report generated: %d events across %d platform(s).",
        report.total_events,
        len(report.platforms),
    )

    return report


def get_platform_report(platform: str) -> PlatformStats:
    """
    Generate a report for a specific platform.

    Args:
        platform: Platform name (youtube, tiktok, twitter).

    Returns:
        PlatformStats for the specified platform.

    Raises:
        ValueError: If platform is not supported.
    """
    if platform.lower() not in _SUPPORTED_PLATFORMS:
        raise ValueError(
            f"Unsupported platform. Supported: {', '.join(sorted(_SUPPORTED_PLATFORMS))}"
        )

    events = _load_events()
    return _compute_platform_stats(events, platform.lower())


def save_report(report: AnalyticsReport, output_path: str) -> str:
    """
    Save an analytics report to a JSON file.

    Args:
        report: The report to save.
        output_path: File path to save to.

    Returns:
        The absolute path to the saved report.
    """
    import tempfile

    if not output_path or "\x00" in output_path:
        raise ValueError("Invalid output path.")

    output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logger.info("Analytics report saved: %s", os.path.basename(output_path))
    return output_path

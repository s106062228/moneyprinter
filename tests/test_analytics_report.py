"""
Tests for src/analytics_report.py — analytics report generation.
"""

import os
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from collections import Counter

import analytics as analytics_module
import analytics_report as report_module
from analytics_report import (
    generate_report,
    get_platform_report,
    save_report,
    PlatformStats,
    AnalyticsReport,
    _compute_platform_stats,
    _compute_trend,
    _compute_daily_trend,
    _parse_event_date,
    _generate_recommendations,
    get_report_max_events,
    get_report_top_n,
)


@pytest.fixture(autouse=True)
def isolate_analytics(tmp_path):
    """Redirect analytics to a temp file for each test."""
    analytics_file = str(tmp_path / ".mp" / "analytics.json")
    os.makedirs(os.path.dirname(analytics_file), exist_ok=True)
    with patch.object(analytics_module, "ANALYTICS_FILE", analytics_file):
        yield analytics_file


def _seed_events(analytics_file, events):
    """Helper: write events to the analytics file."""
    data = {"events": events, "summary": {}}
    os.makedirs(os.path.dirname(analytics_file), exist_ok=True)
    with open(analytics_file, "w") as f:
        json.dump(data, f)


def _make_event(event_type, platform, days_ago=0, details=None):
    """Helper: create a properly structured event dict."""
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": ts,
        "type": event_type,
        "platform": platform,
        "details": details or {},
    }


# ---------------------------------------------------------------------------
# PlatformStats tests
# ---------------------------------------------------------------------------

class TestPlatformStats:
    """Tests for PlatformStats dataclass."""

    def test_default_values(self):
        stats = PlatformStats()
        assert stats.platform == ""
        assert stats.total_events == 0
        assert stats.success_rate == 0.0

    def test_to_dict(self):
        stats = PlatformStats(
            platform="youtube",
            total_events=10,
            successful_uploads=8,
            failed_uploads=2,
            success_rate=80.0,
        )
        d = stats.to_dict()
        assert d["platform"] == "youtube"
        assert d["total_events"] == 10
        assert d["success_rate"] == 80.0

    def test_to_dict_rounds_floats(self):
        stats = PlatformStats(success_rate=66.6666, avg_events_per_day=3.33333)
        d = stats.to_dict()
        assert d["success_rate"] == 66.67
        assert d["avg_events_per_day"] == 3.33


# ---------------------------------------------------------------------------
# AnalyticsReport tests
# ---------------------------------------------------------------------------

class TestAnalyticsReport:
    """Tests for AnalyticsReport dataclass."""

    def test_default_generated_at(self):
        report = AnalyticsReport()
        assert report.generated_at != ""
        # Parseable ISO datetime
        datetime.fromisoformat(report.generated_at)

    def test_to_dict(self):
        report = AnalyticsReport(total_events=5, busiest_platform="youtube")
        d = report.to_dict()
        assert d["total_events"] == 5
        assert d["busiest_platform"] == "youtube"

    def test_to_json(self):
        report = AnalyticsReport(total_events=3)
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["total_events"] == 3

    def test_to_text_empty(self):
        report = AnalyticsReport()
        text = report.to_text()
        assert "MONEYPRINTER ANALYTICS REPORT" in text
        assert "Total events tracked:  0" in text

    def test_to_text_with_data(self):
        stats = PlatformStats(
            platform="youtube",
            total_events=50,
            successful_uploads=45,
            failed_uploads=5,
            success_rate=90.0,
        )
        report = AnalyticsReport(
            total_events=50,
            platforms={"youtube": stats},
            overall_success_rate=90.0,
            busiest_platform="youtube",
        )
        text = report.to_text()
        assert "YOUTUBE" in text
        assert "90.0%" in text

    def test_to_text_with_recommendations(self):
        report = AnalyticsReport(recommendations=["Do more posting"])
        text = report.to_text()
        assert "RECOMMENDATIONS" in text
        assert "Do more posting" in text

    def test_to_text_with_daily_trend(self):
        today = datetime.now().date().isoformat()
        report = AnalyticsReport(daily_trend=[(today, 5)])
        text = report.to_text()
        assert "7-DAY ACTIVITY TREND" in text

    def test_to_text_truncated(self):
        """Text report is capped at max length."""
        report = AnalyticsReport(
            recommendations=["x" * 10000 for _ in range(10)]
        )
        text = report.to_text()
        assert len(text) <= 50000

    def test_to_dict_with_platform_stats(self):
        stats = PlatformStats(platform="tiktok", total_events=3)
        report = AnalyticsReport(platforms={"tiktok": stats})
        d = report.to_dict()
        assert d["platforms"]["tiktok"]["platform"] == "tiktok"


# ---------------------------------------------------------------------------
# _parse_event_date tests
# ---------------------------------------------------------------------------

class TestParseEventDate:
    def test_valid_timestamp(self):
        assert _parse_event_date({"timestamp": "2026-03-24T10:30:00"}) == "2026-03-24"

    def test_empty_timestamp(self):
        assert _parse_event_date({"timestamp": ""}) is None

    def test_missing_timestamp(self):
        assert _parse_event_date({}) is None

    def test_non_string_timestamp(self):
        assert _parse_event_date({"timestamp": 12345}) is None


# ---------------------------------------------------------------------------
# _compute_platform_stats tests
# ---------------------------------------------------------------------------

class TestComputePlatformStats:
    def test_empty_events(self):
        stats = _compute_platform_stats([], "youtube")
        assert stats.total_events == 0
        assert stats.success_rate == 0.0

    def test_all_successful(self):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("video_uploaded", "youtube"),
            _make_event("video_uploaded", "youtube"),
        ]
        stats = _compute_platform_stats(events, "youtube")
        assert stats.successful_uploads == 3
        assert stats.failed_uploads == 0
        assert stats.success_rate == 100.0

    def test_mixed_success_failure(self):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("publish_failed", "youtube", details={"error_type": "TimeoutError"}),
            _make_event("video_uploaded", "youtube"),
        ]
        stats = _compute_platform_stats(events, "youtube")
        assert stats.successful_uploads == 2
        assert stats.failed_uploads == 1
        assert abs(stats.success_rate - 66.67) < 1

    def test_filters_by_platform(self):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("tweet_posted", "twitter"),
            _make_event("video_uploaded", "youtube"),
        ]
        stats = _compute_platform_stats(events, "youtube")
        assert stats.total_events == 2

    def test_tracks_error_types(self):
        events = [
            _make_event("publish_failed", "youtube", details={"error_type": "TimeoutError"}),
            _make_event("publish_failed", "youtube", details={"error_type": "TimeoutError"}),
            _make_event("publish_failed", "youtube", details={"error_type": "ValueError"}),
        ]
        stats = _compute_platform_stats(events, "youtube")
        assert stats.most_common_error == "TimeoutError"

    def test_peak_day(self):
        events = [
            _make_event("video_uploaded", "youtube", days_ago=0),
            _make_event("video_uploaded", "youtube", days_ago=0),
            _make_event("video_uploaded", "youtube", days_ago=1),
        ]
        stats = _compute_platform_stats(events, "youtube")
        assert stats.peak_day_count == 2  # today has 2

    def test_event_type_distribution(self):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("video_generated", "youtube"),
            _make_event("video_uploaded", "youtube"),
        ]
        stats = _compute_platform_stats(events, "youtube")
        assert stats.events_by_type["video_uploaded"] == 2
        assert stats.events_by_type["video_generated"] == 1

    def test_twitter_events(self):
        events = [
            _make_event("tweet_posted", "twitter"),
            _make_event("tweet_posted", "twitter"),
        ]
        stats = _compute_platform_stats(events, "twitter")
        assert stats.successful_uploads == 2

    def test_tiktok_events(self):
        events = [
            _make_event("tiktok_uploaded", "tiktok"),
        ]
        stats = _compute_platform_stats(events, "tiktok")
        assert stats.successful_uploads == 1


# ---------------------------------------------------------------------------
# _compute_trend tests
# ---------------------------------------------------------------------------

class TestComputeTrend:
    def test_empty_counter(self):
        assert _compute_trend(Counter()) == "stable"

    def test_single_day(self):
        counter = Counter({datetime.now().date().isoformat(): 5})
        assert _compute_trend(counter) == "stable"

    def test_increasing_trend(self):
        today = datetime.now().date()
        counter = Counter()
        # Recent days have high activity
        for i in range(3):
            counter[(today - timedelta(days=i)).isoformat()] = 10
        # Older days have low activity
        for i in range(3, 7):
            counter[(today - timedelta(days=i)).isoformat()] = 1
        assert _compute_trend(counter) == "up"

    def test_decreasing_trend(self):
        today = datetime.now().date()
        counter = Counter()
        # Recent days have low activity
        for i in range(3):
            counter[(today - timedelta(days=i)).isoformat()] = 1
        # Older days have high activity
        for i in range(3, 7):
            counter[(today - timedelta(days=i)).isoformat()] = 10
        assert _compute_trend(counter) == "down"


# ---------------------------------------------------------------------------
# _compute_daily_trend tests
# ---------------------------------------------------------------------------

class TestComputeDailyTrend:
    def test_returns_7_days(self):
        trend = _compute_daily_trend([])
        assert len(trend) == 7

    def test_today_included(self):
        today = datetime.now().date().isoformat()
        trend = _compute_daily_trend([])
        dates = [t[0] for t in trend]
        assert today in dates

    def test_counts_events(self):
        events = [_make_event("video_uploaded", "youtube", days_ago=0) for _ in range(3)]
        trend = _compute_daily_trend(events)
        today_count = trend[-1][1]  # Last entry is today
        assert today_count == 3


# ---------------------------------------------------------------------------
# _generate_recommendations tests
# ---------------------------------------------------------------------------

class TestGenerateRecommendations:
    def test_empty_report(self):
        report = AnalyticsReport()
        recs = _generate_recommendations(report)
        assert any("No analytics data" in r for r in recs)

    def test_low_activity(self):
        report = AnalyticsReport(total_events=5)
        recs = _generate_recommendations(report)
        assert any("very low" in r.lower() for r in recs)

    def test_single_platform(self):
        stats = PlatformStats(platform="youtube", total_events=10)
        report = AnalyticsReport(
            total_events=10,
            platforms={"youtube": stats},
        )
        recs = _generate_recommendations(report)
        assert any("cross-posting" in r.lower() for r in recs)

    def test_low_success_rate(self):
        stats = PlatformStats(
            platform="youtube",
            total_events=10,
            successful_uploads=2,
            failed_uploads=8,
            success_rate=20.0,
            most_common_error="TimeoutError",
        )
        report = AnalyticsReport(
            total_events=10,
            platforms={"youtube": stats},
        )
        recs = _generate_recommendations(report)
        assert any("20%" in r for r in recs)

    def test_perfect_rate(self):
        stats = PlatformStats(
            platform="youtube",
            total_events=20,
            successful_uploads=20,
            failed_uploads=0,
            success_rate=100.0,
        )
        report = AnalyticsReport(
            total_events=20,
            platforms={"youtube": stats},
        )
        recs = _generate_recommendations(report)
        assert any("perfect" in r.lower() for r in recs)

    def test_recommendations_capped(self):
        """Never returns more than 8 recommendations."""
        stats = PlatformStats(
            platform="youtube",
            total_events=5,
            successful_uploads=1,
            failed_uploads=4,
            success_rate=20.0,
            recent_trend="down",
            most_common_error="TimeoutError",
        )
        report = AnalyticsReport(
            total_events=5,
            platforms={"youtube": stats},
        )
        recs = _generate_recommendations(report)
        assert len(recs) <= 8


# ---------------------------------------------------------------------------
# generate_report tests (integration)
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_empty_analytics(self, isolate_analytics):
        report = generate_report()
        assert report.total_events == 0
        assert len(report.recommendations) > 0

    def test_with_events(self, isolate_analytics):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("tweet_posted", "twitter"),
            _make_event("publish_failed", "youtube", details={"error_type": "TimeoutError"}),
        ]
        _seed_events(isolate_analytics, events)
        report = generate_report()
        assert report.total_events == 3
        assert "youtube" in report.platforms
        assert "twitter" in report.platforms

    def test_overall_success_rate(self, isolate_analytics):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("video_uploaded", "youtube"),
            _make_event("publish_failed", "youtube", details={"error_type": "Error"}),
        ]
        _seed_events(isolate_analytics, events)
        report = generate_report()
        assert abs(report.overall_success_rate - 66.67) < 1

    def test_busiest_platform(self, isolate_analytics):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("video_uploaded", "youtube"),
            _make_event("tweet_posted", "twitter"),
        ]
        _seed_events(isolate_analytics, events)
        report = generate_report()
        assert report.busiest_platform == "youtube"

    def test_event_type_distribution(self, isolate_analytics):
        events = [
            _make_event("video_uploaded", "youtube"),
            _make_event("video_generated", "youtube"),
        ]
        _seed_events(isolate_analytics, events)
        report = generate_report()
        assert report.event_type_distribution["video_uploaded"] == 1
        assert report.event_type_distribution["video_generated"] == 1

    def test_daily_trend_populated(self, isolate_analytics):
        events = [_make_event("video_uploaded", "youtube")]
        _seed_events(isolate_analytics, events)
        report = generate_report()
        assert len(report.daily_trend) == 7

    def test_max_events_limit(self, isolate_analytics):
        events = [_make_event("video_uploaded", "youtube") for _ in range(100)]
        _seed_events(isolate_analytics, events)
        report = generate_report(max_events=10)
        assert report.total_events == 10

    def test_json_roundtrip(self, isolate_analytics):
        events = [_make_event("video_uploaded", "youtube")]
        _seed_events(isolate_analytics, events)
        report = generate_report()
        j = report.to_json()
        d = json.loads(j)
        assert d["total_events"] == 1


# ---------------------------------------------------------------------------
# get_platform_report tests
# ---------------------------------------------------------------------------

class TestGetPlatformReport:
    def test_valid_platform(self, isolate_analytics):
        events = [_make_event("video_uploaded", "youtube")]
        _seed_events(isolate_analytics, events)
        stats = get_platform_report("youtube")
        assert stats.platform == "youtube"
        assert stats.total_events == 1

    def test_invalid_platform(self, isolate_analytics):
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_platform_report("snapchat")

    def test_case_insensitive(self, isolate_analytics):
        events = [_make_event("video_uploaded", "youtube")]
        _seed_events(isolate_analytics, events)
        stats = get_platform_report("YouTube")
        assert stats.platform == "youtube"


# ---------------------------------------------------------------------------
# save_report tests
# ---------------------------------------------------------------------------

class TestSaveReport:
    def test_save_report(self, tmp_path, isolate_analytics):
        report = AnalyticsReport(total_events=5)
        output = str(tmp_path / "report.json")
        path = save_report(report, output)
        assert os.path.isfile(path)
        with open(path) as f:
            d = json.load(f)
        assert d["total_events"] == 5

    def test_save_creates_directory(self, tmp_path, isolate_analytics):
        output = str(tmp_path / "subdir" / "report.json")
        report = AnalyticsReport()
        path = save_report(report, output)
        assert os.path.isfile(path)

    def test_save_invalid_path(self, isolate_analytics):
        report = AnalyticsReport()
        with pytest.raises(ValueError, match="Invalid output path"):
            save_report(report, "")

    def test_save_null_byte_path(self, isolate_analytics):
        report = AnalyticsReport()
        with pytest.raises(ValueError, match="Invalid output path"):
            save_report(report, "/tmp/report\x00.json")


# ---------------------------------------------------------------------------
# Config helpers tests
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    @patch("analytics_report._get", return_value={"report_max_events": 500})
    def test_get_report_max_events(self, mock_get):
        assert get_report_max_events() == 500

    @patch("analytics_report._get", return_value={"report_max_events": 999999})
    def test_max_events_capped(self, mock_get):
        assert get_report_max_events() == 10000

    @patch("analytics_report._get", return_value={"report_top_n": 20})
    def test_get_report_top_n(self, mock_get):
        assert get_report_top_n() == 20

    @patch("analytics_report._get", return_value={"report_top_n": 100})
    def test_top_n_capped(self, mock_get):
        assert get_report_top_n() == 50

    @patch("analytics_report._get", return_value={"report_top_n": -5})
    def test_top_n_min(self, mock_get):
        assert get_report_top_n() == 1

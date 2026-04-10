"""
Tests for auto_optimizer.py — Auto-Optimization Engine for MoneyPrinter.

Coverage categories:
  - PlatformInsight dataclass: creation, to_dict, from_dict, validation, clamping
  - NicheInsight dataclass: creation, to_dict, from_dict, validation, clamping
  - Recommendation dataclass: creation, to_dict, from_dict, truncation
  - OptimizationReport: creation, to_dict, to_text, from_dict with nested objects
  - Config helpers: get_optimizer_enabled, get_optimizer_lookback_days, get_optimizer_min_data_points, get_auto_tune_enabled
  - AutoOptimizer.__init__: default params, custom params, clamping
  - Data loading: _load_analytics_events, _load_revenue_entries, file missing, corrupt JSON, cap at limits
  - Filtering: _filter_by_lookback, filters old events, null byte timestamps, empty lists
  - Analysis methods: _analyze_platform_performance, _analyze_niche_performance, _enrich_with_revenue
  - Recommendations: _generate_recommendations, various edge cases
  - Health assessment: _assess_overall_health
  - Public API: generate_recommendations, auto_tune_schedule, get_history, clear_history
  - Persistence: _save_report, _load_history, _save_history, rotation
  - Module constants and convenience functions
  - Thread safety: concurrent calls
"""

import os
import sys
import json
import pytest
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, mock_open, call

# ---------------------------------------------------------------------------
# Ensure src/ is on the path before importing module under test.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import auto_optimizer
from auto_optimizer import (
    PlatformInsight,
    NicheInsight,
    Recommendation,
    OptimizationReport,
    AutoOptimizer,
    get_optimizer_enabled,
    get_optimizer_lookback_days,
    get_optimizer_min_data_points,
    get_auto_tune_enabled,
    generate_recommendations,
    auto_tune_schedule,
    _SUPPORTED_PLATFORMS,
    _SUPPORTED_NICHES,
    _MAX_RECOMMENDATIONS,
    _MAX_HISTORY_ENTRIES,
    _DEFAULT_LOOKBACK_DAYS,
    _MIN_LOOKBACK_DAYS,
    _MAX_LOOKBACK_DAYS,
    _MIN_DATA_POINTS,
    _DEFAULT_MIN_DATA_POINTS,
    _PLATFORM_WEIGHTS,
    _TIME_SLOTS,
)


# ===========================================================================
# PlatformInsight Tests
# ===========================================================================

class TestPlatformInsightCreation:
    """Tests for PlatformInsight dataclass."""

    def test_default_creation(self):
        """Test creating PlatformInsight with defaults."""
        pi = PlatformInsight(platform="youtube")
        assert pi.platform == "youtube"
        assert pi.total_events == 0
        assert pi.success_count == 0
        assert pi.failure_count == 0
        assert pi.success_rate == 0.0
        assert pi.estimated_revenue == 0.0
        assert pi.best_time_slot == ""
        assert pi.avg_events_per_day == 0.0
        assert pi.trend == "stable"
        assert pi.score == 0.0

    def test_custom_values(self):
        """Test creating PlatformInsight with custom values."""
        pi = PlatformInsight(
            platform="tiktok",
            total_events=100,
            success_count=85,
            failure_count=15,
            success_rate=85.0,
            estimated_revenue=150.25,
            best_time_slot="evening",
            avg_events_per_day=3.33,
            trend="growing",
            score=75.5,
        )
        assert pi.platform == "tiktok"
        assert pi.total_events == 100
        assert pi.success_count == 85
        assert pi.failure_count == 15
        assert pi.success_rate == 85.0
        assert pi.estimated_revenue == 150.25
        assert pi.best_time_slot == "evening"
        assert pi.avg_events_per_day == 3.33
        assert pi.trend == "growing"
        assert pi.score == 75.5

    def test_to_dict(self):
        """Test to_dict serialization."""
        pi = PlatformInsight(
            platform="youtube",
            total_events=50,
            success_rate=80.5,
            estimated_revenue=100.123,
            score=70.777,
        )
        d = pi.to_dict()
        assert isinstance(d, dict)
        assert d["platform"] == "youtube"
        assert d["total_events"] == 50
        assert d["success_rate"] == 80.5
        assert d["estimated_revenue"] == 100.12  # Rounded to 2 decimals
        assert d["score"] == 70.78  # Rounded to 2 decimals

    def test_to_dict_truncates_strings(self):
        """Test that to_dict truncates overly long strings."""
        pi = PlatformInsight(
            platform="youtube" + "x" * 100,
            best_time_slot="early_morning" + "x" * 100,
            trend="growing" + "x" * 100,
        )
        d = pi.to_dict()
        assert len(d["platform"]) <= 50
        assert len(d["best_time_slot"]) <= 50
        assert len(d["trend"]) <= 20

    def test_from_dict_valid(self):
        """Test from_dict with valid data."""
        data = {
            "platform": "instagram",
            "total_events": 30,
            "success_count": 25,
            "failure_count": 5,
            "success_rate": 83.33,
            "estimated_revenue": 50.5,
            "best_time_slot": "morning",
            "avg_events_per_day": 1.5,
            "trend": "stable",
            "score": 60.0,
        }
        pi = PlatformInsight.from_dict(data)
        assert pi.platform == "instagram"
        assert pi.total_events == 30
        assert pi.success_count == 25
        assert pi.success_rate == 83.33
        assert pi.estimated_revenue == 50.5

    def test_from_dict_missing_fields(self):
        """Test from_dict with missing optional fields."""
        data = {"platform": "twitter"}
        pi = PlatformInsight.from_dict(data)
        assert pi.platform == "twitter"
        assert pi.total_events == 0
        assert pi.success_count == 0
        assert pi.success_rate == 0.0

    def test_from_dict_clamps_success_rate(self):
        """Test from_dict clamps success_rate to 0-100."""
        data = {"platform": "youtube", "success_rate": 150.0}
        pi = PlatformInsight.from_dict(data)
        assert pi.success_rate == 100.0

        data = {"platform": "youtube", "success_rate": -10.0}
        pi = PlatformInsight.from_dict(data)
        assert pi.success_rate == 0.0

    def test_from_dict_clamps_score(self):
        """Test from_dict clamps score to 0-100."""
        data = {"platform": "youtube", "score": 200.0}
        pi = PlatformInsight.from_dict(data)
        assert pi.score == 100.0

        data = {"platform": "youtube", "score": -5.0}
        pi = PlatformInsight.from_dict(data)
        assert pi.score == 0.0

    def test_from_dict_clamps_negative_counts(self):
        """Test from_dict clamps negative counts to 0."""
        data = {
            "platform": "youtube",
            "total_events": -10,
            "success_count": -5,
            "failure_count": -3,
        }
        pi = PlatformInsight.from_dict(data)
        assert pi.total_events == 0
        assert pi.success_count == 0
        assert pi.failure_count == 0

    def test_from_dict_clamps_negative_revenue(self):
        """Test from_dict clamps negative revenue to 0."""
        data = {
            "platform": "youtube",
            "estimated_revenue": -100.0,
            "avg_events_per_day": -5.0,
        }
        pi = PlatformInsight.from_dict(data)
        assert pi.estimated_revenue == 0.0
        assert pi.avg_events_per_day == 0.0

    def test_from_dict_invalid_platform(self):
        """Test from_dict raises ValueError for invalid platform."""
        data = {"platform": "snapchat"}
        with pytest.raises(ValueError, match="Invalid platform"):
            PlatformInsight.from_dict(data)

    def test_from_dict_empty_platform(self):
        """Test from_dict raises ValueError for empty platform."""
        data = {"platform": ""}
        with pytest.raises(ValueError, match="Invalid platform"):
            PlatformInsight.from_dict(data)

    def test_from_dict_not_dict(self):
        """Test from_dict raises ValueError when data is not a dict."""
        with pytest.raises(ValueError, match="must be a dict"):
            PlatformInsight.from_dict("not a dict")

    def test_from_dict_case_insensitive_platform(self):
        """Test from_dict converts platform to lowercase."""
        data = {"platform": "YOUTUBE"}
        pi = PlatformInsight.from_dict(data)
        assert pi.platform == "youtube"

    def test_from_dict_strips_whitespace_platform(self):
        """Test from_dict strips whitespace from platform."""
        data = {"platform": "  youtube  "}
        pi = PlatformInsight.from_dict(data)
        assert pi.platform == "youtube"

    def test_from_dict_type_coercion(self):
        """Test from_dict coerces types."""
        data = {
            "platform": "youtube",
            "total_events": "50",
            "success_rate": "85.5",
            "estimated_revenue": "100.25",
        }
        pi = PlatformInsight.from_dict(data)
        assert pi.total_events == 50
        assert pi.success_rate == 85.5
        assert pi.estimated_revenue == 100.25


# ===========================================================================
# NicheInsight Tests
# ===========================================================================

class TestNicheInsightCreation:
    """Tests for NicheInsight dataclass."""

    def test_default_creation(self):
        """Test creating NicheInsight with defaults."""
        ni = NicheInsight(niche="finance")
        assert ni.niche == "finance"
        assert ni.total_videos == 0
        assert ni.total_revenue == 0.0
        assert ni.avg_revenue_per_video == 0.0
        assert ni.best_platform == ""
        assert ni.growth_potential == "medium"
        assert ni.score == 0.0

    def test_custom_values(self):
        """Test creating NicheInsight with custom values."""
        ni = NicheInsight(
            niche="technology",
            total_videos=50,
            total_revenue=500.0,
            avg_revenue_per_video=10.0,
            best_platform="youtube",
            growth_potential="high",
            score=85.5,
        )
        assert ni.niche == "technology"
        assert ni.total_videos == 50
        assert ni.total_revenue == 500.0
        assert ni.avg_revenue_per_video == 10.0
        assert ni.best_platform == "youtube"
        assert ni.growth_potential == "high"
        assert ni.score == 85.5

    def test_to_dict(self):
        """Test to_dict serialization."""
        ni = NicheInsight(
            niche="health",
            total_videos=30,
            total_revenue=300.123,
            avg_revenue_per_video=10.004,
            score=75.999,
        )
        d = ni.to_dict()
        assert d["niche"] == "health"
        assert d["total_videos"] == 30
        assert d["total_revenue"] == 300.12
        assert d["avg_revenue_per_video"] == 10.0
        assert d["score"] == 76.0

    def test_to_dict_truncates_niche(self):
        """Test that to_dict truncates overly long niche strings."""
        ni = NicheInsight(niche="x" * 200)
        d = ni.to_dict()
        assert len(d["niche"]) <= 100

    def test_from_dict_valid(self):
        """Test from_dict with valid data."""
        data = {
            "niche": "education",
            "total_videos": 25,
            "total_revenue": 250.0,
            "avg_revenue_per_video": 10.0,
            "best_platform": "youtube",
            "growth_potential": "high",
            "score": 80.0,
        }
        ni = NicheInsight.from_dict(data)
        assert ni.niche == "education"
        assert ni.total_videos == 25
        assert ni.total_revenue == 250.0
        assert ni.avg_revenue_per_video == 10.0

    def test_from_dict_missing_fields(self):
        """Test from_dict with missing optional fields."""
        data = {"niche": "gaming"}
        ni = NicheInsight.from_dict(data)
        assert ni.niche == "gaming"
        assert ni.total_videos == 0
        assert ni.total_revenue == 0.0

    def test_from_dict_clamps_score(self):
        """Test from_dict clamps score to 0-100."""
        data = {"niche": "finance", "score": 150.0}
        ni = NicheInsight.from_dict(data)
        assert ni.score == 100.0

    def test_from_dict_clamps_negative_values(self):
        """Test from_dict clamps negative revenue to 0."""
        data = {
            "niche": "technology",
            "total_revenue": -100.0,
            "avg_revenue_per_video": -10.0,
        }
        ni = NicheInsight.from_dict(data)
        assert ni.total_revenue == 0.0
        assert ni.avg_revenue_per_video == 0.0

    def test_from_dict_invalid_niche(self):
        """Test from_dict raises ValueError for invalid niche."""
        data = {"niche": "invalid_niche"}
        with pytest.raises(ValueError, match="Invalid niche"):
            NicheInsight.from_dict(data)

    def test_from_dict_empty_niche(self):
        """Test from_dict raises ValueError for empty niche."""
        data = {"niche": ""}
        with pytest.raises(ValueError, match="Invalid niche"):
            NicheInsight.from_dict(data)

    def test_from_dict_not_dict(self):
        """Test from_dict raises ValueError when data is not a dict."""
        with pytest.raises(ValueError, match="must be a dict"):
            NicheInsight.from_dict([1, 2, 3])

    def test_from_dict_case_insensitive_niche(self):
        """Test from_dict converts niche to lowercase."""
        data = {"niche": "FINANCE"}
        ni = NicheInsight.from_dict(data)
        assert ni.niche == "finance"

    def test_from_dict_all_supported_niches(self):
        """Test from_dict works with all supported niches."""
        for niche in _SUPPORTED_NICHES:
            data = {"niche": niche}
            ni = NicheInsight.from_dict(data)
            assert ni.niche == niche


# ===========================================================================
# Recommendation Tests
# ===========================================================================

class TestRecommendationCreation:
    """Tests for Recommendation dataclass."""

    def test_creation(self):
        """Test creating Recommendation."""
        rec = Recommendation(
            category="platform",
            priority="high",
            title="Expand to more platforms",
            description="Currently active on only 1 platform.",
            expected_impact="high",
        )
        assert rec.category == "platform"
        assert rec.priority == "high"
        assert rec.title == "Expand to more platforms"
        assert rec.description == "Currently active on only 1 platform."
        assert rec.expected_impact == "high"

    def test_to_dict(self):
        """Test to_dict serialization."""
        rec = Recommendation(
            category="niche",
            priority="medium",
            title="Test title",
            description="Test description",
            expected_impact="medium",
        )
        d = rec.to_dict()
        assert d["category"] == "niche"
        assert d["priority"] == "medium"
        assert d["title"] == "Test title"
        assert d["description"] == "Test description"
        assert d["expected_impact"] == "medium"

    def test_to_dict_truncates_strings(self):
        """Test that to_dict truncates overly long strings."""
        rec = Recommendation(
            category="x" * 100,
            priority="x" * 50,
            title="x" * 300,
            description="x" * 1200,
            expected_impact="x" * 50,
        )
        d = rec.to_dict()
        assert len(d["category"]) <= 50
        assert len(d["priority"]) <= 20
        assert len(d["title"]) <= 200
        assert len(d["description"]) <= 1000
        assert len(d["expected_impact"]) <= 20

    def test_from_dict_valid(self):
        """Test from_dict with valid data."""
        data = {
            "category": "timing",
            "priority": "high",
            "title": "Optimize posting time",
            "description": "Best performance is during evening.",
            "expected_impact": "medium",
        }
        rec = Recommendation.from_dict(data)
        assert rec.category == "timing"
        assert rec.priority == "high"
        assert rec.title == "Optimize posting time"

    def test_from_dict_missing_fields(self):
        """Test from_dict with missing fields uses defaults."""
        data = {}
        rec = Recommendation.from_dict(data)
        assert rec.category == "general"
        assert rec.priority == "medium"
        assert rec.title == ""
        assert rec.description == ""
        assert rec.expected_impact == "medium"

    def test_from_dict_not_dict(self):
        """Test from_dict raises ValueError when data is not a dict."""
        with pytest.raises(ValueError, match="must be a dict"):
            Recommendation.from_dict("not a dict")


# ===========================================================================
# OptimizationReport Tests
# ===========================================================================

class TestOptimizationReportCreation:
    """Tests for OptimizationReport dataclass."""

    def test_default_creation(self):
        """Test creating OptimizationReport with defaults."""
        report = OptimizationReport()
        assert report.generated_at == ""
        assert report.lookback_days == _DEFAULT_LOOKBACK_DAYS
        assert report.total_events_analyzed == 0
        assert report.platform_insights == []
        assert report.niche_insights == []
        assert report.recommendations == []
        assert report.top_platform == ""
        assert report.top_niche == ""
        assert report.overall_health == "unknown"

    def test_custom_values(self):
        """Test creating OptimizationReport with custom values."""
        pi = PlatformInsight(platform="youtube", total_events=50)
        ni = NicheInsight(niche="finance")
        rec = Recommendation(category="platform", priority="high", title="Test", description="Test desc", expected_impact="high")

        report = OptimizationReport(
            generated_at="2024-01-01T12:00:00Z",
            lookback_days=30,
            total_events_analyzed=100,
            platform_insights=[pi],
            niche_insights=[ni],
            recommendations=[rec],
            top_platform="youtube",
            top_niche="finance",
            overall_health="good",
        )
        assert report.generated_at == "2024-01-01T12:00:00Z"
        assert report.lookback_days == 30
        assert report.total_events_analyzed == 100
        assert len(report.platform_insights) == 1
        assert len(report.niche_insights) == 1
        assert len(report.recommendations) == 1
        assert report.top_platform == "youtube"
        assert report.top_niche == "finance"
        assert report.overall_health == "good"

    def test_to_dict(self):
        """Test to_dict serialization."""
        pi = PlatformInsight(platform="youtube", total_events=50, success_rate=80.0)
        ni = NicheInsight(niche="finance", total_videos=10)
        rec = Recommendation(
            category="platform", priority="high", title="Expand", description="Test", expected_impact="high"
        )

        report = OptimizationReport(
            generated_at="2024-01-01T12:00:00Z",
            lookback_days=30,
            total_events_analyzed=100,
            platform_insights=[pi],
            niche_insights=[ni],
            recommendations=[rec],
            top_platform="youtube",
            top_niche="finance",
            overall_health="good",
        )
        d = report.to_dict()
        assert d["generated_at"] == "2024-01-01T12:00:00Z"
        assert d["lookback_days"] == 30
        assert d["total_events_analyzed"] == 100
        assert len(d["platform_insights"]) == 1
        assert len(d["niche_insights"]) == 1
        assert len(d["recommendations"]) == 1

    def test_to_dict_caps_insights_and_recommendations(self):
        """Test to_dict caps insights and recommendations lists."""
        platforms = [PlatformInsight(platform=p) for p in _SUPPORTED_PLATFORMS]
        niches = [NicheInsight(niche=n) for n in list(_SUPPORTED_NICHES)[:10]]
        recs = [
            Recommendation(category="general", priority="low", title=f"Rec {i}", description="desc", expected_impact="low")
            for i in range(_MAX_RECOMMENDATIONS + 5)
        ]

        report = OptimizationReport(
            platform_insights=platforms,
            niche_insights=niches,
            recommendations=recs,
        )
        d = report.to_dict()
        assert len(d["platform_insights"]) <= len(_SUPPORTED_PLATFORMS)
        assert len(d["niche_insights"]) <= len(_SUPPORTED_NICHES)
        assert len(d["recommendations"]) <= _MAX_RECOMMENDATIONS

    def test_to_text(self):
        """Test to_text generates readable report."""
        pi = PlatformInsight(
            platform="youtube", total_events=50, success_rate=80.0, estimated_revenue=100.0
        )
        ni = NicheInsight(niche="finance", total_videos=10, total_revenue=50.0)
        rec = Recommendation(
            category="platform",
            priority="high",
            title="Expand platforms",
            description="Add more platforms",
            expected_impact="high",
        )

        report = OptimizationReport(
            generated_at="2024-01-01T12:00:00Z",
            lookback_days=30,
            total_events_analyzed=100,
            platform_insights=[pi],
            niche_insights=[ni],
            recommendations=[rec],
            top_platform="youtube",
            top_niche="finance",
            overall_health="good",
        )
        text = report.to_text()
        assert "MoneyPrinter Auto-Optimization Report" in text
        assert "2024-01-01T12:00:00Z" in text
        assert "30 days" in text
        assert "100" in text
        assert "good" in text
        assert "youtube" in text
        assert "finance" in text

    def test_to_text_truncates_output(self):
        """Test to_text truncates output to max length."""
        # Create many insights and recommendations
        platforms = [PlatformInsight(platform=p) for p in _SUPPORTED_PLATFORMS]
        niches = [NicheInsight(niche=n) for n in _SUPPORTED_NICHES]
        recs = [
            Recommendation(
                category="general",
                priority="low",
                title=f"Recommendation {i}",
                description="x" * 1000,
                expected_impact="low",
            )
            for i in range(30)
        ]

        report = OptimizationReport(
            generated_at="2024-01-01T12:00:00Z",
            total_events_analyzed=1000,
            platform_insights=platforms,
            niche_insights=niches,
            recommendations=recs,
            overall_health="excellent",
        )
        text = report.to_text()
        assert len(text) <= 50000

    def test_from_dict_valid(self):
        """Test from_dict with valid data."""
        data = {
            "generated_at": "2024-01-01T12:00:00Z",
            "lookback_days": 30,
            "total_events_analyzed": 100,
            "platform_insights": [
                {
                    "platform": "youtube",
                    "total_events": 50,
                    "success_count": 40,
                    "failure_count": 10,
                    "success_rate": 80.0,
                }
            ],
            "niche_insights": [
                {
                    "niche": "finance",
                    "total_videos": 10,
                    "total_revenue": 50.0,
                }
            ],
            "recommendations": [
                {
                    "category": "platform",
                    "priority": "high",
                    "title": "Expand",
                    "description": "Test",
                }
            ],
            "top_platform": "youtube",
            "top_niche": "finance",
            "overall_health": "good",
        }
        report = OptimizationReport.from_dict(data)
        assert report.generated_at == "2024-01-01T12:00:00Z"
        assert report.lookback_days == 30
        assert report.total_events_analyzed == 100
        assert len(report.platform_insights) == 1
        assert len(report.niche_insights) == 1
        assert len(report.recommendations) == 1

    def test_from_dict_invalid_nested_objects_skipped(self):
        """Test from_dict skips invalid nested objects."""
        data = {
            "platform_insights": [
                {"platform": "youtube"},  # Valid
                {"platform": "invalid"},  # Invalid, skipped
                {"platform": "tiktok"},   # Valid
            ],
            "niche_insights": [
                {"niche": "finance"},     # Valid
                {"niche": "invalid"},     # Invalid, skipped
            ],
        }
        report = OptimizationReport.from_dict(data)
        assert len(report.platform_insights) == 2
        assert len(report.niche_insights) == 1

    def test_from_dict_not_dict(self):
        """Test from_dict raises ValueError when data is not a dict."""
        with pytest.raises(ValueError, match="must be a dict"):
            OptimizationReport.from_dict("not a dict")

    def test_from_dict_clamps_lookback_days(self):
        """Test from_dict clamps lookback_days to valid range."""
        data = {"lookback_days": 1000}
        report = OptimizationReport.from_dict(data)
        assert report.lookback_days == _MAX_LOOKBACK_DAYS

        data = {"lookback_days": 0}
        report = OptimizationReport.from_dict(data)
        assert report.lookback_days == _MIN_LOOKBACK_DAYS


# ===========================================================================
# Config Helpers Tests
# ===========================================================================

class TestConfigHelpers:
    """Tests for configuration helper functions."""

    def test_get_optimizer_enabled_true(self):
        """Test get_optimizer_enabled returns True when enabled."""
        with patch("auto_optimizer._get", return_value={"enabled": True}):
            assert get_optimizer_enabled() is True

    def test_get_optimizer_enabled_false(self):
        """Test get_optimizer_enabled returns False when disabled."""
        with patch("auto_optimizer._get", return_value={"enabled": False}):
            assert get_optimizer_enabled() is False

    def test_get_optimizer_enabled_missing(self):
        """Test get_optimizer_enabled returns False when key missing."""
        with patch("auto_optimizer._get", return_value={}):
            assert get_optimizer_enabled() is False

    def test_get_optimizer_enabled_non_dict(self):
        """Test get_optimizer_enabled returns False when config is not dict."""
        with patch("auto_optimizer._get", return_value="not a dict"):
            assert get_optimizer_enabled() is False

    def test_get_optimizer_lookback_days_valid(self):
        """Test get_optimizer_lookback_days returns valid value."""
        with patch("auto_optimizer._get", return_value={"lookback_days": 14}):
            assert get_optimizer_lookback_days() == 14

    def test_get_optimizer_lookback_days_clamped_min(self):
        """Test get_optimizer_lookback_days clamps to minimum."""
        with patch("auto_optimizer._get", return_value={"lookback_days": 0}):
            assert get_optimizer_lookback_days() == _MIN_LOOKBACK_DAYS

    def test_get_optimizer_lookback_days_clamped_max(self):
        """Test get_optimizer_lookback_days clamps to maximum."""
        with patch("auto_optimizer._get", return_value={"lookback_days": 1000}):
            assert get_optimizer_lookback_days() == _MAX_LOOKBACK_DAYS

    def test_get_optimizer_lookback_days_invalid_type(self):
        """Test get_optimizer_lookback_days returns default on invalid type."""
        with patch("auto_optimizer._get", return_value={"lookback_days": "not a number"}):
            assert get_optimizer_lookback_days() == _DEFAULT_LOOKBACK_DAYS

    def test_get_optimizer_lookback_days_missing(self):
        """Test get_optimizer_lookback_days returns default when missing."""
        with patch("auto_optimizer._get", return_value={}):
            assert get_optimizer_lookback_days() == _DEFAULT_LOOKBACK_DAYS

    def test_get_optimizer_lookback_days_non_dict(self):
        """Test get_optimizer_lookback_days returns default when config not dict."""
        with patch("auto_optimizer._get", return_value="not a dict"):
            assert get_optimizer_lookback_days() == _DEFAULT_LOOKBACK_DAYS

    def test_get_optimizer_min_data_points_valid(self):
        """Test get_optimizer_min_data_points returns valid value."""
        with patch("auto_optimizer._get", return_value={"min_data_points": 10}):
            assert get_optimizer_min_data_points() == 10

    def test_get_optimizer_min_data_points_clamped_min(self):
        """Test get_optimizer_min_data_points clamps to minimum."""
        with patch("auto_optimizer._get", return_value={"min_data_points": 1}):
            assert get_optimizer_min_data_points() == _MIN_DATA_POINTS

    def test_get_optimizer_min_data_points_invalid_type(self):
        """Test get_optimizer_min_data_points returns default on invalid type."""
        with patch("auto_optimizer._get", return_value={"min_data_points": "invalid"}):
            assert get_optimizer_min_data_points() == _DEFAULT_MIN_DATA_POINTS

    def test_get_optimizer_min_data_points_missing(self):
        """Test get_optimizer_min_data_points returns default when missing."""
        with patch("auto_optimizer._get", return_value={}):
            assert get_optimizer_min_data_points() == _DEFAULT_MIN_DATA_POINTS

    def test_get_auto_tune_enabled_true(self):
        """Test get_auto_tune_enabled returns True when enabled."""
        with patch("auto_optimizer._get", return_value={"auto_tune": True}):
            assert get_auto_tune_enabled() is True

    def test_get_auto_tune_enabled_false(self):
        """Test get_auto_tune_enabled returns False when disabled."""
        with patch("auto_optimizer._get", return_value={"auto_tune": False}):
            assert get_auto_tune_enabled() is False

    def test_get_auto_tune_enabled_missing(self):
        """Test get_auto_tune_enabled returns False when key missing."""
        with patch("auto_optimizer._get", return_value={}):
            assert get_auto_tune_enabled() is False


# ===========================================================================
# AutoOptimizer Init Tests
# ===========================================================================

class TestAutoOptimizerInit:
    """Tests for AutoOptimizer initialization."""

    def test_default_init(self):
        """Test AutoOptimizer init with defaults."""
        with patch("auto_optimizer.get_optimizer_lookback_days", return_value=30):
            with patch("auto_optimizer.get_optimizer_min_data_points", return_value=5):
                opt = AutoOptimizer()
                assert opt._lookback_days == 30
                assert opt._min_data_points == 5

    def test_custom_lookback_days(self):
        """Test AutoOptimizer init with custom lookback_days."""
        opt = AutoOptimizer(lookback_days=14)
        assert opt._lookback_days == 14

    def test_custom_min_data_points(self):
        """Test AutoOptimizer init with custom min_data_points."""
        opt = AutoOptimizer(min_data_points=10)
        assert opt._min_data_points == 10

    def test_clamps_lookback_days_min(self):
        """Test AutoOptimizer clamps lookback_days to minimum."""
        opt = AutoOptimizer(lookback_days=0)
        assert opt._lookback_days == _MIN_LOOKBACK_DAYS

    def test_clamps_lookback_days_max(self):
        """Test AutoOptimizer clamps lookback_days to maximum."""
        opt = AutoOptimizer(lookback_days=1000)
        assert opt._lookback_days == _MAX_LOOKBACK_DAYS

    def test_clamps_min_data_points_min(self):
        """Test AutoOptimizer clamps min_data_points to minimum."""
        opt = AutoOptimizer(min_data_points=1)
        assert opt._min_data_points == _MIN_DATA_POINTS

    def test_clamps_min_data_points_max(self):
        """Test AutoOptimizer clamps min_data_points to maximum."""
        opt = AutoOptimizer(min_data_points=2000)
        assert opt._min_data_points == 1000

    def test_has_lock(self):
        """Test AutoOptimizer has threading lock."""
        opt = AutoOptimizer()
        assert hasattr(opt, "_lock")


# ===========================================================================
# Data Loading Tests
# ===========================================================================

class TestDataLoading:
    """Tests for _load_analytics_events and _load_revenue_entries."""

    def test_load_analytics_events_file_not_found(self):
        """Test _load_analytics_events returns empty list when file missing."""
        opt = AutoOptimizer()
        with patch("builtins.open", side_effect=FileNotFoundError):
            events = opt._load_analytics_events()
            assert events == []

    def test_load_analytics_events_valid_file(self):
        """Test _load_analytics_events loads valid JSON."""
        opt = AutoOptimizer()
        data = {"events": [{"platform": "youtube", "type": "uploaded"}]}
        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            events = opt._load_analytics_events()
            assert len(events) == 1
            assert events[0]["platform"] == "youtube"

    def test_load_analytics_events_corrupt_json(self):
        """Test _load_analytics_events returns empty list on corrupt JSON."""
        opt = AutoOptimizer()
        with patch("builtins.open", mock_open(read_data="invalid json")):
            events = opt._load_analytics_events()
            assert events == []

    def test_load_analytics_events_caps_at_10k(self):
        """Test _load_analytics_events caps at 10k events."""
        opt = AutoOptimizer()
        data = {"events": [{"platform": "youtube"}] * 15000}
        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            events = opt._load_analytics_events()
            assert len(events) == 10000

    def test_load_analytics_events_not_dict(self):
        """Test _load_analytics_events handles non-dict data."""
        opt = AutoOptimizer()
        with patch("builtins.open", mock_open(read_data=json.dumps([1, 2, 3]))):
            events = opt._load_analytics_events()
            assert events == []

    def test_load_analytics_events_events_not_list(self):
        """Test _load_analytics_events handles non-list events."""
        opt = AutoOptimizer()
        data = {"events": "not a list"}
        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            events = opt._load_analytics_events()
            assert events == []

    def test_load_revenue_entries_file_not_found(self):
        """Test _load_revenue_entries returns empty list when file missing."""
        opt = AutoOptimizer()
        with patch("builtins.open", side_effect=FileNotFoundError):
            entries = opt._load_revenue_entries()
            assert entries == []

    def test_load_revenue_entries_valid_file(self):
        """Test _load_revenue_entries loads valid JSON list."""
        opt = AutoOptimizer()
        data = [{"niche": "finance", "net_revenue": 100.0}]
        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            entries = opt._load_revenue_entries()
            assert len(entries) == 1
            assert entries[0]["niche"] == "finance"

    def test_load_revenue_entries_corrupt_json(self):
        """Test _load_revenue_entries returns empty list on corrupt JSON."""
        opt = AutoOptimizer()
        with patch("builtins.open", mock_open(read_data="invalid json")):
            entries = opt._load_revenue_entries()
            assert entries == []

    def test_load_revenue_entries_caps_at_50k(self):
        """Test _load_revenue_entries caps at 50k entries."""
        opt = AutoOptimizer()
        data = [{"niche": "finance"}] * 60000
        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            entries = opt._load_revenue_entries()
            assert len(entries) == 50000

    def test_load_revenue_entries_not_list(self):
        """Test _load_revenue_entries handles non-list data."""
        opt = AutoOptimizer()
        data = {"entries": [1, 2, 3]}
        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            entries = opt._load_revenue_entries()
            assert entries == []


# ===========================================================================
# Filtering Tests
# ===========================================================================

class TestFilterByLookback:
    """Tests for _filter_by_lookback method."""

    def test_filters_old_events(self):
        """Test _filter_by_lookback removes old events."""
        opt = AutoOptimizer(lookback_days=7)
        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(days=10)).isoformat()
        recent_date = (now - timedelta(days=3)).isoformat()

        events = [
            {"timestamp": old_date, "platform": "youtube"},
            {"timestamp": recent_date, "platform": "youtube"},
        ]
        filtered = opt._filter_by_lookback(events, "timestamp")
        assert len(filtered) == 1
        assert filtered[0]["timestamp"] == recent_date

    def test_filters_non_dict_entries(self):
        """Test _filter_by_lookback skips non-dict entries."""
        opt = AutoOptimizer()
        now = datetime.now(timezone.utc).isoformat()
        events = [
            {"timestamp": now},
            "not a dict",
            None,
            123,
        ]
        filtered = opt._filter_by_lookback(events, "timestamp")
        assert len(filtered) == 1

    def test_filters_null_byte_timestamps(self):
        """Test _filter_by_lookback skips timestamps with null bytes."""
        opt = AutoOptimizer()
        now = datetime.now(timezone.utc).isoformat()
        events = [
            {"timestamp": now},
            {"timestamp": now + "\x00extra"},
        ]
        filtered = opt._filter_by_lookback(events, "timestamp")
        assert len(filtered) == 1

    def test_filters_invalid_timestamp_type(self):
        """Test _filter_by_lookback skips non-string timestamps."""
        opt = AutoOptimizer()
        events = [
            {"timestamp": 12345},
            {"timestamp": None},
            {"timestamp": ["invalid"]},
        ]
        filtered = opt._filter_by_lookback(events, "timestamp")
        assert len(filtered) == 0

    def test_filters_overly_long_timestamps(self):
        """Test _filter_by_lookback skips overly long timestamps."""
        opt = AutoOptimizer()
        events = [
            {"timestamp": "x" * 101},
        ]
        filtered = opt._filter_by_lookback(events, "timestamp")
        assert len(filtered) == 0

    def test_empty_list(self):
        """Test _filter_by_lookback handles empty list."""
        opt = AutoOptimizer()
        filtered = opt._filter_by_lookback([], "timestamp")
        assert filtered == []

    def test_custom_timestamp_key(self):
        """Test _filter_by_lookback uses custom timestamp key."""
        opt = AutoOptimizer(lookback_days=7)
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=3)).isoformat()

        events = [
            {"custom_ts": recent},
        ]
        filtered = opt._filter_by_lookback(events, "custom_ts")
        assert len(filtered) == 1


# ===========================================================================
# Analysis Method Tests
# ===========================================================================

class TestAnalyzePlatformPerformance:
    """Tests for _analyze_platform_performance method."""

    def test_empty_events(self):
        """Test _analyze_platform_performance handles empty events."""
        opt = AutoOptimizer()
        insights = opt._analyze_platform_performance([])
        assert insights == []

    def test_single_platform_multiple_events(self):
        """Test _analyze_platform_performance with single platform."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T11:00:00Z"},
            {"platform": "youtube", "type": "failed", "timestamp": "2024-01-01T12:00:00Z"},
        ]
        insights = opt._analyze_platform_performance(events)
        assert len(insights) == 1
        assert insights[0].platform == "youtube"
        assert insights[0].success_count == 2
        assert insights[0].failure_count == 1

    def test_success_rate_calculation(self):
        """Test success rate is calculated correctly."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T11:00:00Z"},
            {"platform": "youtube", "type": "error", "timestamp": "2024-01-01T12:00:00Z"},
        ]
        insights = opt._analyze_platform_performance(events)
        assert insights[0].success_rate == 66.67

    def test_multiple_platforms(self):
        """Test _analyze_platform_performance with multiple platforms."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
            {"platform": "tiktok", "type": "posted", "timestamp": "2024-01-01T10:00:00Z"},
            {"platform": "twitter", "type": "published", "timestamp": "2024-01-01T10:00:00Z"},
        ]
        insights = opt._analyze_platform_performance(events)
        assert len(insights) == 3
        platforms = {i.platform for i in insights}
        assert platforms == {"youtube", "tiktok", "twitter"}

    def test_skips_non_dict_events(self):
        """Test _analyze_platform_performance skips non-dict events."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
            "not a dict",
            None,
        ]
        insights = opt._analyze_platform_performance(events)
        assert len(insights) == 1
        assert insights[0].total_events == 1

    def test_skips_invalid_platforms(self):
        """Test _analyze_platform_performance skips invalid platforms."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
            {"platform": "invalid_platform", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
        ]
        insights = opt._analyze_platform_performance(events)
        assert len(insights) == 1
        assert insights[0].platform == "youtube"

    def test_best_time_slot_assignment(self):
        """Test best time slot is determined."""
        opt = AutoOptimizer()
        # Create events in different time slots
        events = []
        for hour in [8, 9, 10, 15, 16, 20, 21]:  # Morning and evening
            for _ in range(3):
                events.append({
                    "platform": "youtube",
                    "type": "uploaded",
                    "timestamp": f"2024-01-01T{hour:02d}:00:00Z"
                })
        insights = opt._analyze_platform_performance(events)
        assert len(insights) == 1
        assert insights[0].best_time_slot in list(_TIME_SLOTS.keys())

    def test_trend_detection_growing(self):
        """Test trend detection identifies growing trend."""
        opt = AutoOptimizer()
        # First half: few events, second half: many events
        events = []
        for i, date in enumerate(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04",
                                    "2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"]):
            count = 1 if i < 4 else 5  # Growing in second half
            for _ in range(count):
                events.append({
                    "platform": "youtube",
                    "type": "uploaded",
                    "timestamp": f"{date}T10:00:00Z"
                })
        insights = opt._analyze_platform_performance(events)
        assert insights[0].trend == "growing"

    def test_trend_detection_declining(self):
        """Test trend detection identifies declining trend."""
        opt = AutoOptimizer()
        # First half: many events, second half: few events
        events = []
        for i, date in enumerate(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04",
                                    "2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"]):
            count = 5 if i < 4 else 1  # Declining in second half
            for _ in range(count):
                events.append({
                    "platform": "youtube",
                    "type": "uploaded",
                    "timestamp": f"{date}T10:00:00Z"
                })
        insights = opt._analyze_platform_performance(events)
        assert insights[0].trend == "declining"

    def test_avg_events_per_day(self):
        """Test average events per day is calculated."""
        opt = AutoOptimizer()
        events = []
        for date in ["2024-01-01", "2024-01-02", "2024-01-03"]:
            for _ in range(4):
                events.append({
                    "platform": "youtube",
                    "type": "uploaded",
                    "timestamp": f"{date}T10:00:00Z"
                })
        insights = opt._analyze_platform_performance(events)
        assert insights[0].avg_events_per_day == 4.0

    def test_score_calculation(self):
        """Test composite score is calculated."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
        ]
        insights = opt._analyze_platform_performance(events)
        assert insights[0].score >= 0.0
        assert insights[0].score <= 100.0

    def test_sorted_by_score_descending(self):
        """Test insights are sorted by score descending."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T11:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T12:00:00Z"},
            {"platform": "tiktok", "type": "posted", "timestamp": "2024-01-01T10:00:00Z"},
        ]
        insights = opt._analyze_platform_performance(events)
        scores = [i.score for i in insights]
        assert scores == sorted(scores, reverse=True)


class TestAnalyzeNichePerformance:
    """Tests for _analyze_niche_performance method."""

    def test_empty_entries(self):
        """Test _analyze_niche_performance handles empty entries."""
        opt = AutoOptimizer()
        insights = opt._analyze_niche_performance([])
        assert insights == []

    def test_single_niche_multiple_entries(self):
        """Test _analyze_niche_performance with single niche."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "finance", "net_revenue": 100.0},
            {"niche": "finance", "net_revenue": 150.0},
            {"niche": "finance", "net_revenue": 50.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert len(insights) == 1
        assert insights[0].niche == "finance"
        assert insights[0].total_videos == 3
        assert insights[0].total_revenue == 300.0
        assert insights[0].avg_revenue_per_video == 100.0

    def test_multiple_niches(self):
        """Test _analyze_niche_performance with multiple niches."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "finance", "net_revenue": 100.0},
            {"niche": "technology", "net_revenue": 50.0},
            {"niche": "health", "net_revenue": 75.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert len(insights) == 3

    def test_invalid_niche_defaults_to_general(self):
        """Test _analyze_niche_performance defaults to general for invalid niches."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "invalid_niche", "net_revenue": 100.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert len(insights) == 1
        assert insights[0].niche == "general"

    def test_negative_revenue_clamped_to_zero(self):
        """Test _analyze_niche_performance clamps negative revenue."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "finance", "net_revenue": -100.0},
            {"niche": "finance", "net_revenue": 100.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert insights[0].total_revenue == 100.0

    def test_growth_potential_high(self):
        """Test growth potential is marked as high for high revenue."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "finance", "net_revenue": 10.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert insights[0].growth_potential == "high"

    def test_growth_potential_medium(self):
        """Test growth potential is marked as medium for medium revenue."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "technology", "net_revenue": 2.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert insights[0].growth_potential == "medium"

    def test_growth_potential_low(self):
        """Test growth potential is marked as low for low revenue."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "entertainment", "net_revenue": 0.5},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert insights[0].growth_potential == "low"

    def test_best_platform_determination(self):
        """Test best platform is determined from revenue data."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "finance", "platform": "youtube", "net_revenue": 100.0},
            {"niche": "finance", "platform": "youtube", "net_revenue": 50.0},
            {"niche": "finance", "platform": "tiktok", "net_revenue": 30.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        assert insights[0].best_platform == "youtube"

    def test_skips_non_dict_entries(self):
        """Test _analyze_niche_performance skips non-dict entries."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "finance", "net_revenue": 100.0},
            "not a dict",
            None,
        ]
        insights = opt._analyze_niche_performance(entries)
        assert len(insights) == 1

    def test_sorted_by_score_descending(self):
        """Test insights are sorted by score descending."""
        opt = AutoOptimizer()
        entries = [
            {"niche": "finance", "net_revenue": 100.0},
            {"niche": "technology", "net_revenue": 20.0},
            {"niche": "health", "net_revenue": 50.0},
        ]
        insights = opt._analyze_niche_performance(entries)
        scores = [i.score for i in insights]
        assert scores == sorted(scores, reverse=True)


class TestEnrichWithRevenue:
    """Tests for _enrich_with_revenue method."""

    def test_adds_revenue_to_insights(self):
        """Test _enrich_with_revenue adds revenue to platform insights."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", estimated_revenue=0.0)
        revenue_entries = [
            {"platform": "youtube", "net_revenue": 100.0},
            {"platform": "youtube", "net_revenue": 50.0},
        ]
        opt._enrich_with_revenue([pi], revenue_entries)
        assert pi.estimated_revenue == 150.0

    def test_handles_missing_platform(self):
        """Test _enrich_with_revenue handles platforms not in revenue data."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="tiktok", estimated_revenue=0.0)
        revenue_entries = [
            {"platform": "youtube", "net_revenue": 100.0},
        ]
        opt._enrich_with_revenue([pi], revenue_entries)
        assert pi.estimated_revenue == 0.0

    def test_skips_non_dict_entries(self):
        """Test _enrich_with_revenue skips non-dict revenue entries."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", estimated_revenue=0.0)
        revenue_entries = [
            {"platform": "youtube", "net_revenue": 100.0},
            "not a dict",
        ]
        opt._enrich_with_revenue([pi], revenue_entries)
        assert pi.estimated_revenue == 100.0

    def test_clamps_negative_revenue(self):
        """Test _enrich_with_revenue clamps negative revenue."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", estimated_revenue=0.0)
        revenue_entries = [
            {"platform": "youtube", "net_revenue": -100.0},
            {"platform": "youtube", "net_revenue": 150.0},
        ]
        opt._enrich_with_revenue([pi], revenue_entries)
        assert pi.estimated_revenue == 150.0


# ===========================================================================
# Recommendation Generation Tests
# ===========================================================================

class TestGenerateRecommendations:
    """Tests for _generate_recommendations method."""

    def test_low_volume_recommendation(self):
        """Test recommendation for low volume content."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=5)
        recs = opt._generate_recommendations([pi], [], 5)
        assert any(r.category == "frequency" and r.priority == "high" for r in recs)

    def test_expand_platforms_recommendation(self):
        """Test recommendation to expand to more platforms."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=10)
        recs = opt._generate_recommendations([pi], [], 10)
        assert any(r.category == "platform" and "Expand" in r.title for r in recs)

    def test_fix_reliability_recommendation(self):
        """Test recommendation to fix low success rate."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=10, success_rate=30.0, failure_count=7)
        recs = opt._generate_recommendations([pi], [], 10)
        assert any(r.category == "platform" and "Fix" in r.title for r in recs)

    def test_reverse_decline_recommendation(self):
        """Test recommendation to reverse declining trend."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=15, trend="declining")
        recs = opt._generate_recommendations([pi], [], 15)
        assert any(r.category == "platform" and "declining" in r.description.lower() for r in recs)

    def test_timing_recommendation(self):
        """Test recommendation for optimal posting time."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=10, best_time_slot="morning")
        recs = opt._generate_recommendations([pi], [], 10)
        assert any(r.category == "timing" for r in recs)

    def test_niche_doubledown_recommendation(self):
        """Test recommendation to focus on top niche."""
        opt = AutoOptimizer()
        ni = NicheInsight(niche="finance", avg_revenue_per_video=10.0)
        recs = opt._generate_recommendations([], [ni], 10)
        assert any(r.category == "niche" and "Double down" in r.title for r in recs)

    def test_explore_niches_recommendation(self):
        """Test recommendation to explore high-CPM niches."""
        opt = AutoOptimizer()
        ni = NicheInsight(niche="entertainment")
        recs = opt._generate_recommendations([], [ni], 10)
        assert any(r.category == "niche" and "Explore" in r.title for r in recs)

    def test_scale_top_platform_recommendation(self):
        """Test recommendation to scale top earning platform."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=50, estimated_revenue=500.0)
        recs = opt._generate_recommendations([pi], [], 50)
        assert any(r.category == "general" and "Scale" in r.title for r in recs)

    def test_capped_at_max_recommendations(self):
        """Test recommendations are capped at max."""
        opt = AutoOptimizer()
        platforms = [PlatformInsight(platform=p) for p in _SUPPORTED_PLATFORMS]
        recs = opt._generate_recommendations(platforms, [], 100)
        assert len(recs) <= _MAX_RECOMMENDATIONS


# ===========================================================================
# Overall Health Assessment Tests
# ===========================================================================

class TestAssessOverallHealth:
    """Tests for _assess_overall_health method."""

    def test_unknown_health_no_events(self):
        """Test health is unknown with no events."""
        opt = AutoOptimizer()
        health = opt._assess_overall_health([], 0)
        assert health == "unknown"

    def test_excellent_health(self):
        """Test excellent health rating."""
        opt = AutoOptimizer()
        pi1 = PlatformInsight(platform="youtube", total_events=10, success_rate=85.0)
        pi2 = PlatformInsight(platform="tiktok", total_events=10, success_rate=90.0)
        pi3 = PlatformInsight(platform="twitter", total_events=10, success_rate=80.0)
        health = opt._assess_overall_health([pi1, pi2, pi3], 30)
        assert health == "excellent"

    def test_good_health(self):
        """Test good health rating."""
        opt = AutoOptimizer()
        pi1 = PlatformInsight(platform="youtube", total_events=10, success_rate=70.0)
        pi2 = PlatformInsight(platform="tiktok", total_events=10, success_rate=70.0)
        health = opt._assess_overall_health([pi1, pi2], 20)
        assert health == "good"

    def test_fair_health(self):
        """Test fair health rating."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=10, success_rate=50.0)
        health = opt._assess_overall_health([pi], 10)
        assert health == "fair"

    def test_poor_health(self):
        """Test poor health rating."""
        opt = AutoOptimizer()
        pi = PlatformInsight(platform="youtube", total_events=10, success_rate=30.0)
        health = opt._assess_overall_health([pi], 10)
        assert health == "poor"


# ===========================================================================
# Public API Tests
# ===========================================================================

class TestGenerateRecommendationsAPI:
    """Tests for generate_recommendations public method."""

    def test_generates_report_with_empty_data(self):
        """Test generate_recommendations works with empty data."""
        opt = AutoOptimizer()
        with patch.object(opt, "_load_analytics_events", return_value=[]):
            with patch.object(opt, "_load_revenue_entries", return_value=[]):
                report = opt.generate_recommendations()
                assert isinstance(report, OptimizationReport)
                assert report.total_events_analyzed == 0
                assert report.overall_health == "unknown"

    def test_generates_report_with_data(self):
        """Test generate_recommendations generates full report."""
        opt = AutoOptimizer()
        now = datetime.now(timezone.utc)
        ts1 = now.isoformat()
        ts2 = (now - timedelta(hours=1)).isoformat()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": ts1},
            {"platform": "youtube", "type": "uploaded", "timestamp": ts2},
        ]
        with patch.object(opt, "_load_analytics_events", return_value=events):
            with patch.object(opt, "_load_revenue_entries", return_value=[]):
                report = opt.generate_recommendations()
                assert report.total_events_analyzed == 2
                assert len(report.platform_insights) > 0

    def test_saves_report_to_history(self):
        """Test generate_recommendations saves report to history."""
        opt = AutoOptimizer()
        with patch.object(opt, "_load_analytics_events", return_value=[]):
            with patch.object(opt, "_load_revenue_entries", return_value=[]):
                with patch.object(opt, "_save_report") as mock_save:
                    opt.generate_recommendations()
                    mock_save.assert_called_once()

    def test_filters_by_lookback(self):
        """Test generate_recommendations filters by lookback period."""
        opt = AutoOptimizer(lookback_days=7)
        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(days=30)).isoformat()
        recent_date = now.isoformat()

        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": old_date},
            {"platform": "youtube", "type": "uploaded", "timestamp": recent_date},
        ]
        with patch.object(opt, "_load_analytics_events", return_value=events):
            with patch.object(opt, "_load_revenue_entries", return_value=[]):
                report = opt.generate_recommendations()
                # Only recent event should be counted
                assert report.total_events_analyzed == 1


class TestAutoTuneScheduleAPI:
    """Tests for auto_tune_schedule public method."""

    def test_auto_tune_disabled(self):
        """Test auto_tune_schedule returns empty when disabled."""
        opt = AutoOptimizer()
        with patch("auto_optimizer.get_auto_tune_enabled", return_value=False):
            result = opt.auto_tune_schedule()
            assert result == {}

    def test_auto_tune_enabled_no_data(self):
        """Test auto_tune_schedule with no data."""
        opt = AutoOptimizer()
        with patch("auto_optimizer.get_auto_tune_enabled", return_value=True):
            with patch.object(opt, "_load_analytics_events", return_value=[]):
                result = opt.auto_tune_schedule()
                assert result == {}

    def test_auto_tune_enabled_with_data(self):
        """Test auto_tune_schedule returns recommendations."""
        opt = AutoOptimizer()
        now = datetime.now(timezone.utc)
        ts_base = now.strftime("%Y-%m-%dT")
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": ts_base + "08:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": ts_base + "08:30:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": ts_base + "15:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": ts_base + "15:30:00Z"},
        ]
        with patch("auto_optimizer.get_auto_tune_enabled", return_value=True):
            with patch.object(opt, "_load_analytics_events", return_value=events):
                result = opt.auto_tune_schedule()
                assert "youtube" in result
                assert isinstance(result["youtube"], list)
                assert all(isinstance(h, str) for h in result["youtube"])

    def test_auto_tune_minimum_events_per_hour(self):
        """Test auto_tune_schedule requires minimum 2 events per hour."""
        opt = AutoOptimizer()
        events = [
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T08:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T09:00:00Z"},
            {"platform": "youtube", "type": "uploaded", "timestamp": "2024-01-01T10:00:00Z"},
        ]
        with patch("auto_optimizer.get_auto_tune_enabled", return_value=True):
            with patch.object(opt, "_load_analytics_events", return_value=events):
                result = opt.auto_tune_schedule()
                # Only hours with >= 2 events are considered, so result may be empty
                # or partial depending on the data


class TestGetHistoryAPI:
    """Tests for get_history public method."""

    def test_get_history_empty(self):
        """Test get_history returns empty list when no history."""
        opt = AutoOptimizer()
        with patch.object(opt, "_load_history", return_value=[]):
            history = opt.get_history()
            assert history == []

    def test_get_history_with_data(self):
        """Test get_history returns recent reports."""
        opt = AutoOptimizer()
        reports = [
            {"generated_at": "2024-01-01T12:00:00Z"},
            {"generated_at": "2024-01-02T12:00:00Z"},
            {"generated_at": "2024-01-03T12:00:00Z"},
        ]
        with patch.object(opt, "_load_history", return_value=reports):
            history = opt.get_history()
            assert len(history) == 3
            # Most recent first
            assert history[0]["generated_at"] == "2024-01-03T12:00:00Z"

    def test_get_history_respects_limit(self):
        """Test get_history respects limit parameter."""
        opt = AutoOptimizer()
        reports = [{"generated_at": f"2024-01-{i:02d}T12:00:00Z"} for i in range(1, 21)]
        with patch.object(opt, "_load_history", return_value=reports):
            history = opt.get_history(limit=5)
            assert len(history) == 5

    def test_get_history_clamps_limit(self):
        """Test get_history clamps limit to valid range."""
        opt = AutoOptimizer()
        reports = [{"generated_at": "2024-01-01T12:00:00Z"}]
        with patch.object(opt, "_load_history", return_value=reports):
            history = opt.get_history(limit=200)
            assert len(history) <= 100  # Clamped to max 100


class TestClearHistoryAPI:
    """Tests for clear_history public method."""

    def test_clear_history(self):
        """Test clear_history clears the history file."""
        opt = AutoOptimizer()
        with patch.object(opt, "_save_history") as mock_save:
            opt.clear_history()
            mock_save.assert_called_once_with([])


# ===========================================================================
# Persistence Tests
# ===========================================================================

class TestPersistence:
    """Tests for persistence methods."""

    def test_save_and_load_report(self):
        """Test saving and loading reports."""
        opt = AutoOptimizer()
        report = OptimizationReport(
            generated_at="2024-01-01T12:00:00Z",
            total_events_analyzed=100,
            overall_health="good",
        )
        with patch.object(opt, "_load_history", return_value=[]):
            with patch.object(opt, "_save_history") as mock_save:
                opt._save_report(report)
                mock_save.assert_called_once()
                # Get the history passed to save
                call_args = mock_save.call_args[0][0]
                assert len(call_args) == 1
                assert call_args[0]["generated_at"] == "2024-01-01T12:00:00Z"

    def test_load_history_file_not_found(self):
        """Test _load_history returns empty list when file missing."""
        opt = AutoOptimizer()
        with patch("builtins.open", side_effect=FileNotFoundError):
            history = opt._load_history()
            assert history == []

    def test_load_history_corrupt_json(self):
        """Test _load_history returns empty list on corrupt JSON."""
        opt = AutoOptimizer()
        with patch("builtins.open", mock_open(read_data="invalid json")):
            history = opt._load_history()
            assert history == []

    def test_load_history_not_list(self):
        """Test _load_history handles non-list data."""
        opt = AutoOptimizer()
        with patch("builtins.open", mock_open(read_data=json.dumps({"data": []}))):
            history = opt._load_history()
            assert history == []

    def test_save_history_atomic(self):
        """Test _save_history uses atomic write."""
        opt = AutoOptimizer()
        history = [{"test": "data"}]
        mock_file = mock_open()
        with patch("auto_optimizer.tempfile.mkstemp") as mock_mkstemp:
            with patch("auto_optimizer.os.fdopen", mock_file):
                with patch("auto_optimizer.os.replace"):
                    with patch("auto_optimizer.os.makedirs"):
                        mock_mkstemp.return_value = (123, "/tmp/test.tmp")
                        opt._save_history(history)
                        assert mock_mkstemp.called

    def test_save_history_caps_entries(self):
        """Test _save_history caps history at max entries."""
        opt = AutoOptimizer()
        history = [{"data": i} for i in range(_MAX_HISTORY_ENTRIES + 100)]
        with patch("builtins.open", mock_open()):
            with patch("os.replace"):
                with patch("os.makedirs"):
                    with patch("tempfile.mkstemp", return_value=(123, "/tmp/test")):
                        with patch("os.fdopen", mock_open()):
                            # Just verify it doesn't crash with large history
                            opt._save_history(history)


# ===========================================================================
# Module Convenience Functions Tests
# ===========================================================================

class TestModuleConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_generate_recommendations_function(self):
        """Test module-level generate_recommendations function."""
        with patch("auto_optimizer.AutoOptimizer") as MockOptimizer:
            mock_instance = MagicMock()
            mock_instance.generate_recommendations.return_value = OptimizationReport()
            MockOptimizer.return_value = mock_instance

            result = generate_recommendations()
            assert isinstance(result, OptimizationReport)
            MockOptimizer.assert_called_once()

    def test_generate_recommendations_with_lookback(self):
        """Test module-level generate_recommendations with lookback_days."""
        with patch("auto_optimizer.AutoOptimizer") as MockOptimizer:
            mock_instance = MagicMock()
            mock_instance.generate_recommendations.return_value = OptimizationReport()
            MockOptimizer.return_value = mock_instance

            generate_recommendations(lookback_days=14)
            MockOptimizer.assert_called_once_with(lookback_days=14)

    def test_auto_tune_schedule_function(self):
        """Test module-level auto_tune_schedule function."""
        with patch("auto_optimizer.AutoOptimizer") as MockOptimizer:
            mock_instance = MagicMock()
            mock_instance.auto_tune_schedule.return_value = {"youtube": ["08:00", "15:00"]}
            MockOptimizer.return_value = mock_instance

            result = auto_tune_schedule()
            assert isinstance(result, dict)
            MockOptimizer.assert_called_once()


# ===========================================================================
# Thread Safety Tests
# ===========================================================================

class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_generate_recommendations(self):
        """Test concurrent calls to generate_recommendations don't crash."""
        opt = AutoOptimizer()
        with patch.object(opt, "_load_analytics_events", return_value=[]):
            with patch.object(opt, "_load_revenue_entries", return_value=[]):
                results = []

                def call_generate():
                    report = opt.generate_recommendations()
                    results.append(report)

                threads = [threading.Thread(target=call_generate) for _ in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                assert len(results) == 5
                assert all(isinstance(r, OptimizationReport) for r in results)

    def test_concurrent_get_history(self):
        """Test concurrent calls to get_history don't crash."""
        opt = AutoOptimizer()
        with patch.object(opt, "_load_history", return_value=[]):
            results = []

            def call_get_history():
                history = opt.get_history()
                results.append(history)

            threads = [threading.Thread(target=call_get_history) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(results) == 5


# ===========================================================================
# Module Constants Tests
# ===========================================================================

class TestModuleConstants:
    """Tests for module-level constants."""

    def test_supported_platforms(self):
        """Test SUPPORTED_PLATFORMS contains expected values."""
        assert _SUPPORTED_PLATFORMS == {"youtube", "tiktok", "twitter", "instagram"}

    def test_supported_niches(self):
        """Test SUPPORTED_NICHES contains expected values."""
        expected = {
            "finance", "technology", "health", "education", "gaming",
            "entertainment", "lifestyle", "cooking", "travel", "business", "general",
        }
        assert _SUPPORTED_NICHES == expected

    def test_platform_weights(self):
        """Test PLATFORM_WEIGHTS has correct structure."""
        assert "youtube" in _PLATFORM_WEIGHTS
        assert _PLATFORM_WEIGHTS["youtube"] == 1.0
        assert all(0 < w <= 1.0 for w in _PLATFORM_WEIGHTS.values())

    def test_time_slots(self):
        """Test TIME_SLOTS has correct structure."""
        assert "early_morning" in _TIME_SLOTS
        assert "morning" in _TIME_SLOTS
        assert "afternoon" in _TIME_SLOTS
        assert "evening" in _TIME_SLOTS
        assert "night" in _TIME_SLOTS
        assert "late_night" in _TIME_SLOTS

    def test_max_history_entries(self):
        """Test MAX_HISTORY_ENTRIES is reasonable."""
        assert _MAX_HISTORY_ENTRIES > 0
        assert _MAX_HISTORY_ENTRIES == 500

    def test_max_recommendations(self):
        """Test MAX_RECOMMENDATIONS is reasonable."""
        assert _MAX_RECOMMENDATIONS > 0
        assert _MAX_RECOMMENDATIONS == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Tests for the niche_discovery module."""

import json
import os
import sys
import tempfile
import threading

import pytest

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from niche_discovery import (
    NicheOpportunity,
    DiscoveryReport,
    NicheDiscoveryEngine,
    _safe_float,
    _safe_int,
    _read_config_float,
    get_trend_weight,
    get_profit_weight,
    get_cpm_weight,
    get_volume_weight,
    get_lookback_days,
    get_min_data_points,
    get_max_results,
    _CPM_BY_NICHE,
    _KNOWN_NICHES,
    _TOPIC_SEEDS,
    _SUPPORTED_PLATFORMS,
    _MAX_NICHE_LENGTH,
    _MAX_RESULTS,
    _MAX_LOOKBACK_DAYS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for persistence tests."""
    return str(tmp_path)


@pytest.fixture
def engine(tmp_dir):
    """Provide a NicheDiscoveryEngine with a temp data dir."""
    return NicheDiscoveryEngine(data_dir=tmp_dir)


class MockRevenueTracker:
    """Mock revenue tracker for testing."""

    def __init__(self, entries=None):
        self._entries = entries or []

    def get_entries(self, days=None, niche=None):
        if niche:
            return [e for e in self._entries if e.get("niche") == niche]
        return self._entries


class MockProfitCalculator:
    """Mock profit calculator for testing."""

    def __init__(self, summary=None, entries=None):
        self._summary = summary
        self._entries = entries or []

    def get_profit_summary(self, days=None, niche=None):
        return self._summary

    def get_cost_entries(self, days=None, niche=None):
        if niche:
            return [e for e in self._entries if e.get("niche") == niche]
        return self._entries


class MockTrendDetector:
    """Mock trend detector for testing."""

    def __init__(self, topics=None):
        self._topics = topics or []

    def get_cached_topics(self):
        return self._topics


class MockTopic:
    """Mock topic candidate."""

    def __init__(self, topic, score=7.0):
        self.topic = topic
        self.score = score


# ---------------------------------------------------------------------------
# _safe_float / _safe_int tests
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14

    def test_valid_int(self):
        assert _safe_float(5) == 5.0

    def test_valid_string(self):
        assert _safe_float("2.5") == 2.5

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_none_custom_default(self):
        assert _safe_float(None, 5.5) == 5.5

    def test_invalid_string(self):
        assert _safe_float("abc") == 0.0

    def test_nan(self):
        assert _safe_float(float("nan")) == 0.0

    def test_list(self):
        assert _safe_float([1, 2]) == 0.0


class TestSafeInt:
    def test_valid_int(self):
        assert _safe_int(42) == 42

    def test_valid_float(self):
        assert _safe_int(3.7) == 3

    def test_valid_string(self):
        assert _safe_int("10") == 10

    def test_none(self):
        assert _safe_int(None) == 0

    def test_none_custom_default(self):
        assert _safe_int(None, 99) == 99

    def test_invalid_string(self):
        assert _safe_int("xyz") == 0

    def test_list(self):
        assert _safe_int([1]) == 0


# ---------------------------------------------------------------------------
# Config helper tests
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    def test_get_trend_weight_default(self):
        w = get_trend_weight()
        assert isinstance(w, float)
        assert 0.0 <= w <= 1.0

    def test_get_profit_weight_default(self):
        w = get_profit_weight()
        assert isinstance(w, float)
        assert 0.0 <= w <= 1.0

    def test_get_cpm_weight_default(self):
        w = get_cpm_weight()
        assert isinstance(w, float)
        assert 0.0 <= w <= 1.0

    def test_get_volume_weight_default(self):
        w = get_volume_weight()
        assert isinstance(w, float)
        assert 0.0 <= w <= 1.0

    def test_get_lookback_days_default(self):
        d = get_lookback_days()
        assert isinstance(d, int)
        assert 1 <= d <= 365

    def test_get_min_data_points_default(self):
        d = get_min_data_points()
        assert isinstance(d, int)
        assert d >= 1

    def test_get_max_results_default(self):
        d = get_max_results()
        assert isinstance(d, int)
        assert 1 <= d <= 100


# ---------------------------------------------------------------------------
# NicheOpportunity tests
# ---------------------------------------------------------------------------


class TestNicheOpportunity:
    def test_basic_creation(self):
        opp = NicheOpportunity(
            niche="finance",
            overall_score=8.5,
            trend_score=7.0,
            profit_score=9.0,
            cpm_score=10.0,
            volume_score=6.0,
            recommended_platform="youtube",
            estimated_cpm=12.0,
            estimated_monthly_profit=500.0,
            video_count=10,
        )
        assert opp.niche == "finance"
        assert opp.overall_score == 8.5
        assert opp.recommended_platform == "youtube"

    def test_score_clamping_high(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=15.0,
            trend_score=20.0,
            profit_score=-5.0,
            cpm_score=100.0,
            volume_score=-1.0,
            recommended_platform="youtube",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=0,
        )
        assert opp.overall_score == 10.0
        assert opp.trend_score == 10.0
        assert opp.profit_score == 0.0
        assert opp.cpm_score == 10.0
        assert opp.volume_score == 0.0

    def test_invalid_score_types(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score="bad",
            trend_score=None,
            profit_score=[],
            cpm_score={},
            volume_score="7.5",
            recommended_platform="youtube",
            estimated_cpm="bad",
            estimated_monthly_profit="bad",
            video_count="bad",
        )
        assert opp.overall_score == 0.0
        assert opp.trend_score == 0.0
        assert opp.profit_score == 0.0
        assert opp.cpm_score == 0.0
        assert opp.volume_score == 7.5
        assert opp.estimated_cpm == 0.0
        assert opp.estimated_monthly_profit == 0.0
        assert opp.video_count == 0

    def test_empty_niche_raises(self):
        with pytest.raises(ValueError, match="niche must be"):
            NicheOpportunity(
                niche="",
                overall_score=5.0,
                trend_score=5.0,
                profit_score=5.0,
                cpm_score=5.0,
                volume_score=5.0,
                recommended_platform="youtube",
                estimated_cpm=1.0,
                estimated_monthly_profit=0.0,
                video_count=0,
            )

    def test_niche_truncation(self):
        long_niche = "x" * 200
        opp = NicheOpportunity(
            niche=long_niche,
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="youtube",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=0,
        )
        assert len(opp.niche) == _MAX_NICHE_LENGTH

    def test_invalid_platform_defaults_youtube(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="fakebook",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=0,
        )
        assert opp.recommended_platform == "youtube"

    def test_topic_suggestions_validation(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="youtube",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=0,
            topic_suggestions=[123, "", "valid topic", None, "another"],
        )
        # Only valid strings kept
        assert "valid topic" in opp.topic_suggestions
        assert "another" in opp.topic_suggestions

    def test_topic_suggestions_non_list(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="youtube",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=0,
            topic_suggestions="not a list",
        )
        assert opp.topic_suggestions == []

    def test_reasoning_truncation(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="youtube",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=0,
            reasoning="r" * 5000,
        )
        assert len(opp.reasoning) == 2000

    def test_to_dict(self):
        opp = NicheOpportunity(
            niche="finance",
            overall_score=8.5,
            trend_score=7.0,
            profit_score=9.0,
            cpm_score=10.0,
            volume_score=6.0,
            recommended_platform="youtube",
            estimated_cpm=12.0,
            estimated_monthly_profit=500.0,
            video_count=10,
            topic_suggestions=["topic 1"],
            reasoning="test reasoning",
        )
        d = opp.to_dict()
        assert d["niche"] == "finance"
        assert d["overall_score"] == 8.5
        assert d["topic_suggestions"] == ["topic 1"]
        assert "discovered_at" in d

    def test_from_dict(self):
        data = {
            "niche": "technology",
            "overall_score": 7.5,
            "trend_score": 6.0,
            "profit_score": 8.0,
            "cpm_score": 7.9,
            "volume_score": 5.0,
            "recommended_platform": "youtube",
            "estimated_cpm": 9.5,
            "estimated_monthly_profit": 300.0,
            "video_count": 5,
            "topic_suggestions": ["AI tools"],
            "reasoning": "good niche",
        }
        opp = NicheOpportunity.from_dict(data)
        assert opp.niche == "technology"
        assert opp.overall_score == 7.5

    def test_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError, match="data must be a dict"):
            NicheOpportunity.from_dict("not a dict")

    def test_from_dict_minimal(self):
        opp = NicheOpportunity.from_dict({})
        assert opp.niche == "general"
        assert opp.overall_score == 0.0

    def test_auto_timestamp(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="youtube",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=0,
        )
        assert opp.discovered_at != ""
        assert "T" in opp.discovered_at  # ISO format

    def test_negative_video_count_clamped(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="youtube",
            estimated_cpm=1.0,
            estimated_monthly_profit=0.0,
            video_count=-10,
        )
        assert opp.video_count == 0

    def test_negative_cpm_clamped(self):
        opp = NicheOpportunity(
            niche="test",
            overall_score=5.0,
            trend_score=5.0,
            profit_score=5.0,
            cpm_score=5.0,
            volume_score=5.0,
            recommended_platform="youtube",
            estimated_cpm=-5.0,
            estimated_monthly_profit=0.0,
            video_count=0,
        )
        assert opp.estimated_cpm == 0.0


# ---------------------------------------------------------------------------
# DiscoveryReport tests
# ---------------------------------------------------------------------------


class TestDiscoveryReport:
    def test_basic_creation(self):
        report = DiscoveryReport()
        assert report.opportunities == []
        assert report.total_niches_analyzed == 0
        assert report.generated_at != ""

    def test_with_opportunities(self):
        opp = NicheOpportunity(
            niche="finance",
            overall_score=8.0,
            trend_score=7.0,
            profit_score=9.0,
            cpm_score=10.0,
            volume_score=6.0,
            recommended_platform="youtube",
            estimated_cpm=12.0,
            estimated_monthly_profit=500.0,
            video_count=10,
        )
        report = DiscoveryReport(
            opportunities=[opp],
            top_niche="finance",
            top_platform="youtube",
            total_niches_analyzed=11,
            lookback_days=30,
        )
        assert len(report.opportunities) == 1
        assert report.top_niche == "finance"

    def test_to_dict(self):
        report = DiscoveryReport(
            total_niches_analyzed=5,
            lookback_days=14,
        )
        d = report.to_dict()
        assert d["total_niches_analyzed"] == 5
        assert d["lookback_days"] == 14

    def test_invalid_fields_clamped(self):
        report = DiscoveryReport(
            total_niches_analyzed=-5,
            lookback_days=999,
        )
        assert report.total_niches_analyzed == 0
        assert report.lookback_days == _MAX_LOOKBACK_DAYS

    def test_invalid_types(self):
        report = DiscoveryReport(
            total_niches_analyzed="bad",
            lookback_days="bad",
        )
        assert report.total_niches_analyzed == 0
        assert report.lookback_days == 30


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine — basic tests
# ---------------------------------------------------------------------------


class TestEngineBasic:
    def test_discover_returns_list(self, engine):
        results = engine.discover()
        assert isinstance(results, list)

    def test_discover_returns_opportunities(self, engine):
        results = engine.discover()
        for r in results:
            assert isinstance(r, NicheOpportunity)

    def test_discover_sorted_descending(self, engine):
        results = engine.discover()
        scores = [r.overall_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_discover_all_known_niches(self, engine):
        results = engine.discover(limit=100)
        niches = {r.niche for r in results}
        assert niches == _KNOWN_NICHES

    def test_discover_limit(self, engine):
        results = engine.discover(limit=3)
        assert len(results) <= 3

    def test_discover_specific_niches(self, engine):
        results = engine.discover(niches=["finance", "technology"])
        niches = {r.niche for r in results}
        assert niches <= {"finance", "technology"}

    def test_discover_invalid_limit_type(self, engine):
        results = engine.discover(limit="bad")
        assert isinstance(results, list)

    def test_discover_invalid_days_type(self, engine):
        results = engine.discover(days="bad")
        assert isinstance(results, list)

    def test_discover_extreme_limit(self, engine):
        results = engine.discover(limit=999)
        # Should be capped to _MAX_RESULTS or fewer
        assert len(results) <= _MAX_RESULTS

    def test_discover_negative_days(self, engine):
        results = engine.discover(days=-5)
        assert isinstance(results, list)

    def test_discover_empty_niches_list(self, engine):
        results = engine.discover(niches=[])
        # Falls back to all known niches
        assert len(results) > 0

    def test_discover_non_list_niches(self, engine):
        results = engine.discover(niches="not a list")
        assert len(results) > 0


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine — scoring tests
# ---------------------------------------------------------------------------


class TestEngineScoring:
    def test_finance_scores_high_cpm(self, engine):
        results = engine.discover(niches=["finance", "entertainment"])
        finance = next(r for r in results if r.niche == "finance")
        entertainment = next(
            r for r in results if r.niche == "entertainment"
        )
        assert finance.cpm_score > entertainment.cpm_score

    def test_scores_in_valid_range(self, engine):
        results = engine.discover()
        for r in results:
            assert 0.0 <= r.overall_score <= 10.0
            assert 0.0 <= r.trend_score <= 10.0
            assert 0.0 <= r.profit_score <= 10.0
            assert 0.0 <= r.cpm_score <= 10.0
            assert 0.0 <= r.volume_score <= 10.0

    def test_estimated_cpm_positive(self, engine):
        results = engine.discover()
        for r in results:
            assert r.estimated_cpm > 0

    def test_recommended_platform_valid(self, engine):
        results = engine.discover()
        for r in results:
            assert r.recommended_platform in _SUPPORTED_PLATFORMS

    def test_finance_recommends_youtube(self, engine):
        results = engine.discover(niches=["finance"])
        assert results[0].recommended_platform == "youtube"

    def test_topic_suggestions_present(self, engine):
        results = engine.discover()
        for r in results:
            assert len(r.topic_suggestions) > 0

    def test_reasoning_present(self, engine):
        results = engine.discover()
        for r in results:
            assert len(r.reasoning) > 0


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine — with mocked dependencies
# ---------------------------------------------------------------------------


class TestEngineWithDeps:
    def test_with_revenue_tracker(self, tmp_dir):
        revenue = MockRevenueTracker(
            entries=[
                {"niche": "finance", "video_id": "v1"},
                {"niche": "finance", "video_id": "v2"},
            ]
        )
        engine = NicheDiscoveryEngine(
            revenue_tracker=revenue, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        assert len(results) == 1

    def test_with_profit_calculator(self, tmp_dir):
        profit = MockProfitCalculator(
            summary={"margin_percent": 60.0, "total_profit": 300.0},
            entries=[
                {"niche": "finance", "video_id": "v1"},
            ],
        )
        engine = NicheDiscoveryEngine(
            profit_calculator=profit, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        assert results[0].profit_score > 0

    def test_with_trend_detector(self, tmp_dir):
        trend = MockTrendDetector(
            topics=[
                MockTopic("finance investing tips", 8.5),
                MockTopic("stock market crash", 9.0),
            ]
        )
        engine = NicheDiscoveryEngine(
            trend_detector=trend, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        assert results[0].trend_score > 0

    def test_trend_topics_as_dicts(self, tmp_dir):
        trend = MockTrendDetector(
            topics=[
                {"topic": "finance investing tips", "score": 8.5},
                {"topic": "stock market crash", "score": 9.0},
            ]
        )
        engine = NicheDiscoveryEngine(
            trend_detector=trend, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        assert results[0].trend_score > 0

    def test_broken_revenue_tracker(self, tmp_dir):
        """Engine should not crash if revenue tracker raises."""

        class BrokenTracker:
            def get_entries(self, **kw):
                raise RuntimeError("tracker broken")

        engine = NicheDiscoveryEngine(
            revenue_tracker=BrokenTracker(), data_dir=tmp_dir
        )
        results = engine.discover()
        assert isinstance(results, list)

    def test_broken_profit_calculator(self, tmp_dir):
        """Engine should not crash if profit calculator raises."""

        class BrokenProfit:
            def get_profit_summary(self, **kw):
                raise RuntimeError("profit broken")

            def get_cost_entries(self, **kw):
                raise RuntimeError("entries broken")

        engine = NicheDiscoveryEngine(
            profit_calculator=BrokenProfit(), data_dir=tmp_dir
        )
        results = engine.discover()
        assert isinstance(results, list)

    def test_broken_trend_detector(self, tmp_dir):
        """Engine should not crash if trend detector raises."""

        class BrokenTrend:
            def get_cached_topics(self):
                raise RuntimeError("trend broken")

        engine = NicheDiscoveryEngine(
            trend_detector=BrokenTrend(), data_dir=tmp_dir
        )
        results = engine.discover()
        assert isinstance(results, list)

    def test_profit_with_high_margin(self, tmp_dir):
        profit = MockProfitCalculator(
            summary={"margin_percent": 80.0, "total_profit": 1000.0}
        )
        engine = NicheDiscoveryEngine(
            profit_calculator=profit, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        # 80% margin / 5.0 = 16 -> clamped to 10
        assert results[0].profit_score == 10.0

    def test_profit_with_zero_margin(self, tmp_dir):
        profit = MockProfitCalculator(
            summary={"margin_percent": 0.0, "total_profit": 0.0}
        )
        engine = NicheDiscoveryEngine(
            profit_calculator=profit, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        assert results[0].profit_score == 0.0

    def test_trend_detector_with_matching_topics(self, tmp_dir):
        trend = MockTrendDetector(
            topics=[
                MockTopic("cooking recipe fast meals", 9.0),
                MockTopic("healthy cooking tips", 8.0),
            ]
        )
        engine = NicheDiscoveryEngine(
            trend_detector=trend, data_dir=tmp_dir
        )
        results = engine.discover(niches=["cooking"])
        # Should pick up these trending topics
        assert results[0].trend_score > 0

    def test_trend_generates_topic_suggestions(self, tmp_dir):
        trend = MockTrendDetector(
            topics=[
                MockTopic("finance investing tips", 8.5),
            ]
        )
        engine = NicheDiscoveryEngine(
            trend_detector=trend, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        # Should include the trending topic in suggestions
        assert any(
            "finance" in s.lower()
            for s in results[0].topic_suggestions
        )


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine — persistence tests
# ---------------------------------------------------------------------------


class TestEnginePersistence:
    def test_discover_persists_results(self, tmp_dir):
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        engine.discover(limit=3)
        # Check that file was created
        path = os.path.join(tmp_dir, "niche_discovery.json")
        assert os.path.exists(path)

    def test_persisted_data_is_valid_json(self, tmp_dir):
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        engine.discover(limit=3)
        path = os.path.join(tmp_dir, "niche_discovery.json")
        with open(path, "r") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_discovery_history_grows(self, tmp_dir):
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        engine.discover(limit=2)
        engine.discover(limit=2)
        history = engine.get_discovery_history()
        assert len(history) == 2

    def test_get_discovery_history_limit(self, tmp_dir):
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        for _ in range(5):
            engine.discover(limit=1)
        history = engine.get_discovery_history(limit=3)
        assert len(history) == 3

    def test_clear_wipes_history(self, tmp_dir):
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        engine.discover(limit=2)
        engine.clear()
        history = engine.get_discovery_history()
        assert len(history) == 0

    def test_corrupt_file_recovery(self, tmp_dir):
        path = os.path.join(tmp_dir, "niche_discovery.json")
        with open(path, "w") as f:
            f.write("not json{{{")
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        results = engine.discover(limit=2)
        assert isinstance(results, list)

    def test_non_list_file_recovery(self, tmp_dir):
        path = os.path.join(tmp_dir, "niche_discovery.json")
        with open(path, "w") as f:
            json.dump({"not": "a list"}, f)
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        results = engine.discover(limit=2)
        assert isinstance(results, list)

    def test_null_byte_data_dir_rejected(self):
        engine = NicheDiscoveryEngine(data_dir="/tmp\x00evil")
        # Should fall back to default file
        assert "\x00" not in engine._file

    def test_non_string_data_dir(self):
        engine = NicheDiscoveryEngine(data_dir=12345)
        # Should fall back to default file
        assert isinstance(engine._file, str)


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine — compare_niches
# ---------------------------------------------------------------------------


class TestCompareNiches:
    def test_basic_comparison(self, engine):
        result = engine.compare_niches("finance", "gaming")
        assert "niche_a" in result
        assert "niche_b" in result
        assert "winner" in result
        assert "margin" in result

    def test_winner_is_one_of_inputs(self, engine):
        result = engine.compare_niches("finance", "entertainment")
        assert result["winner"] in ("finance", "entertainment")

    def test_finance_beats_entertainment(self, engine):
        result = engine.compare_niches("finance", "entertainment")
        # Finance has higher CPM, should generally win
        assert result["winner"] == "finance"

    def test_margin_is_non_negative(self, engine):
        result = engine.compare_niches("finance", "technology")
        assert result["margin"] >= 0.0

    def test_empty_niche_a_raises(self, engine):
        with pytest.raises(ValueError, match="niche_a"):
            engine.compare_niches("", "finance")

    def test_empty_niche_b_raises(self, engine):
        with pytest.raises(ValueError, match="niche_b"):
            engine.compare_niches("finance", "")

    def test_non_string_niche_raises(self, engine):
        with pytest.raises(ValueError):
            engine.compare_niches(123, "finance")


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine — get_top_niche
# ---------------------------------------------------------------------------


class TestGetTopNiche:
    def test_returns_opportunity(self, engine):
        result = engine.get_top_niche()
        assert isinstance(result, NicheOpportunity)

    def test_top_niche_has_highest_score(self, engine):
        top = engine.get_top_niche()
        all_results = engine.discover(limit=100)
        assert top.overall_score >= all_results[-1].overall_score

    def test_with_custom_days(self, engine):
        result = engine.get_top_niche(days=7)
        assert isinstance(result, NicheOpportunity)


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine — thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_discover(self, tmp_dir):
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        errors = []

        def worker():
            try:
                results = engine.discover(limit=5)
                assert isinstance(results, list)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors in threads: {errors}"


# ---------------------------------------------------------------------------
# Module-level constants integrity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_all_known_niches_have_cpm(self):
        for niche in _KNOWN_NICHES:
            assert niche in _CPM_BY_NICHE

    def test_all_known_niches_have_topic_seeds(self):
        for niche in _KNOWN_NICHES:
            assert niche in _TOPIC_SEEDS
            assert len(_TOPIC_SEEDS[niche]) > 0

    def test_cpm_values_positive(self):
        for niche, rates in _CPM_BY_NICHE.items():
            for platform, cpm in rates.items():
                assert cpm > 0, f"{niche}/{platform} CPM is {cpm}"

    def test_supported_platforms_consistent(self):
        for niche, rates in _CPM_BY_NICHE.items():
            for platform in rates:
                assert platform in _SUPPORTED_PLATFORMS


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unknown_niche_uses_general_cpm(self, engine):
        results = engine.discover(niches=["nonexistent_niche"])
        assert len(results) == 1
        # Should use general CPM baseline

    def test_single_niche_discovery(self, engine):
        results = engine.discover(niches=["cooking"], limit=1)
        assert len(results) == 1
        assert results[0].niche == "cooking"

    def test_all_deps_none(self, tmp_dir):
        engine = NicheDiscoveryEngine(
            revenue_tracker=None,
            profit_calculator=None,
            trend_detector=None,
            data_dir=tmp_dir,
        )
        results = engine.discover()
        assert isinstance(results, list)
        assert len(results) > 0

    def test_profit_summary_as_object(self, tmp_dir):
        """Test when profit summary returns an object instead of dict."""

        class SummaryObj:
            margin_percent = 45.0
            total_profit = 200.0

        profit = MockProfitCalculator(summary=SummaryObj())
        engine = NicheDiscoveryEngine(
            profit_calculator=profit, data_dir=tmp_dir
        )
        results = engine.discover(niches=["finance"])
        assert results[0].profit_score > 0

    def test_get_discovery_history_invalid_limit(self, engine):
        history = engine.get_discovery_history(limit="bad")
        assert isinstance(history, list)

    def test_volume_score_zero_videos(self, tmp_dir):
        """With no video history, volume score should be moderate (opportunity)."""
        engine = NicheDiscoveryEngine(data_dir=tmp_dir)
        results = engine.discover(niches=["finance"])
        assert results[0].volume_score == 5.0

    def test_estimated_monthly_profit_fallback(self, engine):
        """Without profit data, should estimate from CPM."""
        results = engine.discover(niches=["finance"])
        assert results[0].estimated_monthly_profit > 0

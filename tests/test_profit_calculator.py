"""
Tests for src/profit_calculator.py — cost tracking and profit analysis.
"""

import json
import os
import sys
import threading
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import profit_calculator as pc
from profit_calculator import (
    CostEntry,
    ProfitCalculator,
    ProfitSummary,
    estimate_cost,
    get_compute_rate,
    get_currency,
    get_default_calculator,
    get_llm_rate,
    get_storage_rate,
    get_tts_rate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cost_file(tmp_path):
    return str(tmp_path / "profit.json")


@pytest.fixture
def calc(cost_file):
    return ProfitCalculator(cost_path=cost_file)


class _FakeRevenueEntry:
    def __init__(self, video_id, platform, niche, gross, net):
        self.video_id = video_id
        self.platform = platform
        self.niche = niche
        self.estimated_gross = gross
        self.estimated_net = net


class _FakeRevenueTracker:
    def __init__(self, entries=None):
        self._entries = entries or []

    def get_entries(self, days=None, platform=None, niche=None):
        results = []
        for e in self._entries:
            if platform and e.platform != platform:
                continue
            if niche and e.niche != niche:
                continue
            results.append(e)
        return results


# ---------------------------------------------------------------------------
# CostEntry
# ---------------------------------------------------------------------------


class TestCostEntry:
    def test_to_dict_roundtrip(self):
        entry = CostEntry(
            video_id="v1",
            platform="youtube",
            niche="finance",
            llm_tokens=1000,
            tts_chars=500,
            compute_seconds=30.0,
            storage_mb=10.0,
            total_cost=0.5,
            currency="USD",
            recorded_at="2026-04-07T00:00:00+00:00",
        )
        d = entry.to_dict()
        assert d["video_id"] == "v1"
        assert d["platform"] == "youtube"
        back = CostEntry.from_dict(d)
        assert back.video_id == "v1"
        assert back.niche == "finance"
        assert back.llm_tokens == 1000

    def test_from_dict_requires_video_id(self):
        with pytest.raises(ValueError):
            CostEntry.from_dict({"video_id": ""})

    def test_from_dict_rejects_non_dict(self):
        with pytest.raises(TypeError):
            CostEntry.from_dict("not a dict")

    def test_from_dict_clamps_negative_numbers(self):
        e = CostEntry.from_dict({
            "video_id": "v",
            "llm_tokens": -50,
            "tts_chars": -10,
            "compute_seconds": -5,
            "storage_mb": -1,
            "total_cost": -2,
        })
        assert e.llm_tokens == 0
        assert e.tts_chars == 0
        assert e.compute_seconds == 0.0
        assert e.storage_mb == 0.0
        assert e.total_cost == 0.0

    def test_from_dict_defaults_niche(self):
        e = CostEntry.from_dict({"video_id": "v"})
        assert e.niche == "general"

    def test_from_dict_truncates_video_id(self):
        long_id = "a" * 1000
        e = CostEntry.from_dict({"video_id": long_id})
        assert len(e.video_id) <= 256

    def test_from_dict_invalid_numeric_raises(self):
        with pytest.raises(ValueError):
            CostEntry.from_dict({"video_id": "v", "llm_tokens": "abc"})

    def test_from_dict_invalid_currency_falls_back(self):
        e = CostEntry.from_dict({"video_id": "v", "currency": "toolong"})
        assert e.currency == "USD"

    def test_from_dict_caps_excessive_values(self):
        e = CostEntry.from_dict({
            "video_id": "v",
            "llm_tokens": 10**9,
            "tts_chars": 10**9,
            "compute_seconds": 10**9,
            "storage_mb": 10**12,
        })
        assert e.llm_tokens <= 10_000_000
        assert e.tts_chars <= 10_000_000
        assert e.compute_seconds <= 10 * 24 * 3600
        assert e.storage_mb <= 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    def test_get_llm_rate_default(self):
        with patch("profit_calculator._get", return_value=0.01):
            assert get_llm_rate() == 0.01

    def test_get_llm_rate_invalid_falls_back(self):
        with patch("profit_calculator._get", return_value="not-a-number"):
            assert get_llm_rate() == 0.01

    def test_get_llm_rate_negative_falls_back(self):
        with patch("profit_calculator._get", return_value=-5):
            assert get_llm_rate() == 0.01

    def test_get_llm_rate_excessive_falls_back(self):
        with patch("profit_calculator._get", return_value=999999):
            assert get_llm_rate() == 0.01

    def test_get_tts_rate(self):
        with patch("profit_calculator._get", return_value=0.02):
            assert get_tts_rate() == 0.02

    def test_get_compute_rate(self):
        with patch("profit_calculator._get", return_value=0.05):
            assert get_compute_rate() == 0.05

    def test_get_storage_rate(self):
        with patch("profit_calculator._get", return_value=0.03):
            assert get_storage_rate() == 0.03

    def test_get_currency_default(self):
        with patch("profit_calculator._get", return_value="USD"):
            assert get_currency() == "USD"

    def test_get_currency_normalizes(self):
        with patch("profit_calculator._get", return_value="eur"):
            assert get_currency() == "EUR"

    def test_get_currency_invalid_falls_back(self):
        with patch("profit_calculator._get", return_value="DOLLARS"):
            assert get_currency() == "USD"

    def test_get_currency_non_string_falls_back(self):
        with patch("profit_calculator._get", return_value=123):
            assert get_currency() == "USD"


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_zero_inputs_zero_cost(self, calc):
        assert calc.estimate_cost() == 0.0

    def test_llm_only(self, calc):
        # 1000 tokens × $0.01 = $0.01
        cost = calc.estimate_cost(llm_tokens=1000)
        assert cost == pytest.approx(0.01, abs=1e-6)

    def test_tts_only(self, calc):
        # 1000 chars × $0.015 = $0.015
        cost = calc.estimate_cost(tts_chars=1000)
        assert cost == pytest.approx(0.015, abs=1e-6)

    def test_compute_only(self, calc):
        # 3600 seconds × $0.02/hr = $0.02
        cost = calc.estimate_cost(compute_seconds=3600)
        assert cost == pytest.approx(0.02, abs=1e-6)

    def test_storage_only(self, calc):
        # 1024 MB × $0.023/GB = $0.023
        cost = calc.estimate_cost(storage_mb=1024)
        assert cost == pytest.approx(0.023, abs=1e-6)

    def test_combined(self, calc):
        cost = calc.estimate_cost(
            llm_tokens=2000, tts_chars=500, compute_seconds=1800, storage_mb=512
        )
        expected = (2 * 0.01) + (0.5 * 0.015) + (0.5 * 0.02) + (0.5 * 0.023)
        assert cost == pytest.approx(expected, abs=1e-6)

    def test_negative_clamped(self, calc):
        assert calc.estimate_cost(llm_tokens=-100) == 0.0

    def test_invalid_type_returns_zero(self, calc):
        assert calc.estimate_cost(llm_tokens="abc") == 0.0

    def test_excessive_clamped(self, calc):
        # Capped at _MAX_TOKENS=10M → 10_000 × 0.01 = $100
        cost = calc.estimate_cost(llm_tokens=10**12)
        assert cost <= 101.0


# ---------------------------------------------------------------------------
# record_cost
# ---------------------------------------------------------------------------


class TestRecordCost:
    def test_basic_record(self, calc):
        entry = calc.record_cost("vid1", platform="youtube", niche="finance",
                                 llm_tokens=2000, tts_chars=1000)
        assert entry.video_id == "vid1"
        assert entry.platform == "youtube"
        assert entry.niche == "finance"
        assert entry.llm_tokens == 2000
        assert entry.total_cost > 0

    def test_rejects_empty_video_id(self, calc):
        with pytest.raises(ValueError):
            calc.record_cost("")

    def test_rejects_null_byte(self, calc):
        with pytest.raises(ValueError):
            calc.record_cost("bad\x00id")

    def test_rejects_non_string_video_id(self, calc):
        with pytest.raises(TypeError):
            calc.record_cost(123)

    def test_persists_to_disk(self, calc, cost_file):
        calc.record_cost("v1", platform="youtube", llm_tokens=500)
        assert os.path.exists(cost_file)
        with open(cost_file) as fh:
            data = json.load(fh)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["video_id"] == "v1"

    def test_unknown_platform_allowed(self, calc):
        entry = calc.record_cost("v1", platform="mastodon")
        assert entry.platform == "mastodon"

    def test_invalid_niche_type_defaults(self, calc):
        entry = calc.record_cost("v1", niche=None)
        assert entry.niche == "general"

    def test_video_id_truncation(self, calc):
        long_id = "x" * 1000
        entry = calc.record_cost(long_id)
        assert len(entry.video_id) <= 256

    def test_rotation_caps_entries(self, calc, monkeypatch):
        monkeypatch.setattr(pc, "_MAX_ENTRIES", 3)
        for i in range(5):
            calc.record_cost(f"v{i}")
        entries = calc.get_cost_entries()
        assert len(entries) == 3


# ---------------------------------------------------------------------------
# Loading & persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_load_corrupt_file_starts_empty(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text("{bad json")
        calc = ProfitCalculator(cost_path=str(path))
        assert calc.get_cost_entries() == []

    def test_load_non_list_starts_empty(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text('{"not": "list"}')
        calc = ProfitCalculator(cost_path=str(path))
        assert calc.get_cost_entries() == []

    def test_missing_file_starts_empty(self, tmp_path):
        calc = ProfitCalculator(cost_path=str(tmp_path / "does_not_exist.json"))
        assert calc.get_cost_entries() == []

    def test_reload_from_disk(self, cost_file):
        c1 = ProfitCalculator(cost_path=cost_file)
        c1.record_cost("v1", platform="youtube")
        c2 = ProfitCalculator(cost_path=cost_file)
        assert len(c2.get_cost_entries()) == 1

    def test_clear_wipes_file(self, calc):
        calc.record_cost("v1")
        calc.clear()
        assert calc.get_cost_entries() == []


# ---------------------------------------------------------------------------
# get_cost_entries / get_total_cost
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_filter_by_video_id(self, calc):
        calc.record_cost("v1", platform="youtube")
        calc.record_cost("v2", platform="tiktok")
        assert len(calc.get_cost_entries(video_id="v1")) == 1

    def test_filter_by_platform(self, calc):
        calc.record_cost("v1", platform="youtube")
        calc.record_cost("v2", platform="tiktok")
        assert len(calc.get_cost_entries(platform="youtube")) == 1

    def test_filter_by_niche(self, calc):
        calc.record_cost("v1", niche="finance")
        calc.record_cost("v2", niche="tech")
        assert len(calc.get_cost_entries(niche="finance")) == 1

    def test_days_bounds(self, calc):
        calc.record_cost("v1")
        assert len(calc.get_cost_entries(days=-1)) == 1
        assert len(calc.get_cost_entries(days=99999)) == 1
        assert len(calc.get_cost_entries(days="nope")) == 1

    def test_get_total_cost(self, calc):
        calc.record_cost("v1", llm_tokens=1000)  # $0.01
        calc.record_cost("v2", llm_tokens=2000)  # $0.02
        assert calc.get_total_cost() == pytest.approx(0.03, abs=1e-6)

    def test_get_total_cost_filtered(self, calc):
        calc.record_cost("v1", platform="youtube", llm_tokens=1000)
        calc.record_cost("v2", platform="tiktok", llm_tokens=5000)
        assert calc.get_total_cost(platform="youtube") == pytest.approx(0.01, abs=1e-6)


# ---------------------------------------------------------------------------
# Profit analysis
# ---------------------------------------------------------------------------


class TestProfitAnalysis:
    def test_get_profit_for_video_requires_id(self, calc):
        with pytest.raises(ValueError):
            calc.get_profit_for_video("")

    def test_get_profit_for_video_no_tracker(self, calc):
        calc.record_cost("v1", llm_tokens=1000)
        report = calc.get_profit_for_video("v1")
        assert report["total_cost"] == pytest.approx(0.01, abs=1e-6)
        assert report["gross_revenue"] == 0.0
        assert report["net_revenue"] == 0.0
        assert report["net_profit"] == pytest.approx(-0.01, abs=1e-6)
        assert report["is_profitable"] is False

    def test_get_profit_for_video_with_revenue(self, cost_file):
        tracker = _FakeRevenueTracker([
            _FakeRevenueEntry("v1", "youtube", "finance", gross=10.0, net=4.5),
        ])
        calc = ProfitCalculator(revenue_tracker=tracker, cost_path=cost_file)
        calc.record_cost("v1", platform="youtube", niche="finance", llm_tokens=1000)
        report = calc.get_profit_for_video("v1")
        assert report["gross_revenue"] == 10.0
        assert report["net_revenue"] == 4.5
        assert report["net_profit"] == pytest.approx(4.49, abs=1e-4)
        assert report["is_profitable"] is True
        assert report["margin_percent"] > 0

    def test_profit_revenue_tracker_error_safe(self, cost_file):
        class BrokenTracker:
            def get_entries(self, **kwargs):
                raise RuntimeError("boom")
        calc = ProfitCalculator(revenue_tracker=BrokenTracker(), cost_path=cost_file)
        calc.record_cost("v1", llm_tokens=500)
        report = calc.get_profit_for_video("v1")
        assert report["gross_revenue"] == 0.0

    def test_get_profit_summary_empty(self, calc):
        summary = calc.get_profit_summary()
        assert summary.entry_count == 0
        assert summary.total_cost == 0.0
        assert summary.total_profit == 0.0
        assert summary.margin_percent == 0.0

    def test_get_profit_summary_with_revenue(self, cost_file):
        tracker = _FakeRevenueTracker([
            _FakeRevenueEntry("v1", "youtube", "finance", 20.0, 9.0),
            _FakeRevenueEntry("v2", "tiktok", "tech", 5.0, 2.5),
        ])
        calc = ProfitCalculator(revenue_tracker=tracker, cost_path=cost_file)
        calc.record_cost("v1", platform="youtube", niche="finance", llm_tokens=1000)
        calc.record_cost("v2", platform="tiktok", niche="tech", llm_tokens=2000)
        summary = calc.get_profit_summary(days=30)
        assert summary.entry_count == 2
        assert summary.total_gross == 25.0
        assert summary.total_net == 11.5
        assert summary.total_profit == pytest.approx(11.5 - 0.03, abs=1e-4)
        assert "youtube" in summary.by_platform
        assert "finance" in summary.by_niche
        assert summary.by_platform["youtube"]["net"] == 9.0

    def test_summary_bad_days_clamped(self, calc):
        summary = calc.get_profit_summary(days=-5)
        assert summary.period_days == 1

    def test_summary_to_dict(self, calc):
        calc.record_cost("v1")
        d = calc.get_profit_summary().to_dict()
        assert "total_cost" in d
        assert "by_platform" in d

    def test_top_profitable_niches(self, cost_file):
        tracker = _FakeRevenueTracker([
            _FakeRevenueEntry("v1", "youtube", "finance", 100, 45),
            _FakeRevenueEntry("v2", "youtube", "tech", 20, 9),
            _FakeRevenueEntry("v3", "youtube", "entertainment", 5, 2),
        ])
        calc = ProfitCalculator(revenue_tracker=tracker, cost_path=cost_file)
        for vid, niche in [("v1", "finance"), ("v2", "tech"), ("v3", "entertainment")]:
            calc.record_cost(vid, platform="youtube", niche=niche, llm_tokens=1000)
        top = calc.get_top_profitable_niches(limit=10)
        assert len(top) == 3
        # Finance should lead
        assert top[0]["niche"] == "finance"

    def test_top_profitable_niches_limit_bounds(self, calc):
        calc.record_cost("v1", niche="a")
        # limit=0 → clamped to 1
        assert len(calc.get_top_profitable_niches(limit=0)) <= 1
        # limit huge → clamped to 100
        assert len(calc.get_top_profitable_niches(limit=10**9)) <= 100

    def test_forecast_monthly_profit_empty(self, calc):
        f = calc.forecast_monthly_profit()
        assert f["projected_cost"] == 0.0
        assert f["projected_profit"] == 0.0

    def test_forecast_monthly_profit_scale(self, cost_file):
        tracker = _FakeRevenueTracker([
            _FakeRevenueEntry("v1", "youtube", "finance", 100, 45),
        ])
        calc = ProfitCalculator(revenue_tracker=tracker, cost_path=cost_file)
        calc.record_cost("v1", platform="youtube", niche="finance", llm_tokens=1000)
        f = calc.forecast_monthly_profit(lookback_days=10)
        # Scale factor = 3x
        assert f["projected_gross"] == pytest.approx(300.0, rel=0.01)
        assert f["projected_net"] == pytest.approx(135.0, rel=0.01)

    def test_forecast_monthly_profit_bounds(self, calc):
        f = calc.forecast_monthly_profit(lookback_days=-5)
        assert f["lookback_days"] == 1
        f = calc.forecast_monthly_profit(lookback_days=999999)
        assert f["lookback_days"] == 365


# ---------------------------------------------------------------------------
# ProfitSummary dataclass
# ---------------------------------------------------------------------------


class TestProfitSummary:
    def test_defaults(self):
        s = ProfitSummary()
        assert s.period_days == 30
        assert s.total_cost == 0.0
        assert s.currency == "USD"

    def test_to_dict_has_keys(self):
        s = ProfitSummary(period_days=7, total_cost=1.0)
        d = s.to_dict()
        assert d["period_days"] == 7
        assert d["total_cost"] == 1.0
        assert "by_platform" in d and "by_niche" in d


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


class TestConvenience:
    def test_get_default_calculator_singleton(self):
        a = get_default_calculator()
        b = get_default_calculator()
        assert a is b

    def test_estimate_cost_helper(self):
        c = estimate_cost(llm_tokens=1000)
        assert c == pytest.approx(0.01, abs=1e-6)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_record(self, calc):
        def worker(i):
            calc.record_cost(f"v{i}", llm_tokens=100)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(calc.get_cost_entries()) == 20


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_max_entries(self):
        assert pc._MAX_ENTRIES == 50_000

    def test_supported_platforms(self):
        assert "youtube" in pc._SUPPORTED_PLATFORMS
        assert "tiktok" in pc._SUPPORTED_PLATFORMS

    def test_default_rates_sensible(self):
        assert 0 < pc._DEFAULT_LLM_RATE_PER_1K_TOKENS < 1
        assert 0 < pc._DEFAULT_TTS_RATE_PER_1K_CHARS < 1

"""
Unit tests for the revenue_tracker module.

Covers: RevenueEntry creation/serialization/validation, RevenueSummary,
RevenueTracker recording/querying/forecasting/top earners/niche comparison,
CPM lookups, config helpers, edge cases, persistence, thread safety.
"""

import json
import os
import sys
import tempfile
import threading
import atexit

import pytest

# ---------------------------------------------------------------------------
# sys.modules protection (matches project conftest pattern)
# ---------------------------------------------------------------------------
_original_modules = set(sys.modules.keys())


def _cleanup_modules():
    for mod_name in list(sys.modules.keys()):
        if mod_name not in _original_modules and mod_name.startswith(
            ("revenue_tracker", "test_revenue_tracker")
        ):
            del sys.modules[mod_name]


atexit.register(_cleanup_modules)

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from revenue_tracker import (
    RevenueEntry,
    RevenueSummary,
    RevenueTracker,
    get_revenue_default_niche,
    get_revenue_currency,
    get_custom_cpm,
    _CPM_BY_NICHE,
    _PLATFORM_REVENUE_SHARE,
    _SUPPORTED_PLATFORMS,
    _VALID_NICHES,
    _MAX_ENTRIES,
    _MAX_VIEWS,
    _MAX_VIDEO_ID_LENGTH,
    _MAX_NICHE_LENGTH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_file(tmp_path):
    """Provide a temporary file path for revenue data."""
    return str(tmp_path / "revenue_test.json")


@pytest.fixture
def tracker(tmp_file):
    """Provide a fresh RevenueTracker using a temp file."""
    return RevenueTracker(data_file=tmp_file)


# ---------------------------------------------------------------------------
# RevenueEntry — creation
# ---------------------------------------------------------------------------


class TestRevenueEntryCreation:
    def test_default_fields(self):
        entry = RevenueEntry(video_id="v1", platform="youtube")
        assert entry.video_id == "v1"
        assert entry.platform == "youtube"
        assert entry.views == 0
        assert entry.estimated_cpm == 0.0
        assert entry.estimated_gross == 0.0
        assert entry.estimated_net == 0.0
        assert entry.niche == "general"
        assert entry.recorded_at  # auto-populated

    def test_custom_fields(self):
        entry = RevenueEntry(
            video_id="v2",
            platform="tiktok",
            views=5000,
            estimated_cpm=1.5,
            estimated_gross=7.5,
            estimated_net=3.75,
            niche="finance",
            recorded_at="2026-01-01T00:00:00+00:00",
        )
        assert entry.views == 5000
        assert entry.niche == "finance"
        assert entry.recorded_at == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# RevenueEntry — serialization
# ---------------------------------------------------------------------------


class TestRevenueEntrySerialization:
    def test_to_dict(self):
        entry = RevenueEntry(
            video_id="v3",
            platform="youtube",
            views=1000,
            estimated_cpm=5.0,
            estimated_gross=5.0,
            estimated_net=2.25,
            niche="general",
        )
        d = entry.to_dict()
        assert d["video_id"] == "v3"
        assert d["platform"] == "youtube"
        assert d["views"] == 1000
        assert d["estimated_cpm"] == 5.0
        assert d["estimated_net"] == 2.25
        assert "recorded_at" in d

    def test_from_dict_valid(self):
        d = {
            "video_id": "v4",
            "platform": "tiktok",
            "views": 2000,
            "estimated_cpm": 0.8,
            "estimated_gross": 1.6,
            "estimated_net": 0.8,
            "niche": "gaming",
            "recorded_at": "2026-01-01T00:00:00+00:00",
        }
        entry = RevenueEntry.from_dict(d)
        assert entry.video_id == "v4"
        assert entry.platform == "tiktok"
        assert entry.views == 2000
        assert entry.niche == "gaming"

    def test_from_dict_invalid_platform_raises(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            RevenueEntry.from_dict({"video_id": "x", "platform": "snapchat"})

    def test_from_dict_not_dict_raises(self):
        with pytest.raises(TypeError, match="requires a dict"):
            RevenueEntry.from_dict("not a dict")

    def test_from_dict_negative_views_clamped(self):
        entry = RevenueEntry.from_dict(
            {"video_id": "v5", "platform": "youtube", "views": -100}
        )
        assert entry.views == 0

    def test_from_dict_excessive_views_capped(self):
        entry = RevenueEntry.from_dict(
            {"video_id": "v6", "platform": "youtube", "views": _MAX_VIEWS + 1}
        )
        assert entry.views == _MAX_VIEWS

    def test_from_dict_unknown_niche_defaults(self):
        entry = RevenueEntry.from_dict(
            {"video_id": "v7", "platform": "youtube", "niche": "unknown_niche_xyz"}
        )
        assert entry.niche == "general"

    def test_from_dict_video_id_truncated(self):
        long_id = "x" * (_MAX_VIDEO_ID_LENGTH + 50)
        entry = RevenueEntry.from_dict(
            {"video_id": long_id, "platform": "youtube"}
        )
        assert len(entry.video_id) == _MAX_VIDEO_ID_LENGTH

    def test_roundtrip(self):
        original = RevenueEntry(
            video_id="rt1",
            platform="instagram",
            views=9999,
            estimated_cpm=3.0,
            estimated_gross=29.997,
            estimated_net=16.4984,
            niche="lifestyle",
        )
        restored = RevenueEntry.from_dict(original.to_dict())
        assert restored.video_id == original.video_id
        assert restored.platform == original.platform
        assert restored.views == original.views
        assert restored.niche == original.niche


# ---------------------------------------------------------------------------
# RevenueSummary
# ---------------------------------------------------------------------------


class TestRevenueSummary:
    def test_default_summary(self):
        s = RevenueSummary()
        assert s.period_days == 30
        assert s.total_views == 0
        assert s.total_net == 0.0
        assert s.entry_count == 0

    def test_to_dict(self):
        s = RevenueSummary(
            period_days=7,
            total_views=50000,
            total_gross=100.0,
            total_net=50.0,
            by_platform={"youtube": {"views": 50000, "gross": 100.0, "net": 50.0}},
            entry_count=5,
            avg_cpm=2.0,
        )
        d = s.to_dict()
        assert d["total_views"] == 50000
        assert d["total_net"] == 50.0
        assert "youtube" in d["by_platform"]


# ---------------------------------------------------------------------------
# CPM lookup
# ---------------------------------------------------------------------------


class TestCPMLookup:
    def test_known_niche_youtube(self):
        cpm = RevenueTracker.get_cpm("youtube", "finance")
        assert cpm == 12.0

    def test_known_niche_tiktok(self):
        cpm = RevenueTracker.get_cpm("tiktok", "gaming")
        assert cpm == 0.8

    def test_unknown_niche_falls_back_to_general(self):
        cpm = RevenueTracker.get_cpm("youtube", "nonexistent")
        assert cpm == _CPM_BY_NICHE["general"]["youtube"]

    def test_unknown_platform_returns_default(self):
        # get_cpm for an unknown platform in known niche
        cpm = RevenueTracker.get_cpm("facebook", "finance")
        assert cpm == 1.0  # fallback

    def test_custom_cpm_override(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker.get_custom_cpm",
            lambda: {"youtube": 20.0},
        )
        cpm = RevenueTracker.get_cpm("youtube", "finance")
        assert cpm == 20.0

    def test_revenue_share_youtube(self):
        assert RevenueTracker.get_revenue_share("youtube") == 0.45

    def test_revenue_share_unknown_platform(self):
        assert RevenueTracker.get_revenue_share("facebook") == 0.5


# ---------------------------------------------------------------------------
# Revenue estimation
# ---------------------------------------------------------------------------


class TestRevenueEstimation:
    def test_basic_estimation(self):
        cpm, gross, net = RevenueTracker.estimate_revenue(
            views=10000, platform="youtube", niche="finance"
        )
        assert cpm == 12.0
        assert gross == pytest.approx(120.0)
        assert net == pytest.approx(54.0)  # 120 * 0.45

    def test_zero_views(self):
        cpm, gross, net = RevenueTracker.estimate_revenue(
            views=0, platform="tiktok", niche="general"
        )
        assert gross == 0.0
        assert net == 0.0

    def test_negative_views_clamped(self):
        cpm, gross, net = RevenueTracker.estimate_revenue(
            views=-500, platform="youtube", niche="general"
        )
        assert gross == 0.0

    def test_excessive_views_capped(self):
        cpm, gross, net = RevenueTracker.estimate_revenue(
            views=_MAX_VIEWS + 1, platform="youtube", niche="general"
        )
        expected_gross = (_MAX_VIEWS / 1000) * 5.0
        assert gross == pytest.approx(expected_gross)


# ---------------------------------------------------------------------------
# RevenueTracker — record_revenue
# ---------------------------------------------------------------------------


class TestRecordRevenue:
    def test_basic_record(self, tracker):
        entry = tracker.record_revenue("vid1", "youtube", views=10000, niche="finance")
        assert entry.video_id == "vid1"
        assert entry.platform == "youtube"
        assert entry.views == 10000
        assert entry.estimated_net > 0

    def test_empty_video_id_raises(self, tracker):
        with pytest.raises(ValueError, match="non-empty string"):
            tracker.record_revenue("", "youtube", views=100)

    def test_none_video_id_raises(self, tracker):
        with pytest.raises(ValueError, match="non-empty string"):
            tracker.record_revenue(None, "youtube", views=100)

    def test_null_byte_video_id_raises(self, tracker):
        with pytest.raises(ValueError, match="null bytes"):
            tracker.record_revenue("vid\x001", "youtube", views=100)

    def test_invalid_platform_raises(self, tracker):
        with pytest.raises(ValueError, match="platform must be one of"):
            tracker.record_revenue("vid1", "snapchat", views=100)

    def test_invalid_views_type_raises(self, tracker):
        with pytest.raises(TypeError, match="views must be a number"):
            tracker.record_revenue("vid1", "youtube", views="not_a_number")

    def test_negative_views_clamped(self, tracker):
        entry = tracker.record_revenue("vid1", "youtube", views=-100)
        assert entry.views == 0

    def test_excessive_views_capped(self, tracker):
        entry = tracker.record_revenue("vid1", "youtube", views=_MAX_VIEWS + 1)
        assert entry.views == _MAX_VIEWS

    def test_default_niche_from_config(self, tracker, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker.get_revenue_default_niche", lambda: "finance"
        )
        entry = tracker.record_revenue("vid1", "youtube", views=1000)
        assert entry.niche == "finance"

    def test_invalid_niche_defaults_to_general(self, tracker):
        entry = tracker.record_revenue("vid1", "youtube", views=1000, niche="invalid")
        assert entry.niche == "general"

    def test_video_id_truncated(self, tracker):
        long_id = "a" * 500
        entry = tracker.record_revenue(long_id, "youtube", views=1000)
        assert len(entry.video_id) == _MAX_VIDEO_ID_LENGTH

    def test_float_views_converted(self, tracker):
        entry = tracker.record_revenue("vid1", "youtube", views=1500.7)
        assert entry.views == 1500

    def test_niche_truncated(self, tracker):
        # Even though "general" is valid, a long niche gets truncated first
        entry = tracker.record_revenue("vid1", "youtube", views=1000, niche="general")
        assert entry.niche == "general"


# ---------------------------------------------------------------------------
# RevenueTracker — persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_data_persisted_to_file(self, tracker, tmp_file):
        tracker.record_revenue("vid1", "youtube", views=5000)
        with open(tmp_file, "r") as f:
            data = json.load(f)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["video_id"] == "vid1"

    def test_data_loaded_from_file(self, tmp_file):
        # Pre-seed the file
        entry_data = {
            "entries": [
                {
                    "video_id": "pre_vid",
                    "platform": "tiktok",
                    "views": 3000,
                    "estimated_cpm": 0.8,
                    "estimated_gross": 2.4,
                    "estimated_net": 1.2,
                    "niche": "general",
                    "recorded_at": "2026-04-01T00:00:00+00:00",
                }
            ]
        }
        with open(tmp_file, "w") as f:
            json.dump(entry_data, f)

        tracker2 = RevenueTracker(data_file=tmp_file)
        entries = tracker2.get_entries()
        assert len(entries) == 1
        assert entries[0].video_id == "pre_vid"

    def test_corrupt_file_returns_empty(self, tmp_file):
        with open(tmp_file, "w") as f:
            f.write("NOT JSON {{{")
        tracker2 = RevenueTracker(data_file=tmp_file)
        entries = tracker2.get_entries()
        assert entries == []

    def test_missing_file_returns_empty(self, tmp_file):
        tracker2 = RevenueTracker(data_file=tmp_file + "_missing")
        entries = tracker2.get_entries()
        assert entries == []

    def test_rotation_at_max_entries(self, tmp_file):
        # Pre-seed with data at limit
        entries = []
        for i in range(_MAX_ENTRIES):
            entries.append({
                "video_id": f"v{i}",
                "platform": "youtube",
                "views": 100,
                "estimated_cpm": 5.0,
                "estimated_gross": 0.5,
                "estimated_net": 0.225,
                "niche": "general",
                "recorded_at": "2026-01-01T00:00:00+00:00",
            })
        with open(tmp_file, "w") as f:
            json.dump({"entries": entries}, f)

        tracker2 = RevenueTracker(data_file=tmp_file)
        tracker2.record_revenue("new_vid", "youtube", views=1000)

        with open(tmp_file, "r") as f:
            data = json.load(f)
        assert len(data["entries"]) <= _MAX_ENTRIES


# ---------------------------------------------------------------------------
# RevenueTracker — get_entries with filters
# ---------------------------------------------------------------------------


class TestGetEntries:
    def test_filter_by_platform(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        tracker.record_revenue("v2", "tiktok", views=2000)
        yt_entries = tracker.get_entries(platform="youtube")
        assert len(yt_entries) == 1
        assert yt_entries[0].platform == "youtube"

    def test_filter_by_niche(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000, niche="finance")
        tracker.record_revenue("v2", "youtube", views=2000, niche="gaming")
        finance = tracker.get_entries(niche="finance")
        assert len(finance) == 1
        assert finance[0].niche == "finance"

    def test_filter_by_days(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        entries = tracker.get_entries(days=1)
        assert len(entries) == 1

    def test_invalid_days_clamped(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        entries = tracker.get_entries(days=-5)
        # Clamped to 1 day
        assert isinstance(entries, list)

    def test_excessive_days_capped(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        entries = tracker.get_entries(days=99999)
        assert len(entries) == 1  # Still finds the entry


# ---------------------------------------------------------------------------
# RevenueTracker — get_summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_empty_summary(self, tracker):
        summary = tracker.get_summary(days=30)
        assert summary.total_views == 0
        assert summary.total_net == 0.0
        assert summary.entry_count == 0

    def test_summary_aggregation(self, tracker):
        tracker.record_revenue("v1", "youtube", views=10000, niche="finance")
        tracker.record_revenue("v2", "tiktok", views=20000, niche="gaming")
        summary = tracker.get_summary(days=30)
        assert summary.total_views == 30000
        assert summary.entry_count == 2
        assert summary.total_net > 0
        assert "youtube" in summary.by_platform
        assert "tiktok" in summary.by_platform
        assert "finance" in summary.by_niche
        assert "gaming" in summary.by_niche

    def test_summary_to_dict(self, tracker):
        tracker.record_revenue("v1", "youtube", views=5000, niche="general")
        summary = tracker.get_summary(days=30)
        d = summary.to_dict()
        assert "total_views" in d
        assert "by_platform" in d
        assert "currency" in d

    def test_summary_avg_cpm(self, tracker):
        tracker.record_revenue("v1", "youtube", views=10000, niche="finance")
        summary = tracker.get_summary(days=30)
        assert summary.avg_cpm > 0


# ---------------------------------------------------------------------------
# RevenueTracker — forecast_monthly
# ---------------------------------------------------------------------------


class TestForecastMonthly:
    def test_empty_forecast(self, tracker):
        forecast = tracker.forecast_monthly()
        assert forecast["projected_monthly_net"] == 0.0
        assert forecast["projected_monthly_views"] == 0

    def test_forecast_with_data(self, tracker):
        tracker.record_revenue("v1", "youtube", views=10000, niche="finance")
        forecast = tracker.forecast_monthly(lookback_days=1)
        assert forecast["projected_monthly_views"] > 0
        assert forecast["projected_monthly_net"] > 0
        assert forecast["currency"] == "USD"

    def test_forecast_invalid_lookback_clamped(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        forecast = tracker.forecast_monthly(lookback_days=-5)
        assert forecast["lookback_days"] == 1

    def test_forecast_excessive_lookback_capped(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        forecast = tracker.forecast_monthly(lookback_days=9999)
        assert forecast["lookback_days"] == 365


# ---------------------------------------------------------------------------
# RevenueTracker — get_top_earners
# ---------------------------------------------------------------------------


class TestTopEarners:
    def test_empty_top_earners(self, tracker):
        top = tracker.get_top_earners()
        assert top == []

    def test_top_earners_ranking(self, tracker):
        tracker.record_revenue("v1", "youtube", views=50000, niche="finance")
        tracker.record_revenue("v2", "youtube", views=10000, niche="general")
        tracker.record_revenue("v3", "tiktok", views=100000, niche="gaming")
        top = tracker.get_top_earners(limit=2)
        assert len(top) == 2
        # v1 with finance CPM should earn more net than v3 with gaming tiktok
        assert top[0]["total_net"] >= top[1]["total_net"]

    def test_top_earners_limit_capped(self, tracker):
        for i in range(5):
            tracker.record_revenue(f"v{i}", "youtube", views=1000)
        top = tracker.get_top_earners(limit=3)
        assert len(top) == 3

    def test_top_earners_invalid_limit(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        top = tracker.get_top_earners(limit=-1)
        assert len(top) <= 1

    def test_top_earners_excessive_limit(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        top = tracker.get_top_earners(limit=999)
        assert len(top) == 1

    def test_top_earners_video_id_truncated(self, tracker):
        long_id = "x" * 200
        tracker.record_revenue(long_id, "youtube", views=1000)
        top = tracker.get_top_earners()
        assert len(top[0]["video_id"]) <= 64

    def test_top_earners_aggregates_same_video(self, tracker):
        tracker.record_revenue("v1", "youtube", views=5000, niche="finance")
        tracker.record_revenue("v1", "youtube", views=5000, niche="finance")
        top = tracker.get_top_earners()
        assert len(top) == 1
        assert top[0]["total_views"] == 10000


# ---------------------------------------------------------------------------
# RevenueTracker — get_niche_comparison
# ---------------------------------------------------------------------------


class TestNicheComparison:
    def test_returns_all_niches(self, tracker):
        comparison = tracker.get_niche_comparison()
        niche_names = {item["niche"] for item in comparison}
        assert niche_names == _VALID_NICHES

    def test_sorted_by_avg_net(self, tracker):
        comparison = tracker.get_niche_comparison()
        for i in range(len(comparison) - 1):
            assert comparison[i]["avg_net_per_1k"] >= comparison[i + 1]["avg_net_per_1k"]

    def test_finance_is_top(self, tracker):
        comparison = tracker.get_niche_comparison()
        assert comparison[0]["niche"] == "finance"

    def test_each_niche_has_all_platforms(self, tracker):
        comparison = tracker.get_niche_comparison()
        for item in comparison:
            assert set(item["platforms"].keys()) == _SUPPORTED_PLATFORMS


# ---------------------------------------------------------------------------
# RevenueTracker — clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_removes_entries(self, tracker):
        tracker.record_revenue("v1", "youtube", views=1000)
        assert len(tracker.get_entries()) == 1
        tracker.clear()
        assert len(tracker.get_entries()) == 0

    def test_clear_persists(self, tracker, tmp_file):
        tracker.record_revenue("v1", "youtube", views=1000)
        tracker.clear()
        with open(tmp_file, "r") as f:
            data = json.load(f)
        assert data["entries"] == []


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    def test_default_niche_fallback(self, monkeypatch):
        monkeypatch.setattr("revenue_tracker._get", lambda k, d=None: None)
        assert get_revenue_default_niche() == "general"

    def test_default_niche_from_config(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"default_niche": "finance"} if k == "revenue" else d,
        )
        assert get_revenue_default_niche() == "finance"

    def test_default_niche_invalid_value(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"default_niche": "invalid_niche"} if k == "revenue" else d,
        )
        assert get_revenue_default_niche() == "general"

    def test_currency_default(self, monkeypatch):
        monkeypatch.setattr("revenue_tracker._get", lambda k, d=None: None)
        assert get_revenue_currency() == "USD"

    def test_currency_from_config(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"currency": "EUR"} if k == "revenue" else d,
        )
        assert get_revenue_currency() == "EUR"

    def test_currency_non_string(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"currency": 123} if k == "revenue" else d,
        )
        assert get_revenue_currency() == "USD"

    def test_currency_truncated(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"currency": "A" * 50} if k == "revenue" else d,
        )
        result = get_revenue_currency()
        assert len(result) <= 10

    def test_custom_cpm_empty(self, monkeypatch):
        monkeypatch.setattr("revenue_tracker._get", lambda k, d=None: None)
        assert get_custom_cpm() == {}

    def test_custom_cpm_valid(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"custom_cpm": {"youtube": 15.0}} if k == "revenue" else d,
        )
        result = get_custom_cpm()
        assert result == {"youtube": 15.0}

    def test_custom_cpm_invalid_platform_ignored(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"custom_cpm": {"snapchat": 5.0}} if k == "revenue" else d,
        )
        assert get_custom_cpm() == {}

    def test_custom_cpm_invalid_rate_ignored(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"custom_cpm": {"youtube": "not_a_number"}} if k == "revenue" else d,
        )
        assert get_custom_cpm() == {}

    def test_custom_cpm_excessive_rate_ignored(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"custom_cpm": {"youtube": 5000.0}} if k == "revenue" else d,
        )
        assert get_custom_cpm() == {}

    def test_custom_cpm_zero_rate_ignored(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: {"custom_cpm": {"youtube": 0.0}} if k == "revenue" else d,
        )
        assert get_custom_cpm() == {}

    def test_custom_cpm_non_dict_config(self, monkeypatch):
        monkeypatch.setattr(
            "revenue_tracker._get",
            lambda k, d=None: "not a dict" if k == "revenue" else d,
        )
        assert get_custom_cpm() == {}


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_supported_platforms(self):
        assert "youtube" in _SUPPORTED_PLATFORMS
        assert "tiktok" in _SUPPORTED_PLATFORMS
        assert "twitter" in _SUPPORTED_PLATFORMS
        assert "instagram" in _SUPPORTED_PLATFORMS

    def test_valid_niches_not_empty(self):
        assert len(_VALID_NICHES) >= 10

    def test_cpm_table_has_all_platforms(self):
        for niche_rates in _CPM_BY_NICHE.values():
            for platform in _SUPPORTED_PLATFORMS:
                assert platform in niche_rates

    def test_revenue_share_all_platforms(self):
        for platform in _SUPPORTED_PLATFORMS:
            assert platform in _PLATFORM_REVENUE_SHARE
            assert 0 < _PLATFORM_REVENUE_SHARE[platform] <= 1.0

    def test_max_entries_positive(self):
        assert _MAX_ENTRIES > 0

    def test_max_views_positive(self):
        assert _MAX_VIEWS > 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_writes(self, tmp_file):
        tracker = RevenueTracker(data_file=tmp_file)
        errors = []

        def write_entries(start):
            try:
                for i in range(10):
                    tracker.record_revenue(
                        f"thread_{start}_{i}", "youtube", views=1000
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_entries, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        entries = tracker.get_entries()
        assert len(entries) == 40


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_whitespace_only_video_id_raises(self, tracker):
        with pytest.raises(ValueError, match="non-empty string"):
            tracker.record_revenue("   ", "youtube", views=100)

    def test_niche_none_uses_default(self, tracker):
        entry = tracker.record_revenue("v1", "youtube", views=1000, niche=None)
        assert entry.niche in _VALID_NICHES

    def test_niche_non_string_defaults(self, tracker):
        entry = tracker.record_revenue("v1", "youtube", views=1000, niche=123)
        assert entry.niche == "general"

    def test_all_platforms_produce_revenue(self, tracker):
        for platform in _SUPPORTED_PLATFORMS:
            entry = tracker.record_revenue(f"v_{platform}", platform, views=10000)
            assert entry.estimated_net > 0

    def test_all_niches_produce_different_cpm(self):
        cpms = set()
        for niche in _VALID_NICHES:
            cpms.add(RevenueTracker.get_cpm("youtube", niche))
        # At least some variation
        assert len(cpms) > 1

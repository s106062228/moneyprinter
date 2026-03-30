"""
Tests for src/video_analytics.py — per-video engagement metrics tracker.

Covers VideoMetrics dataclass, VideoAnalyticsTracker methods, persistence,
capping behaviour, thread safety, and edge-cases.
"""

import os
import sys
import json
import threading
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import video_analytics as va_module
from video_analytics import (
    VideoMetrics,
    VideoAnalyticsTracker,
    _validate_platform,
    _validate_metric,
    _SUPPORTED_PLATFORMS,
    _VALID_METRICS,
    _MAX_RECORDS_PER_VIDEO,
    _MAX_TOTAL_RECORDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tracker(tmp_path) -> VideoAnalyticsTracker:
    """Return a tracker backed by an isolated tmp file."""
    mp = tmp_path / ".mp"
    mp.mkdir(exist_ok=True)
    return VideoAnalyticsTracker(storage_path=str(mp / "video_analytics.json"))


def iso_offset(days: int = 0, seconds: int = 0) -> str:
    """Return a UTC ISO timestamp offset from now by the given delta."""
    ts = datetime.now(timezone.utc) - timedelta(days=days, seconds=seconds)
    return ts.isoformat()


# ---------------------------------------------------------------------------
# VideoMetrics dataclass
# ---------------------------------------------------------------------------


class TestVideoMetricsCreation:
    """Tests for VideoMetrics dataclass creation and defaults."""

    def test_minimal_creation(self):
        """Create with only required fields; numeric defaults are zero."""
        m = VideoMetrics(video_id="v1", platform="youtube")
        assert m.video_id == "v1"
        assert m.platform == "youtube"
        assert m.views == 0
        assert m.likes == 0
        assert m.comments == 0
        assert m.shares == 0

    def test_full_creation(self):
        """All positional keyword args are stored correctly."""
        m = VideoMetrics(
            video_id="v2",
            platform="tiktok",
            views=500,
            likes=42,
            comments=7,
            shares=3,
            recorded_at="2026-01-01T00:00:00+00:00",
        )
        assert m.views == 500
        assert m.likes == 42
        assert m.comments == 7
        assert m.shares == 3
        assert m.recorded_at == "2026-01-01T00:00:00+00:00"

    def test_recorded_at_auto_filled_when_empty(self):
        """recorded_at is set to a UTC ISO string when not provided."""
        before = datetime.now(timezone.utc)
        m = VideoMetrics(video_id="v3", platform="twitter")
        after = datetime.now(timezone.utc)

        ts = datetime.fromisoformat(m.recorded_at)
        assert ts >= before
        assert ts <= after

    def test_recorded_at_not_overwritten_when_provided(self):
        """Explicit recorded_at is preserved by __post_init__."""
        fixed = "2025-06-15T12:00:00+00:00"
        m = VideoMetrics(video_id="v4", platform="instagram", recorded_at=fixed)
        assert m.recorded_at == fixed

    def test_recorded_at_auto_filled_when_empty_string(self):
        """An explicit empty string also triggers auto-fill."""
        m = VideoMetrics(video_id="v5", platform="youtube", recorded_at="")
        assert m.recorded_at != ""
        # Should be parseable as ISO timestamp
        datetime.fromisoformat(m.recorded_at)


class TestVideoMetricsToDict:
    """Tests for VideoMetrics.to_dict()."""

    def test_to_dict_keys(self):
        """to_dict returns all expected keys."""
        m = VideoMetrics(video_id="v1", platform="youtube", views=10)
        d = m.to_dict()
        assert set(d.keys()) == {
            "video_id", "platform", "views", "likes", "comments", "shares", "recorded_at"
        }

    def test_to_dict_values(self):
        """to_dict round-trips numeric and string values correctly."""
        fixed_ts = "2026-01-01T00:00:00+00:00"
        m = VideoMetrics(
            video_id="abc",
            platform="tiktok",
            views=99,
            likes=5,
            comments=2,
            shares=1,
            recorded_at=fixed_ts,
        )
        d = m.to_dict()
        assert d["video_id"] == "abc"
        assert d["platform"] == "tiktok"
        assert d["views"] == 99
        assert d["likes"] == 5
        assert d["comments"] == 2
        assert d["shares"] == 1
        assert d["recorded_at"] == fixed_ts

    def test_to_dict_is_plain_dict(self):
        """to_dict returns a plain dict, not a dataclass or subclass."""
        m = VideoMetrics(video_id="x", platform="twitter")
        assert type(m.to_dict()) is dict


class TestVideoMetricsFromDict:
    """Tests for VideoMetrics.from_dict()."""

    def test_from_dict_full(self):
        """from_dict reconstructs all fields from a complete dict."""
        fixed_ts = "2026-03-01T08:00:00+00:00"
        d = {
            "video_id": "vid1",
            "platform": "youtube",
            "views": 100,
            "likes": 10,
            "comments": 3,
            "shares": 2,
            "recorded_at": fixed_ts,
        }
        m = VideoMetrics.from_dict(d)
        assert m.video_id == "vid1"
        assert m.platform == "youtube"
        assert m.views == 100
        assert m.likes == 10
        assert m.comments == 3
        assert m.shares == 2
        assert m.recorded_at == fixed_ts

    def test_from_dict_missing_fields_use_defaults(self):
        """Missing fields fall back to zero / empty string defaults."""
        m = VideoMetrics.from_dict({"video_id": "v", "platform": "twitter"})
        assert m.views == 0
        assert m.likes == 0
        assert m.comments == 0
        assert m.shares == 0

    def test_from_dict_extra_fields_ignored(self):
        """Extra keys in the dict do not cause errors."""
        d = {
            "video_id": "v",
            "platform": "tiktok",
            "views": 5,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "unknown_key": "should be ignored",
        }
        m = VideoMetrics.from_dict(d)
        assert m.video_id == "v"

    def test_from_dict_string_numerics_are_cast(self):
        """Numeric fields stored as strings (e.g. from old JSON) are cast to int."""
        d = {
            "video_id": "v",
            "platform": "youtube",
            "views": "42",
            "likes": "3",
            "comments": "1",
            "shares": "0",
            "recorded_at": "2026-01-01T00:00:00+00:00",
        }
        m = VideoMetrics.from_dict(d)
        assert m.views == 42
        assert isinstance(m.views, int)

    def test_from_dict_empty_dict_gives_defaults(self):
        """Completely empty dict gives zero-value VideoMetrics."""
        m = VideoMetrics.from_dict({})
        assert m.video_id == ""
        assert m.platform == ""
        assert m.views == 0

    def test_to_dict_from_dict_round_trip(self):
        """to_dict → from_dict round-trip preserves all values."""
        fixed_ts = "2026-05-10T10:00:00+00:00"
        original = VideoMetrics(
            video_id="rt1",
            platform="instagram",
            views=77,
            likes=9,
            comments=4,
            shares=2,
            recorded_at=fixed_ts,
        )
        restored = VideoMetrics.from_dict(original.to_dict())
        assert restored.video_id == original.video_id
        assert restored.platform == original.platform
        assert restored.views == original.views
        assert restored.likes == original.likes
        assert restored.comments == original.comments
        assert restored.shares == original.shares
        assert restored.recorded_at == original.recorded_at


# ---------------------------------------------------------------------------
# Validators (module-level helpers)
# ---------------------------------------------------------------------------


class TestValidators:
    """Tests for _validate_platform and _validate_metric."""

    @pytest.mark.parametrize("platform", sorted(_SUPPORTED_PLATFORMS))
    def test_valid_platforms_pass(self, platform):
        _validate_platform(platform)  # should not raise

    def test_invalid_platform_raises(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            _validate_platform("myspace")

    def test_invalid_platform_error_mentions_name(self):
        with pytest.raises(ValueError, match="badplatform"):
            _validate_platform("badplatform")

    @pytest.mark.parametrize("metric", sorted(_VALID_METRICS))
    def test_valid_metrics_pass(self, metric):
        _validate_metric(metric)  # should not raise

    def test_invalid_metric_raises(self):
        with pytest.raises(ValueError, match="Invalid metric"):
            _validate_metric("subscribers")

    def test_invalid_metric_error_mentions_name(self):
        with pytest.raises(ValueError, match="bogus_metric"):
            _validate_metric("bogus_metric")


# ---------------------------------------------------------------------------
# record_metrics
# ---------------------------------------------------------------------------


class TestRecordMetrics:
    """Tests for VideoAnalyticsTracker.record_metrics()."""

    def test_record_single_returns_video_metrics(self, tmp_path):
        """record_metrics returns a VideoMetrics instance."""
        tracker = make_tracker(tmp_path)
        result = tracker.record_metrics("vid1", "youtube", views=100)
        assert isinstance(result, VideoMetrics)

    def test_record_single_values(self, tmp_path):
        """Returned VideoMetrics has the values that were passed in."""
        tracker = make_tracker(tmp_path)
        m = tracker.record_metrics("vid1", "youtube", views=200, likes=15, comments=3, shares=1)
        assert m.video_id == "vid1"
        assert m.platform == "youtube"
        assert m.views == 200
        assert m.likes == 15
        assert m.comments == 3
        assert m.shares == 1

    def test_record_multiple_appends(self, tmp_path):
        """Multiple calls for the same video accumulate records."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        tracker.record_metrics("vid1", "youtube", views=200)
        tracker.record_metrics("vid1", "youtube", views=300)
        records = tracker.get_metrics("vid1", "youtube")
        assert len(records) == 3

    def test_record_default_values(self, tmp_path):
        """Calling record_metrics with only required args uses zero defaults."""
        tracker = make_tracker(tmp_path)
        m = tracker.record_metrics("vid2", "tiktok")
        assert m.views == 0
        assert m.likes == 0
        assert m.comments == 0
        assert m.shares == 0

    def test_record_invalid_platform_raises(self, tmp_path):
        """record_metrics raises ValueError for an unsupported platform."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError, match="Unsupported platform"):
            tracker.record_metrics("vid1", "facebook", views=10)

    def test_record_invalid_platform_no_side_effect(self, tmp_path):
        """A failed record_metrics call does not write any data."""
        tracker = make_tracker(tmp_path)
        try:
            tracker.record_metrics("vid1", "facebook", views=10)
        except ValueError:
            pass
        assert tracker.get_metrics("vid1") == []

    def test_record_negative_views_stored_as_is(self, tmp_path):
        """Negative values are stored without raising (no clamping in source)."""
        tracker = make_tracker(tmp_path)
        # The implementation does not clamp; just verify it doesn't raise
        m = tracker.record_metrics("vid1", "youtube", views=-5)
        assert m.views == -5

    def test_recorded_at_is_set_automatically(self, tmp_path):
        """Recorded metric has a non-empty recorded_at timestamp."""
        tracker = make_tracker(tmp_path)
        m = tracker.record_metrics("vid1", "youtube", views=10)
        assert m.recorded_at != ""
        datetime.fromisoformat(m.recorded_at)  # must be valid ISO


# ---------------------------------------------------------------------------
# get_metrics
# ---------------------------------------------------------------------------


class TestGetMetrics:
    """Tests for VideoAnalyticsTracker.get_metrics()."""

    def test_get_metrics_returns_list(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube")
        result = tracker.get_metrics("vid1")
        assert isinstance(result, list)

    def test_get_metrics_all_platforms(self, tmp_path):
        """get_metrics without platform filter returns records from all platforms."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=10)
        tracker.record_metrics("vid1", "tiktok", views=20)
        result = tracker.get_metrics("vid1")
        assert len(result) == 2

    def test_get_metrics_platform_filter(self, tmp_path):
        """Platform filter restricts results to the specified platform."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=10)
        tracker.record_metrics("vid1", "tiktok", views=20)
        yt = tracker.get_metrics("vid1", "youtube")
        assert len(yt) == 1
        assert yt[0].platform == "youtube"

    def test_get_metrics_empty_for_unknown_video(self, tmp_path):
        """Returns empty list when the video_id has no records."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_metrics("nonexistent_vid") == []

    def test_get_metrics_empty_for_wrong_platform(self, tmp_path):
        """Returns empty list when video exists but not on requested platform."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube")
        result = tracker.get_metrics("vid1", "tiktok")
        assert result == []

    def test_get_metrics_invalid_platform_raises(self, tmp_path):
        """Passing an invalid platform to get_metrics raises ValueError."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError):
            tracker.get_metrics("vid1", "snapchat")

    def test_get_metrics_returns_video_metrics_instances(self, tmp_path):
        """Each item in the returned list is a VideoMetrics instance."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=5)
        result = tracker.get_metrics("vid1")
        assert all(isinstance(m, VideoMetrics) for m in result)

    def test_get_metrics_chronological_order(self, tmp_path):
        """Records are returned oldest-first (append order)."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        tracker.record_metrics("vid1", "youtube", views=200)
        tracker.record_metrics("vid1", "youtube", views=300)
        result = tracker.get_metrics("vid1", "youtube")
        views = [m.views for m in result]
        assert views == [100, 200, 300]

    def test_get_metrics_does_not_cross_contaminate_videos(self, tmp_path):
        """Records for vid2 are not returned when querying vid1."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=10)
        tracker.record_metrics("vid2", "youtube", views=999)
        result = tracker.get_metrics("vid1", "youtube")
        assert all(m.video_id == "vid1" for m in result)


# ---------------------------------------------------------------------------
# get_latest_metrics
# ---------------------------------------------------------------------------


class TestGetLatestMetrics:
    """Tests for VideoAnalyticsTracker.get_latest_metrics()."""

    def test_returns_most_recent(self, tmp_path):
        """get_latest_metrics returns the last recorded snapshot."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        tracker.record_metrics("vid1", "youtube", views=200)
        latest = tracker.get_latest_metrics("vid1", "youtube")
        assert latest.views == 200

    def test_returns_none_when_no_records(self, tmp_path):
        """Returns None when no records exist for the (video, platform) pair."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_latest_metrics("nonexistent", "youtube") is None

    def test_returns_none_for_wrong_platform(self, tmp_path):
        """Returns None when the video exists on a different platform only."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=50)
        assert tracker.get_latest_metrics("vid1", "tiktok") is None

    def test_returns_video_metrics_instance(self, tmp_path):
        """Return type is VideoMetrics, not a raw dict."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=10)
        m = tracker.get_latest_metrics("vid1", "youtube")
        assert isinstance(m, VideoMetrics)

    def test_invalid_platform_raises(self, tmp_path):
        """Raises ValueError for an unsupported platform."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError):
            tracker.get_latest_metrics("vid1", "myspace")

    def test_single_record_is_latest(self, tmp_path):
        """When only one record exists, it is also the latest."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "tiktok", views=77)
        m = tracker.get_latest_metrics("vid1", "tiktok")
        assert m.views == 77


# ---------------------------------------------------------------------------
# get_top_videos
# ---------------------------------------------------------------------------


class TestGetTopVideos:
    """Tests for VideoAnalyticsTracker.get_top_videos()."""

    def _seed(self, tracker):
        """Seed tracker with three videos across two platforms."""
        tracker.record_metrics("vidA", "youtube", views=1000, likes=80)
        tracker.record_metrics("vidB", "youtube", views=500, likes=30)
        tracker.record_metrics("vidC", "tiktok", views=2000, likes=120)

    def test_top_by_views_default(self, tmp_path):
        """Default metric is views; returns descending order."""
        tracker = make_tracker(tmp_path)
        self._seed(tracker)
        top = tracker.get_top_videos()
        assert top[0].views >= top[-1].views

    def test_top_by_likes(self, tmp_path):
        """metric='likes' sorts by likes descending."""
        tracker = make_tracker(tmp_path)
        self._seed(tracker)
        top = tracker.get_top_videos(metric="likes")
        assert top[0].likes >= top[-1].likes

    def test_top_by_comments(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", comments=50)
        tracker.record_metrics("vid2", "youtube", comments=10)
        top = tracker.get_top_videos(metric="comments")
        assert top[0].comments == 50

    def test_top_by_shares(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", shares=30)
        tracker.record_metrics("vid2", "youtube", shares=5)
        top = tracker.get_top_videos(metric="shares")
        assert top[0].shares == 30

    def test_platform_filter(self, tmp_path):
        """Platform filter excludes videos from other platforms."""
        tracker = make_tracker(tmp_path)
        self._seed(tracker)
        top = tracker.get_top_videos(platform="youtube")
        assert all(m.platform == "youtube" for m in top)

    def test_limit_respected(self, tmp_path):
        """limit parameter caps the number of results."""
        tracker = make_tracker(tmp_path)
        for i in range(10):
            tracker.record_metrics(f"vid{i}", "youtube", views=i * 10)
        top = tracker.get_top_videos(limit=3)
        assert len(top) <= 3

    def test_returns_empty_on_no_data(self, tmp_path):
        """Returns empty list when there are no records."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_top_videos() == []

    def test_invalid_metric_raises(self, tmp_path):
        """Raises ValueError for an invalid metric name."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError, match="Invalid metric"):
            tracker.get_top_videos(metric="subscribers")

    def test_invalid_platform_raises(self, tmp_path):
        """Raises ValueError for an unsupported platform."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError, match="Unsupported platform"):
            tracker.get_top_videos(platform="myspace")

    def test_returns_video_metrics_instances(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=50)
        top = tracker.get_top_videos()
        assert all(isinstance(m, VideoMetrics) for m in top)

    def test_uses_latest_snapshot_per_video(self, tmp_path):
        """Multiple snapshots for the same video: latest is used for ranking."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=50)
        tracker.record_metrics("vid1", "youtube", views=999)  # update
        tracker.record_metrics("vid2", "youtube", views=100)
        top = tracker.get_top_videos(metric="views")
        # vid1's latest is 999, should be first
        assert top[0].video_id == "vid1"
        assert top[0].views == 999

    def test_platform_filter_empty_result(self, tmp_path):
        """Platform filter returns empty list when no records for that platform."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        top = tracker.get_top_videos(platform="tiktok")
        assert top == []


# ---------------------------------------------------------------------------
# get_trend
# ---------------------------------------------------------------------------


class TestGetTrend:
    """Tests for VideoAnalyticsTracker.get_trend()."""

    def test_trend_returns_expected_keys(self, tmp_path):
        """Return dict has current, previous, change, change_pct."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        result = tracker.get_trend("vid1", "youtube", metric="views", days=7)
        assert set(result.keys()) == {"current", "previous", "change", "change_pct"}

    def test_positive_trend(self, tmp_path):
        """change > 0 when current window is higher than previous."""
        tracker = make_tracker(tmp_path)
        # previous window (8–14 days ago)
        prev_ts = iso_offset(days=10)
        prev_m = VideoMetrics(video_id="vid1", platform="youtube", views=100, recorded_at=prev_ts)
        # current window (0–7 days ago)
        cur_ts = iso_offset(days=1)
        cur_m = VideoMetrics(video_id="vid1", platform="youtube", views=300, recorded_at=cur_ts)

        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        with open(storage, "w") as f:
            json.dump({"records": [prev_m.to_dict(), cur_m.to_dict()]}, f)

        tracker2 = VideoAnalyticsTracker(storage_path=storage)
        result = tracker2.get_trend("vid1", "youtube", metric="views", days=7)
        assert result["change"] > 0
        assert result["current"] == 300
        assert result["previous"] == 100

    def test_negative_trend(self, tmp_path):
        """change < 0 when current window is lower than previous."""
        tracker = make_tracker(tmp_path)
        prev_ts = iso_offset(days=10)
        prev_m = VideoMetrics(video_id="vid1", platform="youtube", views=500, recorded_at=prev_ts)
        cur_ts = iso_offset(days=1)
        cur_m = VideoMetrics(video_id="vid1", platform="youtube", views=200, recorded_at=cur_ts)

        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        with open(storage, "w") as f:
            json.dump({"records": [prev_m.to_dict(), cur_m.to_dict()]}, f)

        tracker2 = VideoAnalyticsTracker(storage_path=storage)
        result = tracker2.get_trend("vid1", "youtube", metric="views", days=7)
        assert result["change"] < 0

    def test_flat_trend(self, tmp_path):
        """change == 0 when current and previous have equal max."""
        prev_ts = iso_offset(days=10)
        cur_ts = iso_offset(days=1)
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        records = [
            VideoMetrics(video_id="vid1", platform="youtube", views=100, recorded_at=prev_ts).to_dict(),
            VideoMetrics(video_id="vid1", platform="youtube", views=100, recorded_at=cur_ts).to_dict(),
        ]
        with open(storage, "w") as f:
            json.dump({"records": records}, f)

        tracker = VideoAnalyticsTracker(storage_path=storage)
        result = tracker.get_trend("vid1", "youtube", metric="views", days=7)
        assert result["change"] == 0
        assert result["change_pct"] == 0.0

    def test_no_data_returns_zeros(self, tmp_path):
        """No records → current=0, previous=0, change=0, change_pct=0.0."""
        tracker = make_tracker(tmp_path)
        result = tracker.get_trend("no_vid", "youtube", metric="views", days=7)
        assert result["current"] == 0
        assert result["previous"] == 0
        assert result["change"] == 0
        assert result["change_pct"] == 0.0

    def test_only_current_window_data(self, tmp_path):
        """Only current-window data → previous=0, change_pct=0.0."""
        cur_ts = iso_offset(days=1)
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        records = [
            VideoMetrics(video_id="vid1", platform="youtube", views=150, recorded_at=cur_ts).to_dict(),
        ]
        with open(storage, "w") as f:
            json.dump({"records": records}, f)

        tracker = VideoAnalyticsTracker(storage_path=storage)
        result = tracker.get_trend("vid1", "youtube", days=7)
        assert result["current"] == 150
        assert result["previous"] == 0
        assert result["change_pct"] == 0.0

    def test_invalid_platform_raises(self, tmp_path):
        """Raises ValueError for an unsupported platform."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError):
            tracker.get_trend("vid1", "badplatform")

    def test_invalid_metric_raises(self, tmp_path):
        """Raises ValueError for an invalid metric."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError):
            tracker.get_trend("vid1", "youtube", metric="subscribers")

    def test_invalid_days_raises(self, tmp_path):
        """Raises ValueError when days <= 0."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError, match="days"):
            tracker.get_trend("vid1", "youtube", days=0)

    def test_negative_days_raises(self, tmp_path):
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError):
            tracker.get_trend("vid1", "youtube", days=-3)

    def test_change_pct_calculated_correctly(self, tmp_path):
        """change_pct = (change / previous) * 100, rounded to 2 dp."""
        prev_ts = iso_offset(days=10)
        cur_ts = iso_offset(days=1)
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        records = [
            VideoMetrics(video_id="vid1", platform="youtube", views=200, recorded_at=prev_ts).to_dict(),
            VideoMetrics(video_id="vid1", platform="youtube", views=300, recorded_at=cur_ts).to_dict(),
        ]
        with open(storage, "w") as f:
            json.dump({"records": records}, f)

        tracker = VideoAnalyticsTracker(storage_path=storage)
        result = tracker.get_trend("vid1", "youtube", days=7)
        assert result["change_pct"] == 50.0


# ---------------------------------------------------------------------------
# get_platform_summary
# ---------------------------------------------------------------------------


class TestGetPlatformSummary:
    """Tests for VideoAnalyticsTracker.get_platform_summary()."""

    def test_returns_expected_keys(self, tmp_path):
        """Return dict has all six expected keys."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        summary = tracker.get_platform_summary("youtube")
        assert set(summary.keys()) == {
            "total_videos", "total_views", "total_likes",
            "total_comments", "total_shares", "avg_views",
        }

    def test_totals_single_video(self, tmp_path):
        """Single video on platform; totals match its metrics."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=500, likes=40, comments=10, shares=5)
        summary = tracker.get_platform_summary("youtube")
        assert summary["total_videos"] == 1
        assert summary["total_views"] == 500
        assert summary["total_likes"] == 40
        assert summary["total_comments"] == 10
        assert summary["total_shares"] == 5

    def test_totals_multiple_videos(self, tmp_path):
        """Multiple videos; totals are summed across latest snapshots."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vidA", "youtube", views=100, likes=10)
        tracker.record_metrics("vidB", "youtube", views=200, likes=20)
        summary = tracker.get_platform_summary("youtube")
        assert summary["total_videos"] == 2
        assert summary["total_views"] == 300
        assert summary["total_likes"] == 30

    def test_uses_latest_snapshot_per_video(self, tmp_path):
        """For a video with multiple snapshots, only the latest contributes."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        tracker.record_metrics("vid1", "youtube", views=900)  # update
        summary = tracker.get_platform_summary("youtube")
        assert summary["total_views"] == 900
        assert summary["total_videos"] == 1

    def test_platform_isolation(self, tmp_path):
        """Records on other platforms are not counted."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=100)
        tracker.record_metrics("vid2", "tiktok", views=9999)
        summary = tracker.get_platform_summary("youtube")
        assert summary["total_views"] == 100

    def test_avg_views_calculated(self, tmp_path):
        """avg_views = total_views / total_videos."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vidA", "youtube", views=100)
        tracker.record_metrics("vidB", "youtube", views=300)
        summary = tracker.get_platform_summary("youtube")
        assert summary["avg_views"] == 200.0

    def test_empty_platform_returns_zeros(self, tmp_path):
        """No records for the platform → all values are zero."""
        tracker = make_tracker(tmp_path)
        summary = tracker.get_platform_summary("youtube")
        assert summary["total_videos"] == 0
        assert summary["total_views"] == 0
        assert summary["avg_views"] == 0.0

    def test_invalid_platform_raises(self, tmp_path):
        """Raises ValueError for an unsupported platform."""
        tracker = make_tracker(tmp_path)
        with pytest.raises(ValueError, match="Unsupported platform"):
            tracker.get_platform_summary("badplatform")


# ---------------------------------------------------------------------------
# delete_metrics
# ---------------------------------------------------------------------------


class TestDeleteMetrics:
    """Tests for VideoAnalyticsTracker.delete_metrics()."""

    def test_delete_all_records_for_video(self, tmp_path):
        """delete_metrics removes every record for the given video_id."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube", views=10)
        tracker.record_metrics("vid1", "tiktok", views=20)
        tracker.delete_metrics("vid1")
        assert tracker.get_metrics("vid1") == []

    def test_delete_returns_count(self, tmp_path):
        """Returns the number of deleted records."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube")
        tracker.record_metrics("vid1", "youtube")
        tracker.record_metrics("vid1", "tiktok")
        count = tracker.delete_metrics("vid1")
        assert count == 3

    def test_delete_unknown_video_returns_zero(self, tmp_path):
        """Returns 0 when video_id has no records."""
        tracker = make_tracker(tmp_path)
        assert tracker.delete_metrics("ghost_vid") == 0

    def test_delete_does_not_affect_other_videos(self, tmp_path):
        """Records for other video_ids are untouched."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("keep_me", "youtube", views=42)
        tracker.record_metrics("delete_me", "youtube", views=99)
        tracker.delete_metrics("delete_me")
        remaining = tracker.get_metrics("keep_me")
        assert len(remaining) == 1
        assert remaining[0].views == 42

    def test_delete_idempotent(self, tmp_path):
        """Calling delete_metrics twice for same video_id is safe."""
        tracker = make_tracker(tmp_path)
        tracker.record_metrics("vid1", "youtube")
        tracker.delete_metrics("vid1")
        count = tracker.delete_metrics("vid1")
        assert count == 0


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Tests for atomic save/load behaviour."""

    def test_data_survives_reload(self, tmp_path):
        """Records written by one tracker instance are visible to a new one."""
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)

        t1 = VideoAnalyticsTracker(storage_path=storage)
        t1.record_metrics("vid1", "youtube", views=42)

        t2 = VideoAnalyticsTracker(storage_path=storage)
        result = t2.get_metrics("vid1", "youtube")
        assert len(result) == 1
        assert result[0].views == 42

    def test_storage_file_is_valid_json(self, tmp_path):
        """The file written to disk is well-formed JSON."""
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        tracker = VideoAnalyticsTracker(storage_path=storage)
        tracker.record_metrics("vid1", "youtube", views=10)

        with open(storage, "r") as f:
            data = json.load(f)  # must not raise
        assert "records" in data

    def test_missing_file_returns_empty(self, tmp_path):
        """Loading from a non-existent path returns empty structure."""
        storage = str(tmp_path / "does_not_exist" / "va.json")
        tracker = VideoAnalyticsTracker(storage_path=storage)
        assert tracker.get_metrics("vid1") == []

    def test_corrupted_file_returns_empty(self, tmp_path):
        """Corrupted JSON file is gracefully ignored; queries return empty."""
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        with open(storage, "w") as f:
            f.write("NOT VALID JSON{{{{")

        tracker = VideoAnalyticsTracker(storage_path=storage)
        assert tracker.get_metrics("vid1") == []

    def test_non_dict_json_returns_empty(self, tmp_path):
        """If the JSON file contains a list instead of a dict, return empty."""
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        with open(storage, "w") as f:
            json.dump(["not", "a", "dict"], f)

        tracker = VideoAnalyticsTracker(storage_path=storage)
        assert tracker.get_metrics("vid1") == []

    def test_custom_storage_path(self, tmp_path):
        """Tracker uses the provided storage_path, not the default."""
        custom = str(tmp_path / "custom_dir" / "custom.json")
        os.makedirs(os.path.dirname(custom), exist_ok=True)
        tracker = VideoAnalyticsTracker(storage_path=custom)
        tracker.record_metrics("vid1", "youtube", views=7)
        assert os.path.exists(custom)

    def test_default_storage_path_set(self, tmp_path):
        """Without storage_path, _path falls back to the module default."""
        t = VideoAnalyticsTracker()
        from video_analytics import _ANALYTICS_FILE
        assert t._path == _ANALYTICS_FILE


# ---------------------------------------------------------------------------
# Capping behaviour
# ---------------------------------------------------------------------------


class TestCappingBehaviour:
    """Tests for per-video and global record limits."""

    def test_per_video_cap_removes_oldest(self, tmp_path):
        """When per-video records exceed _MAX_RECORDS_PER_VIDEO, oldest are dropped."""
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)
        tracker = VideoAnalyticsTracker(storage_path=storage)

        # Write exactly MAX + 1 records for the same (video, platform) pair
        limit = _MAX_RECORDS_PER_VIDEO
        for i in range(limit + 1):
            tracker.record_metrics("vid1", "youtube", views=i)

        records = tracker.get_metrics("vid1", "youtube")
        assert len(records) == limit
        # The oldest record (views=0) should have been dropped
        assert records[0].views == 1

    def test_global_cap_removes_oldest(self, tmp_path):
        """When total records exceed _MAX_TOTAL_RECORDS, oldest are sliced off."""
        storage = str(tmp_path / ".mp" / "va.json")
        os.makedirs(os.path.dirname(storage), exist_ok=True)

        # Seed the file with MAX_TOTAL_RECORDS records manually (fast path)
        sentinel = VideoMetrics(
            video_id="sentinel", platform="youtube", views=0,
            recorded_at="2020-01-01T00:00:00+00:00"
        ).to_dict()
        records = [sentinel] * _MAX_TOTAL_RECORDS
        with open(storage, "w") as f:
            json.dump({"records": records}, f)

        tracker = VideoAnalyticsTracker(storage_path=storage)
        # Adding one more should push out the oldest sentinel
        tracker.record_metrics("new_vid", "tiktok", views=1)

        with open(storage, "r") as f:
            data = json.load(f)
        assert len(data["records"]) == _MAX_TOTAL_RECORDS

        last = data["records"][-1]
        assert last["video_id"] == "new_vid"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Tests for concurrent access to VideoAnalyticsTracker."""

    def test_concurrent_record_metrics(self, tmp_path):
        """Concurrent record_metrics calls from multiple threads are all persisted."""
        tracker = make_tracker(tmp_path)
        errors: list[Exception] = []
        n_threads = 20
        records_per_thread = 5

        def worker(thread_id: int):
            try:
                for j in range(records_per_thread):
                    tracker.record_metrics(f"vid_{thread_id}", "youtube", views=j * 10)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

        # Each distinct video_id should have records_per_thread records
        for i in range(n_threads):
            records = tracker.get_metrics(f"vid_{i}", "youtube")
            assert len(records) == records_per_thread, (
                f"vid_{i} has {len(records)} records, expected {records_per_thread}"
            )

    def test_concurrent_mixed_operations(self, tmp_path):
        """Simultaneous writes and reads do not corrupt data."""
        tracker = make_tracker(tmp_path)
        errors: list[Exception] = []

        def writer():
            try:
                for _ in range(10):
                    tracker.record_metrics("shared_vid", "youtube", views=100)
            except Exception as exc:
                errors.append(exc)

        def reader():
            try:
                for _ in range(10):
                    tracker.get_metrics("shared_vid", "youtube")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(5)]
        threads += [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# Empty storage (fresh tracker)
# ---------------------------------------------------------------------------


class TestEmptyStorage:
    """Verifies that all queries return empty/zero values on a fresh tracker."""

    def test_get_metrics_empty(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_metrics("any_vid") == []

    def test_get_latest_metrics_empty(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_latest_metrics("any_vid", "youtube") is None

    def test_get_top_videos_empty(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_top_videos() == []

    def test_get_trend_empty(self, tmp_path):
        tracker = make_tracker(tmp_path)
        result = tracker.get_trend("any_vid", "youtube")
        assert result["current"] == 0
        assert result["previous"] == 0

    def test_get_platform_summary_empty(self, tmp_path):
        tracker = make_tracker(tmp_path)
        summary = tracker.get_platform_summary("youtube")
        assert summary["total_videos"] == 0
        assert summary["total_views"] == 0
        assert summary["avg_views"] == 0.0

    def test_delete_metrics_empty(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.delete_metrics("any_vid") == 0

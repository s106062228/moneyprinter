"""
Tests for src/analytics.py — event tracking and metrics.
"""

import os
import json
import pytest
from unittest.mock import patch

import analytics as analytics_module


@pytest.fixture(autouse=True)
def isolate_analytics(tmp_path):
    """Redirect analytics to a temp file for each test."""
    analytics_file = str(tmp_path / ".mp" / "analytics.json")
    os.makedirs(os.path.dirname(analytics_file), exist_ok=True)
    with patch.object(analytics_module, "ANALYTICS_FILE", analytics_file):
        yield analytics_file


class TestTrackEvent:
    """Tests for track_event()."""

    def test_track_single_event(self, isolate_analytics):
        """Records a single event with correct structure."""
        analytics_module.track_event("video_generated", "youtube", {"topic": "AI"})

        with open(isolate_analytics) as f:
            data = json.load(f)

        assert len(data["events"]) == 1
        event = data["events"][0]
        assert event["type"] == "video_generated"
        assert event["platform"] == "youtube"
        assert event["details"]["topic"] == "AI"
        assert "timestamp" in event

    def test_track_multiple_events(self, isolate_analytics):
        """Records multiple events and updates summary counters."""
        analytics_module.track_event("video_generated", "youtube")
        analytics_module.track_event("video_uploaded", "youtube")
        analytics_module.track_event("tweet_posted", "twitter")

        with open(isolate_analytics) as f:
            data = json.load(f)

        assert len(data["events"]) == 3
        assert data["summary"]["youtube"]["total_events"] == 2
        assert data["summary"]["youtube"]["video_generated"] == 1
        assert data["summary"]["youtube"]["video_uploaded"] == 1
        assert data["summary"]["twitter"]["total_events"] == 1

    def test_track_event_no_details(self, isolate_analytics):
        """Records event with empty details dict when none provided."""
        analytics_module.track_event("tweet_posted", "twitter")

        with open(isolate_analytics) as f:
            data = json.load(f)

        assert data["events"][0]["details"] == {}


class TestGetSummary:
    """Tests for get_summary()."""

    def test_empty_summary(self, isolate_analytics):
        """Returns empty dict when no events tracked."""
        result = analytics_module.get_summary()
        assert result == {}

    def test_summary_after_events(self, isolate_analytics):
        """Returns correct summary after tracking events."""
        analytics_module.track_event("video_generated", "youtube")
        analytics_module.track_event("video_generated", "youtube")

        summary = analytics_module.get_summary()
        assert summary["youtube"]["video_generated"] == 2
        assert summary["youtube"]["total_events"] == 2


class TestGetEvents:
    """Tests for get_events()."""

    def test_get_events_empty(self, isolate_analytics):
        """Returns empty list when no events."""
        assert analytics_module.get_events() == []

    def test_get_events_returns_recent_first(self, isolate_analytics):
        """Events are returned most recent first."""
        analytics_module.track_event("first", "youtube")
        analytics_module.track_event("second", "youtube")
        analytics_module.track_event("third", "youtube")

        events = analytics_module.get_events()
        assert events[0]["type"] == "third"
        assert events[2]["type"] == "first"

    def test_filter_by_platform(self, isolate_analytics):
        """Filters events by platform."""
        analytics_module.track_event("tweet_posted", "twitter")
        analytics_module.track_event("video_generated", "youtube")

        events = analytics_module.get_events(platform="twitter")
        assert len(events) == 1
        assert events[0]["platform"] == "twitter"

    def test_filter_by_event_type(self, isolate_analytics):
        """Filters events by type."""
        analytics_module.track_event("video_generated", "youtube")
        analytics_module.track_event("video_uploaded", "youtube")

        events = analytics_module.get_events(event_type="video_generated")
        assert len(events) == 1
        assert events[0]["type"] == "video_generated"

    def test_limit_parameter(self, isolate_analytics):
        """Respects the limit parameter."""
        for i in range(10):
            analytics_module.track_event(f"event_{i}", "youtube")

        events = analytics_module.get_events(limit=3)
        assert len(events) == 3


class TestGetPlatformStats:
    """Tests for get_platform_stats()."""

    def test_unknown_platform(self, isolate_analytics):
        """Returns empty dict for unknown platform."""
        assert analytics_module.get_platform_stats("instagram") == {}

    def test_known_platform(self, isolate_analytics):
        """Returns correct stats for tracked platform."""
        analytics_module.track_event("video_generated", "youtube")
        stats = analytics_module.get_platform_stats("youtube")
        assert stats["video_generated"] == 1
        assert stats["total_events"] == 1

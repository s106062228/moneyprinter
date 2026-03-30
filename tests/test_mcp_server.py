"""
Tests for mcp_server.py — MCP tool functions.

Strategy: fastmcp may not be installed, so we inject a mock into sys.modules
before importing mcp_server.  The @mcp.tool decorator is replaced with a
pass-through so each tool is just a plain Python function.  All lazily-imported
inner modules (smart_clipper, publisher, content_scheduler, analytics_report)
are patched via sys.modules so they never need to be installed.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Ensure src/ is on the path (same pattern used by the rest of the test suite)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ---------------------------------------------------------------------------
# Stub out fastmcp BEFORE importing mcp_server so the import doesn't fail
# ---------------------------------------------------------------------------
_MCP_SERVER_PREV_FASTMCP = sys.modules.get("fastmcp")
_mock_fastmcp_module = MagicMock()
_mock_mcp_instance = MagicMock()
# .tool must be a pass-through decorator so the functions stay callable
_mock_mcp_instance.tool = lambda fn: fn
_mock_fastmcp_module.FastMCP.return_value = _mock_mcp_instance
sys.modules["fastmcp"] = _mock_fastmcp_module

# Now it is safe to import the four tool functions
from mcp_server import analyze_video, publish_content, schedule_content, get_analytics  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

def _make_clip(start=0.0, end=30.0, duration=30.0, score=8.0,
               transcript="Great content", reason="High engagement",
               scene_count=3):
    """Return a MagicMock that mimics a ClipCandidate."""
    clip = MagicMock()
    clip.to_dict.return_value = {
        "start_time": start,
        "end_time": end,
        "duration": duration,
        "score": score,
        "transcript": transcript,
        "reason": reason,
        "scene_count": scene_count,
    }
    return clip


def _make_publish_result_dict(platform="youtube", success=True):
    """Return a plain dict that mimics a PublishResult."""
    return {
        "platform": platform,
        "success": success,
        "timestamp": "2026-03-28T04:00:00Z",
        "error_type": None,
        "duration_seconds": 12.3,
        "details": {},
    }


def _make_publish_result_obj(platform="youtube", success=True):
    """Return an object whose __dict__ looks like a PublishResult."""
    result = MagicMock()
    result.__dict__ = _make_publish_result_dict(platform, success)
    return result


# ===========================================================================
# analyze_video
# ===========================================================================

class TestAnalyzeVideo:
    """Tests for the analyze_video MCP tool."""

    # ------------------------------------------------------------------
    # 1. Happy-path: returns serialised highlights
    # ------------------------------------------------------------------
    def test_analyze_video_returns_highlights(self):
        clips = [_make_clip(start=0.0, end=30.0), _make_clip(start=60.0, end=90.0)]
        mock_clipper_instance = MagicMock()
        mock_clipper_instance.find_highlights.return_value = clips

        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.return_value = mock_clipper_instance

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            result = analyze_video("video.mp4")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["start_time"] == 0.0
        assert result[1]["start_time"] == 60.0

    # ------------------------------------------------------------------
    # 2. Constructor parameters are forwarded correctly
    # ------------------------------------------------------------------
    def test_analyze_video_passes_params(self):
        mock_clipper_instance = MagicMock()
        mock_clipper_instance.find_highlights.return_value = []

        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.return_value = mock_clipper_instance

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            analyze_video("vid.mp4", min_clip_duration=10.0, max_clip_duration=45.0, top_n=3)

        mock_smart_clipper.SmartClipper.assert_called_once_with(
            min_clip_duration=10.0,
            max_clip_duration=45.0,
            top_n=3,
        )

    # ------------------------------------------------------------------
    # 3. find_highlights is called with the supplied video_path
    # ------------------------------------------------------------------
    def test_analyze_video_passes_video_path(self):
        mock_clipper_instance = MagicMock()
        mock_clipper_instance.find_highlights.return_value = []

        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.return_value = mock_clipper_instance

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            analyze_video("/absolute/path/to/video.mp4")

        mock_clipper_instance.find_highlights.assert_called_once_with("/absolute/path/to/video.mp4")

    # ------------------------------------------------------------------
    # 4. FileNotFoundError → error dict
    # ------------------------------------------------------------------
    def test_analyze_video_file_not_found(self):
        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.side_effect = FileNotFoundError("no such file")

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            result = analyze_video("missing.mp4")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["error"] == "FileNotFoundError"
        assert "no such file" in result[0]["message"]

    # ------------------------------------------------------------------
    # 5. ValueError → error dict
    # ------------------------------------------------------------------
    def test_analyze_video_value_error(self):
        mock_clipper_instance = MagicMock()
        mock_clipper_instance.find_highlights.side_effect = ValueError("bad duration")

        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.return_value = mock_clipper_instance

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            result = analyze_video("vid.mp4")

        assert result[0]["error"] == "ValueError"
        assert "bad duration" in result[0]["message"]

    # ------------------------------------------------------------------
    # 6. Unexpected exception → error dict with class name
    # ------------------------------------------------------------------
    def test_analyze_video_unexpected_error(self):
        mock_clipper_instance = MagicMock()
        mock_clipper_instance.find_highlights.side_effect = RuntimeError("GPU exploded")

        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.return_value = mock_clipper_instance

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            result = analyze_video("vid.mp4")

        assert result[0]["error"] == "RuntimeError"
        assert "GPU exploded" in result[0]["message"]

    # ------------------------------------------------------------------
    # 7. Empty results list is returned as-is
    # ------------------------------------------------------------------
    def test_analyze_video_empty_results(self):
        mock_clipper_instance = MagicMock()
        mock_clipper_instance.find_highlights.return_value = []

        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.return_value = mock_clipper_instance

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            result = analyze_video("vid.mp4")

        assert result == []

    # ------------------------------------------------------------------
    # 8. Default parameter values (min=15, max=60, top_n=5)
    # ------------------------------------------------------------------
    def test_analyze_video_default_params(self):
        mock_clipper_instance = MagicMock()
        mock_clipper_instance.find_highlights.return_value = []

        mock_smart_clipper = MagicMock()
        mock_smart_clipper.SmartClipper.return_value = mock_clipper_instance

        with patch.dict(sys.modules, {"smart_clipper": mock_smart_clipper}):
            analyze_video("vid.mp4")

        mock_smart_clipper.SmartClipper.assert_called_once_with(
            min_clip_duration=15.0,
            max_clip_duration=60.0,
            top_n=5,
        )


# ===========================================================================
# publish_content
# ===========================================================================

class TestPublishContent:
    """Tests for the publish_content MCP tool."""

    # ------------------------------------------------------------------
    # 9. Happy-path: result dicts are forwarded as-is
    # ------------------------------------------------------------------
    def test_publish_returns_results(self):
        results = [
            _make_publish_result_dict("youtube", True),
            _make_publish_result_dict("tiktok", True),
        ]
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish.return_value = results

        mock_publisher_mod = MagicMock()
        mock_publisher_mod.ContentPublisher.return_value = mock_publisher_instance
        mock_publisher_mod.PublishJob = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {"publisher": mock_publisher_mod}):
            output = publish_content("vid.mp4", "My Title", platforms=["youtube", "tiktok"])

        assert len(output) == 2
        assert output[0]["platform"] == "youtube"
        assert output[1]["platform"] == "tiktok"

    # ------------------------------------------------------------------
    # 10. Job is constructed with correct keyword arguments
    # ------------------------------------------------------------------
    def test_publish_passes_job_params(self):
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish.return_value = []

        mock_publisher_mod = MagicMock()
        mock_publisher_mod.ContentPublisher.return_value = mock_publisher_instance
        # Capture the PublishJob constructor call
        mock_job_cls = MagicMock()
        mock_publisher_mod.PublishJob = mock_job_cls

        with patch.dict(sys.modules, {"publisher": mock_publisher_mod}):
            publish_content(
                "clip.mp4",
                "Title Here",
                description="Some description",
                platforms=["youtube", "instagram"],
            )

        mock_job_cls.assert_called_once_with(
            video_path="clip.mp4",
            title="Title Here",
            description="Some description",
            platforms=["youtube", "instagram"],
        )

    # ------------------------------------------------------------------
    # 11. Results that are objects (have __dict__) get serialised
    # ------------------------------------------------------------------
    def test_publish_object_results_serialised(self):
        obj_result = _make_publish_result_obj("youtube", True)
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish.return_value = [obj_result]

        mock_publisher_mod = MagicMock()
        mock_publisher_mod.ContentPublisher.return_value = mock_publisher_instance
        mock_publisher_mod.PublishJob = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {"publisher": mock_publisher_mod}):
            output = publish_content("vid.mp4", "T")

        assert isinstance(output[0], dict)
        assert output[0]["platform"] == "youtube"

    # ------------------------------------------------------------------
    # 12. Results that are neither dict nor have __dict__ → {"raw": ...}
    # ------------------------------------------------------------------
    def test_publish_raw_fallback_for_unknown_result_type(self):
        mock_publisher_instance = MagicMock()
        # Return a plain string as a result item (no __dict__, not a dict)
        mock_publisher_instance.publish.return_value = ["ok"]

        mock_publisher_mod = MagicMock()
        mock_publisher_mod.ContentPublisher.return_value = mock_publisher_instance
        mock_publisher_mod.PublishJob = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {"publisher": mock_publisher_mod}):
            output = publish_content("vid.mp4", "T")

        assert output[0] == {"raw": "ok"}

    # ------------------------------------------------------------------
    # 13. ValueError → error dict
    # ------------------------------------------------------------------
    def test_publish_value_error(self):
        mock_publisher_mod = MagicMock()
        mock_publisher_mod.PublishJob.side_effect = ValueError("empty title")

        with patch.dict(sys.modules, {"publisher": mock_publisher_mod}):
            output = publish_content("vid.mp4", "")

        assert output[0]["error"] == "ValueError"
        assert "empty title" in output[0]["message"]

    # ------------------------------------------------------------------
    # 14. Unexpected exception → error dict
    # ------------------------------------------------------------------
    def test_publish_unexpected_error(self):
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish.side_effect = ConnectionError("upload failed")

        mock_publisher_mod = MagicMock()
        mock_publisher_mod.ContentPublisher.return_value = mock_publisher_instance
        mock_publisher_mod.PublishJob = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {"publisher": mock_publisher_mod}):
            output = publish_content("vid.mp4", "Title")

        assert output[0]["error"] == "ConnectionError"
        assert "upload failed" in output[0]["message"]

    # ------------------------------------------------------------------
    # 15. Default platforms is ["youtube"]
    # ------------------------------------------------------------------
    def test_publish_default_platforms(self):
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish.return_value = []

        mock_publisher_mod = MagicMock()
        mock_publisher_mod.ContentPublisher.return_value = mock_publisher_instance
        mock_job_cls = MagicMock()
        mock_publisher_mod.PublishJob = mock_job_cls

        with patch.dict(sys.modules, {"publisher": mock_publisher_mod}):
            publish_content("vid.mp4", "Title")

        _, kwargs = mock_job_cls.call_args
        assert kwargs["platforms"] == ["youtube"]


# ===========================================================================
# schedule_content
# ===========================================================================

class TestScheduleContent:
    """Tests for the schedule_content MCP tool."""

    def _mock_scheduler_mod(self, job_id="job-abc-123", suggest_return="2026-04-01T10:00:00",
                             best_time_return=None):
        """Build a sys.modules stub for content_scheduler."""
        mod = MagicMock()

        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.add_job.return_value = job_id
        mod.ContentScheduler.return_value = mock_scheduler_instance

        mock_job_cls = MagicMock()
        mod.ScheduledJob = mock_job_cls

        mod.suggest_next_optimal_time.return_value = suggest_return
        if best_time_return is not None:
            mod.get_best_posting_time.return_value = best_time_return
        else:
            mod.get_best_posting_time.return_value = {"peak_hour": 10, "peak_day": "Tuesday"}

        return mod

    # ------------------------------------------------------------------
    # 16. Explicit scheduled_time is passed straight through
    # ------------------------------------------------------------------
    def test_schedule_with_explicit_time(self):
        mod = self._mock_scheduler_mod(job_id="j-001")

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content(
                "vid.mp4", "Title", ["youtube"],
                scheduled_time="2026-05-01T12:00:00",
            )

        assert result["status"] == "scheduled"
        assert result["scheduled_time"] == "2026-05-01T12:00:00"
        # suggest_next_optimal_time must NOT have been called
        mod.suggest_next_optimal_time.assert_not_called()

    # ------------------------------------------------------------------
    # 17. Empty scheduled_time triggers auto-pick via suggest_next_optimal_time
    # ------------------------------------------------------------------
    def test_schedule_auto_pick_optimal(self):
        mod = self._mock_scheduler_mod(suggest_return="2026-04-01T10:00:00")

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content("vid.mp4", "Title", ["youtube"], scheduled_time="")

        mod.suggest_next_optimal_time.assert_called_once_with("youtube")
        assert result["scheduled_time"] == "2026-04-01T10:00:00"

    # ------------------------------------------------------------------
    # 18. Result dict contains required keys including job_id
    # ------------------------------------------------------------------
    def test_schedule_returns_job_id(self):
        mod = self._mock_scheduler_mod(job_id="job-xyz-789")

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content(
                "vid.mp4", "My Show", ["youtube", "tiktok"],
                scheduled_time="2026-04-01T18:00:00",
            )

        assert result["job_id"] == "job-xyz-789"
        assert result["status"] == "scheduled"
        assert result["title"] == "My Show"
        assert result["platforms"] == ["youtube", "tiktok"]

    # ------------------------------------------------------------------
    # 19. repeat_interval_hours is forwarded to ScheduledJob
    # ------------------------------------------------------------------
    def test_schedule_with_repeat(self):
        mod = self._mock_scheduler_mod()

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content(
                "vid.mp4", "Daily Post", ["twitter"],
                scheduled_time="2026-04-01T09:00:00",
                repeat_interval_hours=24,
            )

        assert result["repeat_interval_hours"] == 24
        _, kwargs = mod.ScheduledJob.call_args
        assert kwargs["repeat_interval_hours"] == 24

    # ------------------------------------------------------------------
    # 20. Auto-pick includes best_time_info in result
    # ------------------------------------------------------------------
    def test_schedule_auto_pick_includes_best_time_info(self):
        best = {"peak_hour": 18, "peak_day": "Friday"}
        mod = self._mock_scheduler_mod(
            suggest_return="2026-04-04T18:00:00",
            best_time_return=best,
        )

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content("vid.mp4", "T", ["youtube"], scheduled_time="")

        assert "best_time_info" in result
        assert result["best_time_info"]["auto_selected"] is True
        assert result["best_time_info"]["suggested_iso"] == "2026-04-04T18:00:00"
        assert result["best_time_info"]["peak_hour"] == 18

    # ------------------------------------------------------------------
    # 21. ValueError → error dict
    # ------------------------------------------------------------------
    def test_schedule_value_error(self):
        mod = MagicMock()
        mod.ScheduledJob.side_effect = ValueError("empty video_path")

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content("", "T", ["youtube"])

        assert result["error"] == "ValueError"
        assert "empty video_path" in result["message"]

    # ------------------------------------------------------------------
    # 22. Unexpected exception → error dict
    # ------------------------------------------------------------------
    def test_schedule_unexpected_error(self):
        mod = self._mock_scheduler_mod()
        mod.ContentScheduler.return_value.add_job.side_effect = IOError("disk full")

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content(
                "vid.mp4", "T", ["youtube"],
                scheduled_time="2026-04-01T10:00:00",
            )

        assert result["error"] == "OSError"
        assert "disk full" in result["message"]

    # ------------------------------------------------------------------
    # 23. Inner get_best_posting_time failure is silently swallowed
    # ------------------------------------------------------------------
    def test_schedule_auto_pick_best_time_info_failure(self):
        mod = self._mock_scheduler_mod()
        mod.get_best_posting_time.side_effect = RuntimeError("no analytics data")

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            result = schedule_content("vid.mp4", "T", ["youtube"], scheduled_time="")

        # The job should still be scheduled successfully
        assert result["status"] == "scheduled"
        # best_time_info should be absent (inner exception was swallowed)
        assert "best_time_info" not in result

    # ------------------------------------------------------------------
    # 24. ScheduledJob gets the description kwarg
    # ------------------------------------------------------------------
    def test_schedule_passes_description(self):
        mod = self._mock_scheduler_mod()

        with patch.dict(sys.modules, {"content_scheduler": mod}):
            schedule_content(
                "vid.mp4", "T", ["youtube"],
                scheduled_time="2026-04-01T10:00:00",
                description="A very long description",
            )

        _, kwargs = mod.ScheduledJob.call_args
        assert kwargs["description"] == "A very long description"


# ===========================================================================
# get_analytics
# ===========================================================================

class TestGetAnalytics:
    """Tests for the get_analytics MCP tool."""

    def _mock_analytics_mod(self, report_dict=None, platform_dict=None):
        """Build a sys.modules stub for analytics_report."""
        mod = MagicMock()

        if report_dict is None:
            report_dict = {
                "generated_at": "2026-03-28T00:00:00Z",
                "total_events": 42,
                "platforms": {"youtube": {}, "tiktok": {}},
                "overall_success_rate": 0.95,
                "busiest_platform": "youtube",
                "most_active_day": "Monday",
                "event_type_distribution": {},
                "daily_trend": [],
                "recommendations": [],
            }
        if platform_dict is None:
            platform_dict = {
                "platform": "youtube",
                "total_events": 20,
                "successful_uploads": 19,
                "failed_uploads": 1,
                "success_rate": 0.95,
                "events_by_type": {},
                "avg_events_per_day": 2.5,
                "peak_day": "Monday",
                "peak_day_count": 5,
                "most_common_error": None,
                "recent_trend": [],
            }

        mock_report = MagicMock()
        mock_report.to_dict.return_value = report_dict
        mod.generate_report.return_value = mock_report

        mock_platform_stats = MagicMock()
        mock_platform_stats.to_dict.return_value = platform_dict
        mod.get_platform_report.return_value = mock_platform_stats

        return mod

    # ------------------------------------------------------------------
    # 25. Empty platform → cross-platform report via generate_report
    # ------------------------------------------------------------------
    def test_analytics_cross_platform(self):
        mod = self._mock_analytics_mod()

        with patch.dict(sys.modules, {"analytics_report": mod}):
            result = get_analytics(platform="")

        mod.generate_report.assert_called_once()
        mod.get_platform_report.assert_not_called()
        assert result["total_events"] == 42
        assert "platforms" in result

    # ------------------------------------------------------------------
    # 26. Specific platform → get_platform_report with lowercased name
    # ------------------------------------------------------------------
    def test_analytics_single_platform(self):
        mod = self._mock_analytics_mod()

        with patch.dict(sys.modules, {"analytics_report": mod}):
            result = get_analytics(platform="YouTube")

        mod.get_platform_report.assert_called_once_with("youtube")
        mod.generate_report.assert_not_called()
        assert result["platform"] == "youtube"

    # ------------------------------------------------------------------
    # 27. max_events > 0 is forwarded to generate_report
    # ------------------------------------------------------------------
    def test_analytics_max_events(self):
        mod = self._mock_analytics_mod()

        with patch.dict(sys.modules, {"analytics_report": mod}):
            get_analytics(platform="", max_events=100)

        mod.generate_report.assert_called_once_with(max_events=100)

    # ------------------------------------------------------------------
    # 28. max_events == 0 → generate_report called without kwargs
    # ------------------------------------------------------------------
    def test_analytics_zero_max_events_omits_kwarg(self):
        mod = self._mock_analytics_mod()

        with patch.dict(sys.modules, {"analytics_report": mod}):
            get_analytics(platform="", max_events=0)

        mod.generate_report.assert_called_once_with()

    # ------------------------------------------------------------------
    # 29. ValueError → error dict
    # ------------------------------------------------------------------
    def test_analytics_value_error(self):
        mod = MagicMock()
        mod.get_platform_report.side_effect = ValueError("unknown platform")

        with patch.dict(sys.modules, {"analytics_report": mod}):
            result = get_analytics(platform="unknown_platform_xyz")

        assert result["error"] == "ValueError"
        assert "unknown platform" in result["message"]

    # ------------------------------------------------------------------
    # 30. Unexpected exception → error dict
    # ------------------------------------------------------------------
    def test_analytics_unexpected_error(self):
        mod = MagicMock()
        mod.generate_report.side_effect = PermissionError("access denied")

        with patch.dict(sys.modules, {"analytics_report": mod}):
            result = get_analytics(platform="")

        assert result["error"] == "PermissionError"
        assert "access denied" in result["message"]

    # ------------------------------------------------------------------
    # 31. generate_report result is fully forwarded
    # ------------------------------------------------------------------
    def test_analytics_full_report_structure(self):
        full_report = {
            "generated_at": "2026-03-28T00:00:00Z",
            "total_events": 150,
            "platforms": {"youtube": {"total_events": 100}, "tiktok": {"total_events": 50}},
            "overall_success_rate": 0.98,
            "busiest_platform": "youtube",
            "most_active_day": "Thursday",
            "event_type_distribution": {"upload": 140, "error": 10},
            "daily_trend": [{"date": "2026-03-27", "count": 20}],
            "recommendations": ["Post more on Fridays"],
        }
        mod = self._mock_analytics_mod(report_dict=full_report)

        with patch.dict(sys.modules, {"analytics_report": mod}):
            result = get_analytics()

        for key in full_report:
            assert result[key] == full_report[key]

    # ------------------------------------------------------------------
    # 32. platform kwarg is stripped to lowercase before forwarding
    # ------------------------------------------------------------------
    def test_analytics_platform_lowercased(self):
        mod = self._mock_analytics_mod()

        with patch.dict(sys.modules, {"analytics_report": mod}):
            get_analytics(platform="TikTok")

        mod.get_platform_report.assert_called_once_with("tiktok")


# ---------------------------------------------------------------------------
# Module-level cleanup — restore fastmcp in sys.modules to whatever it was
# before this file injected the mock, so later test files are not polluted.
# ---------------------------------------------------------------------------
import atexit as _atexit


def _cleanup_mcp_server_mocks():
    if _MCP_SERVER_PREV_FASTMCP is None:
        sys.modules.pop("fastmcp", None)
    else:
        sys.modules["fastmcp"] = _MCP_SERVER_PREV_FASTMCP


_atexit.register(_cleanup_mcp_server_mocks)

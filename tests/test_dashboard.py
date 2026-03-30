"""
Tests for the web dashboard module (src/dashboard.py).
"""

import os
import sys
import json
import asyncio
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import dashboard


# ---------------------------------------------------------------------------
# Helper data
# ---------------------------------------------------------------------------

SAMPLE_ANALYTICS = {
    "events": [
        {"timestamp": "2026-03-28T10:00:00", "type": "video_generated", "platform": "youtube", "details": {}},
        {"timestamp": "2026-03-28T10:05:00", "type": "video_uploaded", "platform": "youtube", "details": {}},
        {"timestamp": "2026-03-28T11:00:00", "type": "tweet_posted", "platform": "twitter", "details": {}},
    ],
    "summary": {
        "youtube": {"video_generated": 1, "video_uploaded": 1, "total_events": 2},
        "twitter": {"tweet_posted": 1, "total_events": 1},
    },
}

SAMPLE_ACCOUNTS = {
    "youtube": {"accounts": [{"id": "yt1", "nickname": "TestYT"}]},
    "twitter": {"accounts": [{"id": "tw1", "nickname": "TestTW"}, {"id": "tw2", "nickname": "TestTW2"}]},
    "instagram": {"accounts": []},
}

SAMPLE_JOBS = {
    "jobs": [
        {"title": "Test Video", "platform": "youtube", "status": "completed", "scheduled_time": "2026-03-28T10:00:00"},
        {"title": "Test Tweet", "platform": "twitter", "status": "pending", "scheduled_time": "2026-03-28T12:00:00"},
    ]
}


# ---------------------------------------------------------------------------
# Unit tests: _load_analytics_data
# ---------------------------------------------------------------------------

class TestLoadAnalyticsData:
    def test_returns_empty_on_missing_file(self, tmp_path):
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_analytics_data()
        assert result == {"events": [], "summary": {}}

    def test_loads_valid_data(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_analytics_data()
        assert len(result["events"]) == 3
        assert "youtube" in result["summary"]

    def test_handles_corrupt_json(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text("not json{{{")
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_analytics_data()
        assert result == {"events": [], "summary": {}}


# ---------------------------------------------------------------------------
# Unit tests: _load_accounts_summary
# ---------------------------------------------------------------------------

class TestLoadAccountsSummary:
    def test_returns_zeros_on_missing_files(self, tmp_path):
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_accounts_summary()
        assert result == {"youtube": 0, "twitter": 0, "instagram": 0}

    def test_counts_accounts_correctly(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        for platform, data in SAMPLE_ACCOUNTS.items():
            (mp_dir / f"{platform}.json").write_text(json.dumps(data))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_accounts_summary()
        assert result["youtube"] == 1
        assert result["twitter"] == 2
        assert result["instagram"] == 0


# ---------------------------------------------------------------------------
# Unit tests: _load_scheduled_jobs
# ---------------------------------------------------------------------------

class TestLoadScheduledJobs:
    def test_returns_empty_on_missing_file(self, tmp_path):
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_scheduled_jobs()
        assert result == []

    def test_loads_jobs(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(SAMPLE_JOBS))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_scheduled_jobs()
        assert len(result) == 2
        assert result[0]["title"] == "Test Video"

    def test_limits_to_50_jobs(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        many_jobs = {"jobs": [{"title": f"Job {i}", "status": "completed"} for i in range(100)]}
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(many_jobs))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_scheduled_jobs()
        assert len(result) == 50


# ---------------------------------------------------------------------------
# Unit tests: _get_health_info
# ---------------------------------------------------------------------------

class TestGetHealthInfo:
    def test_returns_health_dict(self, tmp_path):
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch.dict(sys.modules, {"ollama": MagicMock()}):
                result = dashboard._get_health_info()
        assert result["status"] == "healthy"
        assert "disk_free_gb" in result
        assert "disk_total_gb" in result
        assert "timestamp" in result

    def test_ollama_offline(self, tmp_path):
        mock_ollama = MagicMock()
        mock_ollama.list.side_effect = Exception("Connection refused")
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch.dict(sys.modules, {"ollama": mock_ollama}):
                result = dashboard._get_health_info()
        assert result["ollama_status"] == "offline"

    def test_cache_size_calculation(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "test.json").write_text("x" * (1024 * 1024))  # 1MB file
        mock_ollama = MagicMock()
        mock_ollama.list.return_value = []
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch.dict(sys.modules, {"ollama": mock_ollama}):
                result = dashboard._get_health_info()
        assert result["cache_size_mb"] >= 1.0


# ---------------------------------------------------------------------------
# Unit tests: FastAPI app routes
# ---------------------------------------------------------------------------

class TestFastAPIApp:
    @pytest.fixture
    def client(self, tmp_path):
        """Create a test client for the FastAPI app."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))
        for platform, data in SAMPLE_ACCOUNTS.items():
            (mp_dir / f"{platform}.json").write_text(json.dumps(data))
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(SAMPLE_JOBS))

        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_health_endpoint(self, client):
        with patch.dict(sys.modules, {"ollama": MagicMock()}):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_jobs_endpoint(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "accounts" in data
        assert data["total_jobs"] == 2

    def test_analytics_endpoint(self, client):
        resp = client.get("/api/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 3
        assert "youtube" in data["summary"]

    def test_dashboard_page_renders(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "MoneyPrinter Dashboard" in resp.text
        assert "htmx" in resp.text

    def test_sse_stream_endpoint_headers(self, tmp_path):
        """Test SSE endpoint returns correct content type."""
        from starlette.testclient import TestClient

        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))

        # Create app that yields one event then stops
        call_count = 0

        async def mock_sleep(_seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError()

        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch("dashboard.asyncio") as mock_asyncio:
                mock_asyncio.sleep = mock_sleep
                mock_asyncio.CancelledError = asyncio.CancelledError
                app = dashboard.create_app()
                client = TestClient(app)
                resp = client.get("/api/stream")
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Unit tests: Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:
    @pytest.fixture
    def empty_client(self, tmp_path):
        from starlette.testclient import TestClient
        (tmp_path / ".mp").mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_analytics_empty(self, empty_client):
        resp = empty_client.get("/api/analytics")
        assert resp.status_code == 200
        assert resp.json()["total_events"] == 0

    def test_jobs_empty(self, empty_client):
        resp = empty_client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.json()["total_jobs"] == 0

    def test_dashboard_renders_empty(self, empty_client):
        resp = empty_client.get("/dashboard")
        assert resp.status_code == 200
        assert "No analytics data" in resp.text or "No scheduled jobs" in resp.text


# ---------------------------------------------------------------------------
# Unit tests: create_app and run_dashboard
# ---------------------------------------------------------------------------

class TestAppCreation:
    def test_create_app_returns_fastapi_instance(self):
        from fastapi import FastAPI
        app = dashboard.create_app()
        assert isinstance(app, FastAPI)
        assert app.title == "MoneyPrinter Dashboard"

    def test_app_has_all_routes(self):
        app = dashboard.create_app()
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/dashboard" in routes
        assert "/api/health" in routes
        assert "/api/jobs" in routes
        assert "/api/analytics" in routes
        assert "/api/stream" in routes

    def test_default_port(self):
        assert dashboard.DEFAULT_PORT == 8765


# ---------------------------------------------------------------------------
# Unit tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_analytics_null_json(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text("null")
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_analytics_data()
        assert result == {"events": [], "summary": {}}

    def test_accounts_null_json(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "youtube.json").write_text("null")
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_accounts_summary()
        assert result["youtube"] == 0

    def test_jobs_null_json(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "scheduler_jobs.json").write_text("null")
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_scheduled_jobs()
        assert result == []

    def test_get_root_dir_fallback(self):
        with patch.dict(sys.modules, {"config": None}):
            result = dashboard._get_root_dir()
        # Should return a valid path even without config module
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Unit tests: Calendar helpers (_load_schedule_data, _save_schedule_data, _job_to_calendar_event)
# ---------------------------------------------------------------------------

SAMPLE_SCHEDULE_JOBS = [
    {
        "job_id": "abc12345",
        "title": "My YT Short",
        "platforms": ["youtube"],
        "scheduled_time": "2026-03-28T10:00:00",
        "status": "pending",
        "video_path": "/tmp/video.mp4",
    },
    {
        "job_id": "def67890",
        "title": "TikTok Post",
        "platforms": ["tiktok"],
        "scheduled_time": "2026-03-29T14:00:00",
        "status": "completed",
        "video_path": "/tmp/tiktok.mp4",
    },
    {
        "job_id": "ghi11111",
        "title": "Multi-Platform",
        "platforms": ["youtube", "instagram"],
        "scheduled_time": "2026-04-01T09:00:00",
        "status": "pending",
        "video_path": "",
    },
]


class TestLoadScheduleData:
    def test_returns_empty_on_missing_file(self, tmp_path):
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_schedule_data()
        assert result == []

    def test_loads_schedule_jobs(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "schedule.json").write_text(json.dumps({"jobs": SAMPLE_SCHEDULE_JOBS}))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_schedule_data()
        assert len(result) == 3
        assert result[0]["job_id"] == "abc12345"

    def test_handles_corrupt_json(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "schedule.json").write_text("{bad json!")
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_schedule_data()
        assert result == []

    def test_handles_non_dict_json(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "schedule.json").write_text('"just a string"')
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            result = dashboard._load_schedule_data()
        assert result == []


class TestSaveScheduleData:
    def test_saves_and_reads_back(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            dashboard._save_schedule_data(SAMPLE_SCHEDULE_JOBS)
            result = dashboard._load_schedule_data()
        assert len(result) == 3
        assert result[0]["title"] == "My YT Short"

    def test_creates_mp_dir_if_missing(self, tmp_path):
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            dashboard._save_schedule_data([{"title": "test"}])
        assert (tmp_path / ".mp" / "schedule.json").exists()

    def test_atomic_write_produces_valid_json(self, tmp_path):
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            dashboard._save_schedule_data(SAMPLE_SCHEDULE_JOBS)
        raw = json.loads((mp_dir / "schedule.json").read_text())
        assert "jobs" in raw
        assert len(raw["jobs"]) == 3


class TestJobToCalendarEvent:
    def test_youtube_color(self):
        event = dashboard._job_to_calendar_event(SAMPLE_SCHEDULE_JOBS[0])
        assert event["color"] == "#ff0000"
        assert event["id"] == "abc12345"
        assert event["title"] == "My YT Short"
        assert event["start"] == "2026-03-28T10:00:00"

    def test_tiktok_color(self):
        event = dashboard._job_to_calendar_event(SAMPLE_SCHEDULE_JOBS[1])
        assert event["color"] == "#00f2ea"

    def test_multi_platform_uses_first(self):
        event = dashboard._job_to_calendar_event(SAMPLE_SCHEDULE_JOBS[2])
        assert event["color"] == "#ff0000"  # youtube is first
        assert event["extendedProps"]["platforms"] == ["youtube", "instagram"]

    def test_unknown_platform_default_color(self):
        event = dashboard._job_to_calendar_event({"platforms": [], "title": "X"})
        assert event["color"] == "#64748b"

    def test_extended_props(self):
        event = dashboard._job_to_calendar_event(SAMPLE_SCHEDULE_JOBS[0])
        assert event["extendedProps"]["status"] == "pending"
        assert event["extendedProps"]["video_path"] == "/tmp/video.mp4"
        assert event["extendedProps"]["platforms"] == ["youtube"]


# ---------------------------------------------------------------------------
# Unit tests: Calendar API endpoints
# ---------------------------------------------------------------------------

class TestCalendarAPI:
    @pytest.fixture
    def cal_client(self, tmp_path):
        """Create a test client with schedule data."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "schedule.json").write_text(json.dumps({"jobs": SAMPLE_SCHEDULE_JOBS}))
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))
        for platform, data in SAMPLE_ACCOUNTS.items():
            (mp_dir / f"{platform}.json").write_text(json.dumps(data))
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(SAMPLE_JOBS))

        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_calendar_page_renders(self, cal_client):
        resp = cal_client.get("/calendar")
        assert resp.status_code == 200
        assert "fullcalendar" in resp.text.lower() or "FullCalendar" in resp.text or "calendar" in resp.text.lower()

    def test_calendar_events_returns_json(self, cal_client):
        resp = cal_client.get("/api/calendar/events")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_calendar_events_format(self, cal_client):
        resp = cal_client.get("/api/calendar/events")
        data = resp.json()
        event = data[0]
        assert "id" in event
        assert "title" in event
        assert "start" in event
        assert "color" in event
        assert "extendedProps" in event

    def test_calendar_events_date_filter(self, cal_client):
        resp = cal_client.get("/api/calendar/events?start=2026-03-29T00:00:00&end=2026-03-30T00:00:00")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "TikTok Post"

    def test_calendar_events_empty_when_no_schedule(self, tmp_path):
        from starlette.testclient import TestClient
        (tmp_path / ".mp").mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            client = TestClient(app)
            resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_event(self, cal_client):
        resp = cal_client.post("/api/calendar/events", json={
            "title": "New Video",
            "platforms": ["instagram"],
            "scheduled_time": "2026-04-05T12:00:00",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "New Video"
        assert data["color"] == "#e1306c"
        assert data["id"]  # has a job_id

    def test_create_event_missing_title(self, cal_client):
        resp = cal_client.post("/api/calendar/events", json={
            "platforms": ["youtube"],
            "scheduled_time": "2026-04-05T12:00:00",
        })
        assert resp.status_code == 422
        assert "title" in resp.json()["error"]

    def test_create_event_missing_platforms(self, cal_client):
        resp = cal_client.post("/api/calendar/events", json={
            "title": "Test",
            "scheduled_time": "2026-04-05T12:00:00",
        })
        assert resp.status_code == 422
        assert "platforms" in resp.json()["error"]

    def test_create_event_missing_scheduled_time(self, cal_client):
        resp = cal_client.post("/api/calendar/events", json={
            "title": "Test",
            "platforms": ["youtube"],
        })
        assert resp.status_code == 422
        assert "scheduled_time" in resp.json()["error"]

    def test_create_event_persists(self, cal_client):
        cal_client.post("/api/calendar/events", json={
            "title": "Persisted",
            "platforms": ["twitter"],
            "scheduled_time": "2026-04-10T08:00:00",
        })
        resp = cal_client.get("/api/calendar/events")
        titles = [e["title"] for e in resp.json()]
        assert "Persisted" in titles

    def test_create_event_string_platforms(self, cal_client):
        resp = cal_client.post("/api/calendar/events", json={
            "title": "Single Platform",
            "platforms": "youtube",
            "scheduled_time": "2026-04-05T12:00:00",
        })
        assert resp.status_code == 201
        assert resp.json()["extendedProps"]["platforms"] == ["youtube"]

    def test_delete_event(self, cal_client):
        resp = cal_client.delete("/api/calendar/events/abc12345")
        assert resp.status_code == 204
        # Verify deleted
        events_resp = cal_client.get("/api/calendar/events")
        ids = [e["id"] for e in events_resp.json()]
        assert "abc12345" not in ids

    def test_delete_nonexistent_event(self, cal_client):
        resp = cal_client.delete("/api/calendar/events/nonexistent")
        assert resp.status_code == 404

    def test_create_event_invalid_json(self, cal_client):
        resp = cal_client.post(
            "/api/calendar/events",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Unit tests: Chart data endpoint
# ---------------------------------------------------------------------------

class TestChartDataAPI:
    @pytest.fixture
    def chart_client(self, tmp_path):
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))
        jobs_data = {
            "jobs": [
                {"title": "V1", "platforms": ["youtube"], "status": "completed", "scheduled_time": "2026-03-28T10:00:00"},
                {"title": "V2", "platforms": ["youtube"], "status": "completed", "scheduled_time": "2026-03-28T14:00:00"},
                {"title": "T1", "platforms": ["tiktok"], "status": "failed", "scheduled_time": "2026-03-27T09:00:00"},
                {"title": "I1", "platforms": ["instagram", "twitter"], "status": "pending", "scheduled_time": "2026-03-29T11:00:00"},
            ]
        }
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(jobs_data))
        for platform, data in SAMPLE_ACCOUNTS.items():
            (mp_dir / f"{platform}.json").write_text(json.dumps(data))

        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_chart_data_returns_200(self, chart_client):
        resp = chart_client.get("/api/analytics/chart-data")
        assert resp.status_code == 200

    def test_chart_data_structure(self, chart_client):
        data = chart_client.get("/api/analytics/chart-data").json()
        assert "jobs_over_time" in data
        assert "platform_counts" in data
        assert "status_counts" in data

    def test_chart_data_jobs_over_time(self, chart_client):
        data = chart_client.get("/api/analytics/chart-data").json()
        dates = {d["date"] for d in data["jobs_over_time"]}
        assert "2026-03-28" in dates
        assert "2026-03-27" in dates
        # March 28 has 2 jobs
        for item in data["jobs_over_time"]:
            if item["date"] == "2026-03-28":
                assert item["count"] == 2

    def test_chart_data_platform_counts(self, chart_client):
        data = chart_client.get("/api/analytics/chart-data").json()
        assert data["platform_counts"]["youtube"] == 2
        assert data["platform_counts"]["tiktok"] == 1
        assert data["platform_counts"]["instagram"] == 1
        assert data["platform_counts"]["twitter"] == 1

    def test_chart_data_status_counts(self, chart_client):
        data = chart_client.get("/api/analytics/chart-data").json()
        assert data["status_counts"]["completed"] == 2
        assert data["status_counts"]["failed"] == 1
        assert data["status_counts"]["pending"] == 1

    def test_chart_data_empty(self, tmp_path):
        from starlette.testclient import TestClient
        (tmp_path / ".mp").mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            client = TestClient(app)
            data = client.get("/api/analytics/chart-data").json()
        assert data["jobs_over_time"] == []
        assert data["platform_counts"] == {}
        assert data["status_counts"] == {}

    def test_chart_data_string_platform(self, tmp_path):
        """Test that string platforms (not list) are handled."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        jobs_data = {"jobs": [
            {"title": "X", "platforms": "youtube", "status": "completed", "scheduled_time": "2026-03-28T10:00:00"},
        ]}
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(jobs_data))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            client = TestClient(app)
            data = client.get("/api/analytics/chart-data").json()
        assert data["platform_counts"]["youtube"] == 1


# ---------------------------------------------------------------------------
# Unit tests: Route registration includes new endpoints
# ---------------------------------------------------------------------------

class TestRouteRegistration:
    def test_app_has_calendar_routes(self):
        app = dashboard.create_app()
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/calendar" in routes
        assert "/api/calendar/events" in routes
        assert "/api/calendar/events/{job_id}" in routes
        assert "/api/analytics/chart-data" in routes

    def test_dashboard_has_calendar_link(self, tmp_path):
        """Dashboard should have a navigation link to calendar."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))
        for platform, data in SAMPLE_ACCOUNTS.items():
            (mp_dir / f"{platform}.json").write_text(json.dumps(data))
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(SAMPLE_JOBS))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            client = TestClient(app)
            resp = client.get("/dashboard")
        assert "/calendar" in resp.text

    def test_dashboard_has_chart_js(self, tmp_path):
        """Dashboard template should include Chart.js CDN."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))
        for platform, data in SAMPLE_ACCOUNTS.items():
            (mp_dir / f"{platform}.json").write_text(json.dumps(data))
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(SAMPLE_JOBS))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            client = TestClient(app)
            resp = client.get("/dashboard")
        assert "chart.js" in resp.text.lower() or "Chart" in resp.text


# ---------------------------------------------------------------------------
# Unit tests: PATCH /api/calendar/events/{job_id} (drag-and-drop rescheduling)
# ---------------------------------------------------------------------------

class TestCalendarPatchAPI:
    @pytest.fixture
    def patch_client(self, tmp_path):
        """Create a test client with schedule data for PATCH tests."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "schedule.json").write_text(json.dumps({"jobs": SAMPLE_SCHEDULE_JOBS}))
        (mp_dir / "analytics.json").write_text(json.dumps(SAMPLE_ANALYTICS))
        for platform, data in SAMPLE_ACCOUNTS.items():
            (mp_dir / f"{platform}.json").write_text(json.dumps(data))
        (mp_dir / "scheduler_jobs.json").write_text(json.dumps(SAMPLE_JOBS))

        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    # 1. PATCH with valid scheduled_time → 200 + updated event
    def test_patch_valid_scheduled_time(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/abc12345",
            json={"scheduled_time": "2026-05-01T10:00:00"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "abc12345"
        assert data["start"] == "2026-05-01T10:00:00"

    # 2. PATCH with invalid JSON → 400
    def test_patch_invalid_json(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/abc12345",
            content=b"not json{{",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]

    # 3. PATCH with missing scheduled_time field → 422
    def test_patch_missing_scheduled_time(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/abc12345",
            json={"title": "Some other field"},
        )
        assert resp.status_code == 422
        assert "scheduled_time" in resp.json()["error"]

    # 4. PATCH with empty scheduled_time string → 422
    def test_patch_empty_scheduled_time(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/abc12345",
            json={"scheduled_time": ""},
        )
        assert resp.status_code == 422
        assert "scheduled_time" in resp.json()["error"]

    # 5. PATCH with non-existent job_id → 404
    def test_patch_nonexistent_job_id(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/doesnotexist",
            json={"scheduled_time": "2026-05-01T10:00:00"},
        )
        assert resp.status_code == 404
        assert "doesnotexist" in resp.json()["error"]

    # 6. PATCH updates the correct job in schedule.json
    def test_patch_updates_correct_job(self, tmp_path):
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "schedule.json").write_text(json.dumps({"jobs": SAMPLE_SCHEDULE_JOBS}))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            client = TestClient(app)
            client.patch(
                "/api/calendar/events/def67890",
                json={"scheduled_time": "2026-06-15T08:30:00"},
            )
            # Read back from disk
            result = dashboard._load_schedule_data()
        job_map = {j["job_id"]: j for j in result}
        # Target job updated
        assert job_map["def67890"]["scheduled_time"] == "2026-06-15T08:30:00"
        # Other jobs untouched
        assert job_map["abc12345"]["scheduled_time"] == "2026-03-28T10:00:00"
        assert job_map["ghi11111"]["scheduled_time"] == "2026-04-01T09:00:00"

    # 7. PATCH returns FullCalendar event format
    def test_patch_returns_fullcalendar_format(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/abc12345",
            json={"scheduled_time": "2026-07-04T12:00:00"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "title" in data
        assert "start" in data
        assert "color" in data
        assert "extendedProps" in data
        assert "platforms" in data["extendedProps"]
        assert "status" in data["extendedProps"]

    # 8. PATCH with extra fields (should ignore them, only update scheduled_time)
    def test_patch_ignores_extra_fields(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/abc12345",
            json={
                "scheduled_time": "2026-08-01T09:00:00",
                "title": "Hacked Title",
                "platforms": ["tiktok"],
                "status": "completed",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # scheduled_time updated
        assert data["start"] == "2026-08-01T09:00:00"
        # title and platforms not changed by PATCH
        assert data["title"] == "My YT Short"
        assert "youtube" in data["extendedProps"]["platforms"]

    # 9. Drag-and-drop scenario: create → patch → verify time changed
    def test_drag_and_drop_scenario(self, tmp_path):
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        (mp_dir / "schedule.json").write_text(json.dumps({"jobs": []}))
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            client = TestClient(app)

            # Step 1: Create
            create_resp = client.post("/api/calendar/events", json={
                "title": "Drag Test",
                "platforms": ["twitter"],
                "scheduled_time": "2026-04-10T10:00:00",
            })
            assert create_resp.status_code == 201
            job_id = create_resp.json()["id"]

            # Step 2: Simulate drag — PATCH to new time
            patch_resp = client.patch(
                f"/api/calendar/events/{job_id}",
                json={"scheduled_time": "2026-04-12T15:00:00"},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["start"] == "2026-04-12T15:00:00"

            # Step 3: Verify via GET
            events_resp = client.get("/api/calendar/events")
            event = next(e for e in events_resp.json() if e["id"] == job_id)
            assert event["start"] == "2026-04-12T15:00:00"

    # 10. Multiple PATCHes to same job — last one wins
    def test_multiple_patches_same_job(self, patch_client):
        times = [
            "2026-05-01T08:00:00",
            "2026-05-02T09:00:00",
            "2026-05-03T10:00:00",
        ]
        for t in times:
            resp = patch_client.patch(
                "/api/calendar/events/abc12345",
                json={"scheduled_time": t},
            )
            assert resp.status_code == 200

        # Final state should reflect the last patch
        events_resp = patch_client.get("/api/calendar/events")
        event = next(e for e in events_resp.json() if e["id"] == "abc12345")
        assert event["start"] == "2026-05-03T10:00:00"

    # 11. PATCH route is registered on the app
    def test_patch_route_registered(self):
        app = dashboard.create_app()
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/calendar/events/{job_id}" in routes

    # 12. PATCH with whitespace-only scheduled_time → 422
    def test_patch_whitespace_scheduled_time(self, patch_client):
        resp = patch_client.patch(
            "/api/calendar/events/abc12345",
            json={"scheduled_time": "   "},
        )
        assert resp.status_code == 422
        assert "scheduled_time" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Unit tests: GET /api/health/liveness (H60)
# ---------------------------------------------------------------------------

class TestLivenessEndpoint:
    """Tests for GET /api/health/liveness (H60)."""

    @pytest.fixture
    def client(self, tmp_path):
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_liveness_returns_200(self, client):
        """Liveness endpoint always returns 200 with status=alive."""
        response = client.get("/api/health/liveness")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_liveness_no_disk_io(self, client):
        """Liveness does NOT call _get_health_info or _get_pipeline_module_health."""
        with patch("dashboard._get_health_info") as mock_health, \
             patch("dashboard._get_pipeline_module_health") as mock_pipeline:
            response = client.get("/api/health/liveness")
            assert response.status_code == 200
            mock_health.assert_not_called()
            mock_pipeline.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests: GET /api/health/readiness (H60)
# ---------------------------------------------------------------------------

class TestReadinessEndpoint:
    """Tests for GET /api/health/readiness (H60)."""

    @pytest.fixture
    def client(self, tmp_path):
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_readiness_ok_when_healthy(self, tmp_path):
        """Returns 200 + ready when pipeline is healthy, ollama is running, .mp exists."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        mock_ollama = MagicMock()
        mock_ollama.list.return_value = []
        healthy_pipeline = {"summary": {"ok": 3, "error": 0}, "modules": {}}
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch("dashboard._get_pipeline_module_health", return_value=healthy_pipeline):
                with patch.dict(sys.modules, {"ollama": mock_ollama}):
                    app = dashboard.create_app()
                    client = TestClient(app)
                    response = client.get("/api/health/readiness")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["issues"] == []

    def test_readiness_503_when_pipeline_errors(self, tmp_path):
        """Returns 503 when pipeline has modules in error state."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        mock_ollama = MagicMock()
        mock_ollama.list.return_value = []
        error_pipeline = {"summary": {"ok": 1, "error": 2}, "modules": {}}
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch("dashboard._get_pipeline_module_health", return_value=error_pipeline):
                with patch.dict(sys.modules, {"ollama": mock_ollama}):
                    app = dashboard.create_app()
                    client = TestClient(app)
                    response = client.get("/api/health/readiness")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert any("pipeline" in issue for issue in data["issues"])

    def test_readiness_503_when_ollama_offline(self, tmp_path):
        """Returns 503 when ollama is not reachable."""
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        mock_ollama = MagicMock()
        mock_ollama.list.side_effect = Exception("Connection refused")
        healthy_pipeline = {"summary": {"ok": 0, "error": 0}, "modules": {}}
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch("dashboard._get_pipeline_module_health", return_value=healthy_pipeline):
                with patch.dict(sys.modules, {"ollama": mock_ollama}):
                    app = dashboard.create_app()
                    client = TestClient(app)
                    response = client.get("/api/health/readiness")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert any("ollama offline" in issue for issue in data["issues"])

    def test_readiness_503_when_mp_dir_missing(self, tmp_path):
        """Returns 503 when .mp directory doesn't exist."""
        from starlette.testclient import TestClient
        # Do NOT create .mp dir
        mock_ollama = MagicMock()
        mock_ollama.list.return_value = []
        healthy_pipeline = {"summary": {"ok": 0, "error": 0}, "modules": {}}
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch("dashboard._get_pipeline_module_health", return_value=healthy_pipeline):
                with patch.dict(sys.modules, {"ollama": mock_ollama}):
                    app = dashboard.create_app()
                    client = TestClient(app)
                    response = client.get("/api/health/readiness")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert any(".mp directory missing" in issue for issue in data["issues"])

    def test_readiness_multiple_issues(self, tmp_path):
        """Multiple issues are accumulated."""
        from starlette.testclient import TestClient
        # No .mp dir + ollama offline + pipeline errors
        mock_ollama = MagicMock()
        mock_ollama.list.side_effect = Exception("offline")
        error_pipeline = {"summary": {"ok": 0, "error": 1}, "modules": {}}
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch("dashboard._get_pipeline_module_health", return_value=error_pipeline):
                with patch.dict(sys.modules, {"ollama": mock_ollama}):
                    app = dashboard.create_app()
                    client = TestClient(app)
                    response = client.get("/api/health/readiness")
        assert response.status_code == 503
        data = response.json()
        assert len(data["issues"]) >= 2


# ---------------------------------------------------------------------------
# Unit tests: GET /api/health pipeline integration (H60)
# ---------------------------------------------------------------------------

class TestHealthApiPipelineKey:
    """Tests for GET /api/health pipeline integration (H60)."""

    @pytest.fixture
    def client(self, tmp_path):
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_api_health_includes_pipeline_key(self, client):
        """The /api/health response now includes a 'pipeline' key."""
        known_pipeline = {
            "summary": {"ok": 2, "error": 0, "warning": 1},
            "modules": {"video_gen": {"status": "ok"}, "tts": {"status": "warning"}},
        }
        with patch("dashboard._get_pipeline_module_health", return_value=known_pipeline):
            with patch.dict(sys.modules, {"ollama": MagicMock()}):
                response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "pipeline" in data
        assert "summary" in data["pipeline"]
        assert "modules" in data["pipeline"]

    def test_api_health_backward_compatible(self, client):
        """Existing keys (status, timestamp, disk_free_gb, etc.) are still present."""
        with patch("dashboard._get_pipeline_module_health", return_value={"summary": {}, "modules": {}}):
            with patch.dict(sys.modules, {"ollama": MagicMock()}):
                response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data

    def test_pipeline_health_failure_returns_empty(self, client):
        """If _get_pipeline_module_health() returns empty (its own guard path), /api/health still works."""
        # _get_pipeline_module_health catches all exceptions internally and returns
        # {"summary": {}, "modules": {}} — simulate that guard path here.
        empty_pipeline = {"summary": {}, "modules": {}}
        with patch("dashboard._get_pipeline_module_health", return_value=empty_pipeline):
            with patch.dict(sys.modules, {"ollama": MagicMock()}):
                response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["pipeline"] == empty_pipeline


# ===========================================================================
# Pipeline Health Panel (H63)
# ===========================================================================


class TestDashboardPipelineHealth:
    """Tests for pipeline health data in dashboard page and SSE."""

    @pytest.fixture
    def client(self, tmp_path):
        from starlette.testclient import TestClient
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()
        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            app = dashboard.create_app()
            yield TestClient(app)

    def test_dashboard_page_includes_pipeline_health(self, client):
        """dashboard_page() passes pipeline_health to the template."""
        with patch("dashboard._get_pipeline_module_health", return_value={
            "summary": {"total": 2, "ok": 1, "degraded": 0, "error": 1, "unknown": 0},
            "modules": {
                "publisher": {
                    "module_name": "publisher", "status": "ok",
                    "success_count": 10, "error_count": 0,
                    "last_check": "2026-03-31T12:00:00+00:00", "last_error": "",
                    "metadata": {},
                },
                "scheduler": {
                    "module_name": "scheduler", "status": "error",
                    "success_count": 5, "error_count": 3,
                    "last_check": "2026-03-31T12:01:00+00:00", "last_error": "timeout",
                    "metadata": {},
                },
            },
        }):
            resp = client.get("/dashboard")
            assert resp.status_code == 200
            html = resp.text
            assert "Pipeline Modules" in html
            assert "publisher" in html
            assert "scheduler" in html

    def test_dashboard_page_empty_pipeline_health(self, client):
        """Empty pipeline health shows 'No pipeline modules' message."""
        with patch("dashboard._get_pipeline_module_health", return_value={
            "summary": {}, "modules": {},
        }):
            resp = client.get("/dashboard")
            assert resp.status_code == 200
            assert "No pipeline modules registered" in resp.text

    def test_api_health_includes_pipeline(self, client):
        """GET /api/health includes pipeline data."""
        with patch("dashboard._get_pipeline_module_health", return_value={
            "summary": {"total": 0, "ok": 0, "degraded": 0, "error": 0, "unknown": 0},
            "modules": {},
        }):
            with patch.dict(sys.modules, {"ollama": MagicMock()}):
                resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "pipeline" in data

    def test_sse_stream_includes_pipeline_health(self, tmp_path):
        """SSE stream payload includes pipeline_health field."""
        from starlette.testclient import TestClient
        from starlette.requests import Request

        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()

        # Stop the generator after the first event by simulating a disconnect.
        disconnect_count = 0

        async def fake_is_disconnected(self):
            nonlocal disconnect_count
            disconnect_count += 1
            return disconnect_count > 1

        pipeline_data = {
            "summary": {"total": 1, "ok": 1, "degraded": 0, "error": 0, "unknown": 0},
            "modules": {"test_mod": {"status": "ok"}},
        }

        with patch.object(dashboard, "_get_root_dir", return_value=str(tmp_path)):
            with patch("dashboard._get_pipeline_module_health", return_value=pipeline_data):
                with patch.object(Request, "is_disconnected", fake_is_disconnected):
                    app = dashboard.create_app()
                    client = TestClient(app)
                    with client.stream("GET", "/api/stream") as resp:
                        assert resp.status_code == 200
                        content = ""
                        for chunk in resp.iter_text():
                            content += chunk
                            if "pipeline_health" in content:
                                break
        assert "pipeline_health" in content

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

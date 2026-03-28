"""
Web Dashboard for MoneyPrinter.

FastAPI backend serving a real-time monitoring dashboard via Jinja2 templates
and HTMX Server-Sent Events. Displays job status, analytics summary, and
pipeline health with zero frontend JavaScript dependencies.

Usage:
    # Standalone
    python src/dashboard.py [--port 8765]

    # From main menu
    Select option 6 "Dashboard" → opens browser automatically

    # Programmatic
    from dashboard import create_app
    app = create_app()
"""

import os
import sys
import json
import asyncio
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from mp_logger import get_logger

logger = get_logger(__name__)

# Default port for the dashboard server
DEFAULT_PORT = 8765
_MAX_SSE_CLIENTS = 100
_SSE_INTERVAL_SECONDS = 2


def _get_root_dir() -> str:
    """Get project root directory safely."""
    try:
        from config import ROOT_DIR
        return ROOT_DIR
    except (ImportError, Exception):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_analytics_data() -> dict:
    """Load analytics data from disk."""
    root = _get_root_dir()
    analytics_file = os.path.join(root, ".mp", "analytics.json")
    try:
        with open(analytics_file, "r") as f:
            data = json.load(f)
            return data if data is not None else {"events": [], "summary": {}}
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {"events": [], "summary": {}}


def _load_accounts_summary() -> dict:
    """Load account counts per platform."""
    root = _get_root_dir()
    mp_dir = os.path.join(root, ".mp")
    result = {}
    for platform in ("youtube", "twitter", "instagram"):
        cache_file = os.path.join(mp_dir, f"{platform}.json")
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
                accounts = data.get("accounts", []) if data else []
                result[platform] = len(accounts)
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            result[platform] = 0
    return result


def _load_scheduled_jobs() -> list:
    """Load scheduled jobs from scheduler persistence file."""
    root = _get_root_dir()
    jobs_file = os.path.join(root, ".mp", "scheduler_jobs.json")
    try:
        with open(jobs_file, "r") as f:
            data = json.load(f)
            jobs = data.get("jobs", []) if data else []
            return jobs[-50:]  # Return last 50 jobs
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return []


def _get_health_info() -> dict:
    """Gather system health information."""
    root = _get_root_dir()

    # Disk usage
    try:
        usage = shutil.disk_usage(root)
        disk_free_gb = round(usage.free / (1024 ** 3), 1)
        disk_total_gb = round(usage.total / (1024 ** 3), 1)
        disk_pct = round((usage.used / usage.total) * 100, 1)
    except OSError:
        disk_free_gb = 0
        disk_total_gb = 0
        disk_pct = 0

    # Ollama status
    ollama_status = "unknown"
    ollama_model = ""
    try:
        from config import get_ollama_model
        ollama_model = get_ollama_model() or ""
    except (ImportError, Exception):
        pass

    try:
        import ollama as ollama_sdk
        ollama_sdk.list()
        ollama_status = "running"
    except Exception:
        ollama_status = "offline"

    # Cache directory size
    mp_dir = os.path.join(root, ".mp")
    cache_size_mb = 0
    try:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(mp_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        cache_size_mb = round(total / (1024 * 1024), 2)
    except OSError:
        pass

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "disk_free_gb": disk_free_gb,
        "disk_total_gb": disk_total_gb,
        "disk_used_pct": disk_pct,
        "ollama_status": ollama_status,
        "ollama_model": ollama_model,
        "cache_size_mb": cache_size_mb,
    }


def create_app():
    """Create and configure the FastAPI application."""
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from starlette.responses import StreamingResponse
    from jinja2 import Environment, FileSystemLoader

    app = FastAPI(title="MoneyPrinter Dashboard", version="1.0.0")

    # Setup Jinja2 templates
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    os.makedirs(templates_dir, exist_ok=True)
    jinja_env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=True,
    )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page():
        """Render the main dashboard HTML page."""
        try:
            template = jinja_env.get_template("dashboard.html")
        except Exception:
            return HTMLResponse(
                content="<h1>Template not found</h1><p>Place dashboard.html in src/templates/</p>",
                status_code=500,
            )
        health = _get_health_info()
        analytics = _load_analytics_data()
        accounts = _load_accounts_summary()
        jobs = _load_scheduled_jobs()
        return HTMLResponse(content=template.render(
            health=health,
            analytics=analytics,
            accounts=accounts,
            jobs=jobs,
        ))

    @app.get("/api/health")
    async def api_health():
        """Return system health information."""
        return JSONResponse(content=_get_health_info())

    @app.get("/api/jobs")
    async def api_jobs():
        """Return recent scheduled/published jobs."""
        jobs = _load_scheduled_jobs()
        accounts = _load_accounts_summary()
        return JSONResponse(content={
            "jobs": jobs,
            "accounts": accounts,
            "total_jobs": len(jobs),
        })

    @app.get("/api/analytics")
    async def api_analytics():
        """Return analytics summary."""
        data = _load_analytics_data()
        summary = data.get("summary", {})
        total_events = len(data.get("events", []))
        recent = data.get("events", [])[-10:]
        return JSONResponse(content={
            "summary": summary,
            "total_events": total_events,
            "recent_events": recent,
        })

    @app.get("/api/stream")
    async def api_stream(request: Request):
        """SSE endpoint that pushes dashboard updates."""
        async def event_generator():
            while True:
                if await request.is_disconnected():
                    break
                health = _get_health_info()
                analytics = _load_analytics_data()
                accounts = _load_accounts_summary()
                jobs = _load_scheduled_jobs()
                payload = json.dumps({
                    "health": health,
                    "analytics_summary": analytics.get("summary", {}),
                    "total_events": len(analytics.get("events", [])),
                    "recent_events": analytics.get("events", [])[-5:],
                    "accounts": accounts,
                    "jobs_count": len(jobs),
                })
                yield f"event: dashboard-update\ndata: {payload}\n\n"
                await asyncio.sleep(_SSE_INTERVAL_SECONDS)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def run_dashboard(port: int = DEFAULT_PORT):
    """Start the dashboard server."""
    import uvicorn
    app = create_app()
    logger.info(f"Starting dashboard on http://localhost:{port}/dashboard")
    print(f"\n  Dashboard: http://localhost:{port}/dashboard\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--port" and i < len(sys.argv) - 1:
                try:
                    port = int(sys.argv[i + 1])
                except ValueError:
                    print(f"Invalid port: {sys.argv[i + 1]}")
                    sys.exit(1)
    run_dashboard(port)

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
import tempfile
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


_PLATFORM_COLORS = {
    "youtube": "#ff0000",
    "tiktok": "#00f2ea",
    "twitter": "#1da1f2",
    "instagram": "#e1306c",
}


def _load_schedule_data() -> list:
    """Load scheduled jobs from content scheduler's persistence file."""
    root = _get_root_dir()
    schedule_file = os.path.join(root, ".mp", "schedule.json")
    try:
        with open(schedule_file, "r") as f:
            data = json.load(f)
            return data.get("jobs", []) if isinstance(data, dict) else []
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return []


def _save_schedule_data(jobs: list) -> None:
    """Save scheduled jobs atomically."""
    root = _get_root_dir()
    mp_dir = os.path.join(root, ".mp")
    os.makedirs(mp_dir, exist_ok=True)
    schedule_file = os.path.join(mp_dir, "schedule.json")
    data = json.dumps({"jobs": jobs}, indent=2)
    fd, tmp = tempfile.mkstemp(dir=mp_dir, suffix=".tmp")
    try:
        os.write(fd, data.encode())
        os.close(fd)
        os.replace(tmp, schedule_file)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _job_to_calendar_event(job: dict) -> dict:
    """Convert a schedule job dict to FullCalendar event format."""
    platforms = job.get("platforms", [])
    primary_platform = platforms[0] if platforms else "unknown"
    color = _PLATFORM_COLORS.get(primary_platform, "#64748b")
    return {
        "id": job.get("job_id", ""),
        "title": job.get("title", "Untitled"),
        "start": job.get("scheduled_time", ""),
        "color": color,
        "extendedProps": {
            "platforms": platforms,
            "status": job.get("status", "pending"),
            "video_path": job.get("video_path", ""),
        },
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

    @app.get("/api/analytics/chart-data")
    async def api_chart_data():
        """Return aggregated chart-ready analytics data."""
        from collections import Counter
        analytics = _load_analytics_data()
        jobs = _load_scheduled_jobs()

        # Jobs over time (last 30 days)
        jobs_by_date = Counter()
        for job in jobs:
            date_str = job.get("scheduled_time", job.get("created_at", ""))[:10]
            if date_str:
                jobs_by_date[date_str] += 1
        # Sort by date, last 30 entries
        sorted_dates = sorted(jobs_by_date.items())[-30:]

        # Platform distribution
        platform_counts = Counter()
        for job in jobs:
            platforms = job.get("platforms", [])
            if isinstance(platforms, list):
                for p in platforms:
                    platform_counts[str(p).lower()] += 1
            elif isinstance(platforms, str):
                platform_counts[platforms.lower()] += 1

        # Success/fail rates
        status_counts = Counter()
        for job in jobs:
            status = job.get("status", "unknown")
            status_counts[status] += 1

        return JSONResponse(content={
            "jobs_over_time": [{"date": d, "count": c} for d, c in sorted_dates],
            "platform_counts": dict(platform_counts),
            "status_counts": dict(status_counts),
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

    @app.get("/calendar", response_class=HTMLResponse)
    async def calendar_page():
        """Render the content calendar HTML page."""
        try:
            template = jinja_env.get_template("calendar.html")
        except Exception:
            return HTMLResponse(
                content="<h1>Template not found</h1><p>Place calendar.html in src/templates/</p>",
                status_code=500,
            )
        return HTMLResponse(content=template.render())

    @app.get("/api/calendar/events")
    async def api_calendar_events(start: str = "", end: str = ""):
        """Return scheduled jobs as FullCalendar-compatible event JSON."""
        jobs = _load_schedule_data()
        events = []
        for job in jobs:
            scheduled_time = job.get("scheduled_time", "")
            if start and scheduled_time and scheduled_time < start:
                continue
            if end and scheduled_time and scheduled_time > end:
                continue
            events.append(_job_to_calendar_event(job))
        return JSONResponse(content=events)

    @app.post("/api/calendar/events", status_code=201)
    async def api_calendar_create(request: Request):
        """Create a new scheduled job and persist it."""
        import uuid
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                content={"error": "Invalid JSON body"},
                status_code=400,
            )

        title = (body.get("title") or "").strip()
        platforms = body.get("platforms") or []
        scheduled_time = (body.get("scheduled_time") or "").strip()
        video_path = (body.get("video_path") or "").strip()

        missing = []
        if not title:
            missing.append("title")
        if not platforms:
            missing.append("platforms")
        if not scheduled_time:
            missing.append("scheduled_time")
        if missing:
            return JSONResponse(
                content={"error": f"Missing required fields: {', '.join(missing)}"},
                status_code=422,
            )

        if isinstance(platforms, str):
            platforms = [platforms]

        job_id = str(uuid.uuid4())[:8]
        new_job = {
            "job_id": job_id,
            "title": title,
            "platforms": platforms,
            "scheduled_time": scheduled_time,
            "status": "pending",
            "video_path": video_path,
        }

        jobs = _load_schedule_data()
        jobs.append(new_job)
        _save_schedule_data(jobs)

        return JSONResponse(content=_job_to_calendar_event(new_job), status_code=201)

    @app.delete("/api/calendar/events/{job_id}", status_code=204)
    async def api_calendar_delete(job_id: str):
        """Delete a scheduled job by job_id."""
        from fastapi.responses import Response
        jobs = _load_schedule_data()
        filtered = [j for j in jobs if j.get("job_id") != job_id]
        if len(filtered) == len(jobs):
            return JSONResponse(
                content={"error": f"Job '{job_id}' not found"},
                status_code=404,
            )
        _save_schedule_data(filtered)
        return Response(status_code=204)

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

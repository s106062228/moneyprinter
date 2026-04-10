"""
Analytics module for tracking MoneyPrinter content generation and upload metrics.

Stores event data in a local JSON file for performance monitoring and
content strategy optimization.
"""

import os
import json
import tempfile
from datetime import datetime, timezone
from typing import Optional
from config import ROOT_DIR


ANALYTICS_FILE = os.path.join(ROOT_DIR, ".mp", "analytics.json")

# Maximum number of events to keep (prevents unbounded disk usage)
_MAX_EVENTS = 10000


def _load_analytics() -> dict:
    """Loads the analytics data from disk (TOCTOU-safe)."""
    try:
        with open(ANALYTICS_FILE, "r") as f:
            data = json.load(f)
            return data if data is not None else {"events": [], "summary": {}}
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {"events": [], "summary": {}}


def _save_analytics(data: dict) -> None:
    """Atomically persists analytics data to disk using tempfile + os.replace."""
    dir_name = os.path.dirname(ANALYTICS_FILE)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, ANALYTICS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def track_event(
    event_type: str,
    platform: str,
    details: Optional[dict] = None,
) -> None:
    """
    Records an analytics event.

    Args:
        event_type: Type of event (e.g. "video_generated", "video_uploaded",
                    "tweet_posted", "pitch_shared").
        platform: Target platform ("youtube", "twitter", "tiktok").
        details: Optional dict with extra metadata.
    """
    data = _load_analytics()

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "platform": platform,
        "details": details or {},
    }
    data["events"].append(event)

    # Rotate old events to prevent unbounded disk usage
    if len(data["events"]) > _MAX_EVENTS:
        data["events"] = data["events"][-_MAX_EVENTS:]

    # Update summary counters
    summary = data.setdefault("summary", {})
    platform_summary = summary.setdefault(platform, {})
    platform_summary[event_type] = platform_summary.get(event_type, 0) + 1
    platform_summary["total_events"] = platform_summary.get("total_events", 0) + 1

    _save_analytics(data)


def get_summary() -> dict:
    """
    Returns a summary of all tracked analytics.

    Returns:
        Dictionary with per-platform event counts.
    """
    data = _load_analytics()
    return data.get("summary", {})


_MAX_QUERY_LIMIT = 10000  # Hard cap on event query limit


def get_events(
    platform: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> list:
    """
    Returns recent analytics events, optionally filtered.

    Args:
        platform: Filter by platform name.
        event_type: Filter by event type.
        limit: Max number of events to return.

    Returns:
        List of event dicts, most recent first.
    """
    data = _load_analytics()
    events = data.get("events", [])

    # Cap limit to prevent excessive memory usage
    limit = min(max(limit, 1), _MAX_QUERY_LIMIT)

    if platform:
        events = [e for e in events if e.get("platform") == platform]
    if event_type:
        events = [e for e in events if e.get("type") == event_type]

    return list(reversed(events))[:limit]


def get_platform_stats(platform: str) -> dict:
    """
    Returns statistics for a specific platform.

    Args:
        platform: Platform name.

    Returns:
        Dict with event counts for the platform.
    """
    summary = get_summary()
    return summary.get(platform, {})

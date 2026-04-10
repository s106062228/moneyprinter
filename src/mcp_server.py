"""
MCP Server for MoneyPrinter Content Pipeline.

Exposes SmartClipper, publisher, scheduler, and analytics as MCP tools
for use by any MCP-compatible AI assistant (Claude, ChatGPT, etc.).

Usage:
    python src/mcp_server.py              # stdio transport (Claude Code)
    python src/mcp_server.py --http 8000  # HTTP transport (remote)
"""

import sys
import os
import logging
from typing import Annotated, Optional

# Add src/ to path (same pattern as main.py)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastmcp import FastMCP

mcp = FastMCP("MoneyPrinter")
logger = logging.getLogger(__name__)

# Route all logging to stderr so it never corrupts the stdio MCP protocol
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _get_auth(token: str | None = None):
    """Return BearerTokenAuth if a token is available, else None."""
    resolved = token or os.environ.get("MCP_AUTH_TOKEN", "")
    if not resolved:
        return None
    try:
        from fastmcp.server.auth import BearerTokenAuth
        return BearerTokenAuth(token=resolved)
    except ImportError:
        logger.warning("BearerTokenAuth not available in this fastmcp version — running without auth")
        return None


# ---------------------------------------------------------------------------
# Tool: analyze_video
# ---------------------------------------------------------------------------

@mcp.tool
def analyze_video(
    video_path: Annotated[str, "Path to the video file to analyze"],
    min_clip_duration: Annotated[float, "Minimum clip duration in seconds"] = 15.0,
    max_clip_duration: Annotated[float, "Maximum clip duration in seconds"] = 60.0,
    top_n: Annotated[int, "Number of top highlights to return"] = 5,
) -> list[dict]:
    """Analyze a video to find highlight clips using scene detection and LLM scoring.

    Runs the full SmartClipper pipeline:
    1. Scene boundary detection (PySceneDetect)
    2. Audio transcription (faster-whisper)
    3. Segment merging (scenes + transcript → coherent windows)
    4. LLM engagement scoring (Ollama)
    5. Returns the top-N ranked clip candidates as dicts.

    Each returned dict has: start_time, end_time, duration, score (0-10),
    transcript, reason, scene_count.
    """
    try:
        from smart_clipper import SmartClipper

        clipper = SmartClipper(
            min_clip_duration=min_clip_duration,
            max_clip_duration=max_clip_duration,
            top_n=top_n,
        )
        highlights = clipper.find_highlights(video_path)
        result = [clip.to_dict() for clip in highlights]
        logger.info(
            "analyze_video: found %d highlights in %s", len(result), video_path
        )
        return result
    except FileNotFoundError:
        logger.error("analyze_video: file not found")
        return [{"error": "FileNotFoundError", "message": "Video file not found"}]
    except ValueError:
        logger.error("analyze_video: invalid argument")
        return [{"error": "ValueError", "message": "Invalid argument provided"}]
    except Exception as exc:
        logger.error("analyze_video: unexpected error — %s", type(exc).__name__)
        return [{"error": type(exc).__name__, "message": "Operation failed"}]


# ---------------------------------------------------------------------------
# Tool: publish_content
# ---------------------------------------------------------------------------

@mcp.tool
def publish_content(
    video_path: Annotated[str, "Path to the video file to publish"],
    title: Annotated[str, "Title for the content"],
    description: Annotated[str, "Description for the content"] = "",
    platforms: Annotated[list[str], "Target platforms (youtube, tiktok, twitter, instagram)"] = ["youtube"],
) -> list[dict]:
    """Publish content across multiple platforms (YouTube, TikTok, Twitter, Instagram).

    Creates a PublishJob and runs it through ContentPublisher, which handles
    retry logic, analytics tracking, and webhook notifications. Returns one
    result dict per platform containing: platform, success, timestamp,
    error_type, duration_seconds, details.
    """
    try:
        from publisher import ContentPublisher, PublishJob

        job = PublishJob(
            video_path=video_path,
            title=title,
            description=description,
            platforms=platforms,
        )
        publisher = ContentPublisher()
        results = publisher.publish(job)

        output = []
        for r in results:
            if hasattr(r, "__dict__"):
                output.append(dict(r.__dict__))
            elif isinstance(r, dict):
                output.append(r)
            else:
                output.append({"raw": str(r)})

        logger.info(
            "publish_content: published '%s' to %d platform(s)", title, len(output)
        )
        return output
    except ValueError as exc:
        logger.error("publish_content: validation error — %s", exc)
        return [{"error": "ValueError", "message": "Operation failed"}]
    except Exception as exc:
        logger.error(
            "publish_content: unexpected error — %s: %s", type(exc).__name__, exc
        )
        return [{"error": type(exc).__name__, "message": "Operation failed"}]


# ---------------------------------------------------------------------------
# Tool: schedule_content
# ---------------------------------------------------------------------------

@mcp.tool
def schedule_content(
    video_path: Annotated[str, "Path to the video file"],
    title: Annotated[str, "Title for the content"],
    platforms: Annotated[list[str], "Target platforms (youtube, tiktok, twitter, instagram)"],
    scheduled_time: Annotated[
        str,
        "ISO 8601 datetime string for when to publish (empty = auto-pick optimal time)",
    ] = "",
    description: Annotated[str, "Description for the content"] = "",
    repeat_interval_hours: Annotated[
        int, "Repeat every N hours (0 = one-shot)"
    ] = 0,
) -> dict:
    """Schedule content for future publishing at optimal times.

    If scheduled_time is empty, automatically picks the next optimal posting
    window for the first platform in the list (based on configured optimal
    times and day-of-week engagement weights).

    Returns a dict with: job_id, scheduled_time, platforms, title, status,
    and (if auto-picked) best_time_info showing the recommended slot details.
    """
    try:
        from content_scheduler import (
            ContentScheduler,
            ScheduledJob,
            suggest_next_optimal_time,
            get_best_posting_time,
        )

        resolved_time = scheduled_time.strip()
        best_time_info: Optional[dict] = None

        # Auto-pick optimal time when none is supplied
        if not resolved_time and platforms:
            primary_platform = platforms[0].lower()
            resolved_time = suggest_next_optimal_time(primary_platform)
            try:
                best_time_info = get_best_posting_time(primary_platform)
                best_time_info["auto_selected"] = True
                best_time_info["suggested_iso"] = resolved_time
            except Exception as inner_exc:
                logger.debug(
                    "schedule_content: could not fetch best_time_info — %s", inner_exc
                )

        job = ScheduledJob(
            video_path=video_path,
            title=title,
            description=description,
            platforms=platforms,
            scheduled_time=resolved_time,
            repeat_interval_hours=repeat_interval_hours,
        )

        scheduler = ContentScheduler()
        job_id = scheduler.add_job(job)

        result: dict = {
            "job_id": job_id,
            "status": "scheduled",
            "title": title,
            "platforms": platforms,
            "scheduled_time": resolved_time,
            "repeat_interval_hours": repeat_interval_hours,
        }
        if best_time_info is not None:
            result["best_time_info"] = best_time_info

        logger.info(
            "schedule_content: job %s scheduled for %s on %s",
            job_id,
            resolved_time or "immediate",
            platforms,
        )
        return result
    except ValueError as exc:
        logger.error("schedule_content: validation error — %s", exc)
        return {"error": "ValueError", "message": "Operation failed"}
    except Exception as exc:
        logger.error(
            "schedule_content: unexpected error — %s: %s", type(exc).__name__, exc
        )
        return {"error": type(exc).__name__, "message": "Operation failed"}


# ---------------------------------------------------------------------------
# Tool: get_analytics
# ---------------------------------------------------------------------------

@mcp.tool
def get_analytics(
    platform: Annotated[
        str,
        "Platform name to filter by (youtube, tiktok, twitter, instagram). "
        "Leave empty for a cross-platform report.",
    ] = "",
    max_events: Annotated[int, "Maximum number of events to analyze (0 = config default)"] = 0,
) -> dict:
    """Generate an analytics report for content performance.

    When platform is empty, returns an AnalyticsReport dict covering all
    platforms with: generated_at, total_events, platforms (per-platform
    PlatformStats), overall_success_rate, busiest_platform, most_active_day,
    event_type_distribution, daily_trend (7-day), recommendations.

    When a platform name is supplied, returns a PlatformStats dict for that
    single platform with: platform, total_events, successful_uploads,
    failed_uploads, success_rate, events_by_type, avg_events_per_day,
    peak_day, peak_day_count, most_common_error, recent_trend.
    """
    try:
        from analytics_report import generate_report, get_platform_report

        if platform:
            stats = get_platform_report(platform.lower())
            result = stats.to_dict()
            logger.info(
                "get_analytics: platform=%s, total_events=%d",
                platform,
                result.get("total_events", 0),
            )
            return result

        # Cross-platform report
        kwargs: dict = {}
        if max_events > 0:
            kwargs["max_events"] = max_events

        report = generate_report(**kwargs)
        result = report.to_dict()
        logger.info(
            "get_analytics: cross-platform report, total_events=%d, platforms=%s",
            result.get("total_events", 0),
            list(result.get("platforms", {}).keys()),
        )
        return result
    except ValueError as exc:
        logger.error("get_analytics: invalid argument — %s", exc)
        return {"error": "ValueError", "message": "Operation failed"}
    except Exception as exc:
        logger.error(
            "get_analytics: unexpected error — %s: %s", type(exc).__name__, exc
        )
        return {"error": type(exc).__name__, "message": "Operation failed"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MoneyPrinter MCP Server — exposes content pipeline as MCP tools."
    )
    parser.add_argument(
        "--http",
        type=int,
        metavar="PORT",
        help="Run HTTP transport on the given port (default: stdio)",
    )
    parser.add_argument(
        "--token",
        type=str,
        metavar="TOKEN",
        default=None,
        help="Bearer token for HTTP auth (default: MCP_AUTH_TOKEN env var)",
    )
    args = parser.parse_args()

    if args.http:
        auth = _get_auth(getattr(args, "token", None))
        if auth:
            mcp.settings.auth = auth
            logger.info("Bearer token auth enabled for HTTP transport")
        else:
            logger.warning(
                "No --token provided; binding to 127.0.0.1 only for safety"
            )
        # Bind to localhost by default when no auth token is set to prevent
        # unauthenticated network exposure (security audit run 23).
        bind_host = "0.0.0.0" if auth else "127.0.0.1"
        logger.info("Starting MoneyPrinter MCP server on %s:%d", bind_host, args.http)
        mcp.run(transport="http", host=bind_host, port=args.http)
    else:
        logger.info("Starting MoneyPrinter MCP server on stdio")
        mcp.run()  # stdio default — compatible with Claude Code

"""
Content Scheduler for MoneyPrinter.

Enables automated scheduling of content publishing across platforms with
optimal posting time recommendations. Integrates with the publisher module
for execution and analytics for performance tracking.

Usage:
    from content_scheduler import ContentScheduler, ScheduledJob

    scheduler = ContentScheduler()
    job = ScheduledJob(
        video_path="/path/to/video.mp4",
        title="My Video",
        platforms=["youtube", "tiktok"],
        scheduled_time="2026-03-25T10:00:00",
    )
    scheduler.add_job(job)
    scheduler.run()  # Blocks and executes jobs at their scheduled times

Configuration (config.json):
    "scheduler": {
        "enabled": true,
        "max_pending_jobs": 100,
        "optimal_times": {
            "youtube": ["10:00", "14:00", "18:00"],
            "tiktok": ["09:00", "12:00", "19:00"],
            "twitter": ["08:00", "12:00", "17:00"]
        }
    }
"""

import os
import json
import time
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import _get, ROOT_DIR
from mp_logger import get_logger
from status import success, error, warning, info
from validation import validate_path

logger = get_logger(__name__)

# Limits to prevent abuse
_MAX_PENDING_JOBS = 100
_MAX_TITLE_LENGTH = 500
_MAX_DESCRIPTION_LENGTH = 5000
_MAX_VIDEO_PATH_LENGTH = 1024
_SCHEDULE_FILE = os.path.join(ROOT_DIR, ".mp", "schedule.json")

# Default optimal posting times per platform (UTC hours)
_DEFAULT_OPTIMAL_TIMES = {
    "youtube": ["09:00", "12:00", "17:00"],
    "tiktok": ["14:00", "17:00", "21:00"],
    "twitter": ["08:00", "12:00", "17:00"],
    "instagram": ["11:00", "14:00", "19:00"],
}

_ALLOWED_PLATFORMS = {"youtube", "tiktok", "twitter", "instagram"}

# Day-of-week engagement weights (0=Monday, 6=Sunday) based on 2026 research
_DAY_WEIGHTS = {
    "youtube":   {0: 0.8, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.9, 5: 0.7, 6: 0.7},
    "tiktok":    {0: 0.9, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.8, 6: 0.8},
    "twitter":   {0: 0.9, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.8, 5: 0.6, 6: 0.6},
    "instagram": {0: 0.8, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.9, 6: 0.9},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScheduledJob:
    """Describes a scheduled content publishing job."""

    video_path: str
    title: str
    description: str = ""
    platforms: list = field(default_factory=list)
    twitter_text: Optional[str] = None
    tags: list = field(default_factory=list)
    scheduled_time: str = ""  # ISO 8601 datetime string
    repeat_interval_hours: int = 0  # 0 = one-shot, >0 = repeat every N hours
    job_id: str = ""
    status: str = "pending"  # pending, running, completed, failed
    created_at: str = ""
    completed_at: str = ""
    error_message: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.job_id:
            import uuid
            self.job_id = str(uuid.uuid4())[:8]

    def validate(self) -> None:
        """
        Validates the scheduled job fields.

        Raises:
            ValueError: If any field is invalid.
        """
        if not self.video_path or not isinstance(self.video_path, str):
            raise ValueError("video_path must be a non-empty string.")
        if len(self.video_path) > _MAX_VIDEO_PATH_LENGTH:
            raise ValueError(
                f"video_path exceeds maximum length of {_MAX_VIDEO_PATH_LENGTH}."
            )
        if "\x00" in self.video_path:
            raise ValueError("video_path contains null bytes.")

        if not self.title or not isinstance(self.title, str):
            raise ValueError("title must be a non-empty string.")
        if len(self.title) > _MAX_TITLE_LENGTH:
            raise ValueError(
                f"title exceeds maximum length of {_MAX_TITLE_LENGTH}."
            )

        if self.description and len(self.description) > _MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"description exceeds maximum length of {_MAX_DESCRIPTION_LENGTH}."
            )

        if not isinstance(self.platforms, list):
            raise ValueError("platforms must be a list.")
        for p in self.platforms:
            if not isinstance(p, str) or p.lower() not in _ALLOWED_PLATFORMS:
                raise ValueError(
                    f"Unknown platform: {p}. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_PLATFORMS))}"
                )

        if self.scheduled_time:
            try:
                datetime.fromisoformat(self.scheduled_time)
            except (ValueError, TypeError):
                raise ValueError(
                    f"scheduled_time must be a valid ISO 8601 datetime string."
                )

        if self.repeat_interval_hours < 0:
            raise ValueError("repeat_interval_hours must be non-negative.")
        # Cap repeat interval to prevent unreasonable values
        if self.repeat_interval_hours > 720:  # 30 days max
            raise ValueError("repeat_interval_hours cannot exceed 720 (30 days).")

    def to_dict(self) -> dict:
        """Serializes to a dictionary for JSON persistence."""
        return {
            "job_id": self.job_id,
            "video_path": self.video_path,
            "title": self.title,
            "description": self.description,
            "platforms": self.platforms,
            "twitter_text": self.twitter_text,
            "tags": self.tags,
            "scheduled_time": self.scheduled_time,
            "repeat_interval_hours": self.repeat_interval_hours,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledJob":
        """Deserializes from a dictionary with validation."""
        if not isinstance(data, dict):
            raise ValueError("ScheduledJob.from_dict requires a dict")
        # Truncate and validate fields from potentially untrusted data
        video_path = str(data.get("video_path", ""))[:_MAX_VIDEO_PATH_LENGTH]
        title = str(data.get("title", ""))[:_MAX_TITLE_LENGTH]
        description = str(data.get("description", ""))[:_MAX_DESCRIPTION_LENGTH]
        # Validate platforms
        raw_platforms = data.get("platforms", [])
        platforms = [
            str(p) for p in (raw_platforms if isinstance(raw_platforms, list) else [])
            if str(p).lower() in _ALLOWED_PLATFORMS
        ][:10]
        # Validate status
        raw_status = str(data.get("status", "pending"))
        valid_statuses = {"pending", "running", "completed", "failed"}
        status = raw_status if raw_status in valid_statuses else "pending"
        # Clamp repeat interval
        try:
            repeat_hours = int(data.get("repeat_interval_hours", 0))
        except (ValueError, TypeError):
            repeat_hours = 0
        repeat_hours = min(max(repeat_hours, 0), 720)
        return cls(
            video_path=video_path,
            title=title,
            description=description,
            platforms=platforms,
            twitter_text=data.get("twitter_text"),
            tags=data.get("tags", [])[:50],
            scheduled_time=str(data.get("scheduled_time", ""))[:50],
            repeat_interval_hours=repeat_hours,
            job_id=str(data.get("job_id", ""))[:50],
            status=status,
            created_at=str(data.get("created_at", ""))[:50],
            completed_at=str(data.get("completed_at", ""))[:50],
            error_message=str(data.get("error_message", ""))[:500],
        )


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_scheduler_config() -> dict:
    """Returns the scheduler configuration block."""
    return _get("scheduler", {})


def get_scheduler_enabled() -> bool:
    """Returns whether the content scheduler is enabled."""
    return bool(_get_scheduler_config().get("enabled", False))


def get_max_pending_jobs() -> int:
    """Returns the max number of pending jobs allowed."""
    val = _get_scheduler_config().get("max_pending_jobs", _MAX_PENDING_JOBS)
    return min(int(val), 500)  # Hard cap at 500


def get_optimal_times(platform: str) -> list:
    """
    Returns optimal posting times for a platform.

    Args:
        platform: Platform name (youtube, tiktok, twitter).

    Returns:
        List of time strings in "HH:MM" format.
    """
    configured = _get_scheduler_config().get("optimal_times", {})
    return configured.get(platform, _DEFAULT_OPTIMAL_TIMES.get(platform, []))


def suggest_next_optimal_time(platform: str) -> str:
    """
    Suggests the next optimal posting time for a platform.

    Based on configured optimal times, returns the next upcoming
    time slot as an ISO 8601 datetime string.

    Args:
        platform: Platform name.

    Returns:
        ISO 8601 datetime string for the next optimal posting time.
    """
    times = get_optimal_times(platform.lower())
    if not times:
        # Default: 1 hour from now
        return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    now = datetime.now(timezone.utc)
    today_slots = []

    for time_str in times:
        try:
            parts = time_str.strip().split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            today_slots.append(slot)
        except (ValueError, IndexError):
            continue

    # Find the next future slot
    future_slots = [s for s in today_slots if s > now]
    if future_slots:
        return min(future_slots).isoformat()

    # All today's slots have passed — use first slot tomorrow
    if today_slots:
        tomorrow_slot = min(today_slots) + timedelta(days=1)
        return tomorrow_slot.isoformat()

    return (now + timedelta(hours=1)).isoformat()


def get_best_posting_time(platform: str, target_date: Optional[datetime] = None) -> dict:
    """
    Returns the best posting time for a platform on a given date,
    considering day-of-week engagement weights.

    Args:
        platform: Platform name (youtube, tiktok, twitter, instagram).
        target_date: The target date (defaults to today UTC).

    Returns:
        Dict with keys: "time" (HH:MM str), "weight" (float 0-1),
        "platform" (str), "day_name" (str).

    Raises:
        ValueError: If platform is not supported.
    """
    platform = platform.lower()
    if platform not in _ALLOWED_PLATFORMS:
        raise ValueError(
            f"Unknown platform: {platform}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_PLATFORMS))}"
        )

    if target_date is None:
        target_date = datetime.now(timezone.utc)

    day_of_week = target_date.weekday()  # 0=Monday
    weight = _DAY_WEIGHTS.get(platform, {}).get(day_of_week, 0.5)

    times = get_optimal_times(platform)
    best_time = times[0] if times else "12:00"

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    return {
        "time": best_time,
        "weight": weight,
        "platform": platform,
        "day_name": day_names[day_of_week],
    }


# ---------------------------------------------------------------------------
# Persistence (atomic reads/writes)
# ---------------------------------------------------------------------------

def _load_schedule() -> dict:
    """Loads schedule data from disk (TOCTOU-safe)."""
    try:
        with open(_SCHEDULE_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"jobs": []}
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {"jobs": []}


def _save_schedule(data: dict) -> None:
    """Atomically persists schedule data to disk."""
    dir_name = os.path.dirname(_SCHEDULE_FILE)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, _SCHEDULE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Content Scheduler
# ---------------------------------------------------------------------------

class ContentScheduler:
    """
    Manages scheduled content publishing jobs.

    Provides methods to add, remove, list, and execute scheduled
    publishing jobs. Integrates with the publisher module for
    actual content delivery and analytics for tracking.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def add_job(self, job: ScheduledJob) -> str:
        """
        Adds a scheduled job to the queue.

        Args:
            job: The ScheduledJob to schedule.

        Returns:
            The job ID.

        Raises:
            ValueError: If the job is invalid or queue is full.
        """
        job.validate()

        with self._lock:
            data = _load_schedule()
            pending = [j for j in data["jobs"] if j.get("status") == "pending"]

            if len(pending) >= get_max_pending_jobs():
                raise ValueError(
                    f"Maximum pending jobs ({get_max_pending_jobs()}) reached. "
                    f"Remove completed jobs or wait for them to execute."
                )

            data["jobs"].append(job.to_dict())
            _save_schedule(data)

        logger.info(f"Scheduled job {job.job_id}: '{job.title}' for {job.scheduled_time or 'immediate'}")
        return job.job_id

    def remove_job(self, job_id: str) -> bool:
        """
        Removes a job from the schedule.

        Args:
            job_id: The job ID to remove.

        Returns:
            True if the job was found and removed, False otherwise.
        """
        if not job_id or not isinstance(job_id, str):
            return False

        with self._lock:
            data = _load_schedule()
            original_count = len(data["jobs"])
            data["jobs"] = [j for j in data["jobs"] if j.get("job_id") != job_id]

            if len(data["jobs"]) < original_count:
                _save_schedule(data)
                logger.info(f"Removed job {job_id}")
                return True

        return False

    def list_jobs(self, status: Optional[str] = None) -> list:
        """
        Lists all scheduled jobs, optionally filtered by status.

        Args:
            status: Filter by status (pending, running, completed, failed).

        Returns:
            List of ScheduledJob objects.
        """
        data = _load_schedule()
        jobs = data.get("jobs", [])

        if status:
            jobs = [j for j in jobs if j.get("status") == status]

        return [ScheduledJob.from_dict(j) for j in jobs]

    def get_pending_jobs(self) -> list:
        """Returns jobs that are ready to execute (scheduled_time has passed)."""
        now = datetime.now(timezone.utc)
        pending = self.list_jobs(status="pending")

        ready = []
        for job in pending:
            if not job.scheduled_time:
                # No scheduled time = execute immediately
                ready.append(job)
            else:
                try:
                    scheduled = datetime.fromisoformat(job.scheduled_time)
                    if scheduled <= now:
                        ready.append(job)
                except (ValueError, TypeError):
                    # Invalid time — skip
                    continue

        return ready

    def execute_job(self, job: ScheduledJob) -> bool:
        """
        Executes a single scheduled job via the publisher.

        Args:
            job: The job to execute.

        Returns:
            True if publishing succeeded for all platforms, False otherwise.
        """
        from publisher import ContentPublisher, PublishJob

        # Update status to running
        self._update_job_status(job.job_id, "running")

        try:
            # Verify video file still exists
            if not os.path.isfile(job.video_path):
                raise FileNotFoundError(
                    "Scheduled video file no longer exists at the specified path."
                )

            publish_job = PublishJob(
                video_path=job.video_path,
                title=job.title,
                description=job.description,
                platforms=job.platforms,
                twitter_text=job.twitter_text,
                tags=job.tags,
            )

            publisher = ContentPublisher()
            results = publisher.publish(publish_job)

            all_succeeded = all(r.success for r in results)

            if all_succeeded:
                self._update_job_status(job.job_id, "completed")
                success(f" => Scheduled job {job.job_id} completed successfully!")
            else:
                failed_platforms = [r.platform for r in results if not r.success]
                self._update_job_status(
                    job.job_id, "failed",
                    error_msg=f"Failed on: {', '.join(failed_platforms)}"
                )
                warning(
                    f" => Scheduled job {job.job_id} partially failed: "
                    f"{', '.join(failed_platforms)}"
                )

            # Handle repeat jobs
            if job.repeat_interval_hours > 0 and all_succeeded:
                self._reschedule_job(job)

            return all_succeeded

        except Exception as e:
            self._update_job_status(
                job.job_id, "failed",
                error_msg=type(e).__name__
            )
            logger.warning(
                f"Scheduled job {job.job_id} failed: {type(e).__name__}"
            )
            return False

    def run_pending(self) -> dict:
        """
        Executes all pending jobs that are ready.

        Returns:
            Dict with execution summary:
                - executed: int
                - succeeded: int
                - failed: int
        """
        ready_jobs = self.get_pending_jobs()
        executed = 0
        succeeded = 0

        for job in ready_jobs:
            executed += 1
            if self.execute_job(job):
                succeeded += 1

        return {
            "executed": executed,
            "succeeded": succeeded,
            "failed": executed - succeeded,
        }

    def cleanup_completed(self, max_age_days: int = 7) -> int:
        """
        Removes completed/failed jobs older than max_age_days.

        Args:
            max_age_days: Remove jobs completed more than this many days ago.

        Returns:
            Number of jobs removed.
        """
        if max_age_days < 0:
            max_age_days = 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        removed = 0

        with self._lock:
            data = _load_schedule()
            kept = []
            for j in data["jobs"]:
                if j.get("status") in ("completed", "failed"):
                    completed_at = j.get("completed_at", "")
                    if completed_at:
                        try:
                            if datetime.fromisoformat(completed_at) < cutoff:
                                removed += 1
                                continue
                        except (ValueError, TypeError):
                            pass
                kept.append(j)

            if removed > 0:
                data["jobs"] = kept
                _save_schedule(data)

        if removed > 0:
            logger.info(f"Cleaned up {removed} old scheduled jobs.")

        return removed

    def _update_job_status(
        self, job_id: str, status: str, error_msg: str = ""
    ) -> None:
        """Updates a job's status in the schedule file."""
        with self._lock:
            data = _load_schedule()
            for j in data["jobs"]:
                if j.get("job_id") == job_id:
                    j["status"] = status
                    if status in ("completed", "failed"):
                        j["completed_at"] = datetime.now(timezone.utc).isoformat()
                    if error_msg:
                        j["error_message"] = error_msg
                    break
            _save_schedule(data)

    def _reschedule_job(self, job: ScheduledJob) -> None:
        """Creates a new job for the next repeat interval."""
        try:
            if job.scheduled_time:
                base_time = datetime.fromisoformat(job.scheduled_time)
            else:
                base_time = datetime.now(timezone.utc)

            next_time = base_time + timedelta(hours=job.repeat_interval_hours)

            new_job = ScheduledJob(
                video_path=job.video_path,
                title=job.title,
                description=job.description,
                platforms=job.platforms,
                twitter_text=job.twitter_text,
                tags=job.tags,
                scheduled_time=next_time.isoformat(),
                repeat_interval_hours=job.repeat_interval_hours,
            )

            self.add_job(new_job)
            logger.info(
                f"Rescheduled job '{job.title}' for {next_time.isoformat()}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to reschedule job {job.job_id}: {type(e).__name__}"
            )

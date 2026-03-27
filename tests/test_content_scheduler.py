"""Tests for the content_scheduler module."""

import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

# Ensure src is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# ScheduledJob tests
# ---------------------------------------------------------------------------

class TestScheduledJob:
    """Tests for the ScheduledJob dataclass."""

    def _make_job(self, **overrides):
        from content_scheduler import ScheduledJob

        defaults = {
            "video_path": "/tmp/test_video.mp4",
            "title": "Test Video",
            "platforms": ["youtube"],
            "scheduled_time": (datetime.now() + timedelta(hours=1)).isoformat(),
        }
        defaults.update(overrides)
        return ScheduledJob(**defaults)

    def test_job_creation_defaults(self):
        from content_scheduler import ScheduledJob

        job = ScheduledJob(video_path="/tmp/v.mp4", title="Hello")
        assert job.status == "pending"
        assert job.job_id  # Auto-generated
        assert job.created_at  # Auto-generated

    def test_job_validate_empty_video_path(self):
        job = self._make_job(video_path="")
        with pytest.raises(ValueError, match="video_path"):
            job.validate()

    def test_job_validate_null_byte_in_path(self):
        job = self._make_job(video_path="/tmp/test\x00.mp4")
        with pytest.raises(ValueError, match="null bytes"):
            job.validate()

    def test_job_validate_path_too_long(self):
        job = self._make_job(video_path="/" + "a" * 1025)
        with pytest.raises(ValueError, match="maximum length"):
            job.validate()

    def test_job_validate_empty_title(self):
        job = self._make_job(title="")
        with pytest.raises(ValueError, match="title"):
            job.validate()

    def test_job_validate_title_too_long(self):
        job = self._make_job(title="x" * 501)
        with pytest.raises(ValueError, match="maximum length"):
            job.validate()

    def test_job_validate_description_too_long(self):
        job = self._make_job(description="x" * 5001)
        with pytest.raises(ValueError, match="description exceeds"):
            job.validate()

    def test_job_validate_unknown_platform(self):
        job = self._make_job(platforms=["snapchat"])
        with pytest.raises(ValueError, match="Unknown platform"):
            job.validate()

    def test_job_validate_invalid_scheduled_time(self):
        job = self._make_job(scheduled_time="not-a-date")
        with pytest.raises(ValueError, match="ISO 8601"):
            job.validate()

    def test_job_validate_negative_repeat_interval(self):
        job = self._make_job(repeat_interval_hours=-1)
        with pytest.raises(ValueError, match="non-negative"):
            job.validate()

    def test_job_validate_excessive_repeat_interval(self):
        job = self._make_job(repeat_interval_hours=999)
        with pytest.raises(ValueError, match="cannot exceed 720"):
            job.validate()

    def test_job_validate_platforms_not_list(self):
        job = self._make_job(platforms="youtube")
        with pytest.raises(ValueError, match="platforms must be a list"):
            job.validate()

    @patch("os.path.isfile", return_value=True)
    def test_job_validate_success(self, _mock_isfile):
        job = self._make_job()
        job.validate()  # Should not raise

    def test_job_serialization_roundtrip(self):
        from content_scheduler import ScheduledJob

        job = self._make_job(
            description="desc",
            twitter_text="tweet text",
            tags=["tag1"],
            repeat_interval_hours=24,
        )
        data = job.to_dict()
        restored = ScheduledJob.from_dict(data)
        assert restored.job_id == job.job_id
        assert restored.video_path == job.video_path
        assert restored.title == job.title
        assert restored.platforms == job.platforms
        assert restored.repeat_interval_hours == 24
        assert restored.twitter_text == "tweet text"

    def test_job_to_dict_keys(self):
        job = self._make_job()
        d = job.to_dict()
        expected_keys = {
            "job_id", "video_path", "title", "description", "platforms",
            "twitter_text", "tags", "scheduled_time", "repeat_interval_hours",
            "status", "created_at", "completed_at", "error_message",
        }
        assert set(d.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Configuration helpers tests
# ---------------------------------------------------------------------------

class TestSchedulerConfig:
    """Tests for scheduler configuration helpers."""

    @patch("content_scheduler._get", return_value={})
    def test_get_scheduler_enabled_default(self, _mock):
        from content_scheduler import get_scheduler_enabled
        assert get_scheduler_enabled() is False

    @patch("content_scheduler._get", return_value={"enabled": True})
    def test_get_scheduler_enabled_true(self, _mock):
        from content_scheduler import get_scheduler_enabled
        assert get_scheduler_enabled() is True

    @patch("content_scheduler._get", return_value={})
    def test_get_max_pending_jobs_default(self, _mock):
        from content_scheduler import get_max_pending_jobs
        assert get_max_pending_jobs() == 100

    @patch("content_scheduler._get", return_value={"max_pending_jobs": 9999})
    def test_get_max_pending_jobs_capped(self, _mock):
        from content_scheduler import get_max_pending_jobs
        assert get_max_pending_jobs() == 500  # Hard cap

    @patch("content_scheduler._get", return_value={})
    def test_get_optimal_times_defaults(self, _mock):
        from content_scheduler import get_optimal_times
        times = get_optimal_times("youtube")
        assert "09:00" in times
        assert "12:00" in times

    @patch("content_scheduler._get", return_value={
        "optimal_times": {"youtube": ["08:00", "20:00"]}
    })
    def test_get_optimal_times_configured(self, _mock):
        from content_scheduler import get_optimal_times
        times = get_optimal_times("youtube")
        assert times == ["08:00", "20:00"]

    @patch("content_scheduler._get", return_value={})
    def test_get_optimal_times_unknown_platform(self, _mock):
        from content_scheduler import get_optimal_times
        assert get_optimal_times("unknown") == []

    @patch("content_scheduler._get", return_value={})
    def test_suggest_next_optimal_time_returns_iso(self, _mock):
        from content_scheduler import suggest_next_optimal_time
        result = suggest_next_optimal_time("youtube")
        # Should be a valid ISO datetime
        datetime.fromisoformat(result)


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestSchedulerPersistence:
    """Tests for schedule file read/write."""

    def test_load_schedule_missing_file(self, tmp_path):
        import content_scheduler
        original = content_scheduler._SCHEDULE_FILE
        content_scheduler._SCHEDULE_FILE = str(tmp_path / "nonexistent.json")
        try:
            data = content_scheduler._load_schedule()
            assert data == {"jobs": []}
        finally:
            content_scheduler._SCHEDULE_FILE = original

    def test_load_schedule_corrupt_file(self, tmp_path):
        import content_scheduler
        original = content_scheduler._SCHEDULE_FILE
        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("not valid json{{{")
        content_scheduler._SCHEDULE_FILE = str(corrupt_file)
        try:
            data = content_scheduler._load_schedule()
            assert data == {"jobs": []}
        finally:
            content_scheduler._SCHEDULE_FILE = original

    def test_save_and_load_roundtrip(self, tmp_path):
        import content_scheduler
        original = content_scheduler._SCHEDULE_FILE
        test_file = str(tmp_path / "schedule.json")
        content_scheduler._SCHEDULE_FILE = test_file
        try:
            test_data = {"jobs": [{"job_id": "abc", "status": "pending"}]}
            content_scheduler._save_schedule(test_data)
            loaded = content_scheduler._load_schedule()
            assert loaded == test_data
        finally:
            content_scheduler._SCHEDULE_FILE = original

    def test_save_creates_directory(self, tmp_path):
        import content_scheduler
        original = content_scheduler._SCHEDULE_FILE
        nested = str(tmp_path / "deep" / "nested" / "schedule.json")
        content_scheduler._SCHEDULE_FILE = nested
        try:
            content_scheduler._save_schedule({"jobs": []})
            assert os.path.isfile(nested)
        finally:
            content_scheduler._SCHEDULE_FILE = original


# ---------------------------------------------------------------------------
# ContentScheduler tests
# ---------------------------------------------------------------------------

class TestContentScheduler:
    """Tests for the ContentScheduler class."""

    @pytest.fixture(autouse=True)
    def setup_tmp_schedule(self, tmp_path):
        """Redirect schedule file to temp dir for all tests."""
        import content_scheduler
        self._original_file = content_scheduler._SCHEDULE_FILE
        content_scheduler._SCHEDULE_FILE = str(tmp_path / "schedule.json")
        yield
        content_scheduler._SCHEDULE_FILE = self._original_file

    def _make_job(self, **overrides):
        from content_scheduler import ScheduledJob
        defaults = {
            "video_path": "/tmp/test_video.mp4",
            "title": "Test Video",
            "platforms": ["youtube"],
            "scheduled_time": (datetime.now() + timedelta(hours=1)).isoformat(),
        }
        defaults.update(overrides)
        return ScheduledJob(**defaults)

    @patch("os.path.isfile", return_value=True)
    def test_add_job(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job = self._make_job()
        job_id = scheduler.add_job(job)
        assert job_id == job.job_id

    @patch("os.path.isfile", return_value=True)
    def test_add_job_returns_in_list(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job = self._make_job()
        scheduler.add_job(job)
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].job_id == job.job_id

    @patch("os.path.isfile", return_value=True)
    def test_remove_job(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job = self._make_job()
        scheduler.add_job(job)
        assert scheduler.remove_job(job.job_id) is True
        assert scheduler.list_jobs() == []

    def test_remove_nonexistent_job(self):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        assert scheduler.remove_job("nonexistent") is False

    def test_remove_job_invalid_input(self):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        assert scheduler.remove_job("") is False
        assert scheduler.remove_job(None) is False

    @patch("os.path.isfile", return_value=True)
    def test_list_jobs_filter_by_status(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job1 = self._make_job(title="Job1")
        job2 = self._make_job(title="Job2")
        scheduler.add_job(job1)
        scheduler.add_job(job2)

        pending = scheduler.list_jobs(status="pending")
        assert len(pending) == 2
        completed = scheduler.list_jobs(status="completed")
        assert len(completed) == 0

    @patch("os.path.isfile", return_value=True)
    def test_get_pending_jobs_time_check(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()

        # Job in the past = ready
        past_job = self._make_job(
            title="Past",
            scheduled_time=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        # Job in the future = not ready
        future_job = self._make_job(
            title="Future",
            scheduled_time=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        )
        scheduler.add_job(past_job)
        scheduler.add_job(future_job)

        ready = scheduler.get_pending_jobs()
        assert len(ready) == 1
        assert ready[0].title == "Past"

    @patch("os.path.isfile", return_value=True)
    def test_get_pending_jobs_no_scheduled_time(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job = self._make_job(scheduled_time="")
        scheduler.add_job(job)
        ready = scheduler.get_pending_jobs()
        assert len(ready) == 1  # Immediate jobs are always ready

    @patch("os.path.isfile", return_value=True)
    def test_max_pending_jobs_limit(self, _mock):
        from content_scheduler import ContentScheduler
        import content_scheduler
        scheduler = ContentScheduler()

        # Patch max to 2
        with patch("content_scheduler.get_max_pending_jobs", return_value=2):
            scheduler.add_job(self._make_job(title="J1"))
            scheduler.add_job(self._make_job(title="J2"))
            with pytest.raises(ValueError, match="Maximum pending jobs"):
                scheduler.add_job(self._make_job(title="J3"))

    @patch("os.path.isfile", return_value=True)
    def test_cleanup_completed_removes_old(self, _mock):
        from content_scheduler import ContentScheduler, _load_schedule, _save_schedule
        scheduler = ContentScheduler()

        # Manually insert a completed job with old timestamp
        job = self._make_job()
        data = _load_schedule()
        job_dict = job.to_dict()
        job_dict["status"] = "completed"
        job_dict["completed_at"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        data["jobs"].append(job_dict)
        _save_schedule(data)

        removed = scheduler.cleanup_completed(max_age_days=7)
        assert removed == 1
        assert len(scheduler.list_jobs()) == 0

    @patch("os.path.isfile", return_value=True)
    def test_cleanup_completed_keeps_recent(self, _mock):
        from content_scheduler import ContentScheduler, _load_schedule, _save_schedule
        scheduler = ContentScheduler()

        job = self._make_job()
        data = _load_schedule()
        job_dict = job.to_dict()
        job_dict["status"] = "completed"
        job_dict["completed_at"] = datetime.now().isoformat()
        data["jobs"].append(job_dict)
        _save_schedule(data)

        removed = scheduler.cleanup_completed(max_age_days=7)
        assert removed == 0
        assert len(scheduler.list_jobs()) == 1

    @patch("os.path.isfile", return_value=True)
    def test_execute_job_file_not_found(self, _mock_isfile):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job = self._make_job()
        scheduler.add_job(job)

        # Override isfile to return False during execution
        with patch("os.path.isfile", return_value=False):
            result = scheduler.execute_job(job)

        assert result is False
        jobs = scheduler.list_jobs(status="failed")
        assert len(jobs) == 1

    @patch("os.path.isfile", return_value=True)
    def test_execute_job_success(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job = self._make_job()
        scheduler.add_job(job)

        mock_result = MagicMock()
        mock_result.success = True
        mock_publisher = MagicMock()
        mock_publisher.publish.return_value = [mock_result]

        with patch("publisher.ContentPublisher", return_value=mock_publisher):
            result = scheduler.execute_job(job)

        assert result is True
        completed = scheduler.list_jobs(status="completed")
        assert len(completed) == 1

    @patch("os.path.isfile", return_value=True)
    def test_execute_job_reschedules_on_repeat(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()
        job = self._make_job(repeat_interval_hours=24)
        scheduler.add_job(job)

        mock_result = MagicMock()
        mock_result.success = True
        mock_publisher = MagicMock()
        mock_publisher.publish.return_value = [mock_result]

        with patch("publisher.ContentPublisher", return_value=mock_publisher):
            scheduler.execute_job(job)

        all_jobs = scheduler.list_jobs()
        # Original (now completed) + new rescheduled
        assert len(all_jobs) == 2
        pending = scheduler.list_jobs(status="pending")
        assert len(pending) == 1

    @patch("os.path.isfile", return_value=True)
    def test_run_pending(self, _mock):
        from content_scheduler import ContentScheduler
        scheduler = ContentScheduler()

        # Add a job in the past (ready)
        job = self._make_job(
            scheduled_time=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        )
        scheduler.add_job(job)

        mock_result = MagicMock()
        mock_result.success = True
        mock_publisher = MagicMock()
        mock_publisher.publish.return_value = [mock_result]

        with patch("publisher.ContentPublisher", return_value=mock_publisher):
            summary = scheduler.run_pending()

        assert summary["executed"] == 1
        assert summary["succeeded"] == 1
        assert summary["failed"] == 0


# ---------------------------------------------------------------------------
# Thread safety test
# ---------------------------------------------------------------------------

class TestSchedulerThreadSafety:
    """Test that concurrent operations don't corrupt the schedule."""

    @pytest.fixture(autouse=True)
    def setup_tmp_schedule(self, tmp_path):
        import content_scheduler
        self._original = content_scheduler._SCHEDULE_FILE
        content_scheduler._SCHEDULE_FILE = str(tmp_path / "schedule.json")
        yield
        content_scheduler._SCHEDULE_FILE = self._original

    @patch("os.path.isfile", return_value=True)
    def test_concurrent_add_jobs(self, _mock):
        from content_scheduler import ContentScheduler, ScheduledJob

        scheduler = ContentScheduler()
        errors = []

        def add_jobs(start_idx):
            for i in range(5):
                try:
                    job = ScheduledJob(
                        video_path="/tmp/test.mp4",
                        title=f"Job {start_idx + i}",
                        platforms=["youtube"],
                        scheduled_time=(datetime.now() + timedelta(hours=1)).isoformat(),
                    )
                    scheduler.add_job(job)
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=add_jobs, args=(i * 5,))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        all_jobs = scheduler.list_jobs()
        assert len(all_jobs) == 20  # 4 threads * 5 jobs each


# ---------------------------------------------------------------------------
# Optimal timing and day-of-week weight tests (2026 research update)
# ---------------------------------------------------------------------------

class TestOptimalTimingUpdate:
    """Tests for updated 2026 optimal posting times and day weights."""

    def test_youtube_default_times_updated(self):
        from content_scheduler import _DEFAULT_OPTIMAL_TIMES
        assert _DEFAULT_OPTIMAL_TIMES["youtube"] == ["09:00", "12:00", "17:00"]

    def test_tiktok_default_times_updated(self):
        from content_scheduler import _DEFAULT_OPTIMAL_TIMES
        assert _DEFAULT_OPTIMAL_TIMES["tiktok"] == ["14:00", "17:00", "21:00"]

    def test_twitter_default_times(self):
        from content_scheduler import _DEFAULT_OPTIMAL_TIMES
        assert _DEFAULT_OPTIMAL_TIMES["twitter"] == ["08:00", "12:00", "17:00"]

    def test_instagram_default_times_updated(self):
        from content_scheduler import _DEFAULT_OPTIMAL_TIMES
        assert _DEFAULT_OPTIMAL_TIMES["instagram"] == ["11:00", "14:00", "19:00"]

    def test_day_weights_exist_for_all_platforms(self):
        from content_scheduler import _DAY_WEIGHTS, _ALLOWED_PLATFORMS
        for platform in _ALLOWED_PLATFORMS:
            assert platform in _DAY_WEIGHTS

    def test_day_weights_cover_all_days(self):
        from content_scheduler import _DAY_WEIGHTS
        for platform, weights in _DAY_WEIGHTS.items():
            for day in range(7):
                assert day in weights, f"Missing day {day} for {platform}"

    def test_day_weights_bounded_0_to_1(self):
        from content_scheduler import _DAY_WEIGHTS
        for platform, weights in _DAY_WEIGHTS.items():
            for day, weight in weights.items():
                assert 0.0 <= weight <= 1.0, (
                    f"{platform} day {day} weight {weight} out of bounds"
                )

    def test_midweek_weights_highest(self):
        """Tue-Thu (days 1-3) should have highest weights for all platforms."""
        from content_scheduler import _DAY_WEIGHTS
        for platform, weights in _DAY_WEIGHTS.items():
            midweek_min = min(weights[d] for d in [1, 2, 3])
            assert midweek_min == 1.0, f"{platform} midweek not 1.0"


class TestGetBestPostingTime:
    """Tests for get_best_posting_time()."""

    def test_returns_dict_with_expected_keys(self):
        from content_scheduler import get_best_posting_time
        result = get_best_posting_time("youtube")
        assert "time" in result
        assert "weight" in result
        assert "platform" in result
        assert "day_name" in result

    def test_returns_valid_time_format(self):
        from content_scheduler import get_best_posting_time
        result = get_best_posting_time("youtube")
        parts = result["time"].split(":")
        assert len(parts) == 2
        assert 0 <= int(parts[0]) <= 23
        assert 0 <= int(parts[1]) <= 59

    def test_weight_is_float_in_range(self):
        from content_scheduler import get_best_posting_time
        result = get_best_posting_time("tiktok")
        assert isinstance(result["weight"], float)
        assert 0.0 <= result["weight"] <= 1.0

    def test_platform_name_returned(self):
        from content_scheduler import get_best_posting_time
        result = get_best_posting_time("Instagram")
        assert result["platform"] == "instagram"

    def test_unknown_platform_raises(self):
        from content_scheduler import get_best_posting_time
        with pytest.raises(ValueError, match="Unknown platform"):
            get_best_posting_time("fakebook")

    @patch("content_scheduler._get")
    def test_weekday_vs_weekend_different_weights(self, mock_get):
        from content_scheduler import get_best_posting_time
        from datetime import timezone
        mock_get.return_value = {}

        # Tuesday (day 1) — weight 1.0
        tuesday = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
        result_tue = get_best_posting_time("youtube", target_date=tuesday)

        # Saturday (day 5) — weight 0.7
        saturday = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)
        result_sat = get_best_posting_time("youtube", target_date=saturday)

        assert result_tue["weight"] > result_sat["weight"]
        assert result_tue["day_name"] == "Tuesday"
        assert result_sat["day_name"] == "Saturday"

    @patch("content_scheduler._get")
    def test_each_platform_returns_result(self, mock_get):
        from content_scheduler import get_best_posting_time, _ALLOWED_PLATFORMS
        mock_get.return_value = {}
        for platform in _ALLOWED_PLATFORMS:
            result = get_best_posting_time(platform)
            assert result["platform"] == platform

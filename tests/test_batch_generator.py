"""Tests for the batch video generation module."""

import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# BatchJob validation tests
# ---------------------------------------------------------------------------

class TestBatchJobValidation:
    """Tests for BatchJob.validate()."""

    def _make_job(self, **kwargs):
        from batch_generator import BatchJob
        defaults = {
            "topics": ["topic1"],
            "niche": "general",
            "language": "en",
        }
        defaults.update(kwargs)
        return BatchJob(**defaults)

    def test_valid_job_passes(self):
        job = self._make_job()
        job.validate()  # Should not raise

    def test_empty_topics_raises(self):
        job = self._make_job(topics=[])
        with pytest.raises(ValueError, match="must not be empty"):
            job.validate()

    def test_non_list_topics_raises(self):
        job = self._make_job(topics="not a list")
        with pytest.raises(ValueError, match="must be a list"):
            job.validate()

    def test_too_many_topics_raises(self):
        job = self._make_job(topics=["t"] * 51)
        with pytest.raises(ValueError, match="Too many topics"):
            job.validate()

    def test_50_topics_passes(self):
        job = self._make_job(topics=[f"topic{i}" for i in range(50)])
        job.validate()  # Should not raise

    def test_empty_string_topic_raises(self):
        job = self._make_job(topics=["valid", ""])
        with pytest.raises(ValueError, match="non-empty string"):
            job.validate()

    def test_null_byte_in_topic_raises(self):
        job = self._make_job(topics=["valid\x00topic"])
        with pytest.raises(ValueError, match="null bytes"):
            job.validate()

    def test_topic_too_long_raises(self):
        job = self._make_job(topics=["x" * 501])
        with pytest.raises(ValueError, match="maximum length"):
            job.validate()

    def test_niche_too_long_raises(self):
        job = self._make_job(niche="x" * 201)
        with pytest.raises(ValueError, match="niche exceeds"):
            job.validate()

    def test_language_too_long_raises(self):
        job = self._make_job(language="x" * 11)
        with pytest.raises(ValueError, match="language code exceeds"):
            job.validate()

    def test_invalid_platform_raises(self):
        job = self._make_job(publish_platforms=["youtube", "fakebook"])
        with pytest.raises(ValueError, match="Unknown publish platform"):
            job.validate()

    def test_valid_platforms_pass(self):
        job = self._make_job(
            publish_platforms=["youtube", "tiktok", "twitter", "instagram"]
        )
        job.validate()  # Should not raise


# ---------------------------------------------------------------------------
# Configuration helper tests
# ---------------------------------------------------------------------------

class TestBatchConfigHelpers:
    """Tests for batch configuration helpers."""

    @patch("batch_generator._get")
    def test_get_max_videos_per_run_default(self, mock_get):
        from batch_generator import get_max_videos_per_run
        mock_get.return_value = {}
        result = get_max_videos_per_run()
        assert result == 10

    @patch("batch_generator._get")
    def test_get_max_videos_per_run_capped(self, mock_get):
        from batch_generator import get_max_videos_per_run
        mock_get.return_value = {"max_videos_per_run": 999}
        result = get_max_videos_per_run()
        assert result == 50

    @patch("batch_generator._get")
    def test_get_max_videos_per_run_minimum(self, mock_get):
        from batch_generator import get_max_videos_per_run
        mock_get.return_value = {"max_videos_per_run": 0}
        result = get_max_videos_per_run()
        assert result == 1

    @patch("batch_generator._get")
    def test_get_delay_default(self, mock_get):
        from batch_generator import get_delay_between_videos
        mock_get.return_value = {}
        result = get_delay_between_videos()
        assert result == 30

    @patch("batch_generator._get")
    def test_get_delay_capped_high(self, mock_get):
        from batch_generator import get_delay_between_videos
        mock_get.return_value = {"delay_between_videos": 9999}
        result = get_delay_between_videos()
        assert result == 600

    @patch("batch_generator._get")
    def test_get_delay_capped_low(self, mock_get):
        from batch_generator import get_delay_between_videos
        mock_get.return_value = {"delay_between_videos": 1}
        result = get_delay_between_videos()
        assert result == 10


# ---------------------------------------------------------------------------
# BatchResult tests
# ---------------------------------------------------------------------------

class TestBatchResult:
    """Tests for BatchResult data class methods."""

    def test_to_dict(self):
        from batch_generator import BatchResult, BatchVideoResult
        result = BatchResult(
            total=2,
            succeeded=1,
            failed=1,
            published=1,
            started_at="2026-03-25T10:00:00Z",
            completed_at="2026-03-25T10:05:00Z",
            duration_seconds=300.123,
            videos=[
                BatchVideoResult(
                    topic="topic1", success=True, published=True
                ),
                BatchVideoResult(
                    topic="topic2", success=False, error_type="TestError"
                ),
            ],
        )
        d = result.to_dict()
        assert d["total"] == 2
        assert d["succeeded"] == 1
        assert d["failed"] == 1
        assert d["duration_seconds"] == 300.12
        assert len(d["videos"]) == 2

    def test_to_text(self):
        from batch_generator import BatchResult
        result = BatchResult(
            total=3,
            succeeded=2,
            failed=1,
            started_at="2026-03-25T10:00:00Z",
            completed_at="2026-03-25T10:05:00Z",
            duration_seconds=300.0,
        )
        text = result.to_text()
        assert "Batch Generation Report" in text
        assert "Succeeded: 2" in text
        assert "Failed: 1" in text

    def test_to_dict_truncates_long_topics(self):
        from batch_generator import BatchResult, BatchVideoResult
        result = BatchResult(
            total=1,
            videos=[
                BatchVideoResult(topic="x" * 500, success=True),
            ],
        )
        d = result.to_dict()
        assert len(d["videos"][0]["topic"]) <= 100


# ---------------------------------------------------------------------------
# BatchGenerator run tests
# ---------------------------------------------------------------------------

class TestBatchGeneratorRun:
    """Tests for BatchGenerator.run()."""

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_returns_batch_result(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob

        gen = BatchGenerator()
        gen._delay = 0  # Override for test speed

        job = BatchJob(topics=["topic1", "topic2"])

        with patch.object(gen, "_generate_single") as mock_gen:
            from batch_generator import BatchVideoResult
            mock_gen.return_value = BatchVideoResult(
                topic="topic", success=True, video_path="/tmp/v.mp4"
            )
            with patch.object(gen, "_track_batch_analytics"):
                with patch("batch_generator.time.sleep"):
                    result = gen.run(job)

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0

    @patch("batch_generator.get_max_videos_per_run", return_value=2)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_caps_topics_to_max_per_run(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["t1", "t2", "t3", "t4", "t5"])

        with patch.object(gen, "_generate_single") as mock_gen:
            from batch_generator import BatchVideoResult
            mock_gen.return_value = BatchVideoResult(
                topic="t", success=True
            )
            with patch.object(gen, "_track_batch_analytics"):
                with patch("batch_generator.time.sleep"):
                    result = gen.run(job)

        assert result.total == 2  # Capped to max_per_run

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_counts_failures(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["good", "bad"])

        call_count = [0]

        def fake_generate(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return BatchVideoResult(topic="good", success=True)
            return BatchVideoResult(
                topic="bad", success=False, error_type="TestError"
            )

        with patch.object(gen, "_generate_single", side_effect=fake_generate):
            with patch.object(gen, "_track_batch_analytics"):
                with patch("batch_generator.time.sleep"):
                    result = gen.run(job)

        assert result.succeeded == 1
        assert result.failed == 1

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_tracks_analytics(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["t1"])

        with patch.object(gen, "_generate_single") as mock_gen:
            mock_gen.return_value = BatchVideoResult(topic="t1", success=True)
            with patch.object(gen, "_track_batch_analytics") as mock_track:
                with patch("batch_generator.time.sleep"):
                    gen.run(job)

        mock_track.assert_called_once()


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestBatchJobEdgeCases:
    """Edge case tests for BatchJob.validate()."""

    def _make_job(self, **kwargs):
        from batch_generator import BatchJob
        defaults = {
            "topics": ["topic1"],
            "niche": "general",
            "language": "en",
        }
        defaults.update(kwargs)
        return BatchJob(**defaults)

    def test_whitespace_only_topic_raises(self):
        job = self._make_job(topics=[" "])
        with pytest.raises(ValueError, match="non-empty string"):
            job.validate()

    def test_none_topic_raises(self):
        job = self._make_job(topics=[None])
        with pytest.raises(ValueError, match="non-empty string"):
            job.validate()

    def test_integer_topic_raises(self):
        job = self._make_job(topics=[123])
        with pytest.raises(ValueError, match="non-empty string"):
            job.validate()

    def test_niche_non_string_raises(self):
        job = self._make_job(niche=123)
        with pytest.raises(ValueError, match="niche must be a string"):
            job.validate()

    def test_language_non_string_raises(self):
        job = self._make_job(language=123)
        with pytest.raises(ValueError, match="language must be a string"):
            job.validate()

    def test_duplicate_topics_passes(self):
        job = self._make_job(topics=["same", "same"])
        job.validate()  # Should not raise

    def test_topic_at_exact_max_length_passes(self):
        job = self._make_job(topics=["x" * 500])
        job.validate()  # Should not raise

    def test_single_topic_passes(self):
        job = self._make_job(topics=["one"])
        job.validate()  # Should not raise


# ---------------------------------------------------------------------------
# Data class defaults tests
# ---------------------------------------------------------------------------

class TestDataClassDefaults:
    """Tests for BatchVideoResult and BatchResult data class defaults."""

    def test_batch_video_result_defaults(self):
        from batch_generator import BatchVideoResult
        result = BatchVideoResult(topic="t", success=False)
        assert result.video_path == ""
        assert result.error_type == ""
        assert result.duration_seconds == 0.0
        assert result.published is False
        assert result.publish_results == []

    def test_batch_result_empty_videos_to_dict(self):
        from batch_generator import BatchResult
        result = BatchResult(total=0)
        d = result.to_dict()
        assert d["videos"] == []

    def test_batch_result_zero_duration_to_text(self):
        from batch_generator import BatchResult
        result = BatchResult(
            total=1,
            succeeded=1,
            failed=0,
            started_at="2026-03-27T00:00:00Z",
            completed_at="2026-03-27T00:00:00Z",
            duration_seconds=0.0,
        )
        text = result.to_text()
        assert "Batch Generation Report" in text
        assert "0.0s" in text


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------

class TestBatchGeneratorIntegration:
    """Integration-style tests for BatchGenerator methods."""

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=["youtube"])
    def test_auto_publish_when_job_flag_true(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(
            topics=["topic1"],
            auto_publish=True,
            publish_platforms=["youtube"],
        )

        success_result = BatchVideoResult(
            topic="topic1", success=True, video_path="/tmp/v.mp4"
        )

        with patch.object(gen, "_generate_single", return_value=success_result):
            with patch.object(gen, "_auto_publish_video", return_value=success_result) as mock_publish:
                with patch.object(gen, "_track_batch_analytics"):
                    with patch("batch_generator.time.sleep"):
                        gen.run(job)

        mock_publish.assert_called_once()

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=True)
    @patch("batch_generator.get_publish_platforms", return_value=["youtube"])
    def test_auto_publish_when_config_flag_true(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["topic1"])

        success_result = BatchVideoResult(
            topic="topic1", success=True, video_path="/tmp/v.mp4"
        )

        with patch.object(gen, "_generate_single", return_value=success_result):
            with patch.object(gen, "_auto_publish_video", return_value=success_result) as mock_publish:
                with patch.object(gen, "_track_batch_analytics"):
                    with patch("batch_generator.time.sleep"):
                        gen.run(job)

        mock_publish.assert_called_once()

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=["youtube"])
    def test_auto_publish_skipped_on_failure(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(
            topics=["topic1"],
            auto_publish=True,
            publish_platforms=["youtube"],
        )

        fail_result = BatchVideoResult(
            topic="topic1", success=False, error_type="TestError"
        )

        with patch.object(gen, "_generate_single", return_value=fail_result):
            with patch.object(gen, "_auto_publish_video") as mock_publish:
                with patch.object(gen, "_track_batch_analytics"):
                    with patch("batch_generator.time.sleep"):
                        gen.run(job)

        mock_publish.assert_not_called()

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_auto_publish_skipped_when_no_platforms(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0

        # auto_publish=True but no platforms on job, and config returns []
        job = BatchJob(
            topics=["topic1"],
            auto_publish=True,
            publish_platforms=[],
        )

        success_result = BatchVideoResult(
            topic="topic1", success=True, video_path="/tmp/v.mp4"
        )

        with patch.object(gen, "_generate_single", return_value=success_result):
            with patch.object(gen, "_auto_publish_video") as mock_publish:
                with patch.object(gen, "_track_batch_analytics"):
                    with patch("batch_generator.time.sleep"):
                        gen.run(job)

        mock_publish.assert_not_called()

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_generate_single_no_accounts(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["topic1"])

        with patch("batch_generator.time.sleep"):
            with patch.object(gen, "_track_batch_analytics"):
                # Patch cache.get_accounts inside _generate_single's import scope
                import sys
                mock_cache = MagicMock()
                mock_cache.get_accounts.return_value = []
                with patch.dict(sys.modules, {"cache": mock_cache, "classes.YouTube": MagicMock(), "classes.Tts": MagicMock()}):
                    result = gen._generate_single(
                        topic="topic1", niche="general", language="en"
                    )

        assert result.success is False
        assert result.error_type == "NoYouTubeAccountConfigured"

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_generate_single_exception(self, *mocks):
        from batch_generator import BatchGenerator

        gen = BatchGenerator()

        import sys
        with patch.dict(sys.modules, {"classes.YouTube": None, "classes.Tts": None, "cache": None}):
            result = gen._generate_single(
                topic="topic1", niche="general", language="en"
            )

        assert result.success is False
        assert result.error_type != ""

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=["youtube"])
    def test_auto_publish_exception_handling(self, *mocks):
        from batch_generator import BatchGenerator, BatchVideoResult

        gen = BatchGenerator()

        video_result = BatchVideoResult(
            topic="topic1", success=True, video_path="/tmp/v.mp4"
        )

        import sys
        mock_publisher_module = MagicMock()
        mock_publisher_module.ContentPublisher.side_effect = RuntimeError("Publisher down")

        with patch.dict(sys.modules, {"publisher": mock_publisher_module}):
            # Should not raise even if publisher fails
            returned = gen._auto_publish_video(
                video_result, "topic1", ["youtube"]
            )

        assert returned is not None
        assert returned.topic == "topic1"

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_track_batch_analytics_success(self, *mocks):
        from batch_generator import BatchGenerator, BatchResult

        gen = BatchGenerator()

        result = BatchResult(
            total=1,
            succeeded=1,
            failed=0,
            published=0,
            duration_seconds=10.0,
        )

        import sys
        mock_analytics = MagicMock()
        with patch.dict(sys.modules, {"analytics": mock_analytics}):
            gen._track_batch_analytics(result)

        mock_analytics.track_event.assert_called_once()

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_track_batch_analytics_silent_failure(self, *mocks):
        from batch_generator import BatchGenerator, BatchResult

        gen = BatchGenerator()

        result = BatchResult(total=1, succeeded=1, duration_seconds=5.0)

        import sys
        mock_analytics = MagicMock()
        mock_analytics.track_event.side_effect = RuntimeError("analytics down")
        with patch.dict(sys.modules, {"analytics": mock_analytics}):
            # Must not raise
            gen._track_batch_analytics(result)

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_calls_sleep_between_videos(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 5

        job = BatchJob(topics=["t1", "t2"])

        with patch.object(gen, "_generate_single") as mock_gen:
            mock_gen.return_value = BatchVideoResult(topic="t", success=True)
            with patch.object(gen, "_track_batch_analytics"):
                with patch("batch_generator.time.sleep") as mock_sleep:
                    gen.run(job)

        # sleep should be called exactly once: between t1 and t2, not after t2
        mock_sleep.assert_called_once_with(5)

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_all_failures_shows_warning(self, *mocks):
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["t1", "t2"])

        with patch.object(gen, "_generate_single") as mock_gen:
            mock_gen.return_value = BatchVideoResult(
                topic="t", success=False, error_type="TestError"
            )
            with patch.object(gen, "_track_batch_analytics"):
                with patch("batch_generator.time.sleep"):
                    with patch("batch_generator.warning") as mock_warning:
                        gen.run(job)

        mock_warning.assert_called_once()


# ---------------------------------------------------------------------------
# Health reporting tests (H59)
# ---------------------------------------------------------------------------

class TestBatchHealthReporting:
    """Tests that BatchGenerator integrates with PipelineHealthMonitor (H59)."""

    def setup_method(self):
        import batch_generator
        batch_generator._get_health_monitor._instance = None
        batch_generator.get_plugin_manager._instance = None

    def teardown_method(self):
        import batch_generator
        batch_generator._get_health_monitor._instance = None
        batch_generator.get_plugin_manager._instance = None

    def _run_with_results(self, gen, job, video_results, mock_monitor):
        """Helper to run batch with mocked single results and health monitor."""
        import batch_generator
        results_iter = iter(video_results)

        with patch.object(batch_generator, "_get_health_monitor", return_value=mock_monitor):
            with patch.object(batch_generator, "get_plugin_manager", return_value=None):
                with patch.object(gen, "_generate_single", side_effect=lambda **kw: next(results_iter)):
                    with patch.object(gen, "_track_batch_analytics"):
                        with patch("batch_generator.time.sleep"):
                            return gen.run(job)

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_all_succeed_reports_ok(self, *mocks):
        """When no failures, report_health('batch_generator', 'ok')."""
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0
        job = BatchJob(topics=["t1", "t2"])

        mock_monitor = MagicMock()
        results = [
            BatchVideoResult(topic="t1", success=True),
            BatchVideoResult(topic="t2", success=True),
        ]
        self._run_with_results(gen, job, results, mock_monitor)

        mock_monitor.report_health.assert_called_once()
        call_args = mock_monitor.report_health.call_args
        assert call_args[0][0] == "batch_generator"
        assert call_args[0][1] == "ok"

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_all_fail_reports_error(self, *mocks):
        """When all fail, report_health with 'error'."""
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0
        job = BatchJob(topics=["t1", "t2"])

        mock_monitor = MagicMock()
        results = [
            BatchVideoResult(topic="t1", success=False, error_type="Err"),
            BatchVideoResult(topic="t2", success=False, error_type="Err"),
        ]
        self._run_with_results(gen, job, results, mock_monitor)

        mock_monitor.report_health.assert_called_once()
        call_args = mock_monitor.report_health.call_args
        assert call_args[0][0] == "batch_generator"
        assert call_args[0][1] == "error"

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_run_partial_fail_reports_degraded(self, *mocks):
        """Mix of success/failure → report_health with 'degraded'."""
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0
        job = BatchJob(topics=["t1", "t2"])

        mock_monitor = MagicMock()
        results = [
            BatchVideoResult(topic="t1", success=True),
            BatchVideoResult(topic="t2", success=False, error_type="Err"),
        ]
        self._run_with_results(gen, job, results, mock_monitor)

        mock_monitor.report_health.assert_called_once()
        call_args = mock_monitor.report_health.call_args
        assert call_args[0][0] == "batch_generator"
        assert call_args[0][1] == "degraded"

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_health_metadata_includes_counts(self, *mocks):
        """Metadata passed to report_health includes total, succeeded, failed, duration_seconds."""
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        gen = BatchGenerator()
        gen._delay = 0
        job = BatchJob(topics=["t1", "t2", "t3"])

        mock_monitor = MagicMock()
        results = [
            BatchVideoResult(topic="t1", success=True),
            BatchVideoResult(topic="t2", success=True),
            BatchVideoResult(topic="t3", success=False, error_type="Err"),
        ]
        self._run_with_results(gen, job, results, mock_monitor)

        call_kwargs = mock_monitor.report_health.call_args[1]
        metadata = call_kwargs.get("metadata", {})
        assert "total" in metadata
        assert "succeeded" in metadata
        assert "failed" in metadata
        assert "duration_seconds" in metadata
        assert metadata["total"] == 3
        assert metadata["succeeded"] == 2
        assert metadata["failed"] == 1

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_health_exception_does_not_block_run(self, *mocks):
        """If monitor raises, run() still returns a BatchResult."""
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult, BatchResult

        gen = BatchGenerator()
        gen._delay = 0
        job = BatchJob(topics=["t1"])

        mock_monitor = MagicMock()
        mock_monitor.report_health.side_effect = RuntimeError("monitor down")

        results = [BatchVideoResult(topic="t1", success=True)]
        result = self._run_with_results(gen, job, results, mock_monitor)

        assert isinstance(result, BatchResult)
        assert result.total == 1


# ---------------------------------------------------------------------------
# Plugin dispatch tests (H61)
# ---------------------------------------------------------------------------

class TestBatchPluginDispatch:
    """Tests that BatchGenerator dispatches plugin hooks (H61)."""

    def setup_method(self):
        import batch_generator
        batch_generator._get_health_monitor._instance = None
        batch_generator.get_plugin_manager._instance = None

    def teardown_method(self):
        import batch_generator
        batch_generator._get_health_monitor._instance = None
        batch_generator.get_plugin_manager._instance = None

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_on_batch_start_called(self, *mocks):
        """on_batch_start is called with topics_count, niche, language, auto_publish."""
        import batch_generator
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        mock_pm = MagicMock()
        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["t1", "t2"], niche="finance", language="en", auto_publish=False)

        with patch.object(batch_generator, "get_plugin_manager", return_value=mock_pm):
            with patch.object(batch_generator, "_get_health_monitor", return_value=None):
                with patch.object(gen, "_generate_single") as mock_gen:
                    mock_gen.return_value = BatchVideoResult(topic="t", success=True)
                    with patch.object(gen, "_track_batch_analytics"):
                        with patch("batch_generator.time.sleep"):
                            gen.run(job)

        mock_pm.hook.on_batch_start.assert_called_once()
        call_kwargs = mock_pm.hook.on_batch_start.call_args[1]
        job_arg = call_kwargs.get("job", {})
        assert job_arg.get("topics_count") == 2
        assert job_arg.get("niche") == "finance"
        assert job_arg.get("language") == "en"
        assert "auto_publish" in job_arg

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_on_batch_complete_called(self, *mocks):
        """on_batch_complete is called with a result dict."""
        import batch_generator
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult

        mock_pm = MagicMock()
        gen = BatchGenerator()
        gen._delay = 0

        job = BatchJob(topics=["t1"])

        with patch.object(batch_generator, "get_plugin_manager", return_value=mock_pm):
            with patch.object(batch_generator, "_get_health_monitor", return_value=None):
                with patch.object(gen, "_generate_single") as mock_gen:
                    mock_gen.return_value = BatchVideoResult(topic="t1", success=True)
                    with patch.object(gen, "_track_batch_analytics"):
                        with patch("batch_generator.time.sleep"):
                            gen.run(job)

        mock_pm.hook.on_batch_complete.assert_called_once()
        call_kwargs = mock_pm.hook.on_batch_complete.call_args[1]
        assert "result" in call_kwargs
        result_dict = call_kwargs["result"]
        assert isinstance(result_dict, dict)
        assert "total" in result_dict

    @patch("batch_generator.get_max_videos_per_run", return_value=10)
    @patch("batch_generator.get_delay_between_videos", return_value=0)
    @patch("batch_generator.get_auto_publish", return_value=False)
    @patch("batch_generator.get_publish_platforms", return_value=[])
    def test_plugin_exception_does_not_block_run(self, *mocks):
        """If plugin raises, run() still returns a BatchResult."""
        import batch_generator
        from batch_generator import BatchGenerator, BatchJob, BatchVideoResult, BatchResult

        mock_pm = MagicMock()
        mock_pm.hook.on_batch_start.side_effect = RuntimeError("plugin exploded")

        gen = BatchGenerator()
        gen._delay = 0
        job = BatchJob(topics=["t1"])

        with patch.object(batch_generator, "get_plugin_manager", return_value=mock_pm):
            with patch.object(batch_generator, "_get_health_monitor", return_value=None):
                with patch.object(gen, "_generate_single") as mock_gen:
                    mock_gen.return_value = BatchVideoResult(topic="t1", success=True)
                    with patch.object(gen, "_track_batch_analytics"):
                        with patch("batch_generator.time.sleep"):
                            result = gen.run(job)  # Must not raise

        assert isinstance(result, BatchResult)
        assert result.total == 1

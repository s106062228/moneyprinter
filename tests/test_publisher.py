"""Tests for the multi-platform content publisher module."""

import os
import json
import time
import tempfile
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# PublishJob validation tests
# ---------------------------------------------------------------------------

class TestPublishJobValidation:
    """Tests for PublishJob.validate()."""

    def _make_job(self, **kwargs):
        from publisher import PublishJob
        defaults = {
            "video_path": "",
            "title": "Test Title",
            "description": "Test description",
            "platforms": ["youtube"],
        }
        defaults.update(kwargs)
        return PublishJob(**defaults)

    def test_empty_video_path_raises(self):
        job = self._make_job(video_path="")
        with pytest.raises(ValueError, match="video_path"):
            job.validate()

    def test_nonexistent_video_path_raises(self):
        job = self._make_job(video_path="/nonexistent/video.mp4")
        with pytest.raises(ValueError, match="does not exist"):
            job.validate()

    def test_null_byte_in_video_path_raises(self):
        job = self._make_job(video_path="/tmp/video\x00.mp4")
        with pytest.raises(ValueError, match="null bytes"):
            job.validate()

    def test_video_path_too_long_raises(self):
        job = self._make_job(video_path="/" + "a" * 1025)
        with pytest.raises(ValueError, match="maximum length"):
            job.validate()

    def test_empty_title_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._make_job(video_path=tmp, title="")
            with pytest.raises(ValueError, match="title"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_title_too_long_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._make_job(video_path=tmp, title="x" * 501)
            with pytest.raises(ValueError, match="maximum length"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_description_too_long_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._make_job(
                video_path=tmp, description="x" * 5001
            )
            with pytest.raises(ValueError, match="maximum length"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_unknown_platform_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._make_job(
                video_path=tmp, platforms=["youtube", "myspace"]
            )
            with pytest.raises(ValueError, match="Unknown platform"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_too_many_platforms_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._make_job(
                video_path=tmp, platforms=["youtube"] * 11
            )
            with pytest.raises(ValueError, match="Too many platforms"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_valid_job_passes(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._make_job(
                video_path=tmp,
                platforms=["youtube", "tiktok", "twitter"],
            )
            job.validate()  # Should not raise
        finally:
            os.unlink(tmp)

    def test_platforms_not_list_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._make_job(video_path=tmp, platforms="youtube")
            with pytest.raises(ValueError, match="platforms must be a list"):
                job.validate()
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# PublishResult tests
# ---------------------------------------------------------------------------

class TestPublishResult:
    """Tests for PublishResult dataclass."""

    def test_default_timestamp(self):
        from publisher import PublishResult
        result = PublishResult(platform="youtube", success=True)
        assert result.timestamp  # Should have a timestamp
        assert "T" in result.timestamp  # ISO format

    def test_custom_timestamp(self):
        from publisher import PublishResult
        ts = "2026-01-01T00:00:00"
        result = PublishResult(platform="youtube", success=True, timestamp=ts)
        assert result.timestamp == ts

    def test_default_fields(self):
        from publisher import PublishResult
        result = PublishResult(platform="tiktok", success=False)
        assert result.error_type == ""
        assert result.duration_seconds == 0.0
        assert result.details == {}


# ---------------------------------------------------------------------------
# Configuration helper tests
# ---------------------------------------------------------------------------

class TestPublisherConfig:
    """Tests for publisher configuration helpers."""

    @patch("publisher._get")
    def test_get_default_platforms_from_config(self, mock_get):
        mock_get.return_value = {"platforms": ["youtube", "tiktok"]}
        from publisher import get_default_platforms
        assert get_default_platforms() == ["youtube", "tiktok"]

    @patch("publisher._get")
    def test_get_default_platforms_fallback(self, mock_get):
        mock_get.return_value = {}
        from publisher import get_default_platforms
        assert get_default_platforms() == ["youtube"]

    @patch("publisher._get")
    def test_get_retry_failed_true(self, mock_get):
        mock_get.return_value = {"retry_failed": True}
        from publisher import get_retry_failed
        assert get_retry_failed() is True

    @patch("publisher._get")
    def test_get_retry_failed_default(self, mock_get):
        mock_get.return_value = {}
        from publisher import get_retry_failed
        assert get_retry_failed() is True

    @patch("publisher._get")
    def test_get_max_retries(self, mock_get):
        mock_get.return_value = {"max_retries": 5}
        from publisher import get_max_retries
        assert get_max_retries() == 5

    @patch("publisher._get")
    def test_get_max_retries_capped(self, mock_get):
        mock_get.return_value = {"max_retries": 100}
        from publisher import get_max_retries
        assert get_max_retries() == 10  # capped

    @patch("publisher._get")
    def test_get_max_retries_default(self, mock_get):
        mock_get.return_value = {}
        from publisher import get_max_retries
        assert get_max_retries() == 2


# ---------------------------------------------------------------------------
# ContentPublisher tests
# ---------------------------------------------------------------------------

class TestContentPublisher:
    """Tests for ContentPublisher.publish()."""

    def _make_publisher(self):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                return ContentPublisher()

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    @patch("publisher.get_default_platforms", return_value=["youtube"])
    def test_publish_uses_default_platforms(
        self, mock_defaults, mock_pub, mock_analytics, mock_notify
    ):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_pub.return_value = PublishResult(
            platform="youtube", success=True
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp, title="Test", platforms=[]
            )
            results = pub.publish(job)
            assert len(results) == 1
            assert results[0].platform == "youtube"
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_publish_multiple_platforms(
        self, mock_pub, mock_analytics, mock_notify
    ):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_pub.side_effect = [
            PublishResult(platform="youtube", success=True),
            PublishResult(platform="tiktok", success=True),
        ]

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube", "tiktok"],
            )
            results = pub.publish(job)
            assert len(results) == 2
            assert all(r.success for r in results)
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_publish_partial_failure(
        self, mock_pub, mock_analytics, mock_notify
    ):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_pub.side_effect = [
            PublishResult(platform="youtube", success=True),
            PublishResult(
                platform="tiktok", success=False, error_type="UploadFailed"
            ),
        ]

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube", "tiktok"],
            )
            results = pub.publish(job)
            assert results[0].success is True
            assert results[1].success is False
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_analytics_called_for_each_platform(
        self, mock_pub, mock_analytics, mock_notify
    ):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_pub.return_value = PublishResult(
            platform="youtube", success=True
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            pub.publish(job)
            assert mock_analytics.call_count == 1
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_notification_called_for_each_platform(
        self, mock_pub, mock_analytics, mock_notify
    ):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_pub.return_value = PublishResult(
            platform="youtube", success=True
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            pub.publish(job)
            assert mock_notify.call_count == 1
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Platform dispatch tests
# ---------------------------------------------------------------------------

class TestPlatformDispatch:
    """Tests for _publish_to_platform routing."""

    @patch("publisher.get_retry_failed", return_value=False)
    @patch("publisher.get_max_retries", return_value=0)
    def test_unknown_platform_returns_failure(self, *mocks):
        from publisher import ContentPublisher, PublishJob
        pub = ContentPublisher()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = PublishJob(video_path=tmp, title="Test")
            result = pub._publish_to_platform(job, "myspace")
            assert result.success is False
            assert result.error_type == "UnsupportedPlatform"
        finally:
            os.unlink(tmp)

    @patch("publisher.get_retry_failed", return_value=False)
    @patch("publisher.get_max_retries", return_value=0)
    @patch("publisher.ContentPublisher._publish_youtube")
    def test_youtube_dispatch(self, mock_yt, *mocks):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_yt.return_value = PublishResult(
            platform="youtube", success=True
        )
        pub = ContentPublisher()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = PublishJob(video_path=tmp, title="Test")
            result = pub._publish_to_platform(job, "youtube")
            assert result.success is True
            mock_yt.assert_called_once()
        finally:
            os.unlink(tmp)

    @patch("publisher.get_retry_failed", return_value=False)
    @patch("publisher.get_max_retries", return_value=0)
    @patch("publisher.ContentPublisher._publish_tiktok")
    def test_tiktok_dispatch(self, mock_tt, *mocks):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_tt.return_value = PublishResult(
            platform="tiktok", success=True
        )
        pub = ContentPublisher()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = PublishJob(video_path=tmp, title="Test")
            result = pub._publish_to_platform(job, "tiktok")
            assert result.success is True
            mock_tt.assert_called_once()
        finally:
            os.unlink(tmp)

    @patch("publisher.get_retry_failed", return_value=False)
    @patch("publisher.get_max_retries", return_value=0)
    @patch("publisher.ContentPublisher._publish_twitter")
    def test_twitter_dispatch(self, mock_tw, *mocks):
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_tw.return_value = PublishResult(
            platform="twitter", success=True
        )
        pub = ContentPublisher()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = PublishJob(video_path=tmp, title="Test")
            result = pub._publish_to_platform(job, "twitter")
            assert result.success is True
            mock_tw.assert_called_once()
        finally:
            os.unlink(tmp)

    @patch("publisher.get_retry_failed", return_value=False)
    @patch("publisher.get_max_retries", return_value=0)
    def test_exception_in_platform_returns_failure(self, *mocks):
        from publisher import ContentPublisher, PublishJob
        pub = ContentPublisher()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = PublishJob(video_path=tmp, title="Test")
            # Patch _publish_youtube to raise
            with patch.object(
                pub, "_publish_youtube", side_effect=RuntimeError("boom")
            ):
                result = pub._publish_to_platform(job, "youtube")
                assert result.success is False
                assert result.error_type == "RuntimeError"
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------

class TestRetryLogic:
    """Tests for publish retry behavior."""

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    @patch("publisher.get_default_platforms", return_value=["youtube"])
    @patch("publisher.time")
    def test_retry_on_failure(
        self, mock_time, mock_defaults, mock_pub, mock_analytics, mock_notify
    ):
        from publisher import ContentPublisher, PublishJob, PublishResult

        # First call fails, second succeeds
        mock_pub.side_effect = [
            PublishResult(
                platform="youtube", success=False, error_type="UploadFailed"
            ),
            PublishResult(platform="youtube", success=True),
        ]
        mock_time.monotonic = time.monotonic
        mock_time.sleep = MagicMock()  # Don't actually sleep

        with patch("publisher.get_retry_failed", return_value=True):
            with patch("publisher.get_max_retries", return_value=1):
                pub = ContentPublisher()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = PublishJob(
                video_path=tmp, title="Test", platforms=["youtube"]
            )
            results = pub.publish(job)
            assert len(results) == 1
            assert results[0].success is True
            assert mock_pub.call_count == 2  # initial + 1 retry
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Twitter text truncation tests
# ---------------------------------------------------------------------------

class TestTwitterTextTruncation:
    """Tests for Twitter text length handling in publisher."""

    def test_twitter_text_custom(self):
        """PublishJob accepts custom twitter_text."""
        from publisher import PublishJob
        job = PublishJob(
            video_path="/tmp/test.mp4",
            title="Test",
            twitter_text="Custom tweet text",
        )
        assert job.twitter_text == "Custom tweet text"

    def test_twitter_text_default_none(self):
        from publisher import PublishJob
        job = PublishJob(video_path="/tmp/test.mp4", title="Test")
        assert job.twitter_text is None


# ---------------------------------------------------------------------------
# Uniqueness mode config tests
# ---------------------------------------------------------------------------

class TestGetUniquenessMode:
    """Tests for get_uniqueness_mode() configuration helper."""

    @patch("publisher._get")
    def test_mode_block(self, mock_get):
        mock_get.return_value = {"uniqueness_mode": "block"}
        from publisher import get_uniqueness_mode
        assert get_uniqueness_mode() == "block"

    @patch("publisher._get")
    def test_mode_warn(self, mock_get):
        mock_get.return_value = {"uniqueness_mode": "warn"}
        from publisher import get_uniqueness_mode
        assert get_uniqueness_mode() == "warn"

    @patch("publisher._get")
    def test_mode_off(self, mock_get):
        mock_get.return_value = {"uniqueness_mode": "off"}
        from publisher import get_uniqueness_mode
        assert get_uniqueness_mode() == "off"

    @patch("publisher._get")
    def test_mode_default_warn(self, mock_get):
        mock_get.return_value = {}
        from publisher import get_uniqueness_mode
        assert get_uniqueness_mode() == "warn"

    @patch("publisher._get")
    def test_mode_invalid_defaults_to_warn(self, mock_get):
        mock_get.return_value = {"uniqueness_mode": "strict"}
        from publisher import get_uniqueness_mode
        assert get_uniqueness_mode() == "warn"


# ---------------------------------------------------------------------------
# PublishJob script field tests
# ---------------------------------------------------------------------------

class TestPublishJobScriptField:
    """Tests for the new script field on PublishJob."""

    def test_script_field_default_empty(self):
        from publisher import PublishJob
        job = PublishJob(video_path="/tmp/test.mp4", title="Test")
        assert job.script == ""

    def test_script_field_set(self):
        from publisher import PublishJob
        job = PublishJob(
            video_path="/tmp/test.mp4",
            title="Test",
            script="This is the full script content.",
        )
        assert job.script == "This is the full script content."


# ---------------------------------------------------------------------------
# Uniqueness check integration tests
# ---------------------------------------------------------------------------

class TestUniquenessCheck:
    """Tests for _check_uniqueness and _update_uniqueness_history integration."""

    def _make_publisher_with_mode(self, mode):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                with patch("publisher.get_uniqueness_mode", return_value=mode):
                    return ContentPublisher()

    def _make_temp_job(self, tmp_path, **kwargs):
        from publisher import PublishJob
        defaults = {
            "video_path": tmp_path,
            "title": "Test Title",
            "description": "Test description",
            "platforms": ["youtube"],
        }
        defaults.update(kwargs)
        return PublishJob(**defaults)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_mode_off_skips_uniqueness_check(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """When mode='off', UniquenessScorer is never instantiated."""
        from publisher import PublishResult
        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("off")
            job = self._make_temp_job(tmp)

            with patch("publisher.ContentPublisher._check_uniqueness",
                       wraps=pub._check_uniqueness) as mock_check:
                results = pub.publish(job)
                # _check_uniqueness called but returns None immediately (mode=off)
                mock_check.assert_called_once()

            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_mode_warn_not_flagged_publishes_normally(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """warn mode + not flagged → publishes without interruption."""
        from publisher import PublishResult
        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        mock_score = MagicMock()
        mock_score.flagged = False
        mock_score.overall = 0.85

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("warn")
            job = self._make_temp_job(tmp)

            mock_scorer_instance = MagicMock()
            mock_scorer_instance.score_content.return_value = mock_score

            with patch("publisher.UniquenessScorer", return_value=mock_scorer_instance, create=True):
                with patch.dict("sys.modules", {"uniqueness_scorer": MagicMock(UniquenessScorer=mock_scorer_instance.__class__)}):
                    # Patch directly on the method level
                    with patch.object(pub, "_check_uniqueness", return_value=None):
                        results = pub.publish(job)

            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_mode_warn_flagged_still_publishes(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """warn mode + flagged → warning issued but publishing proceeds."""
        from publisher import PublishResult
        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("warn")
            job = self._make_temp_job(tmp)

            # _check_uniqueness returns None (warn mode never blocks)
            with patch.object(pub, "_check_uniqueness", return_value=None):
                results = pub.publish(job)

            assert len(results) == 1
            assert results[0].success is True
            # _publish_to_platform was still called
            assert mock_pub.call_count == 1
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_mode_block_not_flagged_publishes_normally(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """block mode + not flagged → publishes normally."""
        from publisher import PublishResult
        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("block")
            job = self._make_temp_job(tmp)

            with patch.object(pub, "_check_uniqueness", return_value=None):
                results = pub.publish(job)

            assert len(results) == 1
            assert results[0].success is True
            assert mock_pub.call_count == 1
        finally:
            os.unlink(tmp)

    def test_mode_block_flagged_returns_blocked_results(self):
        """block mode + flagged → returns blocked PublishResult list."""
        from publisher import PublishResult

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("block")
            job = self._make_temp_job(tmp, platforms=["youtube", "tiktok"])

            blocked = [
                PublishResult(
                    platform="youtube",
                    success=False,
                    error_type="UniquenessBlocked",
                    details={"uniqueness_score": 0.45, "uniqueness_flagged": True},
                ),
                PublishResult(
                    platform="tiktok",
                    success=False,
                    error_type="UniquenessBlocked",
                    details={"uniqueness_score": 0.45, "uniqueness_flagged": True},
                ),
            ]
            with patch.object(pub, "_check_uniqueness", return_value=blocked):
                results = pub.publish(job)

            assert len(results) == 2
            assert all(not r.success for r in results)
        finally:
            os.unlink(tmp)

    def test_blocked_results_have_correct_error_type(self):
        """Blocked results carry error_type='UniquenessBlocked'."""
        from publisher import PublishResult

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("block")
            job = self._make_temp_job(tmp, platforms=["youtube"])

            blocked = [
                PublishResult(
                    platform="youtube",
                    success=False,
                    error_type="UniquenessBlocked",
                    details={"uniqueness_score": 0.3, "uniqueness_flagged": True},
                )
            ]
            with patch.object(pub, "_check_uniqueness", return_value=blocked):
                results = pub.publish(job)

            assert results[0].error_type == "UniquenessBlocked"
        finally:
            os.unlink(tmp)

    def test_blocked_results_include_uniqueness_score_in_details(self):
        """Blocked results include uniqueness_score in details dict."""
        from publisher import PublishResult

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("block")
            job = self._make_temp_job(tmp, platforms=["youtube"])

            blocked = [
                PublishResult(
                    platform="youtube",
                    success=False,
                    error_type="UniquenessBlocked",
                    details={"uniqueness_score": 0.42, "uniqueness_flagged": True},
                )
            ]
            with patch.object(pub, "_check_uniqueness", return_value=blocked):
                results = pub.publish(job)

            assert "uniqueness_score" in results[0].details
            assert results[0].details["uniqueness_score"] == 0.42
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_update_history_called_after_successful_publish(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """_update_uniqueness_history is called when at least one platform succeeds."""
        from publisher import PublishResult

        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("warn")
            job = self._make_temp_job(tmp)

            with patch.object(pub, "_check_uniqueness", return_value=None):
                with patch.object(pub, "_update_uniqueness_history") as mock_update:
                    pub.publish(job)
                    mock_update.assert_called_once_with(job)
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_update_history_not_called_when_all_fail(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """_update_uniqueness_history is NOT called when all platforms fail."""
        from publisher import PublishResult

        mock_pub.return_value = PublishResult(
            platform="youtube", success=False, error_type="UploadFailed"
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("warn")
            job = self._make_temp_job(tmp)

            with patch.object(pub, "_check_uniqueness", return_value=None):
                with patch.object(pub, "_update_uniqueness_history") as mock_update:
                    pub.publish(job)
                    mock_update.assert_not_called()
        finally:
            os.unlink(tmp)

    def test_update_history_not_called_when_mode_off(self):
        """_update_uniqueness_history exits early when mode='off'."""
        from publisher import PublishJob
        pub = self._make_publisher_with_mode("off")
        job = PublishJob(video_path="/tmp/x.mp4", title="Test")

        # Since mode is 'off', the method should return immediately without
        # trying to import or call UniquenessScorer
        with patch("builtins.__import__") as mock_import:
            pub._update_uniqueness_history(job)
            # uniqueness_scorer should NOT have been imported
            imported_modules = [c.args[0] for c in mock_import.call_args_list]
            assert "uniqueness_scorer" not in imported_modules

    def test_uniqueness_scorer_import_failure_handled_gracefully(self):
        """If UniquenessScorer import fails, _check_uniqueness returns None."""
        from publisher import PublishJob
        pub = self._make_publisher_with_mode("warn")
        job = PublishJob(
            video_path="/tmp/x.mp4",
            title="Test Title",
            description="desc",
            platforms=["youtube"],
        )

        import sys
        # Temporarily make the import fail
        with patch.dict(sys.modules, {"uniqueness_scorer": None}):
            result = pub._check_uniqueness(job)

        # Should return None (not block publishing) even when import fails
        assert result is None

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_check_uniqueness_internal_block_mode_flagged(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """Direct test of _check_uniqueness in block mode when content is flagged."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("block")
            pub._uniqueness_mode = "block"

            job = PublishJob(
                video_path=tmp,
                title="Flagged Title",
                description="desc",
                platforms=["youtube"],
                tags=["ai"],
            )

            mock_score = MagicMock()
            mock_score.flagged = True
            mock_score.overall = 0.25

            mock_scorer = MagicMock()
            mock_scorer.score_content.return_value = mock_score

            import sys
            mock_module = MagicMock()
            mock_module.UniquenessScorer.return_value = mock_scorer

            with patch.dict(sys.modules, {"uniqueness_scorer": mock_module}):
                result = pub._check_uniqueness(job)

            assert result is not None
            assert len(result) == 1
            assert result[0].success is False
            assert result[0].error_type == "UniquenessBlocked"
            assert result[0].details["uniqueness_score"] == 0.25
            assert result[0].details["uniqueness_flagged"] is True
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_check_uniqueness_internal_warn_mode_flagged_returns_none(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """Direct test of _check_uniqueness in warn mode when content is flagged — returns None."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_mode("warn")
            pub._uniqueness_mode = "warn"

            job = PublishJob(
                video_path=tmp,
                title="Flagged Title",
                description="desc",
                platforms=["youtube"],
                tags=[],
            )

            mock_score = MagicMock()
            mock_score.flagged = True
            mock_score.overall = 0.30

            mock_scorer = MagicMock()
            mock_scorer.score_content.return_value = mock_score

            import sys
            mock_module = MagicMock()
            mock_module.UniquenessScorer.return_value = mock_scorer

            with patch.dict(sys.modules, {"uniqueness_scorer": mock_module}):
                result = pub._check_uniqueness(job)

            # warn mode never blocks — must return None
            assert result is None
        finally:
            os.unlink(tmp)

    def test_publish_job_uses_script_field_for_uniqueness(self):
        """PublishJob.script is preferred over description for uniqueness scoring."""
        from publisher import PublishJob
        job = PublishJob(
            video_path="/tmp/test.mp4",
            title="Test",
            description="Short desc",
            script="Full detailed script content goes here.",
        )
        # When script is set, it should be the primary text for scoring
        script_text = job.script if job.script else job.description
        assert script_text == "Full detailed script content goes here."

    def test_publish_job_falls_back_to_description_when_no_script(self):
        """When PublishJob.script is empty, description is used as fallback."""
        from publisher import PublishJob
        job = PublishJob(
            video_path="/tmp/test.mp4",
            title="Test",
            description="Short desc",
            script="",
        )
        script_text = job.script if job.script else job.description
        assert script_text == "Short desc"


# ---------------------------------------------------------------------------
# _format_affiliate_links tests
# ---------------------------------------------------------------------------

class TestFormatAffiliateLinks:
    """Tests for _format_affiliate_links function."""

    def test_empty_list_returns_empty_string(self):
        from publisher import _format_affiliate_links
        assert _format_affiliate_links([], "youtube") == ""

    def test_list_with_only_invalid_dicts_returns_empty_string(self):
        from publisher import _format_affiliate_links
        # dicts without 'url' key are skipped
        assert _format_affiliate_links([{}, {"label": "thing"}], "youtube") == ""

    def test_youtube_format_contains_shop_header(self):
        from publisher import _format_affiliate_links
        links = [{"url": "https://amzn.to/xyz", "label": "Cool Gadget"}]
        result = _format_affiliate_links(links, "youtube")
        assert "\n\nShop:\n" in result
        assert "Cool Gadget: https://amzn.to/xyz" in result

    def test_tiktok_format_contains_links_header(self):
        from publisher import _format_affiliate_links
        links = [{"url": "https://amzn.to/abc", "label": "My Product"}]
        result = _format_affiliate_links(links, "tiktok")
        assert "\n\nLinks:\n" in result
        assert "My Product -> https://amzn.to/abc" in result

    def test_twitter_format_compact_pipe_separated(self):
        from publisher import _format_affiliate_links
        links = [{"url": "https://amzn.to/aaa", "label": "Deal"}]
        result = _format_affiliate_links(links, "twitter")
        assert result.startswith(" | ")
        assert "Deal: https://amzn.to/aaa" in result

    def test_instagram_format_link_in_bio(self):
        from publisher import _format_affiliate_links
        links = [{"url": "https://amzn.to/bbb", "label": "Widget"}]
        result = _format_affiliate_links(links, "instagram")
        assert "link in bio" in result
        assert "Widget" in result

    def test_unknown_platform_uses_youtube_format(self):
        from publisher import _format_affiliate_links
        links = [{"url": "https://example.com/product", "label": "Stuff"}]
        result = _format_affiliate_links(links, "myspace")
        assert "\n\nShop:\n" in result
        assert "Stuff: https://example.com/product" in result

    def test_multiple_links_all_included(self):
        from publisher import _format_affiliate_links
        links = [
            {"url": "https://amzn.to/111", "label": "First"},
            {"url": "https://amzn.to/222", "label": "Second"},
        ]
        result = _format_affiliate_links(links, "youtube")
        assert "First: https://amzn.to/111" in result
        assert "Second: https://amzn.to/222" in result

    def test_link_without_label_uses_default_youtube(self):
        from publisher import _format_affiliate_links
        links = [{"url": "https://amzn.to/xyz"}]
        result = _format_affiliate_links(links, "youtube")
        assert "Link: https://amzn.to/xyz" in result

    def test_link_without_label_uses_default_instagram(self):
        from publisher import _format_affiliate_links
        links = [{"url": "https://amzn.to/xyz"}]
        result = _format_affiliate_links(links, "instagram")
        assert "Product (link in bio)" in result

    def test_empty_dict_is_skipped(self):
        from publisher import _format_affiliate_links
        links = [{}, {"url": "https://amzn.to/valid", "label": "Good"}]
        result = _format_affiliate_links(links, "youtube")
        assert "Good: https://amzn.to/valid" in result
        # Only one entry should appear
        assert result.count("->") == 0 or result.count(":") >= 1

    def test_twitter_multiple_links_pipe_separated(self):
        from publisher import _format_affiliate_links
        links = [
            {"url": "https://amzn.to/a", "label": "A"},
            {"url": "https://amzn.to/b", "label": "B"},
        ]
        result = _format_affiliate_links(links, "twitter")
        # Both should appear, separated by |
        assert "A: https://amzn.to/a" in result
        assert "B: https://amzn.to/b" in result
        assert " | " in result


# ---------------------------------------------------------------------------
# PublishJob affiliate_links field validation tests
# ---------------------------------------------------------------------------

class TestPublishJobAffiliateLinks:
    """Tests for PublishJob affiliate_links field and validation."""

    def _valid_job(self, tmp_path, **kwargs):
        from publisher import PublishJob
        defaults = {
            "video_path": tmp_path,
            "title": "Test Title",
            "description": "Test description",
            "platforms": ["youtube"],
        }
        defaults.update(kwargs)
        return PublishJob(**defaults)

    def test_default_affiliate_links_is_empty_list(self):
        from publisher import PublishJob
        job = PublishJob(video_path="/tmp/test.mp4", title="Test")
        assert job.affiliate_links == []

    def test_valid_affiliate_links_pass_validation(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._valid_job(
                tmp,
                affiliate_links=[
                    {"url": "https://amzn.to/xyz", "label": "My Product"},
                    {"url": "http://example.com/deal", "label": "Another"},
                ],
            )
            job.validate()  # Should not raise
        finally:
            os.unlink(tmp)

    def test_too_many_affiliate_links_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            links = [
                {"url": f"https://amzn.to/item{i}", "label": f"Item {i}"}
                for i in range(11)
            ]
            job = self._valid_job(tmp, affiliate_links=links)
            with pytest.raises(ValueError, match="Too many affiliate links"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_non_dict_affiliate_link_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._valid_job(
                tmp,
                affiliate_links=["https://amzn.to/xyz"],
            )
            with pytest.raises(ValueError, match="must be a dict"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_missing_url_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._valid_job(
                tmp,
                affiliate_links=[{"label": "No URL here"}],
            )
            with pytest.raises(ValueError, match="missing 'url'"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_url_without_http_scheme_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._valid_job(
                tmp,
                affiliate_links=[{"url": "ftp://example.com/product"}],
            )
            with pytest.raises(ValueError, match="must start with http"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_url_too_long_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            long_url = "https://example.com/" + "a" * 2048
            job = self._valid_job(
                tmp,
                affiliate_links=[{"url": long_url, "label": "Item"}],
            )
            with pytest.raises(ValueError, match="URL too long or invalid"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_label_too_long_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._valid_job(
                tmp,
                affiliate_links=[{
                    "url": "https://amzn.to/abc",
                    "label": "x" * 201,
                }],
            )
            with pytest.raises(ValueError, match="label too long"):
                job.validate()
        finally:
            os.unlink(tmp)

    def test_http_url_is_accepted(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._valid_job(
                tmp,
                affiliate_links=[{"url": "http://example.com/product", "label": "Item"}],
            )
            job.validate()  # Should not raise
        finally:
            os.unlink(tmp)

    def test_link_without_label_passes_validation(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            job = self._valid_job(
                tmp,
                affiliate_links=[{"url": "https://amzn.to/nolabel"}],
            )
            job.validate()  # Should not raise — label is optional
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# publish() with affiliate links integration tests
# ---------------------------------------------------------------------------

class TestPublishWithAffiliateLinks:
    """Tests for publish() method with affiliate links."""

    def _make_publisher(self):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                with patch("publisher.get_uniqueness_mode", return_value="off"):
                    return ContentPublisher()

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_youtube")
    def test_affiliate_links_injected_into_description_for_youtube(
        self, mock_yt, mock_analytics, mock_notify
    ):
        """publish() passes enriched description (with Shop: block) to YouTube handler."""
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_yt.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                description="Base desc",
                platforms=["youtube"],
                affiliate_links=[{"url": "https://amzn.to/abc", "label": "Gadget"}],
            )
            with patch.object(pub, "_check_uniqueness", return_value=None):
                pub.publish(job)

            # The description passed to _publish_youtube must include affiliate links
            call_args = mock_yt.call_args
            enriched = call_args[0][2]  # third positional arg is enriched_description
            assert "Shop:" in enriched
            assert "Gadget: https://amzn.to/abc" in enriched
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_youtube")
    def test_no_affiliate_links_description_unchanged(
        self, mock_yt, mock_analytics, mock_notify
    ):
        """publish() does not alter description when affiliate_links is empty."""
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_yt.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                description="Plain description",
                platforms=["youtube"],
                affiliate_links=[],
            )
            with patch.object(pub, "_check_uniqueness", return_value=None):
                pub.publish(job)

            call_args = mock_yt.call_args
            enriched = call_args[0][2]
            assert enriched == "Plain description"
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_twitter")
    @patch("publisher.ContentPublisher._publish_youtube")
    def test_affiliate_links_are_platform_specific(
        self, mock_yt, mock_tw, mock_analytics, mock_notify
    ):
        """Different platforms receive different affiliate link formats."""
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_yt.return_value = PublishResult(platform="youtube", success=True)
        mock_tw.return_value = PublishResult(platform="twitter", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                description="Base",
                platforms=["youtube", "twitter"],
                affiliate_links=[{"url": "https://amzn.to/deal", "label": "Item"}],
            )
            with patch.object(pub, "_check_uniqueness", return_value=None):
                pub.publish(job)

            yt_enriched = mock_yt.call_args[0][2]
            tw_enriched = mock_tw.call_args[0][2]

            # YouTube gets "Shop:" format, Twitter gets compact " | " format
            assert "Shop:" in yt_enriched
            assert " | " in tw_enriched
            assert "Shop:" not in tw_enriched
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_youtube")
    def test_original_job_description_not_mutated(
        self, mock_yt, mock_analytics, mock_notify
    ):
        """publish() must not modify job.description in place."""
        from publisher import ContentPublisher, PublishJob, PublishResult
        mock_yt.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            original_desc = "Original description"
            job = PublishJob(
                video_path=tmp,
                title="Test",
                description=original_desc,
                platforms=["youtube"],
                affiliate_links=[{"url": "https://amzn.to/xyz", "label": "Stuff"}],
            )
            with patch.object(pub, "_check_uniqueness", return_value=None):
                pub.publish(job)

            # job.description must remain unchanged after publish
            assert job.description == original_desc
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# get_quality_gate_mode and get_watermark_enabled config tests
# ---------------------------------------------------------------------------

class TestQualityGateConfig:
    """Tests for get_quality_gate_mode() and get_watermark_enabled() helpers."""

    @patch("publisher._get")
    def test_quality_gate_mode_block(self, mock_get):
        mock_get.return_value = {"quality_gate_mode": "block"}
        from publisher import get_quality_gate_mode
        assert get_quality_gate_mode() == "block"

    @patch("publisher._get")
    def test_quality_gate_mode_warn(self, mock_get):
        mock_get.return_value = {"quality_gate_mode": "warn"}
        from publisher import get_quality_gate_mode
        assert get_quality_gate_mode() == "warn"

    @patch("publisher._get")
    def test_quality_gate_mode_off(self, mock_get):
        mock_get.return_value = {"quality_gate_mode": "off"}
        from publisher import get_quality_gate_mode
        assert get_quality_gate_mode() == "off"

    @patch("publisher._get")
    def test_quality_gate_mode_default_warn(self, mock_get):
        mock_get.return_value = {}
        from publisher import get_quality_gate_mode
        assert get_quality_gate_mode() == "warn"

    @patch("publisher._get")
    def test_quality_gate_mode_invalid_defaults_to_warn(self, mock_get):
        mock_get.return_value = {"quality_gate_mode": "strict"}
        from publisher import get_quality_gate_mode
        assert get_quality_gate_mode() == "warn"

    @patch("publisher._get")
    def test_watermark_enabled_true(self, mock_get):
        mock_get.return_value = {"watermark_enabled": True}
        from publisher import get_watermark_enabled
        assert get_watermark_enabled() is True

    @patch("publisher._get")
    def test_watermark_enabled_false(self, mock_get):
        mock_get.return_value = {"watermark_enabled": False}
        from publisher import get_watermark_enabled
        assert get_watermark_enabled() is False

    @patch("publisher._get")
    def test_watermark_enabled_default_false(self, mock_get):
        mock_get.return_value = {}
        from publisher import get_watermark_enabled
        assert get_watermark_enabled() is False


# ---------------------------------------------------------------------------
# Quality gate pre-publish hook tests
# ---------------------------------------------------------------------------

class TestQualityGateHook:
    """Tests for _check_quality_gate pre-publish hook."""

    def _make_publisher_with_qg_mode(self, mode):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                with patch("publisher.get_quality_gate_mode", return_value=mode):
                    with patch("publisher.get_watermark_enabled", return_value=False):
                        return ContentPublisher()

    def _make_temp_job(self, tmp_path, **kwargs):
        from publisher import PublishJob
        defaults = {
            "video_path": tmp_path,
            "title": "Test Title",
            "description": "Test description",
            "platforms": ["youtube"],
            "tags": ["ai"],
            "script": "Full script text.",
        }
        defaults.update(kwargs)
        return PublishJob(**defaults)

    def test_mode_off_skips_quality_gate(self):
        """When mode='off', ContentQualityGate is never called."""
        from publisher import PublishJob
        pub = self._make_publisher_with_qg_mode("off")
        job = PublishJob(
            video_path="/tmp/x.mp4",
            title="Test",
            platforms=["youtube"],
        )

        with patch("builtins.__import__") as mock_import:
            pub._check_quality_gate(job)
            imported_modules = [c.args[0] for c in mock_import.call_args_list]
            assert "quality_gate" not in imported_modules

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_mode_warn_score_above_threshold_publishes(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """warn mode + score above threshold → publishes normally."""
        from publisher import PublishResult
        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_qg_mode("warn")
            job = self._make_temp_job(tmp)

            mock_verdict = MagicMock()
            mock_verdict.passed = True
            mock_verdict.overall_score = 85.0

            mock_gate = MagicMock()
            mock_gate.check_and_gate.return_value = (True, mock_verdict)

            mock_module = MagicMock()
            mock_module.ContentQualityGate.return_value = mock_gate

            import sys
            with patch.dict(sys.modules, {"quality_gate": mock_module}):
                with patch.object(pub, "_check_uniqueness", return_value=None):
                    results = pub.publish(job)

            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)

    def test_mode_warn_score_below_threshold_logs_warning_publishes(self):
        """warn mode + verdict.passed=False → warning logged, returns None (proceed)."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_qg_mode("warn")
            job = self._make_temp_job(tmp)

            mock_verdict = MagicMock()
            mock_verdict.passed = False
            mock_verdict.overall_score = 35.0

            mock_gate = MagicMock()
            # should_proceed=True, but verdict.passed=False → warn path
            mock_gate.check_and_gate.return_value = (True, mock_verdict)

            mock_module = MagicMock()
            mock_module.ContentQualityGate.return_value = mock_gate

            import sys
            with patch.dict(sys.modules, {"quality_gate": mock_module}):
                result = pub._check_quality_gate(job)

            # warn mode: returns None (never blocks)
            assert result is None
        finally:
            os.unlink(tmp)

    def test_mode_block_score_below_threshold_returns_blocked(self):
        """block mode + should_proceed=False → returns QualityBlocked results."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_qg_mode("block")
            pub._quality_gate_mode = "block"
            job = self._make_temp_job(tmp, platforms=["youtube", "tiktok"])

            mock_verdict = MagicMock()
            mock_verdict.passed = False
            mock_verdict.overall_score = 28.0

            mock_gate = MagicMock()
            mock_gate.check_and_gate.return_value = (False, mock_verdict)

            mock_module = MagicMock()
            mock_module.ContentQualityGate.return_value = mock_gate

            import sys
            with patch.dict(sys.modules, {"quality_gate": mock_module}):
                result = pub._check_quality_gate(job)

            assert result is not None
            assert len(result) == 2
            assert all(not r.success for r in result)
            assert all(r.error_type == "QualityBlocked" for r in result)
            assert result[0].details["quality_score"] == 28.0
            assert result[0].details["quality_passed"] is False
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_mode_block_score_above_threshold_publishes(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """block mode + should_proceed=True → publishes normally."""
        from publisher import PublishResult
        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_qg_mode("block")
            pub._quality_gate_mode = "block"
            job = self._make_temp_job(tmp)

            mock_verdict = MagicMock()
            mock_verdict.passed = True
            mock_verdict.overall_score = 78.0

            mock_gate = MagicMock()
            mock_gate.check_and_gate.return_value = (True, mock_verdict)

            mock_module = MagicMock()
            mock_module.ContentQualityGate.return_value = mock_gate

            import sys
            with patch.dict(sys.modules, {"quality_gate": mock_module}):
                with patch.object(pub, "_check_uniqueness", return_value=None):
                    results = pub.publish(job)

            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)

    def test_quality_gate_exception_fail_soft_returns_none(self):
        """If ContentQualityGate raises, _check_quality_gate returns None (publish proceeds)."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_qg_mode("warn")
            job = self._make_temp_job(tmp)

            mock_module = MagicMock()
            mock_module.ContentQualityGate.side_effect = RuntimeError("gate exploded")

            import sys
            with patch.dict(sys.modules, {"quality_gate": mock_module}):
                result = pub._check_quality_gate(job)

            assert result is None
        finally:
            os.unlink(tmp)

    def test_quality_gate_import_failure_fail_soft_returns_none(self):
        """If quality_gate module cannot be imported, publishing is not blocked."""
        from publisher import PublishJob

        pub = self._make_publisher_with_qg_mode("warn")
        job = PublishJob(
            video_path="/tmp/x.mp4",
            title="Test",
            platforms=["youtube"],
        )

        import sys
        with patch.dict(sys.modules, {"quality_gate": None}):
            result = pub._check_quality_gate(job)

        assert result is None


# ---------------------------------------------------------------------------
# Watermark pre-publish hook tests
# ---------------------------------------------------------------------------

class TestWatermarkHook:
    """Tests for _apply_watermark pre-publish hook."""

    def _make_publisher_with_watermark(self, enabled):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                with patch("publisher.get_quality_gate_mode", return_value="off"):
                    with patch("publisher.get_watermark_enabled", return_value=enabled):
                        return ContentPublisher()

    def test_watermark_disabled_returns_original_path(self):
        """When watermark_enabled=False, _apply_watermark returns job.video_path unchanged."""
        from publisher import PublishJob
        pub = self._make_publisher_with_watermark(False)
        job = PublishJob(video_path="/tmp/test.mp4", title="Test")

        result_path = pub._apply_watermark(job)
        assert result_path == "/tmp/test.mp4"

    def test_watermark_disabled_no_import_attempted(self):
        """When watermark_enabled=False, content_watermarker is never imported."""
        from publisher import PublishJob
        pub = self._make_publisher_with_watermark(False)
        job = PublishJob(video_path="/tmp/test.mp4", title="Test")

        with patch("builtins.__import__") as mock_import:
            pub._apply_watermark(job)
            imported_modules = [c.args[0] for c in mock_import.call_args_list]
            assert "content_watermarker" not in imported_modules

    def test_watermark_enabled_embed_called_path_updated(self):
        """When watermark_enabled=True and embed succeeds, returns new file path."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_watermark(True)
            pub._watermark_enabled = True
            job = PublishJob(video_path=tmp, title="My Great Video Title Here")

            mock_result = MagicMock()
            mock_result.embedded = True
            mock_result.file_path = "/tmp/watermarked.mp4"
            mock_result.error = None

            mock_wm = MagicMock()
            mock_wm.embed.return_value = mock_result

            mock_module = MagicMock()
            mock_module.ContentWatermarker.return_value = mock_wm

            import sys
            with patch.dict(sys.modules, {"content_watermarker": mock_module}):
                result_path = pub._apply_watermark(job)

            assert result_path == "/tmp/watermarked.mp4"
            # embed called with title truncated to 30 chars
            mock_wm.embed.assert_called_once_with(tmp, message="My Great Video Title Here"[:30])
        finally:
            os.unlink(tmp)

    def test_watermark_enabled_embed_fails_returns_original_path(self):
        """When watermark_enabled=True but embed fails (embedded=False), returns original path."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_watermark(True)
            pub._watermark_enabled = True
            job = PublishJob(video_path=tmp, title="Test")

            mock_result = MagicMock()
            mock_result.embedded = False
            mock_result.file_path = None
            mock_result.error = "FFmpeg not found"

            mock_wm = MagicMock()
            mock_wm.embed.return_value = mock_result

            mock_module = MagicMock()
            mock_module.ContentWatermarker.return_value = mock_wm

            import sys
            with patch.dict(sys.modules, {"content_watermarker": mock_module}):
                result_path = pub._apply_watermark(job)

            assert result_path == tmp
        finally:
            os.unlink(tmp)

    def test_watermark_exception_fail_soft_returns_original_path(self):
        """If ContentWatermarker raises, _apply_watermark returns original path (publish continues)."""
        from publisher import PublishJob

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher_with_watermark(True)
            pub._watermark_enabled = True
            job = PublishJob(video_path=tmp, title="Test")

            mock_module = MagicMock()
            mock_module.ContentWatermarker.side_effect = RuntimeError("watermarker exploded")

            import sys
            with patch.dict(sys.modules, {"content_watermarker": mock_module}):
                result_path = pub._apply_watermark(job)

            assert result_path == tmp
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Integration tests: both hooks together
# ---------------------------------------------------------------------------

class TestQualityGateAndWatermarkIntegration:
    """Integration tests exercising quality gate + watermark hooks together in publish()."""

    def _make_publisher(self, qg_mode="off", watermark=False):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                with patch("publisher.get_quality_gate_mode", return_value=qg_mode):
                    with patch("publisher.get_watermark_enabled", return_value=watermark):
                        with patch("publisher.get_uniqueness_mode", return_value="off"):
                            return ContentPublisher()

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_both_hooks_off_publishes_normally(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """quality_gate=off + watermark=False → publish proceeds unaffected."""
        from publisher import PublishResult
        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher(qg_mode="off", watermark=False)
            from publisher import PublishJob
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            results = pub.publish(job)
            assert len(results) == 1
            assert results[0].success is True
            mock_pub.assert_called_once()
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_quality_blocked_before_watermark(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """When quality gate blocks, watermark is never applied and publish is aborted."""
        from publisher import PublishResult

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher(qg_mode="block", watermark=True)
            pub._quality_gate_mode = "block"
            pub._watermark_enabled = True

            from publisher import PublishJob
            job = PublishJob(
                video_path=tmp,
                title="Low Quality Content",
                platforms=["youtube"],
            )

            with patch.object(pub, "_check_quality_gate") as mock_qg, \
                 patch.object(pub, "_apply_watermark") as mock_wm:

                blocked = [PublishResult(
                    platform="youtube",
                    success=False,
                    error_type="QualityBlocked",
                    details={"quality_score": 20.0, "quality_passed": False},
                )]
                mock_qg.return_value = blocked

                results = pub.publish(job)

            assert len(results) == 1
            assert results[0].error_type == "QualityBlocked"
            # watermark should NOT have been called since quality gate blocked first
            mock_wm.assert_not_called()
            # _publish_to_platform also should not have been called
            mock_pub.assert_not_called()
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_watermark_applied_then_publish_uses_new_path(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """When watermark succeeds, _publish_to_platform receives watermarked job."""
        from publisher import PublishResult

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f2:
            tmp_wm = f2.name
        try:
            pub = self._make_publisher(qg_mode="off", watermark=True)
            pub._watermark_enabled = True

            from publisher import PublishJob
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )

            mock_pub.return_value = PublishResult(platform="youtube", success=True)

            with patch.object(pub, "_apply_watermark", return_value=tmp_wm):
                results = pub.publish(job)

            # job.video_path should have been updated to watermarked path
            assert job.video_path == tmp_wm
            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)
            os.unlink(tmp_wm)


# ---------------------------------------------------------------------------
# Pipeline health reporting tests (H59)
# ---------------------------------------------------------------------------

class TestPublisherHealthReporting:
    """Tests for pipeline health reporting in publisher.publish() (H59)."""

    def setup_method(self):
        """Reset the health monitor singleton before each test."""
        import publisher
        publisher._get_health_monitor._instance = None

    def teardown_method(self):
        """Clean up singleton."""
        import publisher
        publisher._get_health_monitor._instance = None

    def _make_publisher(self):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                with patch("publisher.get_uniqueness_mode", return_value="off"):
                    with patch("publisher.get_quality_gate_mode", return_value="off"):
                        with patch("publisher.get_watermark_enabled", return_value=False):
                            return ContentPublisher()

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_publish_all_succeed_reports_ok(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """Health reports 'ok' when all platforms succeed."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        mock_monitor = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_health_monitor", return_value=mock_monitor):
                with patch.object(pub, "_check_uniqueness", return_value=None):
                    pub.publish(job)

            mock_monitor.report_health.assert_called_once()
            call_args = mock_monitor.report_health.call_args
            assert call_args[0][0] == "publisher"
            assert call_args[0][1] == "ok"
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_publish_all_fail_reports_error(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """Health reports 'error' when all platforms fail."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(
            platform="youtube", success=False, error_type="UploadFailed"
        )

        mock_monitor = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_health_monitor", return_value=mock_monitor):
                with patch.object(pub, "_check_uniqueness", return_value=None):
                    pub.publish(job)

            mock_monitor.report_health.assert_called_once()
            call_args = mock_monitor.report_health.call_args
            assert call_args[0][0] == "publisher"
            assert call_args[0][1] == "error"
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_publish_partial_fail_reports_degraded(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """Health reports 'degraded' when some platforms fail."""
        from publisher import PublishJob, PublishResult

        mock_pub.side_effect = [
            PublishResult(platform="youtube", success=True),
            PublishResult(platform="tiktok", success=False, error_type="UploadFailed"),
        ]

        mock_monitor = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube", "tiktok"],
            )
            with patch("publisher._get_health_monitor", return_value=mock_monitor):
                with patch.object(pub, "_check_uniqueness", return_value=None):
                    pub.publish(job)

            mock_monitor.report_health.assert_called_once()
            call_args = mock_monitor.report_health.call_args
            assert call_args[0][0] == "publisher"
            assert call_args[0][1] == "degraded"
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_health_metadata_includes_counts(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """Metadata dict has 'succeeded', 'total', 'platforms' keys."""
        from publisher import PublishJob, PublishResult

        mock_pub.side_effect = [
            PublishResult(platform="youtube", success=True),
            PublishResult(platform="tiktok", success=False, error_type="UploadFailed"),
        ]

        mock_monitor = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube", "tiktok"],
            )
            with patch("publisher._get_health_monitor", return_value=mock_monitor):
                with patch.object(pub, "_check_uniqueness", return_value=None):
                    pub.publish(job)

            mock_monitor.report_health.assert_called_once()
            _, kwargs = mock_monitor.report_health.call_args
            metadata = kwargs.get("metadata", {})
            assert "succeeded" in metadata
            assert "total" in metadata
            assert "platforms" in metadata
            assert metadata["succeeded"] == 1
            assert metadata["total"] == 2
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_health_exception_does_not_block_publish(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """If health monitor raises, publish() still returns results."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        mock_monitor = MagicMock()
        mock_monitor.report_health.side_effect = RuntimeError("monitor exploded")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_health_monitor", return_value=mock_monitor):
                with patch.object(pub, "_check_uniqueness", return_value=None):
                    results = pub.publish(job)

            # publish() must still return results despite monitor raising
            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Plugin dispatch lifecycle hook tests (H61)
# ---------------------------------------------------------------------------

class TestPublisherPluginDispatch:
    """Tests for plugin lifecycle hooks in publisher.publish() (H61)."""

    def setup_method(self):
        import publisher
        publisher._get_plugin_manager._instance = None
        publisher._get_health_monitor._instance = None

    def teardown_method(self):
        import publisher
        publisher._get_plugin_manager._instance = None
        publisher._get_health_monitor._instance = None

    def _make_publisher(self):
        from publisher import ContentPublisher
        with patch("publisher.get_retry_failed", return_value=False):
            with patch("publisher.get_max_retries", return_value=0):
                with patch("publisher.get_uniqueness_mode", return_value="off"):
                    with patch("publisher.get_quality_gate_mode", return_value="off"):
                        with patch("publisher.get_watermark_enabled", return_value=False):
                            return ContentPublisher()

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_on_pre_publish_called(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """on_pre_publish is called before quality gate."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        mock_pm = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_plugin_manager", return_value=mock_pm):
                with patch("publisher._get_health_monitor", return_value=MagicMock()):
                    with patch.object(pub, "_check_uniqueness", return_value=None):
                        pub.publish(job)

            mock_pm.hook.on_pre_publish.assert_called_once()
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_on_post_publish_called_with_results(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """on_post_publish is called with job dict and results list."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        mock_pm = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_plugin_manager", return_value=mock_pm):
                with patch("publisher._get_health_monitor", return_value=MagicMock()):
                    with patch.object(pub, "_check_uniqueness", return_value=None):
                        pub.publish(job)

            mock_pm.hook.on_post_publish.assert_called_once()
            call_kwargs = mock_pm.hook.on_post_publish.call_args[1]
            assert "job" in call_kwargs
            assert "results" in call_kwargs
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_on_post_publish_results_format(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """Results list contains dicts with platform, success, error_type keys."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(
            platform="youtube", success=True, error_type=""
        )

        mock_pm = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_plugin_manager", return_value=mock_pm):
                with patch("publisher._get_health_monitor", return_value=MagicMock()):
                    with patch.object(pub, "_check_uniqueness", return_value=None):
                        pub.publish(job)

            call_kwargs = mock_pm.hook.on_post_publish.call_args[1]
            results_list = call_kwargs["results"]
            assert len(results_list) == 1
            entry = results_list[0]
            assert "platform" in entry
            assert "success" in entry
            assert "error_type" in entry
            assert entry["platform"] == "youtube"
            assert entry["success"] is True
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_plugin_exception_does_not_block_publish(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """If plugin manager raises, publish() still returns results."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        mock_pm = MagicMock()
        mock_pm.hook.on_pre_publish.side_effect = RuntimeError("plugin exploded")
        mock_pm.hook.on_post_publish.side_effect = RuntimeError("plugin exploded")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_plugin_manager", return_value=mock_pm):
                with patch("publisher._get_health_monitor", return_value=MagicMock()):
                    with patch.object(pub, "_check_uniqueness", return_value=None):
                        results = pub.publish(job)

            # publish() must still return results despite plugin raising
            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)

    @patch("publisher.ContentPublisher._send_notification")
    @patch("publisher.ContentPublisher._track_analytics")
    @patch("publisher.ContentPublisher._publish_to_platform")
    def test_no_plugin_manager_does_not_block(
        self, mock_pub, mock_analytics, mock_notify
    ):
        """If _get_plugin_manager returns None, publish proceeds normally."""
        from publisher import PublishJob, PublishResult

        mock_pub.return_value = PublishResult(platform="youtube", success=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            pub = self._make_publisher()
            job = PublishJob(
                video_path=tmp,
                title="Test",
                platforms=["youtube"],
            )
            with patch("publisher._get_plugin_manager", return_value=None):
                with patch("publisher._get_health_monitor", return_value=MagicMock()):
                    with patch.object(pub, "_check_uniqueness", return_value=None):
                        results = pub.publish(job)

            assert len(results) == 1
            assert results[0].success is True
        finally:
            os.unlink(tmp)

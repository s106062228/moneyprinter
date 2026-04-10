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

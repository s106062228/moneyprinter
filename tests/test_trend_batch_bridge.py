"""Tests for trend_batch_bridge.py.

Mocks TrendDetector.detect() and BatchGenerator.run() — no real API calls.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trend_detector import TopicCandidate
from batch_generator import BatchResult, BatchJob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_topic(topic: str, score: float = 7.0) -> TopicCandidate:
    """Create a TopicCandidate with minimal required fields."""
    return TopicCandidate(
        topic=topic,
        source="google_trends",
        score=score,
        trend_velocity=0.0,
    )


def _make_result(total: int = 5, succeeded: int = 5) -> BatchResult:
    """Create a BatchResult for use as a mock return value."""
    return BatchResult(total=total, succeeded=succeeded, failed=total - succeeded)


# ---------------------------------------------------------------------------
# 1. generate_trending_batch() happy path
# ---------------------------------------------------------------------------

class TestGenerateTrendingBatchHappyPath:
    """generate_trending_batch() happy path: detector returns topics, generator returns result."""

    def test_returns_batch_result(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic(f"topic{i}", score=float(6 + i)) for i in range(5)]
        mock_result = _make_result(5, 5)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            result = generate_trending_batch("finance")

        assert result is mock_result

    def test_creates_detector_with_correct_niche(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("AI investing", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            generate_trending_batch("finance")

        MockDetector.assert_called_once_with(niches=["finance"])

    def test_calls_generator_run_once(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("topic", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            generate_trending_batch("tech")

        assert MockGenerator.return_value.run.call_count == 1

    def test_batch_job_niche_matches(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("topic", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("cooking")

        assert captured_job[0].niche == "cooking"

    def test_topics_passed_to_batch_job(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic(f"topic_{i}", score=float(7)) for i in range(3)]
        mock_result = _make_result(3, 3)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("fitness", count=3)

        assert captured_job[0].topics == ["topic_0", "topic_1", "topic_2"]


# ---------------------------------------------------------------------------
# 2. generate_trending_batch() min_score filtering
# ---------------------------------------------------------------------------

class TestMinScoreFiltering:
    """min_score filtering: all above, all below, mixed."""

    def test_all_topics_above_min_score(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic(f"t{i}", score=8.0) for i in range(5)]
        mock_result = _make_result(5, 5)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("finance", min_score=5.0)

        assert len(captured_job[0].topics) == 5

    def test_all_topics_below_min_score_returns_empty_result(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic(f"t{i}", score=3.0) for i in range(5)]

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics

            result = generate_trending_batch("finance", min_score=7.0)

        MockGenerator.return_value.run.assert_not_called()
        assert result.total == 0
        assert result.succeeded == 0

    def test_mixed_filtering_passes_only_above_threshold(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [
            _make_topic("high1", score=8.0),
            _make_topic("low1", score=3.0),
            _make_topic("high2", score=7.5),
            _make_topic("low2", score=4.9),
        ]
        mock_result = _make_result(2, 2)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("finance", min_score=5.0)

        assert set(captured_job[0].topics) == {"high1", "high2"}

    def test_exact_min_score_is_included(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("exact", score=5.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", min_score=5.0)

        assert "exact" in captured_job[0].topics

    def test_just_below_min_score_excluded(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("borderline", score=4.99)]

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics

            result = generate_trending_batch("tech", min_score=5.0)

        MockGenerator.return_value.run.assert_not_called()
        assert result.total == 0


# ---------------------------------------------------------------------------
# 3. generate_trending_batch() count limiting
# ---------------------------------------------------------------------------

class TestCountLimiting:
    """count limiting: 3 requested, 10 available."""

    def test_count_limits_topics_passed_to_generator(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic(f"t{i}", score=float(i)) for i in range(10)]
        mock_result = _make_result(3, 3)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", count=3, min_score=0.0)

        assert len(captured_job[0].topics) == 3

    def test_count_one_picks_top_topic(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [
            _make_topic("best", score=9.0),
            _make_topic("second", score=7.0),
            _make_topic("third", score=5.0),
        ]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", count=1, min_score=0.0)

        assert captured_job[0].topics == ["best"]

    def test_count_larger_than_available_uses_all_available(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic(f"t{i}", score=7.0) for i in range(3)]
        mock_result = _make_result(3, 3)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", count=10, min_score=0.0)

        assert len(captured_job[0].topics) == 3


# ---------------------------------------------------------------------------
# 4. generate_trending_batch() empty trends
# ---------------------------------------------------------------------------

class TestEmptyTrends:
    """Detector returns empty list."""

    def test_empty_detect_returns_empty_batch_result(self):
        from trend_batch_bridge import generate_trending_batch

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = []

            result = generate_trending_batch("finance")

        MockGenerator.return_value.run.assert_not_called()
        assert result.total == 0
        assert result.succeeded == 0

    def test_empty_detect_does_not_call_generator(self):
        from trend_batch_bridge import generate_trending_batch

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = []

            generate_trending_batch("finance")

        assert MockGenerator.return_value.run.call_count == 0

    def test_empty_detect_returns_batch_result_instance(self):
        from trend_batch_bridge import generate_trending_batch

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator"):
            MockDetector.return_value.detect.return_value = []

            result = generate_trending_batch("finance")

        assert isinstance(result, BatchResult)


# ---------------------------------------------------------------------------
# 5. generate_trending_batch() auto_publish passthrough
# ---------------------------------------------------------------------------

class TestAutoPublishPassthrough:
    """auto_publish is forwarded to BatchJob."""

    def test_auto_publish_true_forwarded(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", auto_publish=True)

        assert captured_job[0].auto_publish is True

    def test_auto_publish_false_forwarded(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", auto_publish=False)

        assert captured_job[0].auto_publish is False

    def test_auto_publish_default_is_false(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech")

        assert captured_job[0].auto_publish is False


# ---------------------------------------------------------------------------
# 6. generate_trending_batch() publish_platforms passthrough
# ---------------------------------------------------------------------------

class TestPublishPlatformsPassthrough:
    """publish_platforms forwarded to BatchJob."""

    def test_custom_platforms_forwarded(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", publish_platforms=["youtube", "tiktok"])

        assert captured_job[0].publish_platforms == ["youtube", "tiktok"]

    def test_none_platforms_defaults_to_youtube(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", publish_platforms=None)

        assert captured_job[0].publish_platforms == ["youtube"]


# ---------------------------------------------------------------------------
# 7. generate_trending_batch() delay passthrough
# ---------------------------------------------------------------------------

class TestDelayPassthrough:
    """delay is stored on BatchJob as delay_between_videos."""

    def test_custom_delay_stored_on_job(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", delay=60)

        assert captured_job[0].delay_between_videos == 60

    def test_default_delay_stored_on_job(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech")

        assert captured_job[0].delay_between_videos == 30


# ---------------------------------------------------------------------------
# 8. generate_trending_batch() subreddits passthrough
# ---------------------------------------------------------------------------

class TestSubredditsPassthrough:
    """subreddits forwarded to TrendDetector.detect()."""

    def test_subreddits_forwarded_to_detect(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            generate_trending_batch(
                "tech",
                subreddits=["technology", "programming"],
            )

        MockDetector.return_value.detect.assert_called_once_with(
            subreddits=["technology", "programming"]
        )

    def test_none_subreddits_passes_empty_list_to_detect(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            generate_trending_batch("tech", subreddits=None)

        MockDetector.return_value.detect.assert_called_once_with(subreddits=[])

    def test_empty_subreddits_list_forwarded(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            generate_trending_batch("tech", subreddits=[])

        MockDetector.return_value.detect.assert_called_once_with(subreddits=[])


# ---------------------------------------------------------------------------
# 9. topics_to_batch_job() valid conversion
# ---------------------------------------------------------------------------

class TestTopicsToBatchJobValidConversion:
    """topics_to_batch_job() converts TopicCandidate list to BatchJob correctly."""

    def test_topics_mapped_to_strings(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [
            _make_topic("AI tools for work"),
            _make_topic("Passive income ideas"),
        ]
        job = topics_to_batch_job(topics, "finance")
        assert job.topics == ["AI tools for work", "Passive income ideas"]

    def test_niche_set_correctly(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(topics, "technology")
        assert job.niche == "technology"

    def test_auto_publish_set(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(topics, "tech", auto_publish=True)
        assert job.auto_publish is True

    def test_publish_platforms_set(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(topics, "tech", publish_platforms=["tiktok"])
        assert job.publish_platforms == ["tiktok"]

    def test_delay_stored_on_job(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(topics, "tech", delay=45)
        assert job.delay_between_videos == 45

    def test_returns_batch_job_instance(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(topics, "tech")
        assert isinstance(job, BatchJob)


# ---------------------------------------------------------------------------
# 10. topics_to_batch_job() empty list
# ---------------------------------------------------------------------------

class TestTopicsToBatchJobEmptyList:
    """topics_to_batch_job() with empty list creates a job with empty topics."""

    def test_empty_list_creates_job_with_empty_topics(self):
        from trend_batch_bridge import topics_to_batch_job
        job = topics_to_batch_job([], "tech")
        assert job.topics == []

    def test_empty_list_does_not_raise(self):
        from trend_batch_bridge import topics_to_batch_job
        # Should not raise — validation of empty topics is BatchJob.validate()'s job
        job = topics_to_batch_job([], "tech")
        assert isinstance(job, BatchJob)


# ---------------------------------------------------------------------------
# 11. topics_to_batch_job() max count exceeded
# ---------------------------------------------------------------------------

class TestTopicsToBatchJobMaxCountExceeded:
    """topics_to_batch_job() raises ValueError when topics > _MAX_COUNT."""

    def test_21_topics_raises(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic(f"t{i}", score=7.0) for i in range(21)]
        with pytest.raises(ValueError, match="exceeds maximum"):
            topics_to_batch_job(topics, "tech")

    def test_20_topics_is_allowed(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic(f"t{i}", score=7.0) for i in range(20)]
        job = topics_to_batch_job(topics, "tech")
        assert len(job.topics) == 20


# ---------------------------------------------------------------------------
# 12. topics_to_batch_job() default platforms
# ---------------------------------------------------------------------------

class TestTopicsToBatchJobDefaultPlatforms:
    """topics_to_batch_job() defaults publish_platforms to ["youtube"]."""

    def test_none_platforms_defaults_to_youtube(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(topics, "tech", publish_platforms=None)
        assert job.publish_platforms == ["youtube"]

    def test_explicit_empty_list_yields_empty(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(topics, "tech", publish_platforms=[])
        assert job.publish_platforms == []

    def test_custom_platforms_preserved(self):
        from trend_batch_bridge import topics_to_batch_job
        topics = [_make_topic("topic")]
        job = topics_to_batch_job(
            topics, "tech", publish_platforms=["youtube", "instagram"]
        )
        assert job.publish_platforms == ["youtube", "instagram"]


# ---------------------------------------------------------------------------
# 13. Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Validates all generate_trending_batch() input parameters."""

    # niche validation

    def test_empty_niche_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="niche"):
            generate_trending_batch("")

    def test_whitespace_only_niche_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="niche"):
            generate_trending_batch("   ")

    def test_niche_too_long_raises(self):
        from trend_batch_bridge import generate_trending_batch
        long_niche = "x" * 201
        with pytest.raises(ValueError, match="niche"):
            generate_trending_batch(long_niche)

    def test_niche_200_chars_is_valid(self):
        from trend_batch_bridge import generate_trending_batch
        niche_200 = "x" * 200
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            result = generate_trending_batch(niche_200)

        assert result is mock_result

    def test_null_byte_in_niche_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="null bytes"):
            generate_trending_batch("finance\x00")

    # count validation

    def test_count_zero_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="count"):
            generate_trending_batch("tech", count=0)

    def test_count_negative_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="count"):
            generate_trending_batch("tech", count=-1)

    def test_count_21_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="count"):
            generate_trending_batch("tech", count=21)

    def test_count_20_is_valid(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic(f"t{i}", score=7.0) for i in range(20)]
        mock_result = _make_result(20, 20)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            result = generate_trending_batch("tech", count=20, min_score=0.0)

        assert result is mock_result

    def test_count_1_is_valid(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            result = generate_trending_batch("tech", count=1)

        assert result is mock_result

    # min_score validation

    def test_min_score_negative_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="min_score"):
            generate_trending_batch("tech", min_score=-0.1)

    def test_min_score_above_10_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="min_score"):
            generate_trending_batch("tech", min_score=10.1)

    def test_min_score_0_is_valid(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=0.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            result = generate_trending_batch("tech", min_score=0.0)

        assert result is mock_result

    def test_min_score_10_is_valid(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=10.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            result = generate_trending_batch("tech", min_score=10.0)

        assert result is mock_result

    # delay validation

    def test_delay_less_than_10_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="delay"):
            generate_trending_batch("tech", delay=9)

    def test_delay_10_is_valid(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]
        mock_result = _make_result(1, 1)

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.return_value = mock_result

            result = generate_trending_batch("tech", delay=10)

        assert result is mock_result

    def test_delay_negative_raises(self):
        from trend_batch_bridge import generate_trending_batch
        with pytest.raises(ValueError, match="delay"):
            generate_trending_batch("tech", delay=-5)


# ---------------------------------------------------------------------------
# 14. Sorting: verify topics sorted by score descending
# ---------------------------------------------------------------------------

class TestSorting:
    """Topics sorted by score descending before selecting top N."""

    def test_top_n_are_highest_scores(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [
            _make_topic("low", score=3.0),
            _make_topic("high", score=9.0),
            _make_topic("mid", score=6.0),
        ]
        mock_result = _make_result(2, 2)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", count=2, min_score=0.0)

        assert captured_job[0].topics[0] == "high"
        assert captured_job[0].topics[1] == "mid"

    def test_sorted_order_is_descending(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [
            _make_topic("score5", score=5.0),
            _make_topic("score9", score=9.0),
            _make_topic("score7", score=7.0),
            _make_topic("score6", score=6.0),
            _make_topic("score8", score=8.0),
        ]
        mock_result = _make_result(5, 5)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", count=5, min_score=0.0)

        assert captured_job[0].topics == [
            "score9", "score8", "score7", "score6", "score5"
        ]

    def test_lowest_scored_excluded_when_count_limits(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [
            _make_topic("best", score=9.0),
            _make_topic("worst", score=5.1),
            _make_topic("second", score=8.0),
        ]
        mock_result = _make_result(2, 2)
        captured_job = []

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = lambda j: (
                captured_job.append(j) or mock_result
            )

            generate_trending_batch("tech", count=2, min_score=0.0)

        assert "worst" not in captured_job[0].topics
        assert captured_job[0].topics == ["best", "second"]

    def test_generator_exception_propagated(self):
        from trend_batch_bridge import generate_trending_batch
        topics = [_make_topic("t", score=7.0)]

        with patch("trend_batch_bridge.TrendDetector") as MockDetector, \
             patch("trend_batch_bridge.BatchGenerator") as MockGenerator:
            MockDetector.return_value.detect.return_value = topics
            MockGenerator.return_value.run.side_effect = RuntimeError("batch failed")

            with pytest.raises(RuntimeError, match="batch failed"):
                generate_trending_batch("tech")

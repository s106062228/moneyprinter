"""
Trend Batch Bridge for MoneyPrinter.

Thin bridge module wiring TrendDetector.detect() output into BatchGenerator.run()
input. Converts TopicCandidate objects into batch topics.

Follows the "compose don't modify" pattern — neither TrendDetector nor
BatchGenerator is modified; this module adapts their interfaces.

Usage:
    from trend_batch_bridge import generate_trending_batch

    result = generate_trending_batch(
        niche="finance",
        count=5,
        min_score=6.0,
        subreddits=["personalfinance", "investing"],
    )
    print(f"Generated {result.succeeded}/{result.total} videos")
"""

from mp_logger import get_logger
from trend_detector import TrendDetector, TopicCandidate
from batch_generator import BatchGenerator, BatchJob, BatchResult

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MIN_SCORE = 5.0
_DEFAULT_COUNT = 5
_MAX_COUNT = 20
_MAX_NICHE_LENGTH = 200


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_trending_batch(
    niche: str,
    *,
    count: int = _DEFAULT_COUNT,
    min_score: float = _DEFAULT_MIN_SCORE,
    subreddits: list[str] | None = None,
    auto_publish: bool = False,
    publish_platforms: list[str] | None = None,
    delay: int = 30,
) -> BatchResult:
    """
    Detect trending topics for a niche and run a batch video generation job.

    Args:
        niche: Topic niche to detect trends for (non-empty, max 200 chars).
        count: Number of topics to generate videos for (1-20).
        min_score: Minimum topic score threshold (0.0-10.0).
        subreddits: Optional list of subreddit names to include.
        auto_publish: Whether to auto-publish generated videos.
        publish_platforms: Platforms to publish to (default: ["youtube"]).
        delay: Seconds to wait between video generations (>= 10).

    Returns:
        BatchResult with per-video outcomes and aggregate stats.

    Raises:
        ValueError: If any input parameter is invalid.
    """
    # --- Input validation ---
    _validate_niche(niche)
    _validate_count(count)
    _validate_min_score(min_score)
    _validate_delay(delay)

    logger.info(
        "generate_trending_batch: niche=%r count=%d min_score=%s subreddits=%r",
        niche, count, min_score, subreddits,
    )

    # --- Detect trending topics ---
    detector = TrendDetector(niches=[niche])
    all_topics: list[TopicCandidate] = detector.detect(
        subreddits=subreddits or []
    )

    if not all_topics:
        logger.warning(
            "generate_trending_batch: TrendDetector returned no topics for niche=%r",
            niche,
        )
        return BatchResult(total=0, succeeded=0)

    # --- Filter by score ---
    filtered = [tc for tc in all_topics if tc.score >= min_score]

    if not filtered:
        logger.warning(
            "generate_trending_batch: no topics passed min_score=%.1f filter "
            "(had %d topics before filtering)",
            min_score, len(all_topics),
        )
        return BatchResult(total=0, succeeded=0)

    # --- Sort by score descending and take top `count` ---
    top_topics = sorted(filtered, key=lambda tc: tc.score, reverse=True)[:count]

    logger.info(
        "generate_trending_batch: %d topics after filtering/sorting (from %d total)",
        len(top_topics), len(all_topics),
    )

    # --- Build BatchJob and run ---
    job = topics_to_batch_job(
        top_topics,
        niche,
        auto_publish=auto_publish,
        publish_platforms=publish_platforms,
        delay=delay,
    )

    generator = BatchGenerator()
    result = generator.run(job)

    logger.info(
        "generate_trending_batch: done — %d/%d succeeded",
        result.succeeded, result.total,
    )
    return result


def topics_to_batch_job(
    topics: list[TopicCandidate],
    niche: str,
    *,
    auto_publish: bool = False,
    publish_platforms: list[str] | None = None,
    delay: int = 30,
) -> BatchJob:
    """
    Pure conversion: transform a list of TopicCandidate objects into a BatchJob.

    Args:
        topics: List of TopicCandidate objects to convert.
        niche: Niche string for the batch job.
        auto_publish: Whether to auto-publish generated videos.
        publish_platforms: Platforms to publish to (default: ["youtube"]).
        delay: Seconds between video generations. Stored on the job object.

    Returns:
        A BatchJob ready for BatchGenerator.run().

    Raises:
        ValueError: If topics count exceeds _MAX_COUNT (20).
    """
    if len(topics) > _MAX_COUNT:
        raise ValueError(
            f"topics count {len(topics)} exceeds maximum allowed count of {_MAX_COUNT}."
        )

    topic_strings = [tc.topic for tc in topics]
    platforms = publish_platforms if publish_platforms is not None else ["youtube"]

    job = BatchJob(
        topics=topic_strings,
        niche=niche,
        auto_publish=auto_publish,
        publish_platforms=platforms,
    )

    # Store delay as an attribute on the job so callers can inspect it.
    # BatchGenerator reads delay from config; this attribute is informational.
    job.delay_between_videos = delay

    return job


# ---------------------------------------------------------------------------
# Internal validation helpers
# ---------------------------------------------------------------------------

def _validate_niche(niche: str) -> None:
    """Validate niche parameter."""
    if not niche or not isinstance(niche, str) or not niche.strip():
        raise ValueError("niche must be a non-empty string.")
    if "\x00" in niche:
        raise ValueError("niche contains null bytes.")
    if len(niche) > _MAX_NICHE_LENGTH:
        raise ValueError(
            f"niche exceeds maximum length of {_MAX_NICHE_LENGTH} characters."
        )


def _validate_count(count: int) -> None:
    """Validate count parameter."""
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError("count must be an integer.")
    if count < 1 or count > _MAX_COUNT:
        raise ValueError(f"count must be between 1 and {_MAX_COUNT}, got {count}.")


def _validate_min_score(min_score: float) -> None:
    """Validate min_score parameter."""
    try:
        val = float(min_score)
    except (TypeError, ValueError):
        raise ValueError("min_score must be a number.")
    if val < 0.0 or val > 10.0:
        raise ValueError(
            f"min_score must be between 0.0 and 10.0, got {min_score}."
        )


def _validate_delay(delay: int) -> None:
    """Validate delay parameter."""
    if not isinstance(delay, int) or isinstance(delay, bool):
        raise ValueError("delay must be an integer.")
    if delay < 10:
        raise ValueError(f"delay must be >= 10 seconds, got {delay}.")

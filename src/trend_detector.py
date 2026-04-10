"""
Trend Detector for MoneyPrinter.

Fetches trending topics from Google Trends and Reddit, scores them for
short-form video potential using an LLM, and caches the results locally.

Usage:
    detector = TrendDetector(niches=["technology", "finance"])
    topics = detector.detect(subreddits=["tech", "personalfinance"])
    for topic in topics:
        print(topic.topic, topic.score)
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import ROOT_DIR
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SOURCES = frozenset({"google_trends", "reddit"})
_SUBREDDIT_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,21}$")

_SCORE_MIN = 0.0
_SCORE_MAX = 10.0


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class TopicCandidate:
    """A single trending topic candidate ready for scoring."""

    topic: str
    source: str           # "google_trends" or "reddit"
    score: float          # 0-10
    trend_velocity: float
    subreddit: str = ""
    reason: str = ""
    fetched_at: str = ""  # ISO 8601 UTC timestamp
    predicted_peak: str = ""  # ISO date of predicted peak, e.g. "2026-04-05"

    def __post_init__(self):
        """Validate fields after construction."""
        if not self.topic or not str(self.topic).strip():
            raise ValueError("topic must be a non-empty string")
        if self.source not in _VALID_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(_VALID_SOURCES)}, got {self.source!r}"
            )
        self.score = float(max(_SCORE_MIN, min(_SCORE_MAX, float(self.score))))
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Serialize to plain dictionary."""
        return {
            "topic": self.topic,
            "source": self.source,
            "score": self.score,
            "trend_velocity": self.trend_velocity,
            "subreddit": self.subreddit,
            "reason": self.reason,
            "fetched_at": self.fetched_at,
            "predicted_peak": self.predicted_peak,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TopicCandidate":
        """Deserialize from dictionary. Validates required fields."""
        topic = str(data.get("topic", "")).strip()
        source = str(data.get("source", ""))
        score = float(data.get("score", 0.0))
        trend_velocity = float(data.get("trend_velocity", 0.0))
        subreddit = str(data.get("subreddit", ""))
        reason = str(data.get("reason", ""))
        fetched_at = str(data.get("fetched_at", ""))
        predicted_peak = str(data.get("predicted_peak", ""))
        return cls(
            topic=topic,
            source=source,
            score=score,
            trend_velocity=trend_velocity,
            subreddit=subreddit,
            reason=reason,
            fetched_at=fetched_at,
            predicted_peak=predicted_peak,
        )


# ---------------------------------------------------------------------------
# TrendDetector
# ---------------------------------------------------------------------------

class TrendDetector:
    """Fetches, scores, and caches trending topics from Google Trends and Reddit."""

    _STORAGE_FILE = ".mp/trending_topics.json"
    _MAX_CACHE_AGE_HOURS = 24
    _REDDIT_BASE_URL = "https://www.reddit.com"
    _MAX_TOPICS = 100
    _MAX_TOPIC_LEN = 500
    _MAX_REASON_LEN = 1000

    def __init__(self, niches: list[str] = None):
        self.niches = niches or ["technology", "trending"]
        self._storage_path = os.path.join(ROOT_DIR, self._STORAGE_FILE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_google_trends(self, niche: str) -> list[TopicCandidate]:
        """Fetch trending topics from Google Trends via trendspyg.

        Args:
            niche: A keyword niche to query (e.g. "technology").

        Returns:
            List of TopicCandidate objects. Empty list on failure.
        """
        logger.info(f"fetch_google_trends: niche={niche!r}")
        try:
            from trendspyg import TrendSpyG  # lazy import
        except ImportError:
            logger.warning("trendspyg not installed; skipping Google Trends fetch")
            return []

        try:
            ts = TrendSpyG()
            df = ts.trending_searches(geo="US")
            candidates: list[TopicCandidate] = []
            now = datetime.now(timezone.utc).isoformat()
            for row in df.itertuples(index=False):
                raw_topic = str(row[0]).strip()
                if not raw_topic:
                    continue
                raw_topic = raw_topic[: self._MAX_TOPIC_LEN]
                candidates.append(
                    TopicCandidate(
                        topic=raw_topic,
                        source="google_trends",
                        score=5.0,
                        trend_velocity=0.0,
                        fetched_at=now,
                    )
                )
            logger.info(
                f"fetch_google_trends: fetched {len(candidates)} topics for niche={niche!r}"
            )
            return candidates
        except Exception as exc:
            logger.warning(f"fetch_google_trends failed for niche={niche!r}: {exc}")
            return []

    def fetch_reddit_trending(
        self, subreddit: str, limit: int = 25
    ) -> list[TopicCandidate]:
        """Fetch hot topics from a subreddit via the public JSON API.

        Args:
            subreddit: Subreddit name (alphanumeric + underscores, max 21 chars).
            limit: Number of hot posts to fetch (default 25).

        Returns:
            List of TopicCandidate objects. Empty list on error.
        """
        logger.info(f"fetch_reddit_trending: subreddit={subreddit!r} limit={limit}")

        if not _SUBREDDIT_NAME_RE.match(subreddit):
            logger.warning(
                f"fetch_reddit_trending: invalid subreddit name {subreddit!r}; "
                "must be alphanumeric + underscores, max 21 chars"
            )
            return []

        try:
            import requests  # lazy import
        except ImportError:
            logger.warning("requests not installed; skipping Reddit fetch")
            return []

        url = f"{self._REDDIT_BASE_URL}/r/{subreddit}/hot.json?limit={limit}"
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "MoneyPrinter/1.0"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            children = data.get("data", {}).get("children", [])
            candidates: list[TopicCandidate] = []
            now = datetime.now(timezone.utc).isoformat()
            for child in children:
                post_data = child.get("data", {})
                title = str(post_data.get("title", "")).strip()
                if not title:
                    continue
                title = title[: self._MAX_TOPIC_LEN]
                score_raw = float(post_data.get("score", 0))
                ups = float(post_data.get("ups", 0))
                # Normalize reddit score to 0-10 scale (heuristic)
                trend_velocity = ups
                # Clamp a rough score into 0-10 (max out at 10k upvotes = 10.0)
                normalized = float(min(10.0, score_raw / 1000.0))
                normalized = float(max(0.0, normalized))
                candidates.append(
                    TopicCandidate(
                        topic=title,
                        source="reddit",
                        score=normalized,
                        trend_velocity=trend_velocity,
                        subreddit=subreddit,
                        fetched_at=now,
                    )
                )
            logger.info(
                f"fetch_reddit_trending: fetched {len(candidates)} posts "
                f"from r/{subreddit}"
            )
            return candidates
        except Exception as exc:
            logger.warning(
                f"fetch_reddit_trending failed for r/{subreddit}: {exc}"
            )
            return []

    def score_topics(
        self, candidates: list[TopicCandidate]
    ) -> list[TopicCandidate]:
        """Score each topic using the LLM for short-form video worthiness.

        Updates candidate.score and candidate.reason in-place. On LLM
        failure the existing score is preserved and reason is set to
        "LLM unavailable".

        Args:
            candidates: List of TopicCandidate objects to score.

        Returns:
            The same list with updated scores/reasons.
        """
        logger.info(f"score_topics: scoring {len(candidates)} candidates")

        try:
            from llm_provider import generate_text  # lazy import
        except ImportError:
            logger.warning("llm_provider not available; skipping LLM scoring")
            for c in candidates:
                c.reason = "LLM unavailable"
            return candidates

        for candidate in candidates:
            prompt = (
                f"Rate this topic for short-form video potential (1-10): "
                f"{candidate.topic}. "
                f'Respond with JSON: {{"score": N, "reason": "..."}}'
            )
            try:
                raw = generate_text(prompt)
                parsed = self._parse_score_response(raw)
                candidate.score = float(
                    max(_SCORE_MIN, min(_SCORE_MAX, float(parsed["score"])))
                )
                candidate.reason = str(parsed.get("reason", ""))[:self._MAX_REASON_LEN]
            except Exception as exc:
                logger.debug(
                    f"score_topics: LLM scoring failed for {candidate.topic!r}: {exc}"
                )
                candidate.reason = "LLM unavailable"

        logger.info("score_topics: scoring complete")
        return candidates

    def detect(
        self,
        niches: list[str] = None,
        subreddits: list[str] = None,
    ) -> list[TopicCandidate]:
        """Full pipeline: fetch → deduplicate → score → rank → cache.

        Args:
            niches: List of niche keywords for Google Trends. Defaults to
                    self.niches.
            subreddits: List of subreddit names for Reddit. Defaults to
                        the same list as niches.

        Returns:
            Ranked list of TopicCandidate objects (highest score first).
        """
        niches = self.niches if niches is None else niches
        subreddits = list(niches) if subreddits is None else subreddits

        logger.info(
            f"detect: niches={niches}, subreddits={subreddits}"
        )

        all_candidates: list[TopicCandidate] = []

        # 1. Fetch from Google Trends
        for niche in niches:
            all_candidates.extend(self.fetch_google_trends(niche))

        # 2. Fetch from Reddit
        for sub in subreddits:
            all_candidates.extend(self.fetch_reddit_trending(sub))

        # 3. Deduplicate by topic (case-insensitive, keep first occurrence)
        seen: set[str] = set()
        unique: list[TopicCandidate] = []
        for c in all_candidates:
            key = c.topic.lower()
            if key not in seen:
                seen.add(key)
                unique.append(c)

        # 4. Score via LLM
        scored = self.score_topics(unique)

        # 5. Sort by score descending
        scored.sort(key=lambda c: c.score, reverse=True)

        # 6. Save to cache
        self._save_cache(scored)

        logger.info(f"detect: returning {len(scored)} ranked topics")
        return scored

    def predict_trends(
        self, topics: list[str] = None, days: int = 7
    ) -> list[TopicCandidate]:
        """Predict which topics will trend based on historical velocity.

        Uses Google Trends interest-over-time data with linear regression
        to identify topics with rising trajectories.

        Args:
            topics: List of topic strings to analyze. If None, uses cached topics.
            days: Number of historical days to analyze (default 7).

        Returns:
            List of TopicCandidate with predicted_peak set, sorted by score descending.
        """
        logger.info(f"predict_trends: topics={topics!r} days={days}")

        try:
            from trendspyg import TrendSpyG  # lazy import
        except ImportError:
            logger.warning("trendspyg not installed; predict_trends returning empty list")
            return []

        if topics is None:
            cached = self._load_cache()
            topics = [c.topic for c in cached]

        if not topics:
            return []

        candidates: list[TopicCandidate] = []
        now = datetime.now(timezone.utc).isoformat()
        for topic in topics:
            try:
                ts = TrendSpyG()
                ts.build_payload([topic], timeframe=f"now {days}-d")
                df = ts.interest_over_time()
                values: list[float] = []
                if df is not None and not df.empty and topic in df.columns:
                    values = [float(v) for v in df[topic].tolist()]
                slope, predicted_peak = self._forecast_peak(values, days_ahead=days)
                # Normalize slope to 0-10 score
                raw_score = slope * 2.0
                score = float(max(_SCORE_MIN, min(_SCORE_MAX, raw_score)))
                candidates.append(
                    TopicCandidate(
                        topic=topic,
                        source="google_trends",
                        score=score,
                        trend_velocity=slope,
                        fetched_at=now,
                        predicted_peak=predicted_peak,
                    )
                )
            except Exception as exc:
                logger.debug(f"predict_trends: failed for topic={topic!r}: {exc}")
                continue

        candidates.sort(key=lambda c: c.score, reverse=True)
        logger.info(f"predict_trends: returning {len(candidates)} candidates")
        return candidates

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _load_cache(self) -> list[TopicCandidate]:
        """Load cached topics. Returns empty list if cache missing or expired."""
        if not os.path.exists(self._storage_path):
            return []

        try:
            mtime = os.path.getmtime(self._storage_path)
            age_hours = (
                datetime.now(timezone.utc).timestamp() - mtime
            ) / 3600.0
            if age_hours > self._MAX_CACHE_AGE_HOURS:
                logger.debug("_load_cache: cache expired")
                return []

            with open(self._storage_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, list):
                return []
            candidates = []
            for item in raw:
                try:
                    candidates.append(TopicCandidate.from_dict(item))
                except (KeyError, ValueError, TypeError):
                    continue
            logger.debug(f"_load_cache: loaded {len(candidates)} topics")
            return candidates
        except (OSError, json.JSONDecodeError, Exception) as exc:
            logger.warning(f"_load_cache: failed to load cache: {exc}")
            return []

    def _save_cache(self, topics: list[TopicCandidate]) -> None:
        """Atomically save topics to JSON cache, truncated to _MAX_TOPICS."""
        truncated = topics[: self._MAX_TOPICS]
        dir_name = os.path.dirname(self._storage_path)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump([t.to_dict() for t in truncated], fh, indent=2)
            os.replace(tmp_path, self._storage_path)
            logger.debug(f"_save_cache: saved {len(truncated)} topics to {self._storage_path}")
        except Exception as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            logger.error(f"_save_cache: failed: {exc}")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _forecast_peak(values: list[float], days_ahead: int = 7) -> tuple[float, str]:
        """Compute linear trend slope and predict peak date.

        Args:
            values: Interest-over-time values (one per day).
            days_ahead: Max days to extrapolate forward.

        Returns:
            (slope, predicted_peak_iso): slope is the daily change rate.
            predicted_peak_iso is ISO date of predicted peak, or "" if declining/flat.
        """
        if len(values) < 2:
            return (0.0, "")

        try:
            import numpy as np
            coeffs = np.polyfit(range(len(values)), values, 1)
            slope = float(coeffs[0])
        except ImportError:
            # Pure Python fallback
            slope = (values[-1] - values[0]) / (len(values) - 1)

        # Treat near-zero slopes as flat (numpy.polyfit can return values
        # like 1e-17 for perfectly flat input due to floating-point noise).
        if slope <= 1e-9:
            return (0.0 if abs(slope) <= 1e-9 else slope, "")

        # Extrapolate: find day where value reaches max(values) * 1.5, capped at days_ahead
        current_max = max(values)
        target = current_max * 1.5
        last_value = values[-1]
        if slope > 0:
            days_to_target = (target - last_value) / slope
        else:
            days_to_target = float(days_ahead)
        estimated_days = int(min(days_ahead, max(1, round(days_to_target))))
        peak_date = (
            datetime.now(timezone.utc) + timedelta(days=estimated_days)
        ).strftime("%Y-%m-%d")
        return (slope, peak_date)

    @staticmethod
    def _parse_score_response(text: str) -> dict:
        """Extract score and reason from LLM JSON response.

        Falls back to defaults on parse failure.
        """
        try:
            json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score = float(data.get("score", 5.0))
                reason = str(data.get("reason", ""))
                return {"score": score, "reason": reason}
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # Fallback: try to extract a bare number
        number_match = re.search(r"\b([0-9](?:\.[0-9]+)?|10(?:\.0+)?)\b", text)
        if number_match:
            return {"score": float(number_match.group(1)), "reason": ""}

        return {"score": 5.0, "reason": ""}

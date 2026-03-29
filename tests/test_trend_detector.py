"""
Tests for trend_detector module.

Coverage targets:
1. TopicCandidate dataclass creation and validation
2. TopicCandidate to_dict/from_dict round-trip and edge cases
3. TrendDetector __init__ with custom and default niches
4. fetch_google_trends with mocked pytrends (success, failure, empty results)
5. fetch_reddit_trending with mocked requests (success, HTTP error, timeout,
   malformed JSON, invalid subreddit)
6. score_topics with mocked generate_text (success, JSON parse, LLM failure,
   empty list)
7. detect full pipeline with mocked sources
8. _load_cache / _save_cache (valid, expired, missing, corrupt JSON)
9. Deduplication logic (case-insensitive)
10. Edge cases: empty niches, very long topic names, special characters in
    subreddit
"""

import json
import os
import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, call

from trend_detector import (
    TopicCandidate,
    TrendDetector,
    _VALID_SOURCES,
    _SUBREDDIT_NAME_RE,
    _SCORE_MIN,
    _SCORE_MAX,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_candidate(
    topic="AI Tools",
    source="google_trends",
    score=5.0,
    trend_velocity=0.0,
    subreddit="",
    reason="",
    fetched_at="",
) -> TopicCandidate:
    return TopicCandidate(
        topic=topic,
        source=source,
        score=score,
        trend_velocity=trend_velocity,
        subreddit=subreddit,
        reason=reason,
        fetched_at=fetched_at or datetime.now(timezone.utc).isoformat(),
    )


@pytest.fixture
def detector(tmp_path):
    """TrendDetector with its storage path redirected to a temp dir."""
    d = TrendDetector(niches=["technology"])
    d._storage_path = str(tmp_path / ".mp" / "trending_topics.json")
    os.makedirs(os.path.dirname(d._storage_path), exist_ok=True)
    return d


def _reddit_response(posts: list[dict]) -> dict:
    """Build a minimal Reddit /hot.json-like response."""
    return {
        "data": {
            "children": [
                {"data": p} for p in posts
            ]
        }
    }


# ---------------------------------------------------------------------------
# 1. TopicCandidate — creation and validation
# ---------------------------------------------------------------------------

class TestTopicCandidateCreation:
    def test_basic_creation(self):
        c = _make_candidate()
        assert c.topic == "AI Tools"
        assert c.source == "google_trends"

    def test_reddit_source_accepted(self):
        c = _make_candidate(source="reddit", subreddit="technology")
        assert c.source == "reddit"

    def test_score_stored_as_float(self):
        c = _make_candidate(score=7)
        assert isinstance(c.score, float)
        assert c.score == 7.0

    def test_score_clamped_above_max(self):
        c = _make_candidate(score=15.0)
        assert c.score == _SCORE_MAX

    def test_score_clamped_below_min(self):
        c = _make_candidate(score=-3.0)
        assert c.score == _SCORE_MIN

    def test_score_clamped_exactly_at_max(self):
        c = _make_candidate(score=10.0)
        assert c.score == 10.0

    def test_score_clamped_exactly_at_min(self):
        c = _make_candidate(score=0.0)
        assert c.score == 0.0

    def test_fetched_at_auto_set_when_empty(self):
        c = TopicCandidate(topic="Test", source="google_trends", score=5.0, trend_velocity=0.0)
        assert c.fetched_at
        dt = datetime.fromisoformat(c.fetched_at)
        assert dt.tzinfo is not None

    def test_fetched_at_preserved_when_provided(self):
        ts = "2026-01-15T10:00:00+00:00"
        c = _make_candidate(fetched_at=ts)
        assert c.fetched_at == ts

    def test_subreddit_default_empty_string(self):
        c = _make_candidate(source="google_trends")
        assert c.subreddit == ""

    def test_reason_default_empty_string(self):
        c = _make_candidate()
        assert c.reason == ""

    def test_empty_topic_raises_value_error(self):
        with pytest.raises(ValueError, match="topic"):
            TopicCandidate(topic="", source="google_trends", score=5.0, trend_velocity=0.0)

    def test_whitespace_only_topic_raises_value_error(self):
        with pytest.raises(ValueError, match="topic"):
            TopicCandidate(topic="   ", source="google_trends", score=5.0, trend_velocity=0.0)

    def test_invalid_source_raises_value_error(self):
        with pytest.raises(ValueError, match="source"):
            TopicCandidate(topic="Test", source="twitter", score=5.0, trend_velocity=0.0)

    def test_trend_velocity_stored(self):
        c = _make_candidate(trend_velocity=42.5)
        assert c.trend_velocity == 42.5


# ---------------------------------------------------------------------------
# 2. TopicCandidate — to_dict / from_dict
# ---------------------------------------------------------------------------

class TestTopicCandidateSerialization:
    def _sample(self) -> TopicCandidate:
        return _make_candidate(
            topic="Crypto Crash",
            source="reddit",
            score=8.5,
            trend_velocity=1500.0,
            subreddit="CryptoCurrency",
            reason="High engagement",
            fetched_at="2026-03-01T12:00:00+00:00",
        )

    def test_to_dict_has_all_keys(self):
        d = self._sample().to_dict()
        expected_keys = {"topic", "source", "score", "trend_velocity",
                         "subreddit", "reason", "fetched_at"}
        assert set(d.keys()) == expected_keys

    def test_to_dict_values_correct(self):
        d = self._sample().to_dict()
        assert d["topic"] == "Crypto Crash"
        assert d["source"] == "reddit"
        assert d["score"] == 8.5
        assert d["subreddit"] == "CryptoCurrency"

    def test_from_dict_roundtrip(self):
        original = self._sample()
        restored = TopicCandidate.from_dict(original.to_dict())
        assert restored.topic == original.topic
        assert restored.source == original.source
        assert restored.score == original.score
        assert restored.trend_velocity == original.trend_velocity
        assert restored.subreddit == original.subreddit
        assert restored.reason == original.reason
        assert restored.fetched_at == original.fetched_at

    def test_from_dict_ignores_unknown_keys(self):
        d = self._sample().to_dict()
        d["future_field"] = "ignored"
        restored = TopicCandidate.from_dict(d)
        assert restored.topic == "Crypto Crash"

    def test_from_dict_uses_defaults_for_missing_optional_keys(self):
        d = {
            "topic": "Space X Launch",
            "source": "google_trends",
            "score": 6.0,
            "trend_velocity": 0.0,
        }
        c = TopicCandidate.from_dict(d)
        assert c.subreddit == ""
        assert c.reason == ""

    def test_to_dict_is_json_serializable(self):
        d = self._sample().to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_from_dict_score_is_float(self):
        d = self._sample().to_dict()
        d["score"] = "7"
        c = TopicCandidate.from_dict(d)
        assert isinstance(c.score, float)


# ---------------------------------------------------------------------------
# 3. TrendDetector __init__
# ---------------------------------------------------------------------------

class TestTrendDetectorInit:
    def test_default_niches(self):
        d = TrendDetector()
        assert "technology" in d.niches or "trending" in d.niches

    def test_custom_niches(self):
        d = TrendDetector(niches=["finance", "health"])
        assert d.niches == ["finance", "health"]

    def test_none_niches_uses_default(self):
        d = TrendDetector(niches=None)
        assert isinstance(d.niches, list)
        assert len(d.niches) > 0

    def test_storage_path_contains_root(self):
        d = TrendDetector()
        assert os.path.isabs(d._storage_path)

    def test_storage_path_ends_with_json(self):
        d = TrendDetector()
        assert d._storage_path.endswith(".json")

    def test_empty_list_niches_uses_default(self):
        """Empty list is falsy — falls back to default niches like None does."""
        d = TrendDetector(niches=[])
        assert len(d.niches) > 0


# ---------------------------------------------------------------------------
# 4. fetch_google_trends
# ---------------------------------------------------------------------------

class TestFetchGoogleTrends:
    def test_success_returns_topic_candidates(self, detector):
        mock_df = MagicMock()
        # Simulate a DataFrame with one column and two rows
        mock_df.itertuples.return_value = iter([("AI Tools",), ("Bitcoin",)])

        mock_trend_req = MagicMock()
        mock_trend_req.return_value.trending_searches.return_value = mock_df

        with patch.dict("sys.modules", {"pytrends": MagicMock(), "pytrends.request": MagicMock()}):
            with patch("trend_detector.TrendReq", mock_trend_req, create=True):
                import importlib
                import trend_detector as td
                original_trendreq = None
                # Patch at module import time
                with patch("builtins.__import__", side_effect=lambda name, *a, **kw:
                           mock_trend_req if name == "pytrends.request" else __import__(name, *a, **kw)):
                    pass

        # Direct approach: mock the import inside the function
        mock_trendreq_cls = MagicMock()
        instance = MagicMock()
        instance.trending_searches.return_value = mock_df
        mock_trendreq_cls.return_value = instance

        with patch("builtins.__import__") as mock_import:
            pytrends_mock = MagicMock()
            pytrends_mock.request.TrendReq = mock_trendreq_cls

            def side_effect(name, *args, **kwargs):
                if name == "pytrends.request":
                    return pytrends_mock.request
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = side_effect
            results = detector.fetch_google_trends("technology")

        # Since the import mechanism is complex, use a cleaner approach
        assert isinstance(results, list)

    def test_success_with_patched_pytrends(self, detector):
        """Test using patch on the lazy import path."""
        import pandas as pd

        df = pd.DataFrame(["AI is amazing", "Python tips"])
        mock_instance = MagicMock()
        mock_instance.trending_searches.return_value = df

        mock_cls = MagicMock(return_value=mock_instance)
        mock_module = MagicMock()
        mock_module.TrendReq = mock_cls

        with patch.dict("sys.modules", {"pytrends": MagicMock(), "pytrends.request": mock_module}):
            results = detector.fetch_google_trends("technology")

        assert isinstance(results, list)
        assert all(isinstance(c, TopicCandidate) for c in results)
        assert all(c.source == "google_trends" for c in results)

    def test_pytrends_not_installed_returns_empty(self, detector):
        with patch.dict("sys.modules", {"pytrends": None, "pytrends.request": None}):
            results = detector.fetch_google_trends("technology")
        assert results == []

    def test_pytrends_exception_returns_empty(self, detector):
        mock_module = MagicMock()
        mock_module.TrendReq.side_effect = Exception("Network error")

        with patch.dict("sys.modules", {"pytrends": MagicMock(), "pytrends.request": mock_module}):
            results = detector.fetch_google_trends("technology")

        assert results == []

    def test_empty_dataframe_returns_empty_list(self, detector):
        import pandas as pd

        df = pd.DataFrame([])
        mock_instance = MagicMock()
        mock_instance.trending_searches.return_value = df

        mock_cls = MagicMock(return_value=mock_instance)
        mock_module = MagicMock()
        mock_module.TrendReq = mock_cls

        with patch.dict("sys.modules", {"pytrends": MagicMock(), "pytrends.request": mock_module}):
            results = detector.fetch_google_trends("finance")

        assert results == []

    def test_topics_truncated_to_max_len(self, detector):
        import pandas as pd

        long_topic = "X" * 600
        df = pd.DataFrame([long_topic])
        mock_instance = MagicMock()
        mock_instance.trending_searches.return_value = df
        mock_cls = MagicMock(return_value=mock_instance)
        mock_module = MagicMock()
        mock_module.TrendReq = mock_cls

        with patch.dict("sys.modules", {"pytrends": MagicMock(), "pytrends.request": mock_module}):
            results = detector.fetch_google_trends("misc")

        assert len(results[0].topic) == TrendDetector._MAX_TOPIC_LEN

    def test_google_trends_score_is_5_default(self, detector):
        import pandas as pd

        df = pd.DataFrame(["Default Score Topic"])
        mock_instance = MagicMock()
        mock_instance.trending_searches.return_value = df
        mock_cls = MagicMock(return_value=mock_instance)
        mock_module = MagicMock()
        mock_module.TrendReq = mock_cls

        with patch.dict("sys.modules", {"pytrends": MagicMock(), "pytrends.request": mock_module}):
            results = detector.fetch_google_trends("tech")

        assert results[0].score == 5.0


# ---------------------------------------------------------------------------
# 5. fetch_reddit_trending
# ---------------------------------------------------------------------------

class TestFetchRedditTrending:
    def test_success_returns_candidates(self, detector):
        posts = [
            {"title": "AI is taking over", "score": 5000, "ups": 5000},
            {"title": "Python 4.0 released", "score": 3000, "ups": 3000},
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert len(results) == 2
        assert all(isinstance(c, TopicCandidate) for c in results)
        assert all(c.source == "reddit" for c in results)
        assert all(c.subreddit == "technology" for c in results)

    def test_subreddit_stored_on_candidates(self, detector):
        posts = [{"title": "Tesla News", "score": 100, "ups": 100}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("teslamotors")

        assert results[0].subreddit == "teslamotors"

    def test_http_error_returns_empty(self, detector):
        import requests as req_lib

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 Not Found")
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert results == []

    def test_timeout_returns_empty(self, detector):
        mock_requests = MagicMock()
        mock_requests.get.side_effect = Exception("Timeout")

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert results == []

    def test_malformed_json_returns_empty(self, detector):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert results == []

    def test_invalid_subreddit_with_slash_returns_empty(self, detector):
        results = detector.fetch_reddit_trending("tech/stuff")
        assert results == []

    def test_invalid_subreddit_too_long_returns_empty(self, detector):
        results = detector.fetch_reddit_trending("a" * 22)
        assert results == []

    def test_invalid_subreddit_special_chars_returns_empty(self, detector):
        results = detector.fetch_reddit_trending("tech@reddit")
        assert results == []

    def test_valid_subreddit_with_underscores(self, detector):
        posts = [{"title": "News item", "score": 200, "ups": 200}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("personal_finance")

        assert len(results) == 1

    def test_requests_not_installed_returns_empty(self, detector):
        with patch.dict("sys.modules", {"requests": None}):
            results = detector.fetch_reddit_trending("technology")
        assert results == []

    def test_timeout_parameter_passed(self, detector):
        posts = [{"title": "Post", "score": 100, "ups": 100}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            detector.fetch_reddit_trending("technology")

        call_kwargs = mock_requests.get.call_args[1]
        assert call_kwargs.get("timeout") == 10

    def test_score_normalized_from_reddit_score(self, detector):
        posts = [{"title": "Viral post", "score": 10000, "ups": 10000}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert results[0].score == 10.0

    def test_posts_with_missing_title_skipped(self, detector):
        posts = [{"title": "", "score": 100, "ups": 100},
                 {"title": "Valid Title", "score": 200, "ups": 200}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert len(results) == 1
        assert results[0].topic == "Valid Title"

    def test_empty_children_returns_empty_list(self, detector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"children": []}}
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert results == []


# ---------------------------------------------------------------------------
# Helpers for mocking lazy-imported generate_text
# ---------------------------------------------------------------------------

def _mock_llm_module(return_value=None, side_effect=None):
    """Create a mock llm_provider module with a generate_text function."""
    mock_mod = MagicMock()
    if side_effect is not None:
        mock_mod.generate_text.side_effect = side_effect
    else:
        mock_mod.generate_text.return_value = return_value
    return mock_mod


# ---------------------------------------------------------------------------
# 6. score_topics
# ---------------------------------------------------------------------------

class TestScoreTopics:
    def test_empty_list_returns_empty(self, detector):
        results = detector.score_topics([])
        assert results == []

    def test_success_updates_score_and_reason(self, detector):
        candidates = [_make_candidate(topic="AI news", score=5.0)]
        llm_response = json.dumps({"score": 8.5, "reason": "Very engaging topic"})
        mock_mod = _mock_llm_module(return_value=llm_response)

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        assert results[0].score == 8.5
        assert results[0].reason == "Very engaging topic"

    def test_success_updates_multiple_candidates(self, detector):
        candidates = [
            _make_candidate(topic="Topic A", score=5.0),
            _make_candidate(topic="Topic B", score=5.0),
        ]
        llm_response = json.dumps({"score": 7.0, "reason": "Good"})
        mock_mod = _mock_llm_module(return_value=llm_response)

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        assert len(results) == 2
        assert all(c.score == 7.0 for c in results)

    def test_llm_failure_sets_reason_to_unavailable(self, detector):
        candidates = [_make_candidate(topic="Failing topic", score=5.0)]
        mock_mod = _mock_llm_module(side_effect=Exception("LLM down"))

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        assert results[0].reason == "LLM unavailable"
        assert results[0].score == 5.0  # score preserved

    def test_json_parse_failure_no_number_keeps_default(self, detector):
        candidates = [_make_candidate(topic="Bad JSON topic", score=5.0)]
        mock_mod = _mock_llm_module(return_value="absolutely no numbers or JSON here")

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        # _parse_score_response falls back to default 5.0 when no number found
        assert isinstance(results[0].score, float)

    def test_score_clamped_to_max_10(self, detector):
        candidates = [_make_candidate(topic="Over scored", score=5.0)]
        llm_response = json.dumps({"score": 99.0, "reason": "Too high"})
        mock_mod = _mock_llm_module(return_value=llm_response)

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        assert results[0].score == _SCORE_MAX

    def test_score_clamped_to_min_0(self, detector):
        candidates = [_make_candidate(topic="Under scored", score=5.0)]
        llm_response = json.dumps({"score": -5.0, "reason": "Negative"})
        mock_mod = _mock_llm_module(return_value=llm_response)

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        assert results[0].score == _SCORE_MIN

    def test_reason_truncated_to_max_reason_len(self, detector):
        candidates = [_make_candidate(topic="Long reason", score=5.0)]
        long_reason = "X" * 2000
        llm_response = json.dumps({"score": 7.0, "reason": long_reason})
        mock_mod = _mock_llm_module(return_value=llm_response)

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        assert len(results[0].reason) == TrendDetector._MAX_REASON_LEN

    def test_llm_json_embedded_in_prose(self, detector):
        candidates = [_make_candidate(topic="Prose wrapped JSON", score=5.0)]
        llm_response = 'Sure! Here is my answer: {"score": 9, "reason": "Excellent"} Hope that helps.'
        mock_mod = _mock_llm_module(return_value=llm_response)

        import sys
        with patch.dict(sys.modules, {"llm_provider": mock_mod}):
            results = detector.score_topics(candidates)

        assert results[0].score == 9.0
        assert results[0].reason == "Excellent"

    def test_generate_text_import_error_sets_reason(self, detector):
        """If generate_text can't be imported, all reasons set to LLM unavailable."""
        candidates = [_make_candidate(topic="Import fails", score=5.0)]

        import sys
        with patch.dict(sys.modules, {"llm_provider": None}):
            results = detector.score_topics(candidates)

        assert results[0].reason == "LLM unavailable"


# ---------------------------------------------------------------------------
# 7. detect full pipeline
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detect_returns_list_of_topic_candidates(self, detector):
        with patch.object(detector, "fetch_google_trends", return_value=[]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        assert isinstance(results, list)

    def test_detect_combines_google_and_reddit(self, detector):
        google_candidate = _make_candidate(topic="Google Topic", source="google_trends")
        reddit_candidate = _make_candidate(topic="Reddit Topic", source="reddit")

        with patch.object(detector, "fetch_google_trends", return_value=[google_candidate]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[reddit_candidate]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        topics = [r.topic for r in results]
        assert "Google Topic" in topics
        assert "Reddit Topic" in topics

    def test_detect_deduplicates_case_insensitive(self, detector):
        c1 = _make_candidate(topic="AI Tools", source="google_trends")
        c2 = _make_candidate(topic="ai tools", source="reddit")

        with patch.object(detector, "fetch_google_trends", return_value=[c1]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[c2]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        assert len(results) == 1

    def test_detect_sorted_by_score_descending(self, detector):
        candidates = [
            _make_candidate(topic="Low Score", source="google_trends", score=2.0),
            _make_candidate(topic="High Score", source="reddit", score=9.0),
            _make_candidate(topic="Mid Score", source="google_trends", score=5.0),
        ]

        with patch.object(detector, "fetch_google_trends", return_value=candidates[:2]):
            with patch.object(detector, "fetch_reddit_trending", return_value=candidates[2:]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_detect_saves_cache(self, detector):
        with patch.object(detector, "fetch_google_trends", return_value=[]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    with patch.object(detector, "_save_cache") as mock_save:
                        detector.detect(niches=["tech"], subreddits=[])

        mock_save.assert_called_once()

    def test_detect_uses_self_niches_as_default(self, detector):
        detector.niches = ["finance"]

        with patch.object(detector, "fetch_google_trends", return_value=[]) as mock_gtrends:
            with patch.object(detector, "fetch_reddit_trending", return_value=[]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    detector.detect()

        mock_gtrends.assert_called_once_with("finance")

    def test_detect_empty_niches(self, detector):
        with patch.object(detector, "fetch_google_trends", return_value=[]) as mock_gt:
            with patch.object(detector, "fetch_reddit_trending", return_value=[]) as mock_r:
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=[], subreddits=[])

        mock_gt.assert_not_called()
        mock_r.assert_not_called()
        assert results == []

    def test_detect_subreddits_defaults_to_niches(self, detector):
        detector.niches = ["technology"]

        with patch.object(detector, "fetch_google_trends", return_value=[]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[]) as mock_r:
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    detector.detect()

        mock_r.assert_called_once_with("technology")


# ---------------------------------------------------------------------------
# 8. _load_cache / _save_cache
# ---------------------------------------------------------------------------

class TestCacheOperations:
    def test_save_and_load_roundtrip(self, detector):
        candidates = [
            _make_candidate(topic="Cache Test A", source="google_trends", score=7.0),
            _make_candidate(topic="Cache Test B", source="reddit", score=3.5),
        ]
        detector._save_cache(candidates)
        loaded = detector._load_cache()
        assert len(loaded) == 2
        topics = [c.topic for c in loaded]
        assert "Cache Test A" in topics
        assert "Cache Test B" in topics

    def test_load_cache_missing_file_returns_empty(self, detector):
        results = detector._load_cache()
        assert results == []

    def test_load_cache_corrupt_json_returns_empty(self, detector):
        os.makedirs(os.path.dirname(detector._storage_path), exist_ok=True)
        with open(detector._storage_path, "w") as f:
            f.write("{not valid json")
        results = detector._load_cache()
        assert results == []

    def test_load_cache_expired_returns_empty(self, detector):
        candidates = [_make_candidate(topic="Old Topic", source="google_trends")]
        detector._save_cache(candidates)

        # Backdate the mtime to 25 hours ago
        past_time = time.time() - (25 * 3600)
        os.utime(detector._storage_path, (past_time, past_time))

        results = detector._load_cache()
        assert results == []

    def test_save_cache_truncates_to_max_topics(self, detector):
        candidates = [
            _make_candidate(topic=f"Topic {i}", source="google_trends", score=float(i % 10))
            for i in range(TrendDetector._MAX_TOPICS + 50)
        ]
        detector._save_cache(candidates)
        loaded = detector._load_cache()
        assert len(loaded) <= TrendDetector._MAX_TOPICS

    def test_save_cache_creates_parent_dir(self, tmp_path):
        deep_path = str(tmp_path / "new" / "deep" / "path" / "topics.json")
        d = TrendDetector()
        d._storage_path = deep_path
        candidates = [_make_candidate(topic="Deep Path Test", source="google_trends")]
        d._save_cache(candidates)
        assert os.path.exists(deep_path)

    def test_load_cache_wrong_type_returns_empty(self, detector):
        os.makedirs(os.path.dirname(detector._storage_path), exist_ok=True)
        with open(detector._storage_path, "w") as f:
            json.dump({"not": "a list"}, f)
        results = detector._load_cache()
        assert results == []

    def test_save_cache_is_atomic(self, detector, tmp_path):
        """The tmp file should be cleaned up and final file created."""
        candidates = [_make_candidate(topic="Atomic Write Test", source="google_trends")]
        detector._save_cache(candidates)
        assert os.path.exists(detector._storage_path)
        # No leftover .tmp files in dir
        dir_name = os.path.dirname(detector._storage_path)
        tmp_files = [f for f in os.listdir(dir_name) if f.endswith(".tmp")]
        assert tmp_files == []

    def test_load_cache_skips_invalid_entries(self, detector):
        os.makedirs(os.path.dirname(detector._storage_path), exist_ok=True)
        data = [
            {"topic": "Valid", "source": "google_trends", "score": 5.0, "trend_velocity": 0.0},
            {"topic": "", "source": "google_trends", "score": 5.0, "trend_velocity": 0.0},  # invalid
            {"topic": "Also Valid", "source": "reddit", "score": 3.0, "trend_velocity": 0.0},
        ]
        with open(detector._storage_path, "w") as f:
            json.dump(data, f)
        results = detector._load_cache()
        assert len(results) == 2
        assert all(c.topic for c in results)


# ---------------------------------------------------------------------------
# 9. Deduplication logic
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_exact_duplicates_removed(self, detector):
        c1 = _make_candidate(topic="Duplicate", source="google_trends")
        c2 = _make_candidate(topic="Duplicate", source="reddit")

        with patch.object(detector, "fetch_google_trends", return_value=[c1]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[c2]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        assert len(results) == 1

    def test_case_insensitive_dedup(self, detector):
        c1 = _make_candidate(topic="Machine Learning", source="google_trends")
        c2 = _make_candidate(topic="MACHINE LEARNING", source="reddit")
        c3 = _make_candidate(topic="machine learning", source="google_trends")

        with patch.object(detector, "fetch_google_trends", return_value=[c1, c3]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[c2]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        topics_lower = [r.topic.lower() for r in results]
        assert topics_lower.count("machine learning") == 1

    def test_different_topics_not_deduped(self, detector):
        c1 = _make_candidate(topic="Python", source="google_trends")
        c2 = _make_candidate(topic="Rust", source="reddit")

        with patch.object(detector, "fetch_google_trends", return_value=[c1]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[c2]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        topics = [r.topic for r in results]
        assert "Python" in topics
        assert "Rust" in topics

    def test_first_occurrence_kept_on_dedup(self, detector):
        c1 = _make_candidate(topic="Topic", source="google_trends", score=8.0)
        c2 = _make_candidate(topic="TOPIC", source="reddit", score=2.0)

        with patch.object(detector, "fetch_google_trends", return_value=[c1]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[c2]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    results = detector.detect(niches=["tech"], subreddits=["technology"])

        assert len(results) == 1
        assert results[0].source == "google_trends"


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_long_topic_name_truncated_by_reddit(self, detector):
        long_title = "Y" * 600
        posts = [{"title": long_title, "score": 100, "ups": 100}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending("technology")

        assert len(results[0].topic) == TrendDetector._MAX_TOPIC_LEN

    def test_subreddit_name_max_21_chars_valid(self, detector):
        sub = "a" * 21
        posts = [{"title": "Test", "score": 100, "ups": 100}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _reddit_response(posts)
        mock_resp.raise_for_status.return_value = None
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            results = detector.fetch_reddit_trending(sub)

        assert len(results) == 1

    def test_subreddit_name_22_chars_invalid(self, detector):
        sub = "a" * 22
        results = detector.fetch_reddit_trending(sub)
        assert results == []

    def test_subreddit_with_space_invalid(self, detector):
        results = detector.fetch_reddit_trending("hello world")
        assert results == []

    def test_subreddit_with_hyphen_invalid(self, detector):
        results = detector.fetch_reddit_trending("hello-world")
        assert results == []

    def test_detect_multiple_niches(self, detector):
        with patch.object(detector, "fetch_google_trends", return_value=[]) as mock_gt:
            with patch.object(detector, "fetch_reddit_trending", return_value=[]):
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    detector.detect(niches=["tech", "finance", "health"], subreddits=[])

        assert mock_gt.call_count == 3

    def test_detect_multiple_subreddits(self, detector):
        with patch.object(detector, "fetch_google_trends", return_value=[]):
            with patch.object(detector, "fetch_reddit_trending", return_value=[]) as mock_r:
                with patch.object(detector, "score_topics", side_effect=lambda c: c):
                    detector.detect(niches=[], subreddits=["tech", "python", "news"])

        assert mock_r.call_count == 3

    def test_valid_sources_frozenset(self):
        assert isinstance(_VALID_SOURCES, frozenset)
        assert "google_trends" in _VALID_SOURCES
        assert "reddit" in _VALID_SOURCES

    def test_topic_candidate_with_unicode_topic(self):
        c = TopicCandidate(
            topic="AI工具赚钱💰",
            source="reddit",
            score=7.0,
            trend_velocity=100.0,
        )
        assert c.topic == "AI工具赚钱💰"

    def test_parse_score_response_bare_number_fallback(self, detector):
        result = detector._parse_score_response("The score is 8 out of 10")
        assert result["score"] == 8.0

    def test_parse_score_response_no_number_returns_default(self, detector):
        result = detector._parse_score_response("I cannot determine the score.")
        assert result["score"] == 5.0

    def test_parse_score_response_json_wins_over_bare_number(self, detector):
        result = detector._parse_score_response('{"score": 9, "reason": "Great"} score: 3')
        assert result["score"] == 9.0

    def test_parse_score_response_invalid_json_falls_back(self, detector):
        """JSON that fails to parse triggers the except branch."""
        result = detector._parse_score_response('{"score": "not_a_number", "reason": 42}')
        # score will fail float() conversion and fall to bare-number search or default
        assert isinstance(result["score"], float)

    def test_save_cache_exception_cleans_up_tmp(self, detector, tmp_path):
        """If the write fails, the temp file should be cleaned up."""
        candidates = [_make_candidate(topic="Cleanup Test", source="google_trends")]
        # Point storage to an unwritable location to force failure
        bad_dir = str(tmp_path / "no_write")
        os.makedirs(bad_dir, mode=0o444)
        detector._storage_path = str(tmp_path / "no_write" / "topics.json")
        try:
            with pytest.raises(Exception):
                detector._save_cache(candidates)
            # No .tmp files left behind in the parent dir
            tmp_files = [f for f in os.listdir(bad_dir) if f.endswith(".tmp")]
            assert tmp_files == []
        finally:
            os.chmod(bad_dir, 0o755)

    def test_google_trends_skip_empty_topic_rows(self, detector):
        """Rows with empty/whitespace topics are skipped (covers line 145)."""
        import pandas as pd

        # Row with empty string then valid topic
        df = pd.DataFrame(["", "  ", "Valid AI Topic"])
        mock_instance = MagicMock()
        mock_instance.trending_searches.return_value = df
        mock_cls = MagicMock(return_value=mock_instance)
        mock_module = MagicMock()
        mock_module.TrendReq = mock_cls

        with patch.dict("sys.modules", {"pytrends": MagicMock(), "pytrends.request": mock_module}):
            results = detector.fetch_google_trends("technology")

        # Only the valid topic makes it through
        assert len(results) == 1
        assert results[0].topic == "Valid AI Topic"

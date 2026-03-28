"""
Tests for virality_scorer module.

Coverage targets:
- ViralityScore dataclass (creation, serialisation, deserialisation)
- ViralityScorer initialisation (valid/invalid platform)
- score() public method (happy path, edge cases, mocked LLM)
- _build_prompt() content checks
- _parse_response() JSON, regex-fallback, and default paths
- Platform weights validation
- Score bounds (always 0-100)
"""

import json
import re
import pytest
from dataclasses import asdict
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from virality_scorer import (
    ViralityScore,
    ViralityScorer,
    _SUPPORTED_PLATFORMS,
    _PLATFORM_WEIGHTS,
    _BREAKDOWN_CATEGORIES,
    _MAX_TITLE_LEN,
    _MAX_DESCRIPTION_LEN,
    _MAX_TAGS,
    _SCORE_MIN,
    _SCORE_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_JSON_RESPONSE = json.dumps({
    "hook_strength": 80,
    "emotional_appeal": 70,
    "clarity": 90,
    "trending_relevance": 60,
    "platform_fit": 75,
    "suggestions": [
        "Add a number to the title",
        "Use stronger emotional language",
        "Include a call-to-action",
    ],
})

_PARTIAL_JSON_RESPONSE = json.dumps({
    "hook_strength": 80,
    "emotional_appeal": 70,
    # clarity, trending_relevance, platform_fit are missing
    "suggestions": ["Try a stronger hook"],
})

_REGEX_FALLBACK_TEXT = (
    "hook_strength: 65\n"
    "emotional_appeal: 55\n"
    "clarity: 70\n"
    "trending_relevance: 40\n"
    "platform_fit: 60\n"
)

_GARBAGE_TEXT = "I cannot score this. Please provide content."


def _make_scorer(platform: str = "youtube") -> ViralityScorer:
    return ViralityScorer(platform=platform)


# ---------------------------------------------------------------------------
# ViralityScore — creation & fields
# ---------------------------------------------------------------------------

class TestViralityScoreCreation:
    def test_basic_creation(self):
        vs = ViralityScore(
            overall_score=75.0,
            breakdown={"hook_strength": 80.0},
            suggestions=["tip1"],
            platform="youtube",
            scored_at="2026-01-01T00:00:00+00:00",
        )
        assert vs.overall_score == 75.0
        assert vs.platform == "youtube"
        assert vs.suggestions == ["tip1"]

    def test_overall_score_float(self):
        vs = ViralityScore(
            overall_score=42,
            breakdown={},
            suggestions=[],
            platform="tiktok",
            scored_at="2026-01-01T00:00:00+00:00",
        )
        assert vs.overall_score == 42

    def test_empty_suggestions(self):
        vs = ViralityScore(
            overall_score=50.0,
            breakdown={},
            suggestions=[],
            platform="twitter",
            scored_at="2026-01-01T00:00:00+00:00",
        )
        assert vs.suggestions == []

    def test_breakdown_dict(self):
        breakdown = {cat: float(i * 10) for i, cat in enumerate(_BREAKDOWN_CATEGORIES)}
        vs = ViralityScore(
            overall_score=30.0,
            breakdown=breakdown,
            suggestions=[],
            platform="instagram",
            scored_at="2026-01-01T00:00:00+00:00",
        )
        assert vs.breakdown == breakdown


# ---------------------------------------------------------------------------
# ViralityScore — to_dict / from_dict
# ---------------------------------------------------------------------------

class TestViralityScoreSerialization:
    def _sample(self) -> ViralityScore:
        return ViralityScore(
            overall_score=68.5,
            breakdown={cat: 70.0 for cat in _BREAKDOWN_CATEGORIES},
            suggestions=["use shorter titles", "add emoji"],
            platform="youtube",
            scored_at="2026-03-01T12:00:00+00:00",
        )

    def test_to_dict_keys(self):
        d = self._sample().to_dict()
        assert set(d.keys()) == {
            "overall_score", "breakdown", "suggestions", "platform", "scored_at"
        }

    def test_to_dict_values(self):
        d = self._sample().to_dict()
        assert d["overall_score"] == 68.5
        assert d["platform"] == "youtube"
        assert d["suggestions"] == ["use shorter titles", "add emoji"]

    def test_from_dict_roundtrip(self):
        original = self._sample()
        restored = ViralityScore.from_dict(original.to_dict())
        assert restored.overall_score == original.overall_score
        assert restored.platform == original.platform
        assert restored.breakdown == original.breakdown
        assert restored.suggestions == original.suggestions
        assert restored.scored_at == original.scored_at

    def test_from_dict_ignores_unknown_keys(self):
        data = self._sample().to_dict()
        data["unknown_future_field"] = "should be ignored"
        restored = ViralityScore.from_dict(data)
        assert restored.overall_score == 68.5

    def test_from_dict_partial_keys(self):
        """from_dict with only some fields should still work if all required present."""
        data = {
            "overall_score": 55.0,
            "breakdown": {},
            "suggestions": [],
            "platform": "tiktok",
            "scored_at": "2026-01-01T00:00:00+00:00",
        }
        vs = ViralityScore.from_dict(data)
        assert vs.platform == "tiktok"

    def test_to_dict_is_plain_dict(self):
        d = self._sample().to_dict()
        assert isinstance(d, dict)
        assert isinstance(d["breakdown"], dict)
        assert isinstance(d["suggestions"], list)


# ---------------------------------------------------------------------------
# ViralityScorer — initialisation
# ---------------------------------------------------------------------------

class TestViralityScorerInit:
    def test_valid_platform_youtube(self):
        s = ViralityScorer(platform="youtube")
        assert s.platform == "youtube"

    def test_valid_platform_tiktok(self):
        s = ViralityScorer(platform="tiktok")
        assert s.platform == "tiktok"

    def test_valid_platform_twitter(self):
        s = ViralityScorer(platform="twitter")
        assert s.platform == "twitter"

    def test_valid_platform_instagram(self):
        s = ViralityScorer(platform="instagram")
        assert s.platform == "instagram"

    def test_default_platform_is_youtube(self):
        s = ViralityScorer()
        assert s.platform == "youtube"

    def test_invalid_platform_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            ViralityScorer(platform="snapchat")

    def test_invalid_platform_message_lists_supported(self):
        with pytest.raises(ValueError, match="instagram"):
            ViralityScorer(platform="linkedin")

    def test_weights_loaded_for_platform(self):
        for platform in _SUPPORTED_PLATFORMS:
            s = ViralityScorer(platform=platform)
            assert s._weights is _PLATFORM_WEIGHTS[platform]


# ---------------------------------------------------------------------------
# ViralityScorer — _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def setup_method(self):
        self.scorer = _make_scorer("youtube")

    def test_platform_name_in_prompt(self):
        prompt = self.scorer._build_prompt("My Title", "", [], [])
        assert "youtube" in prompt.lower()

    def test_all_categories_in_prompt(self):
        prompt = self.scorer._build_prompt("My Title", "", [], [])
        for cat in _BREAKDOWN_CATEGORIES:
            assert cat in prompt

    def test_weight_percentages_in_prompt(self):
        prompt = self.scorer._build_prompt("My Title", "", [], [])
        # youtube hook_strength = 30%
        assert "30%" in prompt

    def test_title_in_prompt(self):
        prompt = self.scorer._build_prompt("Amazing Title", "", [], [])
        assert "Amazing Title" in prompt

    def test_description_preview_in_prompt(self):
        desc = "A" * 600
        prompt = self.scorer._build_prompt("Title", desc, [], [])
        # Description is previewed at 500 chars
        assert "A" * 500 in prompt
        assert "A" * 501 not in prompt

    def test_tags_in_prompt(self):
        prompt = self.scorer._build_prompt("T", "", ["ai", "money"], [])
        assert "ai" in prompt
        assert "money" in prompt

    def test_hashtags_in_prompt(self):
        prompt = self.scorer._build_prompt("T", "", [], ["#viral", "#trending"])
        assert "#viral" in prompt

    def test_empty_tags_shows_none(self):
        prompt = self.scorer._build_prompt("T", "", [], [])
        assert "none" in prompt.lower()

    def test_json_format_instruction_in_prompt(self):
        prompt = self.scorer._build_prompt("T", "", [], [])
        assert "JSON" in prompt or "json" in prompt.lower()

    def test_tiktok_prompt_mentions_tiktok(self):
        scorer = _make_scorer("tiktok")
        prompt = scorer._build_prompt("T", "", [], [])
        assert "tiktok" in prompt.lower()

    def test_tiktok_hook_weight_35_percent(self):
        scorer = _make_scorer("tiktok")
        prompt = scorer._build_prompt("T", "", [], [])
        assert "35%" in prompt


# ---------------------------------------------------------------------------
# ViralityScorer — _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def setup_method(self):
        self.scorer = _make_scorer("youtube")

    def test_valid_json_all_categories(self):
        result = self.scorer._parse_response(_FULL_JSON_RESPONSE)
        assert result.breakdown["hook_strength"] == 80.0
        assert result.breakdown["emotional_appeal"] == 70.0
        assert result.breakdown["clarity"] == 90.0
        assert result.breakdown["trending_relevance"] == 60.0
        assert result.breakdown["platform_fit"] == 75.0

    def test_valid_json_suggestions_list(self):
        result = self.scorer._parse_response(_FULL_JSON_RESPONSE)
        assert len(result.suggestions) == 3
        assert "Add a number to the title" in result.suggestions

    def test_valid_json_computes_overall(self):
        result = self.scorer._parse_response(_FULL_JSON_RESPONSE)
        # Manual calculation for youtube weights
        weights = _PLATFORM_WEIGHTS["youtube"]
        expected = round(
            80 * weights["hook_strength"]
            + 70 * weights["emotional_appeal"]
            + 90 * weights["clarity"]
            + 60 * weights["trending_relevance"]
            + 75 * weights["platform_fit"],
            1,
        )
        assert result.overall_score == expected

    def test_partial_json_missing_categories_default_to_50(self):
        result = self.scorer._parse_response(_PARTIAL_JSON_RESPONSE)
        assert result.breakdown["hook_strength"] == 80.0
        assert result.breakdown["emotional_appeal"] == 70.0
        assert result.breakdown["clarity"] == 50.0
        assert result.breakdown["trending_relevance"] == 50.0
        assert result.breakdown["platform_fit"] == 50.0

    def test_malformed_json_uses_regex_fallback(self):
        result = self.scorer._parse_response(_REGEX_FALLBACK_TEXT)
        assert result.breakdown["hook_strength"] == 65.0
        assert result.breakdown["emotional_appeal"] == 55.0
        assert result.breakdown["clarity"] == 70.0
        assert result.breakdown["trending_relevance"] == 40.0
        assert result.breakdown["platform_fit"] == 60.0

    def test_completely_invalid_text_defaults_all_to_50(self):
        result = self.scorer._parse_response(_GARBAGE_TEXT)
        for cat in _BREAKDOWN_CATEGORIES:
            assert result.breakdown[cat] == 50.0

    def test_suggestions_truncated_to_5(self):
        data = {cat: 70 for cat in _BREAKDOWN_CATEGORIES}
        data["suggestions"] = [f"tip{i}" for i in range(10)]
        result = self.scorer._parse_response(json.dumps(data))
        assert len(result.suggestions) <= 5

    def test_suggestions_each_truncated_to_200_chars(self):
        data = {cat: 70 for cat in _BREAKDOWN_CATEGORIES}
        data["suggestions"] = ["X" * 300]
        result = self.scorer._parse_response(json.dumps(data))
        assert len(result.suggestions[0]) == 200

    def test_suggestions_as_string_becomes_list(self):
        data = {cat: 70 for cat in _BREAKDOWN_CATEGORIES}
        data["suggestions"] = "Just one suggestion"
        result = self.scorer._parse_response(json.dumps(data))
        assert isinstance(result.suggestions, list)
        assert result.suggestions[0] == "Just one suggestion"

    def test_missing_suggestions_key_gives_empty_list(self):
        data = {cat: 70 for cat in _BREAKDOWN_CATEGORIES}
        result = self.scorer._parse_response(json.dumps(data))
        assert result.suggestions == []

    def test_score_clamped_above_100(self):
        data = {cat: 150 for cat in _BREAKDOWN_CATEGORIES}
        data["suggestions"] = []
        result = self.scorer._parse_response(json.dumps(data))
        for cat in _BREAKDOWN_CATEGORIES:
            assert result.breakdown[cat] == 100.0
        assert result.overall_score <= 100.0

    def test_score_clamped_below_0(self):
        data = {cat: -20 for cat in _BREAKDOWN_CATEGORIES}
        data["suggestions"] = []
        result = self.scorer._parse_response(json.dumps(data))
        for cat in _BREAKDOWN_CATEGORIES:
            assert result.breakdown[cat] == 0.0
        assert result.overall_score >= 0.0

    def test_json_embedded_in_prose(self):
        prose = (
            "Sure! Here is my evaluation:\n"
            + _FULL_JSON_RESPONSE
            + "\nI hope this helps."
        )
        result = self.scorer._parse_response(prose)
        assert result.breakdown["hook_strength"] == 80.0

    def test_platform_set_on_result(self):
        result = self.scorer._parse_response(_FULL_JSON_RESPONSE)
        assert result.platform == "youtube"

    def test_scored_at_is_iso8601(self):
        result = self.scorer._parse_response(_FULL_JSON_RESPONSE)
        # Should not raise
        dt = datetime.fromisoformat(result.scored_at)
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# ViralityScorer — score() (integration with mocked LLM)
# ---------------------------------------------------------------------------

class TestScoreMethod:
    def test_score_returns_virality_score(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE):
            scorer = _make_scorer("youtube")
            result = scorer.score("Amazing AI Video")
        assert isinstance(result, ViralityScore)

    def test_score_empty_title_raises_value_error(self):
        scorer = _make_scorer("youtube")
        with pytest.raises(ValueError, match="Title is required"):
            scorer.score("")

    def test_score_whitespace_only_title_raises_value_error(self):
        scorer = _make_scorer("youtube")
        with pytest.raises(ValueError, match="Title is required"):
            scorer.score("   ")

    def test_score_truncates_long_title(self):
        long_title = "A" * 1000
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE) as mock_gen:
            scorer = _make_scorer("youtube")
            scorer.score(long_title)
            prompt_used = mock_gen.call_args[0][0]
            # Title in prompt should be truncated
            assert "A" * _MAX_TITLE_LEN in prompt_used
            assert "A" * (_MAX_TITLE_LEN + 1) not in prompt_used

    def test_score_truncates_long_description(self):
        long_desc = "D" * 10000
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE) as mock_gen:
            scorer = _make_scorer("youtube")
            scorer.score("Title", description=long_desc)
            prompt_used = mock_gen.call_args[0][0]
            # Description in prompt is previewed at 500 chars
            assert "D" * 500 in prompt_used

    def test_score_truncates_too_many_tags(self):
        many_tags = [f"tag{i}" for i in range(100)]
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE) as mock_gen:
            scorer = _make_scorer("youtube")
            scorer.score("Title", tags=many_tags)
            prompt_used = mock_gen.call_args[0][0]
            # Only first _MAX_TAGS tags should be present
            assert "tag49" in prompt_used   # 50th tag (0-indexed)
            assert "tag50" not in prompt_used  # 51st would be excluded

    def test_score_no_description(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE):
            scorer = _make_scorer("tiktok")
            result = scorer.score("Title Only")
        assert isinstance(result, ViralityScore)

    def test_score_no_tags_no_hashtags(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE):
            scorer = _make_scorer("twitter")
            result = scorer.score("Short tweet text")
        assert isinstance(result, ViralityScore)

    def test_score_with_all_inputs(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE):
            scorer = _make_scorer("instagram")
            result = scorer.score(
                title="Top 10 AI Hacks",
                description="Full script here...",
                tags=["ai", "hacks", "money"],
                hashtags=["#AI", "#money"],
            )
        assert result.platform == "instagram"

    def test_score_unicode_title(self):
        unicode_title = "AI工具让你赚钱💰🚀"
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE):
            scorer = _make_scorer("youtube")
            result = scorer.score(unicode_title)
        assert isinstance(result, ViralityScore)

    def test_score_overall_in_bounds(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE):
            scorer = _make_scorer("youtube")
            result = scorer.score("Title")
        assert _SCORE_MIN <= result.overall_score <= _SCORE_MAX

    def test_score_breakdown_all_in_bounds(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE):
            scorer = _make_scorer("youtube")
            result = scorer.score("Title")
        for cat in _BREAKDOWN_CATEGORIES:
            assert _SCORE_MIN <= result.breakdown[cat] <= _SCORE_MAX

    def test_score_calls_generate_text_once(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE) as mock_gen:
            scorer = _make_scorer("youtube")
            scorer.score("Title")
        mock_gen.assert_called_once()

    def test_score_passes_prompt_to_generate_text(self):
        with patch("virality_scorer.generate_text", return_value=_FULL_JSON_RESPONSE) as mock_gen:
            scorer = _make_scorer("youtube")
            scorer.score("My Test Title")
            prompt = mock_gen.call_args[0][0]
        assert "My Test Title" in prompt

    def test_score_llm_garbage_response_still_returns_virality_score(self):
        with patch("virality_scorer.generate_text", return_value=_GARBAGE_TEXT):
            scorer = _make_scorer("youtube")
            result = scorer.score("Title")
        assert isinstance(result, ViralityScore)
        assert _SCORE_MIN <= result.overall_score <= _SCORE_MAX


# ---------------------------------------------------------------------------
# Platform weights validation
# ---------------------------------------------------------------------------

class TestPlatformWeights:
    def test_all_supported_platforms_have_weights(self):
        for platform in _SUPPORTED_PLATFORMS:
            assert platform in _PLATFORM_WEIGHTS

    def test_all_platforms_have_all_categories(self):
        for platform, weights in _PLATFORM_WEIGHTS.items():
            for cat in _BREAKDOWN_CATEGORIES:
                assert cat in weights, (
                    f"Platform '{platform}' missing weight for '{cat}'"
                )

    def test_weights_sum_to_1_for_each_platform(self):
        for platform, weights in _PLATFORM_WEIGHTS.items():
            total = sum(weights[cat] for cat in _BREAKDOWN_CATEGORIES)
            assert abs(total - 1.0) < 1e-9, (
                f"Weights for '{platform}' sum to {total}, expected 1.0"
            )

    def test_all_weights_positive(self):
        for platform, weights in _PLATFORM_WEIGHTS.items():
            for cat, w in weights.items():
                assert w > 0, f"Weight for {platform}/{cat} is not positive: {w}"

    def test_tiktok_hook_strength_highest_weight(self):
        """TikTok hook_strength should be the highest single weight."""
        tiktok_w = _PLATFORM_WEIGHTS["tiktok"]
        assert tiktok_w["hook_strength"] == max(tiktok_w.values())

    def test_twitter_clarity_highest_weight(self):
        """Twitter clarity should be the highest single weight."""
        twitter_w = _PLATFORM_WEIGHTS["twitter"]
        assert twitter_w["clarity"] == max(twitter_w.values())


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_supported_platforms_is_frozenset(self):
        assert isinstance(_SUPPORTED_PLATFORMS, frozenset)

    def test_supported_platforms_contains_expected(self):
        assert _SUPPORTED_PLATFORMS == {"youtube", "tiktok", "twitter", "instagram"}

    def test_breakdown_categories_tuple(self):
        assert isinstance(_BREAKDOWN_CATEGORIES, tuple)
        assert len(_BREAKDOWN_CATEGORIES) == 5

    def test_score_bounds(self):
        assert _SCORE_MIN == 0
        assert _SCORE_MAX == 100

    def test_max_title_len(self):
        assert _MAX_TITLE_LEN == 500

    def test_max_description_len(self):
        assert _MAX_DESCRIPTION_LEN == 5000

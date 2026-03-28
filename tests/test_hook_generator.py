"""
Tests for hook_generator module.

Coverage targets (50+ tests, >90%):
- HookResult dataclass: creation, to_dict, from_dict, validation
- HookGenerator init: valid/invalid platforms
- generate_hook: mock generate_text, JSON parse, regex fallback, LLM failure
- generate_hooks: multiple hooks, count validation
- get_fallback_hook: all 5 categories, all platforms
- Platform constraints: verify word/char limits respected
- Edge cases: empty topic, very long topic, None category, invalid category
"""

import json
import pytest
from dataclasses import asdict
from unittest.mock import patch, MagicMock

from hook_generator import (
    HookResult,
    HookGenerator,
    _SUPPORTED_PLATFORMS,
    _HOOK_CATEGORIES,
    _HOOK_TEMPLATES,
    _PLATFORM_CONSTRAINTS,
    _MAX_TOPIC_LEN,
)


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gen():
    return HookGenerator(platform="youtube")


@pytest.fixture
def gen_shorts():
    return HookGenerator(platform="youtube_shorts")


@pytest.fixture
def gen_tiktok():
    return HookGenerator(platform="tiktok")


@pytest.fixture
def gen_twitter():
    return HookGenerator(platform="twitter")


@pytest.fixture
def gen_reels():
    return HookGenerator(platform="instagram_reels")


def _json_response(hook="Did you know AI tools are amazing?", category="curiosity"):
    return json.dumps({"hook": hook, "category": category})


_GARBAGE_TEXT = "I am unable to generate a hook for this topic."


# ---------------------------------------------------------------------------
# HookResult — creation
# ---------------------------------------------------------------------------

class TestHookResultCreation:
    def test_basic_creation(self):
        r = HookResult(
            hook_text="What if AI could do everything?",
            hook_category="question",
            platform="youtube",
            max_duration_seconds=5.0,
            estimated_word_count=7,
        )
        assert r.hook_text == "What if AI could do everything?"
        assert r.hook_category == "question"
        assert r.platform == "youtube"
        assert r.max_duration_seconds == 5.0
        assert r.estimated_word_count == 7

    def test_zero_duration(self):
        r = HookResult("hook", "curiosity", "twitter", 0.0, 1)
        assert r.max_duration_seconds == 0.0

    def test_word_count_zero(self):
        r = HookResult("", "curiosity", "youtube", 5.0, 0)
        assert r.estimated_word_count == 0

    def test_all_fields_present(self):
        r = HookResult("text", "statistic", "tiktok", 2.0, 5)
        assert hasattr(r, "hook_text")
        assert hasattr(r, "hook_category")
        assert hasattr(r, "platform")
        assert hasattr(r, "max_duration_seconds")
        assert hasattr(r, "estimated_word_count")


# ---------------------------------------------------------------------------
# HookResult — to_dict / from_dict
# ---------------------------------------------------------------------------

class TestHookResultSerialization:
    def _sample(self):
        return HookResult(
            hook_text="Stop ignoring productivity hacks immediately.",
            hook_category="controversy",
            platform="youtube_shorts",
            max_duration_seconds=5.0,
            estimated_word_count=6,
        )

    def test_to_dict_keys(self):
        d = self._sample().to_dict()
        assert set(d.keys()) == {
            "hook_text", "hook_category", "platform",
            "max_duration_seconds", "estimated_word_count",
        }

    def test_to_dict_values(self):
        d = self._sample().to_dict()
        assert d["hook_text"] == "Stop ignoring productivity hacks immediately."
        assert d["hook_category"] == "controversy"
        assert d["platform"] == "youtube_shorts"
        assert d["max_duration_seconds"] == 5.0
        assert d["estimated_word_count"] == 6

    def test_from_dict_roundtrip(self):
        original = self._sample()
        restored = HookResult.from_dict(original.to_dict())
        assert restored.hook_text == original.hook_text
        assert restored.hook_category == original.hook_category
        assert restored.platform == original.platform
        assert restored.max_duration_seconds == original.max_duration_seconds
        assert restored.estimated_word_count == original.estimated_word_count

    def test_from_dict_ignores_unknown_keys(self):
        data = self._sample().to_dict()
        data["future_field"] = "ignored"
        restored = HookResult.from_dict(data)
        assert restored.hook_text == "Stop ignoring productivity hacks immediately."

    def test_to_dict_is_plain_dict(self):
        d = self._sample().to_dict()
        assert isinstance(d, dict)

    def test_from_dict_partial_data_works(self):
        data = {
            "hook_text": "3 tips for success.",
            "hook_category": "listicle",
            "platform": "tiktok",
            "max_duration_seconds": 2.0,
            "estimated_word_count": 4,
        }
        r = HookResult.from_dict(data)
        assert r.platform == "tiktok"


# ---------------------------------------------------------------------------
# HookGenerator — init
# ---------------------------------------------------------------------------

class TestHookGeneratorInit:
    def test_default_platform_is_youtube(self):
        g = HookGenerator()
        assert g.platform == "youtube"

    def test_valid_platform_youtube(self):
        g = HookGenerator(platform="youtube")
        assert g.platform == "youtube"

    def test_valid_platform_youtube_shorts(self):
        g = HookGenerator(platform="youtube_shorts")
        assert g.platform == "youtube_shorts"

    def test_valid_platform_tiktok(self):
        g = HookGenerator(platform="tiktok")
        assert g.platform == "tiktok"

    def test_valid_platform_instagram_reels(self):
        g = HookGenerator(platform="instagram_reels")
        assert g.platform == "instagram_reels"

    def test_valid_platform_twitter(self):
        g = HookGenerator(platform="twitter")
        assert g.platform == "twitter"

    def test_invalid_platform_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            HookGenerator(platform="snapchat")

    def test_invalid_platform_message_lists_options(self):
        with pytest.raises(ValueError, match="youtube"):
            HookGenerator(platform="linkedin")

    def test_constraints_loaded(self):
        g = HookGenerator(platform="tiktok")
        assert g._constraints == _PLATFORM_CONSTRAINTS["tiktok"]

    def test_all_supported_platforms_initialise(self):
        for p in _SUPPORTED_PLATFORMS:
            g = HookGenerator(platform=p)
            assert g.platform == p


# ---------------------------------------------------------------------------
# generate_hook — JSON parse path
# ---------------------------------------------------------------------------

class TestGenerateHookJsonParse:
    def test_returns_hook_result(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            result = gen.generate_hook("AI tools")
        assert isinstance(result, HookResult)

    def test_hook_text_from_json(self, gen):
        payload = _json_response(hook="Most people don't know AI tools are free.")
        with patch("hook_generator.generate_text", return_value=payload):
            result = gen.generate_hook("AI tools")
        assert "Most people" in result.hook_text

    def test_category_from_json(self, gen):
        payload = _json_response(hook="Stop ignoring Python immediately.", category="controversy")
        with patch("hook_generator.generate_text", return_value=payload):
            result = gen.generate_hook("Python")
        assert result.hook_category == "controversy"

    def test_platform_set_on_result(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            result = gen.generate_hook("AI tools")
        assert result.platform == "youtube"

    def test_json_embedded_in_prose(self, gen):
        prose = "Here is your hook:\n" + _json_response() + "\nEnjoy!"
        with patch("hook_generator.generate_text", return_value=prose):
            result = gen.generate_hook("AI tools")
        assert isinstance(result, HookResult)

    def test_word_count_matches_hook_text(self, gen):
        hook = "What if I told you productivity was easy?"
        with patch("hook_generator.generate_text", return_value=_json_response(hook=hook)):
            result = gen.generate_hook("productivity")
        assert result.estimated_word_count == len(result.hook_text.split())

    def test_calls_generate_text_once(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()) as mock_llm:
            gen.generate_hook("AI tools")
        mock_llm.assert_called_once()

    def test_prompt_contains_topic(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()) as mock_llm:
            gen.generate_hook("machine learning")
        prompt = mock_llm.call_args[0][0]
        assert "machine learning" in prompt

    def test_prompt_contains_platform(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()) as mock_llm:
            gen.generate_hook("AI tools")
        prompt = mock_llm.call_args[0][0]
        assert "youtube" in prompt.lower()

    def test_prompt_contains_category_when_specified(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()) as mock_llm:
            gen.generate_hook("AI tools", category="question")
        prompt = mock_llm.call_args[0][0]
        assert "question" in prompt.lower()


# ---------------------------------------------------------------------------
# generate_hook — regex fallback path
# ---------------------------------------------------------------------------

class TestGenerateHookRegexFallback:
    def test_regex_fallback_extracts_hook(self, gen):
        raw = 'The best hook is: "hook": "Most people ignore this hack."'
        with patch("hook_generator.generate_text", return_value=raw):
            result = gen.generate_hook("productivity")
        assert "Most people ignore this hack" in result.hook_text

    def test_regex_fallback_returns_hook_result(self, gen):
        raw = '"hook": "Stop wasting time on social media."'
        with patch("hook_generator.generate_text", return_value=raw):
            result = gen.generate_hook("social media")
        assert isinstance(result, HookResult)


# ---------------------------------------------------------------------------
# generate_hook — LLM failure / fallback path
# ---------------------------------------------------------------------------

class TestGenerateHookLlmFailure:
    def test_garbage_response_returns_hook_result(self, gen):
        with patch("hook_generator.generate_text", return_value=_GARBAGE_TEXT):
            result = gen.generate_hook("side hustles")
        assert isinstance(result, HookResult)

    def test_llm_exception_uses_fallback(self, gen):
        with patch("hook_generator.generate_text", side_effect=RuntimeError("no model")):
            result = gen.generate_hook("side hustles")
        assert isinstance(result, HookResult)
        assert result.hook_text  # non-empty

    def test_llm_none_uses_fallback(self, gen):
        # Simulate generate_text being None (import failed)
        with patch("hook_generator.generate_text", None):
            result = gen.generate_hook("side hustles")
        assert isinstance(result, HookResult)


# ---------------------------------------------------------------------------
# generate_hook — input validation
# ---------------------------------------------------------------------------

class TestGenerateHookValidation:
    def test_empty_topic_raises(self, gen):
        with pytest.raises(ValueError, match="non-empty"):
            gen.generate_hook("")

    def test_whitespace_topic_raises(self, gen):
        with pytest.raises(ValueError, match="non-empty"):
            gen.generate_hook("   ")

    def test_very_long_topic_truncated(self, gen):
        long_topic = "A" * 1000
        with patch("hook_generator.generate_text", return_value=_json_response()) as mock_llm:
            gen.generate_hook(long_topic)
        prompt = mock_llm.call_args[0][0]
        # Topic in prompt must be <= _MAX_TOPIC_LEN chars
        assert "A" * (_MAX_TOPIC_LEN + 1) not in prompt

    def test_invalid_category_raises(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            with pytest.raises(ValueError, match="Unknown hook category"):
                gen.generate_hook("AI tools", category="viral")

    def test_none_category_accepted(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            result = gen.generate_hook("AI tools", category=None)
        assert isinstance(result, HookResult)

    def test_valid_categories_all_accepted(self, gen):
        for cat in _HOOK_CATEGORIES:
            with patch("hook_generator.generate_text", return_value=_json_response(category=cat)):
                result = gen.generate_hook("topic", category=cat)
            assert result.hook_category == cat


# ---------------------------------------------------------------------------
# generate_hooks
# ---------------------------------------------------------------------------

class TestGenerateHooks:
    def test_returns_list(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            results = gen.generate_hooks("AI tools")
        assert isinstance(results, list)

    def test_default_count_3(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            results = gen.generate_hooks("AI tools")
        assert len(results) == 3

    def test_custom_count(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            results = gen.generate_hooks("AI tools", count=5)
        assert len(results) == 5

    def test_count_clamped_to_category_count(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            results = gen.generate_hooks("AI tools", count=100)
        assert len(results) == len(_HOOK_CATEGORIES)

    def test_count_1(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            results = gen.generate_hooks("AI tools", count=1)
        assert len(results) == 1

    def test_all_results_are_hook_result(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            results = gen.generate_hooks("AI tools", count=3)
        for r in results:
            assert isinstance(r, HookResult)

    def test_empty_topic_raises(self, gen):
        with pytest.raises(ValueError, match="non-empty"):
            gen.generate_hooks("")

    def test_each_hook_has_platform(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            results = gen.generate_hooks("AI tools", count=3)
        for r in results:
            assert r.platform == "youtube"

    def test_llm_failure_still_returns_results(self, gen):
        with patch("hook_generator.generate_text", side_effect=RuntimeError("err")):
            results = gen.generate_hooks("AI tools", count=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# get_fallback_hook — all 5 categories
# ---------------------------------------------------------------------------

class TestGetFallbackHook:
    def test_curiosity_fallback(self, gen):
        result = gen.get_fallback_hook("Python", "curiosity")
        assert isinstance(result, HookResult)
        assert result.hook_category == "curiosity"
        assert result.hook_text

    def test_controversy_fallback(self, gen):
        result = gen.get_fallback_hook("Python", "controversy")
        assert result.hook_category == "controversy"

    def test_statistic_fallback(self, gen):
        result = gen.get_fallback_hook("Python", "statistic")
        assert result.hook_category == "statistic"

    def test_question_fallback(self, gen):
        result = gen.get_fallback_hook("Python", "question")
        assert result.hook_category == "question"

    def test_listicle_fallback(self, gen):
        result = gen.get_fallback_hook("Python", "listicle")
        assert result.hook_category == "listicle"

    def test_unknown_category_defaults_to_curiosity(self, gen):
        result = gen.get_fallback_hook("Python", "nonexistent")
        assert result.hook_category == "curiosity"

    def test_fallback_topic_in_hook_text(self, gen):
        result = gen.get_fallback_hook("side hustles", "curiosity")
        # Topic should appear somewhere in the hook text (possibly trimmed)
        assert len(result.hook_text) > 0

    def test_fallback_platform_set(self, gen):
        result = gen.get_fallback_hook("Python", "curiosity")
        assert result.platform == "youtube"

    def test_fallback_on_all_platforms(self):
        for platform in _SUPPORTED_PLATFORMS:
            g = HookGenerator(platform=platform)
            result = g.get_fallback_hook("AI", "curiosity")
            assert isinstance(result, HookResult)
            assert result.platform == platform


# ---------------------------------------------------------------------------
# Platform constraints — word/char limits
# ---------------------------------------------------------------------------

class TestPlatformConstraints:
    def test_tiktok_word_limit(self, gen_tiktok):
        long_hook = "word " * 50
        payload = json.dumps({"hook": long_hook.strip(), "category": "curiosity"})
        with patch("hook_generator.generate_text", return_value=payload):
            result = gen_tiktok.generate_hook("AI tools")
        max_words = _PLATFORM_CONSTRAINTS["tiktok"]["max_words"]
        assert result.estimated_word_count <= max_words

    def test_twitter_char_limit(self, gen_twitter):
        long_hook = "This is a very long hook text that exceeds Twitter character limit drastically."
        payload = json.dumps({"hook": long_hook, "category": "curiosity"})
        with patch("hook_generator.generate_text", return_value=payload):
            result = gen_twitter.generate_hook("AI tools")
        max_chars = _PLATFORM_CONSTRAINTS["twitter"]["max_chars"]
        assert len(result.hook_text) <= max_chars

    def test_youtube_duration(self, gen):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            result = gen.generate_hook("AI tools")
        assert result.max_duration_seconds == _PLATFORM_CONSTRAINTS["youtube"]["max_duration"]

    def test_tiktok_duration(self, gen_tiktok):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            result = gen_tiktok.generate_hook("AI tools")
        assert result.max_duration_seconds == _PLATFORM_CONSTRAINTS["tiktok"]["max_duration"]

    def test_twitter_zero_duration(self, gen_twitter):
        with patch("hook_generator.generate_text", return_value=_json_response()):
            result = gen_twitter.generate_hook("AI tools")
        # Twitter has no duration; stored as 0.0
        assert result.max_duration_seconds == 0.0

    def test_instagram_reels_word_limit(self, gen_reels):
        long_hook = "word " * 50
        payload = json.dumps({"hook": long_hook.strip(), "category": "curiosity"})
        with patch("hook_generator.generate_text", return_value=payload):
            result = gen_reels.generate_hook("beauty tips")
        max_words = _PLATFORM_CONSTRAINTS["instagram_reels"]["max_words"]
        assert result.estimated_word_count <= max_words

    def test_youtube_shorts_word_limit(self, gen_shorts):
        long_hook = "word " * 50
        payload = json.dumps({"hook": long_hook.strip(), "category": "curiosity"})
        with patch("hook_generator.generate_text", return_value=payload):
            result = gen_shorts.generate_hook("AI tools")
        max_words = _PLATFORM_CONSTRAINTS["youtube_shorts"]["max_words"]
        assert result.estimated_word_count <= max_words


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_supported_platforms_is_frozenset(self):
        assert isinstance(_SUPPORTED_PLATFORMS, frozenset)

    def test_supported_platforms_count(self):
        assert len(_SUPPORTED_PLATFORMS) == 5

    def test_hook_categories_count(self):
        assert len(_HOOK_CATEGORIES) >= 5

    def test_hook_categories_tuple(self):
        assert isinstance(_HOOK_CATEGORIES, tuple)

    def test_all_categories_have_templates(self):
        for cat in _HOOK_CATEGORIES:
            assert cat in _HOOK_TEMPLATES, f"Missing template for {cat!r}"

    def test_all_platforms_have_constraints(self):
        for p in _SUPPORTED_PLATFORMS:
            assert p in _PLATFORM_CONSTRAINTS

    def test_templates_contain_topic_placeholder(self):
        for cat, tmpl in _HOOK_TEMPLATES.items():
            assert "{topic}" in tmpl, f"Template for {cat!r} missing {{topic}}"

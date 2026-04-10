"""Tests for seo_optimizer module."""

import json
import pytest
from unittest.mock import patch, MagicMock

import seo_optimizer
from seo_optimizer import (
    SEOResult,
    optimize_metadata,
    optimize_existing_metadata,
    get_seo_enabled,
    get_seo_target_platforms,
    get_seo_language,
    get_seo_include_tags,
    get_seo_include_hooks,
    get_seo_hashtag_count,
    _validate_input,
    _parse_json_array,
    _clean_title,
    _clean_description,
    _clean_hashtags,
    _clean_tags,
    _estimate_seo_score,
    _build_title_prompt,
    _build_description_prompt,
    _build_tags_prompt,
    _build_hashtags_prompt,
    _build_hooks_prompt,
    _PLATFORM_LIMITS,
    _SUPPORTED_PLATFORMS,
    _MAX_SUBJECT_LEN,
    _MAX_SCRIPT_LEN,
    _MAX_NICHE_LEN,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_generate(prompt: str) -> str:
    """Mock LLM generator that returns predictable SEO content."""
    prompt_lower = prompt.lower()
    if "generate one highly optimized video title" in prompt_lower:
        return "How I Made $10K in 30 Days Using AI — Nobody Talks About This"
    elif "generate an optimized video description" in prompt_lower:
        return (
            "Discover the exact strategy I used to earn $10K in just 30 days "
            "using AI tools. In this video, I break down every step of the "
            "process so you can replicate it. Like, subscribe, and comment "
            "your questions below!"
        )
    elif "generate 15-20 relevant tags" in prompt_lower:
        return json.dumps([
            "make money online", "AI money", "passive income", "AI tools",
            "side hustle", "online business", "earn money fast", "AI automation",
            "how to make money", "income streams", "AI business", "money making",
            "financial freedom", "work from home", "digital income"
        ])
    elif "generate exactly" in prompt_lower and "hashtag" in prompt_lower:
        return json.dumps([
            "#Shorts", "#MakeMoney", "#AI", "#PassiveIncome",
            "#SideHustle", "#AITools", "#FinancialFreedom", "#MoneyTips"
        ])
    elif "scroll-stopping opening hooks" in prompt_lower:
        return json.dumps([
            "Most people will never know this $10K secret...",
            "Stop scrolling if you want to make money while you sleep.",
            "What if I told you AI could pay your rent?"
        ])
    return "default response"


# ---------------------------------------------------------------------------
# SEOResult tests
# ---------------------------------------------------------------------------

class TestSEOResult:
    def test_default_values(self):
        result = SEOResult()
        assert result.title == ""
        assert result.description == ""
        assert result.tags == []
        assert result.hashtags == []
        assert result.hooks == []
        assert result.platform == "youtube"
        assert result.score == 0

    def test_to_dict(self):
        result = SEOResult(
            title="Test Title",
            description="Test desc",
            tags=["tag1"],
            hashtags=["#test"],
            hooks=["Hook 1"],
            platform="tiktok",
            score=75,
        )
        d = result.to_dict()
        assert d["title"] == "Test Title"
        assert d["platform"] == "tiktok"
        assert d["score"] == 75
        assert d["tags"] == ["tag1"]
        assert d["hashtags"] == ["#test"]
        assert d["hooks"] == ["Hook 1"]

    def test_from_dict(self):
        data = {
            "title": "Title",
            "description": "Desc",
            "tags": ["a", "b"],
            "hashtags": ["#x"],
            "hooks": ["h1"],
            "platform": "twitter",
            "score": 50,
        }
        result = SEOResult.from_dict(data)
        assert result.title == "Title"
        assert result.platform == "twitter"
        assert result.score == 50

    def test_from_dict_invalid_input(self):
        with pytest.raises(ValueError, match="requires a dict"):
            SEOResult.from_dict("not a dict")

    def test_from_dict_missing_fields(self):
        result = SEOResult.from_dict({})
        assert result.title == ""
        assert result.tags == []
        assert result.platform == "youtube"

    def test_roundtrip(self):
        original = SEOResult(
            title="Roundtrip Test",
            description="Desc",
            tags=["a"],
            hashtags=["#b"],
            hooks=["c"],
            platform="tiktok",
            score=80,
        )
        restored = SEOResult.from_dict(original.to_dict())
        assert original.title == restored.title
        assert original.platform == restored.platform
        assert original.score == restored.score


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_input(self):
        _validate_input("Test subject", "Test script", "tech", "youtube")

    def test_empty_subject(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_input("", "script", "niche", "youtube")

    def test_whitespace_subject(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_input("   ", "script", "niche", "youtube")

    def test_null_bytes_subject(self):
        with pytest.raises(ValueError, match="Null bytes"):
            _validate_input("test\x00", "script", "niche", "youtube")

    def test_null_bytes_script(self):
        with pytest.raises(ValueError, match="Null bytes"):
            _validate_input("test", "script\x00", "niche", "youtube")

    def test_null_bytes_niche(self):
        with pytest.raises(ValueError, match="Null bytes"):
            _validate_input("test", "script", "niche\x00", "youtube")

    def test_subject_too_long(self):
        with pytest.raises(ValueError, match="Subject too long"):
            _validate_input("x" * 501, "script", "niche", "youtube")

    def test_script_too_long(self):
        with pytest.raises(ValueError, match="Script too long"):
            _validate_input("test", "x" * 10001, "niche", "youtube")

    def test_niche_too_long(self):
        with pytest.raises(ValueError, match="Niche too long"):
            _validate_input("test", "script", "x" * 201, "youtube")

    def test_invalid_platform(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            _validate_input("test", "script", "niche", "instagram")

    def test_all_supported_platforms(self):
        for platform in _SUPPORTED_PLATFORMS:
            _validate_input("test", "script", "niche", platform)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParsers:
    def test_parse_json_array_basic(self):
        result = _parse_json_array('["a", "b", "c"]')
        assert result == ["a", "b", "c"]

    def test_parse_json_array_with_code_fences(self):
        result = _parse_json_array('```json\n["a", "b"]\n```')
        assert result == ["a", "b"]

    def test_parse_json_array_with_surrounding_text(self):
        result = _parse_json_array('Here are the tags: ["tag1", "tag2"] hope this helps!')
        assert result == ["tag1", "tag2"]

    def test_parse_json_array_empty(self):
        result = _parse_json_array("no array here")
        assert result == []

    def test_parse_json_array_filters_empty(self):
        result = _parse_json_array('["a", "", "b"]')
        assert result == ["a", "b"]

    def test_parse_json_array_invalid_json(self):
        result = _parse_json_array("{not valid json")
        assert result == []


class TestCleanTitle:
    def test_basic_cleaning(self):
        assert _clean_title('"My Title"', 100) == "My Title"

    def test_strips_hashtags(self):
        result = _clean_title("My Title #Shorts #Viral", 100)
        assert "#" not in result
        assert "My Title" in result

    def test_truncates_long_title(self):
        long_title = "A" * 150
        result = _clean_title(long_title, 100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_preserves_short_title(self):
        title = "Short Title"
        assert _clean_title(title, 100) == title


class TestCleanDescription:
    def test_basic(self):
        result = _clean_description("  Hello world  ", 5000)
        assert result == "Hello world"

    def test_truncates(self):
        long_desc = "word " * 1000
        result = _clean_description(long_desc, 200)
        assert len(result) <= 200


class TestCleanHashtags:
    def test_adds_hash_prefix(self):
        result = _clean_hashtags(["Shorts", "Viral"], 10)
        assert all(h.startswith("#") for h in result)

    def test_removes_duplicates(self):
        result = _clean_hashtags(["#Shorts", "#shorts", "#SHORTS"], 10)
        assert len(result) == 1

    def test_enforces_limit(self):
        tags = [f"#Tag{i}" for i in range(20)]
        result = _clean_hashtags(tags, 5)
        assert len(result) == 5

    def test_removes_spaces(self):
        result = _clean_hashtags(["#Make Money"], 10)
        assert result == ["#MakeMoney"]

    def test_truncates_long_hashtag(self):
        result = _clean_hashtags(["#" + "A" * 50], 10)
        assert len(result[0]) <= 30

    def test_filters_empty(self):
        result = _clean_hashtags(["", "  ", "#Valid"], 10)
        assert result == ["#Valid"]


class TestCleanTags:
    def test_basic(self):
        result = _clean_tags(["tag one", "tag two"], 500)
        assert result == ["tag one", "tag two"]

    def test_removes_hash(self):
        result = _clean_tags(["#tag"], 500)
        assert result == ["tag"]

    def test_removes_duplicates(self):
        result = _clean_tags(["Tag", "tag", "TAG"], 500)
        assert len(result) == 1

    def test_respects_char_limit(self):
        result = _clean_tags(["a" * 100, "b" * 100, "c" * 100], 250)
        total = sum(len(t) for t in result)
        assert total <= 250

    def test_filters_empty(self):
        result = _clean_tags(["", "  ", "valid"], 500)
        assert result == ["valid"]


# ---------------------------------------------------------------------------
# Score estimation tests
# ---------------------------------------------------------------------------

class TestScoreEstimation:
    def test_empty_result_scores_zero(self):
        assert _estimate_seo_score(SEOResult()) == 0

    def test_complete_result_scores_high(self):
        result = SEOResult(
            title="How I Made $10K in 30 Days — The Secret Nobody Tells You",
            description="Discover exactly how I used AI to earn $10K. What tools did I use? Watch to find out.",
            tags=[f"tag{i}" for i in range(15)],
            hashtags=["#Shorts", "#Viral", "#AI", "#Money", "#Tips"],
            hooks=["Hook 1", "Hook 2", "Hook 3"],
            platform="youtube",
        )
        score = _estimate_seo_score(result)
        assert score >= 80

    def test_title_with_number_scores_higher(self):
        with_number = SEOResult(title="5 Ways to Make Money with AI")
        without_number = SEOResult(title="Ways to Make Money with AI")
        assert _estimate_seo_score(with_number) > _estimate_seo_score(without_number)

    def test_description_with_question_scores_higher(self):
        with_q = SEOResult(
            title="Test Title",
            description="This is a long enough description to count. " * 5 + "Want to learn more?",
        )
        without_q = SEOResult(
            title="Test Title",
            description="This is a long enough description to count. " * 5,
        )
        assert _estimate_seo_score(with_q) > _estimate_seo_score(without_q)

    def test_score_capped_at_100(self):
        result = SEOResult(
            title="How I Made $10K — Secret Method",
            description="Long description " * 50 + "?",
            tags=[f"t{i}" for i in range(20)],
            hashtags=["#Shorts", "#Viral", "#FYP", "#AI", "#Money", "#Tips"],
            hooks=["h1", "h2", "h3"],
        )
        assert _estimate_seo_score(result) <= 100


# ---------------------------------------------------------------------------
# Config helper tests
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    @patch("seo_optimizer._get")
    def test_seo_enabled_default(self, mock_get):
        mock_get.return_value = {}
        assert get_seo_enabled() is True

    @patch("seo_optimizer._get")
    def test_seo_enabled_explicit(self, mock_get):
        mock_get.return_value = {"enabled": False}
        assert get_seo_enabled() is False

    @patch("seo_optimizer._get")
    def test_seo_platforms_default(self, mock_get):
        mock_get.return_value = {}
        assert get_seo_target_platforms() == ["youtube"]

    @patch("seo_optimizer._get")
    def test_seo_platforms_custom(self, mock_get):
        mock_get.return_value = {"platforms": ["youtube", "tiktok", "twitter"]}
        result = get_seo_target_platforms()
        assert "youtube" in result
        assert "tiktok" in result

    @patch("seo_optimizer._get")
    def test_seo_platforms_filters_invalid(self, mock_get):
        mock_get.return_value = {"platforms": ["youtube", "instagram", "invalid"]}
        result = get_seo_target_platforms()
        assert result == ["youtube"]

    @patch("seo_optimizer._get")
    def test_seo_language_default(self, mock_get):
        mock_get.return_value = {}
        assert get_seo_language() == "en"

    @patch("seo_optimizer._get")
    def test_seo_include_tags_default(self, mock_get):
        mock_get.return_value = {}
        assert get_seo_include_tags() is True

    @patch("seo_optimizer._get")
    def test_seo_include_hooks_default(self, mock_get):
        mock_get.return_value = {}
        assert get_seo_include_hooks() is True

    @patch("seo_optimizer._get")
    def test_seo_hashtag_count_default(self, mock_get):
        mock_get.return_value = {}
        assert get_seo_hashtag_count() == 8

    @patch("seo_optimizer._get")
    def test_seo_hashtag_count_clamped_low(self, mock_get):
        mock_get.return_value = {"hashtag_count": 0}
        assert get_seo_hashtag_count() == 1

    @patch("seo_optimizer._get")
    def test_seo_hashtag_count_clamped_high(self, mock_get):
        mock_get.return_value = {"hashtag_count": 100}
        assert get_seo_hashtag_count() == 15


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------

class TestPromptBuilders:
    def test_title_prompt_contains_subject(self):
        prompt = _build_title_prompt("AI Money Tips", "finance", "youtube", "en")
        assert "AI Money Tips" in prompt
        assert "finance" in prompt
        assert "youtube" in prompt

    def test_description_prompt_contains_script(self):
        prompt = _build_description_prompt("Topic", "My script text", "niche", "youtube", "en")
        assert "My script text" in prompt

    def test_description_prompt_tiktok(self):
        prompt = _build_description_prompt("Topic", "Script", "niche", "tiktok", "en")
        assert "concise" in prompt.lower() or "punchy" in prompt.lower()

    def test_description_prompt_twitter(self):
        prompt = _build_description_prompt("Topic", "Script", "niche", "twitter", "en")
        assert "280" in prompt

    def test_tags_prompt(self):
        prompt = _build_tags_prompt("AI", "tech", "en")
        assert "15-20" in prompt
        assert "JSON" in prompt

    def test_hashtags_prompt_count(self):
        prompt = _build_hashtags_prompt("AI", "tech", "youtube", 8, "en")
        assert "8" in prompt

    def test_hooks_prompt(self):
        prompt = _build_hooks_prompt("AI", "tech", "youtube", "en")
        assert "3" in prompt
        assert "hook" in prompt.lower() or "scroll" in prompt.lower()


# ---------------------------------------------------------------------------
# Full optimization tests
# ---------------------------------------------------------------------------

class TestOptimizeMetadata:
    def test_youtube_full_optimization(self):
        result = optimize_metadata(
            subject="How to make money with AI",
            script="In this video we explore AI money making strategies...",
            niche="finance",
            platform="youtube",
            language="en",
            generate_fn=_mock_generate,
        )
        assert isinstance(result, SEOResult)
        assert result.platform == "youtube"
        assert len(result.title) > 0
        assert len(result.description) > 0
        assert len(result.tags) > 0
        assert len(result.hashtags) > 0
        assert len(result.hooks) > 0
        assert 0 <= result.score <= 100

    def test_tiktok_optimization(self):
        result = optimize_metadata(
            subject="AI money tips",
            platform="tiktok",
            generate_fn=_mock_generate,
        )
        assert result.platform == "tiktok"
        assert result.tags == []  # TikTok doesn't use tags

    def test_twitter_optimization(self):
        result = optimize_metadata(
            subject="AI money tips",
            platform="twitter",
            generate_fn=_mock_generate,
        )
        assert result.platform == "twitter"
        assert result.tags == []

    def test_empty_subject_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            optimize_metadata(subject="", generate_fn=_mock_generate)

    def test_invalid_platform_raises(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            optimize_metadata(subject="test", platform="invalid", generate_fn=_mock_generate)

    def test_null_byte_raises(self):
        with pytest.raises(ValueError, match="Null bytes"):
            optimize_metadata(subject="test\x00", generate_fn=_mock_generate)

    def test_long_subject_truncated(self):
        long_subject = "A" * 600
        result = optimize_metadata(
            subject=long_subject,
            generate_fn=_mock_generate,
        )
        assert isinstance(result, SEOResult)

    def test_default_niche(self):
        result = optimize_metadata(
            subject="Test video",
            niche="",
            generate_fn=_mock_generate,
        )
        assert isinstance(result, SEOResult)

    @patch("seo_optimizer.get_seo_include_tags")
    def test_tags_disabled(self, mock_tags):
        mock_tags.return_value = False
        result = optimize_metadata(
            subject="Test",
            platform="youtube",
            generate_fn=_mock_generate,
        )
        assert result.tags == []

    @patch("seo_optimizer.get_seo_include_hooks")
    def test_hooks_disabled(self, mock_hooks):
        mock_hooks.return_value = False
        result = optimize_metadata(
            subject="Test",
            generate_fn=_mock_generate,
        )
        assert result.hooks == []

    def test_title_respects_platform_limit(self):
        def long_title_gen(prompt):
            if "title" in prompt.lower() and "tag" not in prompt.lower():
                return "A" * 200
            return _mock_generate(prompt)

        result = optimize_metadata(
            subject="Test",
            platform="youtube",
            generate_fn=long_title_gen,
        )
        assert len(result.title) <= _PLATFORM_LIMITS["youtube"]["title"]


class TestOptimizeExistingMetadata:
    def test_basic(self):
        metadata = {"title": "My Video", "description": "A great video."}
        result = optimize_existing_metadata(
            metadata=metadata,
            niche="tech",
            generate_fn=_mock_generate,
        )
        assert isinstance(result, SEOResult)
        assert len(result.title) > 0

    def test_with_subject_key(self):
        metadata = {"subject": "AI Tips", "script": "Full script here..."}
        result = optimize_existing_metadata(
            metadata=metadata,
            generate_fn=_mock_generate,
        )
        assert isinstance(result, SEOResult)

    def test_invalid_metadata_type(self):
        with pytest.raises(ValueError, match="must be a dict"):
            optimize_existing_metadata(metadata="not a dict", generate_fn=_mock_generate)

    def test_empty_metadata(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            optimize_existing_metadata(metadata={}, generate_fn=_mock_generate)


# ---------------------------------------------------------------------------
# Platform limits tests
# ---------------------------------------------------------------------------

class TestPlatformLimits:
    def test_youtube_limits_exist(self):
        assert "youtube" in _PLATFORM_LIMITS
        assert "title" in _PLATFORM_LIMITS["youtube"]
        assert "description" in _PLATFORM_LIMITS["youtube"]
        assert "tags" in _PLATFORM_LIMITS["youtube"]
        assert "hashtags" in _PLATFORM_LIMITS["youtube"]

    def test_tiktok_limits_exist(self):
        assert "tiktok" in _PLATFORM_LIMITS
        assert "title" in _PLATFORM_LIMITS["tiktok"]
        assert "tags" not in _PLATFORM_LIMITS["tiktok"]

    def test_twitter_limits_exist(self):
        assert "twitter" in _PLATFORM_LIMITS
        assert _PLATFORM_LIMITS["twitter"]["description"] == 280

    def test_supported_platforms(self):
        assert _SUPPORTED_PLATFORMS == {"youtube", "tiktok", "twitter"}

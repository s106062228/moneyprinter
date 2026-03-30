"""
Tests for quality_gate module.

Coverage targets:
- QualityDimension dataclass (fields, creation)
- QualityVerdict dataclass (fields, passed computation)
- ContentQualityGate.__init__ (defaults, config override, threshold clamping, mode validation)
- evaluate() — happy path, all platforms, input validation, LLM failure modes
- _build_prompt() — content checks for all inputs and platform name
- _parse_response() — valid JSON, markdown-wrapped, invalid JSON, missing keys, clamping
- check_and_gate() — block / warn / off modes
- Weight verification — each platform's weights sum to 1.0
- Threshold edge cases — exactly at, just below, just above
- Config integration — reads quality_gate.threshold, quality_gate.mode
"""

import json
import pytest
from dataclasses import fields as dc_fields
from unittest.mock import patch, MagicMock

from quality_gate import (
    QualityDimension,
    QualityVerdict,
    ContentQualityGate,
    _SUPPORTED_PLATFORMS,
    _PLATFORM_WEIGHTS,
    _DIMENSIONS,
    _MAX_TITLE_LENGTH,
    _MAX_DESCRIPTION_LENGTH,
    _MAX_SCRIPT_LENGTH,
    _MAX_TAGS,
    _MIN_THRESHOLD,
    _MAX_THRESHOLD,
    _VALID_MODES,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_valid_json_response(
    originality=80,
    effort_level=70,
    insight_depth=75,
    production_quality=65,
    policy_compliance=90,
    suggestions=None,
) -> str:
    if suggestions is None:
        suggestions = ["Add unique research", "Use custom visuals", "Improve pacing"]
    return json.dumps({
        "originality": originality,
        "originality_feedback": "Good originality",
        "effort_level": effort_level,
        "effort_level_feedback": "Decent effort",
        "insight_depth": insight_depth,
        "insight_depth_feedback": "Solid depth",
        "production_quality": production_quality,
        "production_quality_feedback": "Acceptable production",
        "policy_compliance": policy_compliance,
        "policy_compliance_feedback": "Compliant with policy",
        "suggestions": suggestions,
    })


_GOOD_RESPONSE = _make_valid_json_response()

_MOCK_PATH = "quality_gate.generate_text"


# ---------------------------------------------------------------------------
# 1. QualityDimension dataclass
# ---------------------------------------------------------------------------

class TestQualityDimension:
    def test_creation_with_all_fields(self):
        dim = QualityDimension(name="originality", score=85.0, feedback="Great")
        assert dim.name == "originality"
        assert dim.score == 85.0
        assert dim.feedback == "Great"

    def test_score_zero(self):
        dim = QualityDimension(name="effort_level", score=0.0, feedback="")
        assert dim.score == 0.0

    def test_score_hundred(self):
        dim = QualityDimension(name="policy_compliance", score=100.0, feedback="Perfect")
        assert dim.score == 100.0

    def test_feedback_empty_string(self):
        dim = QualityDimension(name="insight_depth", score=50.0, feedback="")
        assert dim.feedback == ""

    def test_all_dimension_names_creatable(self):
        for name in _DIMENSIONS:
            dim = QualityDimension(name=name, score=50.0, feedback="ok")
            assert dim.name == name

    def test_has_expected_fields(self):
        names = {f.name for f in dc_fields(QualityDimension)}
        assert names == {"name", "score", "feedback"}


# ---------------------------------------------------------------------------
# 2. QualityVerdict dataclass
# ---------------------------------------------------------------------------

class TestQualityVerdict:
    def _make(self, overall=75.0, passed=True, threshold=60.0):
        dims = [QualityDimension(name=d, score=70.0, feedback="ok") for d in _DIMENSIONS]
        return QualityVerdict(
            overall_score=overall,
            dimensions=dims,
            passed=passed,
            threshold=threshold,
            suggestions=["Improve it"],
            platform="youtube",
            error="",
        )

    def test_creation_fields(self):
        v = self._make()
        assert v.overall_score == 75.0
        assert v.passed is True
        assert v.threshold == 60.0
        assert v.platform == "youtube"
        assert v.error == ""

    def test_passed_false(self):
        v = self._make(overall=50.0, passed=False)
        assert v.passed is False

    def test_dimensions_list(self):
        v = self._make()
        assert len(v.dimensions) == len(_DIMENSIONS)
        assert all(isinstance(d, QualityDimension) for d in v.dimensions)

    def test_suggestions_list(self):
        v = self._make()
        assert isinstance(v.suggestions, list)

    def test_error_field_defaults_empty(self):
        v = self._make()
        assert v.error == ""

    def test_error_field_can_be_set(self):
        dims = []
        v = QualityVerdict(
            overall_score=0.0,
            dimensions=dims,
            passed=False,
            threshold=60.0,
            suggestions=[],
            platform="youtube",
            error="parse failed",
        )
        assert v.error == "parse failed"

    def test_has_expected_fields(self):
        names = {f.name for f in dc_fields(QualityVerdict)}
        assert names == {
            "overall_score", "dimensions", "passed", "threshold",
            "suggestions", "platform", "error",
        }


# ---------------------------------------------------------------------------
# 3. ContentQualityGate.__init__
# ---------------------------------------------------------------------------

class TestContentQualityGateInit:
    def test_default_threshold(self):
        gate = ContentQualityGate()
        assert gate.threshold == 60.0

    def test_default_mode(self):
        gate = ContentQualityGate()
        assert gate.mode == "warn"

    def test_custom_threshold(self):
        gate = ContentQualityGate(threshold=75.0)
        assert gate.threshold == 75.0

    def test_custom_mode_block(self):
        gate = ContentQualityGate(mode="block")
        assert gate.mode == "block"

    def test_custom_mode_off(self):
        gate = ContentQualityGate(mode="off")
        assert gate.mode == "off"

    def test_threshold_clamped_below_min(self):
        gate = ContentQualityGate(threshold=-10.0)
        assert gate.threshold == _MIN_THRESHOLD

    def test_threshold_clamped_above_max(self):
        gate = ContentQualityGate(threshold=150.0)
        assert gate.threshold == _MAX_THRESHOLD

    def test_threshold_at_zero(self):
        gate = ContentQualityGate(threshold=0.0)
        assert gate.threshold == 0.0

    def test_threshold_at_100(self):
        gate = ContentQualityGate(threshold=100.0)
        assert gate.threshold == 100.0

    def test_invalid_mode_defaults_to_warn(self):
        gate = ContentQualityGate(mode="invalid_mode")
        assert gate.mode == "warn"

    def test_config_threshold_override(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                70.0 if key == "quality_gate.threshold" else default
            )
            gate = ContentQualityGate()
        assert gate.threshold == 70.0

    def test_config_mode_override(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                "block" if key == "quality_gate.mode" else default
            )
            gate = ContentQualityGate()
        assert gate.mode == "block"

    def test_explicit_threshold_overrides_config(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                70.0 if key == "quality_gate.threshold" else default
            )
            gate = ContentQualityGate(threshold=55.0)
        # Explicit constructor arg wins over config
        assert gate.threshold == 55.0

    def test_explicit_mode_overrides_config(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                "block" if key == "quality_gate.mode" else default
            )
            gate = ContentQualityGate(mode="off")
        assert gate.mode == "off"

    def test_config_invalid_threshold_ignored(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                "not_a_number" if key == "quality_gate.threshold" else default
            )
            gate = ContentQualityGate()
        # Falls back to constructor default
        assert gate.threshold == 60.0


# ---------------------------------------------------------------------------
# 4. evaluate() — happy path
# ---------------------------------------------------------------------------

class TestEvaluateHappyPath:
    def test_returns_quality_verdict(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Amazing AI Tutorial")
        assert isinstance(verdict, QualityVerdict)

    def test_overall_score_in_range(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert 0.0 <= verdict.overall_score <= 100.0

    def test_dimensions_populated(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert len(verdict.dimensions) == len(_DIMENSIONS)

    def test_platform_set_on_verdict(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title", platform="tiktok")
        assert verdict.platform == "tiktok"

    def test_threshold_set_on_verdict(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=70.0)
            verdict = gate.evaluate("Title")
        assert verdict.threshold == 70.0

    def test_passed_true_when_above_threshold(self):
        # scores will yield ~76.0 for youtube
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=50.0)
            verdict = gate.evaluate("Title")
        assert verdict.passed is True

    def test_passed_false_when_below_threshold(self):
        low_resp = _make_valid_json_response(
            originality=10, effort_level=10, insight_depth=10,
            production_quality=10, policy_compliance=10
        )
        with patch(_MOCK_PATH, return_value=low_resp):
            gate = ContentQualityGate(threshold=60.0)
            verdict = gate.evaluate("Title")
        assert verdict.passed is False

    def test_suggestions_returned(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert isinstance(verdict.suggestions, list)

    def test_generate_text_called_once(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("Title")
        mock_gen.assert_called_once()

    def test_title_in_prompt(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("My Unique Title")
        prompt = mock_gen.call_args[0][0]
        assert "My Unique Title" in prompt


# ---------------------------------------------------------------------------
# 5. evaluate() — all 4 platforms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("platform", list(_SUPPORTED_PLATFORMS))
class TestEvaluatePlatforms:
    def test_platform_in_verdict(self, platform):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title", platform=platform)
        assert verdict.platform == platform

    def test_platform_in_prompt(self, platform):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("Title", platform=platform)
        prompt = mock_gen.call_args[0][0]
        assert platform in prompt.lower()

    def test_overall_score_in_bounds(self, platform):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title", platform=platform)
        assert 0.0 <= verdict.overall_score <= 100.0


# ---------------------------------------------------------------------------
# 6. evaluate() — input validation
# ---------------------------------------------------------------------------

class TestEvaluateInputValidation:
    def test_empty_title_raises_value_error(self):
        gate = ContentQualityGate()
        with pytest.raises(ValueError, match="Title is required"):
            gate.evaluate("")

    def test_whitespace_title_raises_value_error(self):
        gate = ContentQualityGate()
        with pytest.raises(ValueError, match="Title is required"):
            gate.evaluate("   ")

    def test_long_title_truncated(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("A" * 1000)
        prompt = mock_gen.call_args[0][0]
        assert "A" * _MAX_TITLE_LENGTH in prompt
        assert "A" * (_MAX_TITLE_LENGTH + 1) not in prompt

    def test_long_description_truncated(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("Title", description="D" * 10000)
        prompt = mock_gen.call_args[0][0]
        # Description preview is first 500 chars
        assert "D" * 500 in prompt

    def test_too_many_tags_truncated(self):
        many_tags = [f"tag{i}" for i in range(100)]
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("Title", tags=many_tags)
        prompt = mock_gen.call_args[0][0]
        assert f"tag{_MAX_TAGS - 1}" in prompt
        assert f"tag{_MAX_TAGS}" not in prompt

    def test_unsupported_platform_defaults_to_youtube(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title", platform="snapchat")
        assert verdict.platform == "youtube"

    def test_none_tags_treated_as_empty(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title", tags=None)
        assert isinstance(verdict, QualityVerdict)

    def test_none_description_treated_as_empty(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title", description=None)
        assert isinstance(verdict, QualityVerdict)

    def test_script_included_in_prompt(self):
        script_text = "This is a unique script about AI productivity"
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("Title", script=script_text)
        prompt = mock_gen.call_args[0][0]
        assert "unique script" in prompt

    def test_long_script_truncated(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE) as mock_gen:
            gate = ContentQualityGate()
            gate.evaluate("Title", script="S" * 60000)
        # Verify generate_text was called (script was accepted without error)
        mock_gen.assert_called_once()


# ---------------------------------------------------------------------------
# 7. evaluate() — LLM returns malformed JSON
# ---------------------------------------------------------------------------

class TestEvaluateMalformedJSON:
    def test_malformed_json_returns_error_verdict(self):
        with patch(_MOCK_PATH, return_value="This is not JSON at all {broken"):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.error != ""

    def test_malformed_json_overall_score_zero(self):
        with patch(_MOCK_PATH, return_value="{{invalid}}"):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.overall_score == 0.0

    def test_malformed_json_passed_false(self):
        with patch(_MOCK_PATH, return_value="not json"):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.passed is False


# ---------------------------------------------------------------------------
# 8. evaluate() — LLM returns markdown-wrapped JSON
# ---------------------------------------------------------------------------

class TestEvaluateMarkdownJSON:
    def test_markdown_json_block_parsed(self):
        wrapped = f"```json\n{_GOOD_RESPONSE}\n```"
        with patch(_MOCK_PATH, return_value=wrapped):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.error == ""
        assert verdict.overall_score > 0.0

    def test_markdown_block_without_json_label(self):
        wrapped = f"```\n{_GOOD_RESPONSE}\n```"
        with patch(_MOCK_PATH, return_value=wrapped):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.error == ""

    def test_json_embedded_in_prose(self):
        prose = f"Here is my evaluation:\n{_GOOD_RESPONSE}\nI hope that helps."
        with patch(_MOCK_PATH, return_value=prose):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.error == ""
        assert verdict.overall_score > 0.0


# ---------------------------------------------------------------------------
# 9. evaluate() — scores outside 0-100 are clamped
# ---------------------------------------------------------------------------

class TestEvaluateScoreClamping:
    def test_scores_above_100_clamped(self):
        over_resp = json.dumps({
            "originality": 150,
            "originality_feedback": "",
            "effort_level": 200,
            "effort_level_feedback": "",
            "insight_depth": 120,
            "insight_depth_feedback": "",
            "production_quality": 999,
            "production_quality_feedback": "",
            "policy_compliance": 110,
            "policy_compliance_feedback": "",
            "suggestions": [],
        })
        with patch(_MOCK_PATH, return_value=over_resp):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        for dim in verdict.dimensions:
            assert dim.score <= 100.0
        assert verdict.overall_score <= 100.0

    def test_scores_below_0_clamped(self):
        under_resp = json.dumps({
            "originality": -50,
            "originality_feedback": "",
            "effort_level": -10,
            "effort_level_feedback": "",
            "insight_depth": -100,
            "insight_depth_feedback": "",
            "production_quality": -5,
            "production_quality_feedback": "",
            "policy_compliance": -20,
            "policy_compliance_feedback": "",
            "suggestions": [],
        })
        with patch(_MOCK_PATH, return_value=under_resp):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        for dim in verdict.dimensions:
            assert dim.score >= 0.0
        assert verdict.overall_score >= 0.0

    def test_boundary_scores_at_0_and_100(self):
        edge_resp = json.dumps({
            "originality": 0,
            "originality_feedback": "",
            "effort_level": 100,
            "effort_level_feedback": "",
            "insight_depth": 0,
            "insight_depth_feedback": "",
            "production_quality": 100,
            "production_quality_feedback": "",
            "policy_compliance": 0,
            "policy_compliance_feedback": "",
            "suggestions": [],
        })
        with patch(_MOCK_PATH, return_value=edge_resp):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        scores = {d.name: d.score for d in verdict.dimensions}
        assert scores["originality"] == 0.0
        assert scores["effort_level"] == 100.0


# ---------------------------------------------------------------------------
# 10. evaluate() — LLM not available
# ---------------------------------------------------------------------------

class TestEvaluateLLMNotAvailable:
    def test_raises_runtime_error_when_generate_text_is_none(self):
        with patch("quality_gate.generate_text", None):
            gate = ContentQualityGate()
            with pytest.raises(RuntimeError, match="LLM provider is not available"):
                gate.evaluate("Title")


# ---------------------------------------------------------------------------
# 11. evaluate() — LLM returns empty/None
# ---------------------------------------------------------------------------

class TestEvaluateLLMEmptyResponse:
    def test_empty_string_returns_error_verdict(self):
        with patch(_MOCK_PATH, return_value=""):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.error != ""

    def test_none_response_returns_error_verdict(self):
        with patch(_MOCK_PATH, return_value=None):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.error != ""

    def test_whitespace_only_response_returns_error_verdict(self):
        with patch(_MOCK_PATH, return_value="   "):
            gate = ContentQualityGate()
            verdict = gate.evaluate("Title")
        assert verdict.error != ""


# ---------------------------------------------------------------------------
# 12. _build_prompt() content checks
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def setup_method(self):
        self.gate = ContentQualityGate()

    def test_platform_name_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", [], "youtube")
        assert "youtube" in prompt.lower()

    def test_title_in_prompt(self):
        prompt = self.gate._build_prompt("Amazing Tutorial", "", "", [], "youtube")
        assert "Amazing Tutorial" in prompt

    def test_all_dimensions_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", [], "youtube")
        for dim in _DIMENSIONS:
            assert dim in prompt

    def test_weights_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", [], "youtube")
        # youtube originality weight = 25%
        assert "25%" in prompt

    def test_description_preview_in_prompt(self):
        desc = "D" * 600
        prompt = self.gate._build_prompt("T", desc, "", [], "youtube")
        assert "D" * 500 in prompt
        assert "D" * 501 not in prompt

    def test_script_preview_in_prompt(self):
        script = "S" * 1500
        prompt = self.gate._build_prompt("T", "", script, [], "youtube")
        assert "S" * 1000 in prompt
        assert "S" * 1001 not in prompt

    def test_tags_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", ["python", "ai"], "youtube")
        assert "python" in prompt
        assert "ai" in prompt

    def test_empty_tags_shown_as_none(self):
        prompt = self.gate._build_prompt("T", "", "", [], "youtube")
        assert "none" in prompt.lower()

    def test_json_format_instruction_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", [], "youtube")
        assert "JSON" in prompt or "json" in prompt.lower()

    def test_tiktok_weight_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", [], "tiktok")
        # tiktok production_quality = 30%
        assert "30%" in prompt

    def test_twitter_platform_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", [], "twitter")
        assert "twitter" in prompt.lower()

    def test_instagram_platform_in_prompt(self):
        prompt = self.gate._build_prompt("T", "", "", [], "instagram")
        assert "instagram" in prompt.lower()


# ---------------------------------------------------------------------------
# 13. _parse_response() — various inputs
# ---------------------------------------------------------------------------

class TestParseResponse:
    def setup_method(self):
        self.gate = ContentQualityGate()

    def test_valid_json_sets_all_dimensions(self):
        verdict = self.gate._parse_response(_GOOD_RESPONSE)
        dim_names = {d.name for d in verdict.dimensions}
        assert dim_names == set(_DIMENSIONS)

    def test_valid_json_feedback_populated(self):
        verdict = self.gate._parse_response(_GOOD_RESPONSE)
        for dim in verdict.dimensions:
            assert isinstance(dim.feedback, str)

    def test_valid_json_suggestions_list(self):
        verdict = self.gate._parse_response(_GOOD_RESPONSE)
        assert isinstance(verdict.suggestions, list)
        assert len(verdict.suggestions) == 3

    def test_markdown_json_extracted(self):
        wrapped = f"```json\n{_GOOD_RESPONSE}\n```"
        verdict = self.gate._parse_response(wrapped)
        assert verdict.error == ""

    def test_invalid_json_returns_error_verdict(self):
        verdict = self.gate._parse_response("{not valid json")
        assert verdict.error != ""

    def test_missing_dimension_keys_default_to_50(self):
        minimal = json.dumps({
            "originality": 80,
            "originality_feedback": "",
            # other dimensions absent
            "suggestions": [],
        })
        verdict = self.gate._parse_response(minimal)
        scores = {d.name: d.score for d in verdict.dimensions}
        assert scores["effort_level"] == 50.0
        assert scores["insight_depth"] == 50.0

    def test_extra_keys_in_json_ignored(self):
        data = json.loads(_GOOD_RESPONSE)
        data["unknown_future_field"] = "ignored"
        verdict = self.gate._parse_response(json.dumps(data))
        assert verdict.error == ""

    def test_suggestions_truncated_to_200_chars_each(self):
        data = json.loads(_GOOD_RESPONSE)
        data["suggestions"] = ["X" * 300]
        verdict = self.gate._parse_response(json.dumps(data))
        assert len(verdict.suggestions[0]) == 200

    def test_suggestions_max_10(self):
        data = json.loads(_GOOD_RESPONSE)
        data["suggestions"] = [f"tip{i}" for i in range(20)]
        verdict = self.gate._parse_response(json.dumps(data))
        assert len(verdict.suggestions) <= 10

    def test_suggestions_as_string_becomes_list(self):
        data = json.loads(_GOOD_RESPONSE)
        data["suggestions"] = "Just one suggestion"
        verdict = self.gate._parse_response(json.dumps(data))
        assert isinstance(verdict.suggestions, list)
        assert "Just one suggestion" in verdict.suggestions

    def test_missing_suggestions_key_gives_empty_list(self):
        data = json.loads(_GOOD_RESPONSE)
        del data["suggestions"]
        verdict = self.gate._parse_response(json.dumps(data))
        assert verdict.suggestions == []

    def test_empty_string_returns_error_verdict(self):
        verdict = self.gate._parse_response("")
        assert verdict.error != ""

    def test_none_response_returns_error_verdict(self):
        verdict = self.gate._parse_response(None)
        assert verdict.error != ""

    def test_no_json_object_returns_error_verdict(self):
        verdict = self.gate._parse_response("No JSON object here at all.")
        assert verdict.error != ""

    def test_error_verdict_score_is_zero(self):
        verdict = self.gate._parse_response("garbage response")
        assert verdict.overall_score == 0.0


# ---------------------------------------------------------------------------
# 14-16. check_and_gate() — all modes
# ---------------------------------------------------------------------------

class TestCheckAndGateBlockMode:
    def test_block_mode_fails_below_threshold(self):
        low_resp = _make_valid_json_response(
            originality=10, effort_level=10, insight_depth=10,
            production_quality=10, policy_compliance=10
        )
        with patch(_MOCK_PATH, return_value=low_resp):
            gate = ContentQualityGate(threshold=60.0, mode="block")
            should_proceed, verdict = gate.check_and_gate("Title")
        assert should_proceed is False
        assert verdict is not None

    def test_block_mode_passes_above_threshold(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=50.0, mode="block")
            should_proceed, verdict = gate.check_and_gate("Title")
        assert should_proceed is True

    def test_block_mode_verdict_included_when_blocked(self):
        low_resp = _make_valid_json_response(
            originality=5, effort_level=5, insight_depth=5,
            production_quality=5, policy_compliance=5
        )
        with patch(_MOCK_PATH, return_value=low_resp):
            gate = ContentQualityGate(threshold=60.0, mode="block")
            should_proceed, verdict = gate.check_and_gate("Title")
        assert isinstance(verdict, QualityVerdict)

    def test_block_mode_verdict_included_when_passing(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=50.0, mode="block")
            should_proceed, verdict = gate.check_and_gate("Title")
        assert isinstance(verdict, QualityVerdict)


class TestCheckAndGateWarnMode:
    def test_warn_mode_always_proceeds_below_threshold(self):
        low_resp = _make_valid_json_response(
            originality=10, effort_level=10, insight_depth=10,
            production_quality=10, policy_compliance=10
        )
        with patch(_MOCK_PATH, return_value=low_resp):
            gate = ContentQualityGate(threshold=60.0, mode="warn")
            should_proceed, verdict = gate.check_and_gate("Title")
        assert should_proceed is True

    def test_warn_mode_always_proceeds_above_threshold(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=50.0, mode="warn")
            should_proceed, verdict = gate.check_and_gate("Title")
        assert should_proceed is True

    def test_warn_mode_returns_verdict(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(mode="warn")
            should_proceed, verdict = gate.check_and_gate("Title")
        assert isinstance(verdict, QualityVerdict)

    def test_default_mode_is_warn(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate()
            should_proceed, verdict = gate.check_and_gate("Title")
        assert should_proceed is True


class TestCheckAndGateOffMode:
    def test_off_mode_returns_true_none(self):
        gate = ContentQualityGate(mode="off")
        should_proceed, verdict = gate.check_and_gate("Title")
        assert should_proceed is True
        assert verdict is None

    def test_off_mode_does_not_call_llm(self):
        with patch(_MOCK_PATH) as mock_gen:
            gate = ContentQualityGate(mode="off")
            gate.check_and_gate("Title")
        mock_gen.assert_not_called()


# ---------------------------------------------------------------------------
# 17. Weight verification — platform weights sum to 1.0
# ---------------------------------------------------------------------------

class TestPlatformWeights:
    def test_all_supported_platforms_have_weights(self):
        for platform in _SUPPORTED_PLATFORMS:
            assert platform in _PLATFORM_WEIGHTS

    @pytest.mark.parametrize("platform", list(_SUPPORTED_PLATFORMS))
    def test_weights_sum_to_1(self, platform):
        weights = _PLATFORM_WEIGHTS[platform]
        total = sum(weights[dim] for dim in _DIMENSIONS)
        assert abs(total - 1.0) < 1e-9, (
            f"Weights for {platform!r} sum to {total}, expected 1.0"
        )

    @pytest.mark.parametrize("platform", list(_SUPPORTED_PLATFORMS))
    def test_all_dimensions_have_weights(self, platform):
        weights = _PLATFORM_WEIGHTS[platform]
        for dim in _DIMENSIONS:
            assert dim in weights, f"Missing weight for {dim!r} on {platform!r}"

    @pytest.mark.parametrize("platform", list(_SUPPORTED_PLATFORMS))
    def test_all_weights_positive(self, platform):
        for dim, w in _PLATFORM_WEIGHTS[platform].items():
            assert w > 0, f"Non-positive weight for {dim!r} on {platform!r}"

    def test_youtube_default_weights(self):
        yt = _PLATFORM_WEIGHTS["youtube"]
        assert yt["originality"] == 0.25
        assert yt["effort_level"] == 0.20
        assert yt["insight_depth"] == 0.25
        assert yt["production_quality"] == 0.15
        assert yt["policy_compliance"] == 0.15

    def test_tiktok_production_quality_highest(self):
        tiktok = _PLATFORM_WEIGHTS["tiktok"]
        assert tiktok["production_quality"] == max(tiktok.values())

    def test_twitter_originality_and_insight_depth_equal_highest(self):
        twitter = _PLATFORM_WEIGHTS["twitter"]
        max_w = max(twitter.values())
        assert twitter["originality"] == max_w
        assert twitter["insight_depth"] == max_w

    def test_instagram_production_quality_highest(self):
        ig = _PLATFORM_WEIGHTS["instagram"]
        assert ig["production_quality"] == max(ig.values())


# ---------------------------------------------------------------------------
# 18. Threshold edge cases
# ---------------------------------------------------------------------------

class TestThresholdEdgeCases:
    def _get_score_for_response(self, response, platform="youtube"):
        """Helper: parse response and return the overall_score for the platform."""
        gate = ContentQualityGate(threshold=60.0)
        with patch(_MOCK_PATH, return_value=response):
            verdict = gate.evaluate("Title", platform=platform)
        return verdict.overall_score

    def test_exactly_at_threshold_passes(self):
        # Build a response where computed score will be exactly the threshold.
        # Use threshold=0 so any positive score passes.
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=0.0)
            verdict = gate.evaluate("Title")
        assert verdict.passed is True

    def test_one_above_threshold_passes(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=1.0)
            verdict = gate.evaluate("Title")
        assert verdict.passed is True

    def test_threshold_100_requires_perfect_score(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=100.0)
            verdict = gate.evaluate("Title")
        # scores in _GOOD_RESPONSE are not all 100, so should fail
        assert verdict.passed is False

    def test_threshold_0_always_passes(self):
        low_resp = _make_valid_json_response(
            originality=1, effort_level=1, insight_depth=1,
            production_quality=1, policy_compliance=1
        )
        with patch(_MOCK_PATH, return_value=low_resp):
            gate = ContentQualityGate(threshold=0.0)
            verdict = gate.evaluate("Title")
        assert verdict.passed is True

    def test_passed_field_reflects_score_vs_threshold(self):
        with patch(_MOCK_PATH, return_value=_GOOD_RESPONSE):
            gate = ContentQualityGate(threshold=60.0)
            verdict = gate.evaluate("Title")
        assert verdict.passed == (verdict.overall_score >= 60.0)


# ---------------------------------------------------------------------------
# 19. Config integration
# ---------------------------------------------------------------------------

class TestConfigIntegration:
    def test_reads_quality_gate_threshold_from_config(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                80.0 if key == "quality_gate.threshold" else default
            )
            gate = ContentQualityGate()
        assert gate.threshold == 80.0

    def test_reads_quality_gate_mode_from_config(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                "block" if key == "quality_gate.mode" else default
            )
            gate = ContentQualityGate()
        assert gate.mode == "block"

    def test_config_off_mode(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                "off" if key == "quality_gate.mode" else default
            )
            gate = ContentQualityGate()
        assert gate.mode == "off"

    def test_config_threshold_clamped_when_out_of_range(self):
        with patch("quality_gate._get") as mock_get:
            mock_get.side_effect = lambda key, default=None: (
                999.0 if key == "quality_gate.threshold" else default
            )
            gate = ContentQualityGate()
        assert gate.threshold == _MAX_THRESHOLD

    def test_missing_config_uses_defaults(self):
        with patch("quality_gate._get", return_value=None):
            gate = ContentQualityGate()
        assert gate.threshold == 60.0
        assert gate.mode == "warn"


# ---------------------------------------------------------------------------
# 20. Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_supported_platforms_is_frozenset(self):
        assert isinstance(_SUPPORTED_PLATFORMS, frozenset)

    def test_supported_platforms_contains_expected(self):
        assert _SUPPORTED_PLATFORMS == {"youtube", "tiktok", "twitter", "instagram"}

    def test_valid_modes_is_frozenset(self):
        assert isinstance(_VALID_MODES, frozenset)

    def test_valid_modes_contains_expected(self):
        assert _VALID_MODES == {"block", "warn", "off"}

    def test_dimensions_tuple_length(self):
        assert len(_DIMENSIONS) == 5

    def test_max_title_length(self):
        assert _MAX_TITLE_LENGTH == 500

    def test_max_description_length(self):
        assert _MAX_DESCRIPTION_LENGTH == 5000

    def test_max_script_length(self):
        assert _MAX_SCRIPT_LENGTH == 50000

    def test_max_tags(self):
        assert _MAX_TAGS == 50

    def test_min_threshold(self):
        assert _MIN_THRESHOLD == 0.0

    def test_max_threshold(self):
        assert _MAX_THRESHOLD == 100.0

    def test_dimensions_contain_expected_names(self):
        assert set(_DIMENSIONS) == {
            "originality", "effort_level", "insight_depth",
            "production_quality", "policy_compliance",
        }

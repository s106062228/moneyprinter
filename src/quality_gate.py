"""
Content Quality Gate for MoneyPrinter.

Evaluates content against YouTube's 2026 AI content policy and general
quality dimensions before publishing. Returns a structured verdict with
per-dimension scores, an overall weighted score, and actionable suggestions.

Usage:
    gate = ContentQualityGate(threshold=60.0, mode="block")
    should_proceed, verdict = gate.check_and_gate(
        title="Top 10 AI Productivity Hacks",
        description="In this video we cover...",
        script="Full script text...",
        tags=["ai", "productivity"],
        platform="youtube",
    )
    if not should_proceed:
        print(f"Blocked: score={verdict.overall_score}")
"""

import json
import re
from dataclasses import dataclass, field

from mp_logger import get_logger
from config import _get

try:
    from llm_provider import generate_text
except Exception:
    generate_text = None  # type: ignore[assignment]

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUPPORTED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})

_MAX_TITLE_LENGTH = 500
_MAX_DESCRIPTION_LENGTH = 5000
_MAX_SCRIPT_LENGTH = 50000
_MAX_TAGS = 50
_MIN_THRESHOLD = 0.0
_MAX_THRESHOLD = 100.0
_VALID_MODES = frozenset({"block", "warn", "off"})

_DIMENSIONS = (
    "originality",
    "effort_level",
    "insight_depth",
    "production_quality",
    "policy_compliance",
)

_PLATFORM_WEIGHTS: dict[str, dict[str, float]] = {
    "youtube": {
        "originality": 0.25,
        "effort_level": 0.20,
        "insight_depth": 0.25,
        "production_quality": 0.15,
        "policy_compliance": 0.15,
    },
    "tiktok": {
        "originality": 0.20,
        "effort_level": 0.15,
        "insight_depth": 0.15,
        "production_quality": 0.30,
        "policy_compliance": 0.20,
    },
    "twitter": {
        "originality": 0.30,
        "effort_level": 0.15,
        "insight_depth": 0.30,
        "production_quality": 0.10,
        "policy_compliance": 0.15,
    },
    "instagram": {
        "originality": 0.20,
        "effort_level": 0.20,
        "insight_depth": 0.15,
        "production_quality": 0.30,
        "policy_compliance": 0.15,
    },
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class QualityDimension:
    """Score for a single quality evaluation dimension."""

    name: str
    score: float        # 0-100
    feedback: str


@dataclass
class QualityVerdict:
    """Full quality evaluation result for a piece of content."""

    overall_score: float            # 0-100 weighted composite
    dimensions: list                # list[QualityDimension]
    passed: bool                    # overall_score >= threshold
    threshold: float
    suggestions: list               # list[str] improvement tips
    platform: str
    error: str = ""                 # non-empty when evaluation failed


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class ContentQualityGate:
    """Evaluate content quality against YouTube 2026 AI content policy."""

    def __init__(self, threshold: float = 60.0, mode: str = "warn"):
        # Config overrides take lower priority than constructor args (explicit wins)
        cfg_threshold = _get("quality_gate.threshold", None)
        cfg_mode = _get("quality_gate.mode", None)

        # Only apply config defaults when constructor receives the default values
        if threshold == 60.0 and cfg_threshold is not None:
            try:
                threshold = float(cfg_threshold)
            except (TypeError, ValueError):
                pass

        if mode == "warn" and cfg_mode is not None:
            mode = str(cfg_mode)

        # Validate and clamp threshold
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 60.0
        threshold = max(_MIN_THRESHOLD, min(_MAX_THRESHOLD, threshold))

        # Validate mode
        if mode not in _VALID_MODES:
            logger.warning(
                f"Invalid quality_gate mode {mode!r}; defaulting to 'warn'"
            )
            mode = "warn"

        self.threshold = threshold
        self.mode = mode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        title: str,
        description: str = "",
        script: str = "",
        tags: list = None,
        platform: str = "youtube",
    ) -> "QualityVerdict":
        """Evaluate content quality using the LLM.

        Args:
            title:       Content title. Required, must not be blank.
            description: Content description. Optional.
            script:      Full script text. Optional.
            tags:        List of keyword tags. Optional.
            platform:    Target platform (youtube/tiktok/twitter/instagram).

        Returns:
            QualityVerdict with scores, pass/fail, and suggestions.

        Raises:
            ValueError: If title is empty or blank.
            RuntimeError: If LLM provider is unavailable.
        """
        if generate_text is None:
            raise RuntimeError(
                "LLM provider is not available. "
                "Ensure llm_provider.py and its dependencies are installed."
            )

        if not title or not title.strip():
            raise ValueError("Title is required for quality evaluation")

        if platform not in _SUPPORTED_PLATFORMS:
            logger.warning(
                f"Unsupported platform {platform!r}; defaulting to 'youtube'"
            )
            platform = "youtube"

        # Sanitise inputs
        title = title[:_MAX_TITLE_LENGTH]
        description = (description or "")[:_MAX_DESCRIPTION_LENGTH]
        script = (script or "")[:_MAX_SCRIPT_LENGTH]
        tags = (tags or [])[:_MAX_TAGS]

        logger.info(
            f"Evaluating content quality: platform={platform!r}, "
            f"title={title[:60]!r}"
        )

        prompt = self._build_prompt(title, description, script, tags, platform)
        response = generate_text(prompt)
        verdict = self._parse_response(response)

        # Stamp the platform and threshold onto the verdict
        verdict.platform = platform
        verdict.threshold = self.threshold
        verdict.passed = verdict.overall_score >= self.threshold

        logger.info(
            f"Quality verdict: overall={verdict.overall_score} "
            f"passed={verdict.passed} platform={platform}"
        )
        return verdict

    def check_and_gate(
        self,
        title: str,
        description: str = "",
        script: str = "",
        tags: list = None,
        platform: str = "youtube",
    ) -> "tuple[bool, QualityVerdict | None]":
        """Evaluate content and return whether publishing should proceed.

        Args:
            title, description, script, tags, platform: Same as evaluate().

        Returns:
            (should_proceed, verdict)
            - mode="off":   (True, None)
            - mode="warn":  (True, verdict) — logs warning if score < threshold
            - mode="block": (False, verdict) if score < threshold, else (True, verdict)
        """
        if self.mode == "off":
            return True, None

        verdict = self.evaluate(
            title=title,
            description=description,
            script=script,
            tags=tags,
            platform=platform,
        )

        if self.mode == "warn":
            if not verdict.passed:
                logger.warning(
                    f"Content quality below threshold "
                    f"(score={verdict.overall_score}, threshold={self.threshold}). "
                    f"Proceeding anyway (mode=warn)."
                )
            return True, verdict

        # mode == "block"
        if not verdict.passed:
            logger.warning(
                f"Content quality gate BLOCKED publish: "
                f"score={verdict.overall_score} < threshold={self.threshold}"
            )
            return False, verdict

        return True, verdict

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        title: str,
        description: str,
        script: str,
        tags: list,
        platform: str,
    ) -> str:
        """Build a platform-specific LLM quality evaluation prompt."""
        weights = _PLATFORM_WEIGHTS.get(platform, _PLATFORM_WEIGHTS["youtube"])
        tags_str = ", ".join(str(t) for t in tags) if tags else "none"
        desc_preview = description[:500] if description else ""
        script_preview = script[:1000] if script else ""

        lines = [
            f"You are a content quality evaluator for {platform} in 2026.",
            "YouTube and other platforms now enforce strict AI content policies requiring",
            "original research, genuine effort, and substantive insight — not generic",
            "AI-generated filler content.",
            "",
            f"Evaluate this {platform} content for quality compliance:",
            "",
            f"Title: {title}",
            f"Description: {desc_preview}",
            f"Script excerpt: {script_preview}",
            f"Tags: {tags_str}",
            "",
            "Score each dimension from 0-100:",
            f"- originality: Does content provide unique insight vs generic AI output? "
            f"(weight: {weights['originality']:.0%})",
            f"- effort_level: Evidence of research, editing, custom visuals? "
            f"(weight: {weights['effort_level']:.0%})",
            f"- insight_depth: Substantive analysis vs surface-level coverage? "
            f"(weight: {weights['insight_depth']:.0%})",
            f"- production_quality: Audio/visual quality, pacing, engagement hooks? "
            f"(weight: {weights['production_quality']:.0%})",
            f"- policy_compliance: Meets {platform} 2026 AI content policy? "
            f"(weight: {weights['policy_compliance']:.0%})",
            "",
            "Respond ONLY with valid JSON in this exact format:",
            (
                '{"originality": <0-100>, "originality_feedback": "<text>", '
                '"effort_level": <0-100>, "effort_level_feedback": "<text>", '
                '"insight_depth": <0-100>, "insight_depth_feedback": "<text>", '
                '"production_quality": <0-100>, "production_quality_feedback": "<text>", '
                '"policy_compliance": <0-100>, "policy_compliance_feedback": "<text>", '
                '"suggestions": ["suggestion1", "suggestion2", "suggestion3"]}'
            ),
        ]
        return "\n".join(lines)

    def _parse_response(self, response: str) -> "QualityVerdict":
        """Parse LLM response into a QualityVerdict.

        Handles: raw JSON, markdown ```json blocks, and malformed responses.
        Returns an error verdict if the response cannot be parsed.
        """
        if not response:
            return self._error_verdict("LLM returned an empty response")

        text = response.strip()

        # Strip markdown code block wrappers
        md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if md_match:
            text = md_match.group(1).strip()

        # Try to extract JSON object from the text
        try:
            json_match = re.search(r"\{[\s\S]*\}", text)
            if not json_match:
                return self._error_verdict(
                    f"No JSON object found in LLM response: {response[:100]!r}"
                )
            data = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError) as exc:
            return self._error_verdict(
                f"Failed to parse LLM response as JSON: {exc}"
            )

        # Build dimension list
        dimensions: list[QualityDimension] = []
        for dim in _DIMENSIONS:
            raw_score = data.get(dim, 50)
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = 50.0
            score = max(0.0, min(100.0, score))
            feedback = str(data.get(f"{dim}_feedback", ""))
            dimensions.append(QualityDimension(name=dim, score=score, feedback=feedback))

        # Suggestions
        raw_suggestions = data.get("suggestions", [])
        if isinstance(raw_suggestions, str):
            suggestions = [raw_suggestions]
        elif isinstance(raw_suggestions, list):
            suggestions = [str(s)[:200] for s in raw_suggestions[:10]]
        else:
            suggestions = []

        # Weighted overall (use youtube defaults; will be overwritten by platform in evaluate())
        overall = self._compute_overall(dimensions, "youtube")

        return QualityVerdict(
            overall_score=overall,
            dimensions=dimensions,
            passed=False,           # overwritten in evaluate()
            threshold=self.threshold,
            suggestions=suggestions,
            platform="youtube",     # overwritten in evaluate()
            error="",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_overall(
        self, dimensions: list, platform: str
    ) -> float:
        """Return weighted average score for the given platform."""
        weights = _PLATFORM_WEIGHTS.get(platform, _PLATFORM_WEIGHTS["youtube"])
        dim_map = {d.name: d.score for d in dimensions}
        total = sum(
            dim_map.get(dim, 50.0) * weights[dim] for dim in _DIMENSIONS
        )
        return round(max(0.0, min(100.0, total)), 1)

    def _error_verdict(self, message: str) -> "QualityVerdict":
        """Return a QualityVerdict that represents a parse/evaluation failure."""
        logger.error(f"Quality gate evaluation error: {message}")
        dimensions = [
            QualityDimension(name=dim, score=0.0, feedback="") for dim in _DIMENSIONS
        ]
        return QualityVerdict(
            overall_score=0.0,
            dimensions=dimensions,
            passed=False,
            threshold=self.threshold,
            suggestions=[],
            platform="youtube",
            error=message,
        )

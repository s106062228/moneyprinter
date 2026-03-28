"""
Virality Scorer for MoneyPrinter.

Scores video metadata (title, description, tags, hashtags) for virality
potential across YouTube, TikTok, Twitter, and Instagram using an LLM
to evaluate hook strength, emotional appeal, clarity, trending relevance,
and platform fit.

Usage:
    scorer = ViralityScorer(platform="youtube")
    result = scorer.score(
        title="10 AI Tools That Will Replace Your Job",
        description="In this video...",
        tags=["ai", "automation"],
        hashtags=["#AItools", "#futureofwork"],
    )
    print(result.overall_score)   # e.g. 74.5
    print(result.breakdown)       # per-category scores
    print(result.suggestions)     # improvement tips
"""

import json
import re
from dataclasses import dataclass, asdict, fields
from datetime import datetime, timezone

from mp_logger import get_logger
from llm_provider import generate_text

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUPPORTED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})

_PLATFORM_WEIGHTS = {
    "youtube": {
        "hook_strength": 0.30,
        "emotional_appeal": 0.20,
        "clarity": 0.20,
        "trending_relevance": 0.15,
        "platform_fit": 0.15,
    },
    "tiktok": {
        "hook_strength": 0.35,
        "emotional_appeal": 0.25,
        "clarity": 0.15,
        "trending_relevance": 0.15,
        "platform_fit": 0.10,
    },
    "twitter": {
        "hook_strength": 0.25,
        "emotional_appeal": 0.20,
        "clarity": 0.30,
        "trending_relevance": 0.15,
        "platform_fit": 0.10,
    },
    "instagram": {
        "hook_strength": 0.30,
        "emotional_appeal": 0.25,
        "clarity": 0.15,
        "trending_relevance": 0.15,
        "platform_fit": 0.15,
    },
}

_MAX_TITLE_LEN = 500
_MAX_DESCRIPTION_LEN = 5000
_MAX_TAGS = 50
_SCORE_MIN = 0
_SCORE_MAX = 100
_BREAKDOWN_CATEGORIES = (
    "hook_strength",
    "emotional_appeal",
    "clarity",
    "trending_relevance",
    "platform_fit",
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ViralityScore:
    """Virality scoring result for a piece of content."""

    overall_score: float       # 0-100 weighted composite
    breakdown: dict            # {hook_strength, emotional_appeal, clarity, trending_relevance, platform_fit} 0-100 each
    suggestions: list          # improvement suggestions (up to 5)
    platform: str              # scored platform
    scored_at: str             # ISO8601 timestamp (UTC)

    def to_dict(self) -> dict:
        """Serialize to plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ViralityScore":
        """Deserialize from dictionary, ignoring unknown keys."""
        allowed = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class ViralityScorer:
    """Score video metadata for virality potential using an LLM."""

    def __init__(self, platform: str = "youtube"):
        if platform not in _SUPPORTED_PLATFORMS:
            raise ValueError(
                f"Unsupported platform: {platform}. "
                f"Must be one of: {sorted(_SUPPORTED_PLATFORMS)}"
            )
        self.platform = platform
        self._weights = _PLATFORM_WEIGHTS[platform]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        title: str,
        description: str = "",
        tags: list = None,
        hashtags: list = None,
    ) -> ViralityScore:
        """Score video metadata for virality potential.

        Args:
            title:       Content title / hook text. Required.
            description: Full description or script excerpt. Optional.
            tags:        List of keyword tags (YouTube-style). Optional.
            hashtags:    List of hashtags (with or without '#'). Optional.

        Returns:
            ViralityScore with overall_score, per-category breakdown,
            improvement suggestions, platform, and timestamp.

        Raises:
            ValueError: If title is empty or blank.
        """
        if not title or not title.strip():
            raise ValueError("Title is required")

        # Truncate inputs to safe bounds
        title = title[:_MAX_TITLE_LEN]
        description = (description or "")[:_MAX_DESCRIPTION_LEN]
        tags = (tags or [])[:_MAX_TAGS]
        hashtags = (hashtags or [])[:_MAX_TAGS]

        logger.info(
            f"Scoring virality for platform={self.platform!r}, "
            f"title={title[:60]!r}"
        )

        prompt = self._build_prompt(title, description, tags, hashtags)

        response = generate_text(prompt)

        result = self._parse_response(response)
        logger.info(
            f"Virality score: overall={result.overall_score} "
            f"platform={self.platform}"
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        title: str,
        description: str,
        tags: list,
        hashtags: list,
    ) -> str:
        """Build a platform-specific LLM scoring prompt."""
        tags_str = ", ".join(str(t) for t in tags) if tags else "none"
        hashtags_str = ", ".join(str(h) for h in hashtags) if hashtags else "none"
        desc_preview = description[:500] if description else ""

        lines = [
            f"Score this {self.platform} video content for virality potential "
            f"(0-100 for each category).",
            "",
            f"Title: {title}",
            f"Description: {desc_preview}",
            f"Tags: {tags_str}",
            f"Hashtags: {hashtags_str}",
            "",
            "Rate each category from 0-100:",
            f"- hook_strength: How attention-grabbing is the title/hook? "
            f"(weight: {self._weights['hook_strength']:.0%})",
            f"- emotional_appeal: Does it trigger emotional response? "
            f"(weight: {self._weights['emotional_appeal']:.0%})",
            f"- clarity: Is the message clear and concise? "
            f"(weight: {self._weights['clarity']:.0%})",
            f"- trending_relevance: Does it align with current trends? "
            f"(weight: {self._weights['trending_relevance']:.0%})",
            f"- platform_fit: Is it optimized for {self.platform}? "
            f"(weight: {self._weights['platform_fit']:.0%})",
            "",
            "Respond in JSON format:",
            (
                '{"hook_strength": <0-100>, "emotional_appeal": <0-100>, '
                '"clarity": <0-100>, "trending_relevance": <0-100>, '
                '"platform_fit": <0-100>, '
                '"suggestions": ["suggestion1", "suggestion2", "suggestion3"]}'
            ),
        ]
        return "\n".join(lines)

    def _parse_response(self, text: str) -> ViralityScore:
        """Parse LLM response text into a ViralityScore.

        Tries JSON extraction first; falls back to per-category regex;
        defaults any missing category to 50.
        """
        breakdown: dict = {}
        suggestions: list = []

        # --- Attempt 1: JSON parse ----------------------------------------
        try:
            # Accept JSON that may be embedded in surrounding prose.
            # Use DOTALL so nested newlines inside the JSON are matched.
            json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for cat in _BREAKDOWN_CATEGORIES:
                    val = data.get(cat, 50)
                    breakdown[cat] = float(
                        max(_SCORE_MIN, min(_SCORE_MAX, float(val)))
                    )
                raw_suggestions = data.get("suggestions", [])
                if isinstance(raw_suggestions, str):
                    suggestions = [raw_suggestions]
                elif isinstance(raw_suggestions, list):
                    suggestions = list(raw_suggestions)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug(f"JSON parse failed, falling back to regex: {exc}")
            breakdown = {}

        # --- Attempt 2: regex fallback ------------------------------------
        if not breakdown:
            for cat in _BREAKDOWN_CATEGORIES:
                pattern = rf'{cat}["\s:]*(\d+)'
                match = re.search(pattern, text, re.IGNORECASE)
                raw = float(match.group(1)) if match else 50.0
                breakdown[cat] = float(max(_SCORE_MIN, min(_SCORE_MAX, raw)))

        # --- Ensure all categories present --------------------------------
        for cat in _BREAKDOWN_CATEGORIES:
            if cat not in breakdown:
                breakdown[cat] = 50.0

        # --- Sanitise suggestions -----------------------------------------
        suggestions = [str(s)[:200] for s in suggestions[:5]]

        # --- Weighted overall score ---------------------------------------
        overall = sum(
            breakdown[cat] * self._weights[cat] for cat in _BREAKDOWN_CATEGORIES
        )
        overall = round(float(max(_SCORE_MIN, min(_SCORE_MAX, overall))), 1)

        return ViralityScore(
            overall_score=overall,
            breakdown=breakdown,
            suggestions=suggestions,
            platform=self.platform,
            scored_at=datetime.now(timezone.utc).isoformat(),
        )

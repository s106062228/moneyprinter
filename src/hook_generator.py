"""
AI Hook Generator for MoneyPrinter.

Generates engaging opening lines (hooks) for video scripts using proven
templates and platform-specific constraints. Supports curiosity, controversy,
statistic, question, and listicle hook categories across YouTube, TikTok,
Instagram Reels, Twitter, and YouTube Shorts.

Usage:
    gen = HookGenerator(platform="youtube_shorts")
    result = gen.generate_hook("AI tools for creators")
    print(result.hook_text)          # e.g. "Most people don't know that AI tools..."
    print(result.hook_category)      # e.g. "curiosity"
    print(result.max_duration_seconds)  # 5.0

    results = gen.generate_hooks("productivity hacks", count=3)
    for r in results:
        print(r.hook_text)
"""

import json
import re
from dataclasses import dataclass, asdict, fields
from datetime import datetime, timezone

from mp_logger import get_logger

logger = get_logger(__name__)

# Module-level reference to LLM generate function.
# Imported here so tests can patch "hook_generator.generate_text".
try:
    from llm_provider import generate_text
except Exception:  # pragma: no cover
    generate_text = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUPPORTED_PLATFORMS = frozenset(
    {"youtube", "youtube_shorts", "tiktok", "instagram_reels", "twitter"}
)

_HOOK_CATEGORIES = (
    "curiosity",
    "controversy",
    "statistic",
    "question",
    "listicle",
)

# Platform constraints: max_duration_seconds, max_words, max_chars (Twitter only)
_PLATFORM_CONSTRAINTS = {
    "youtube_shorts": {"max_duration": 5.0, "max_words": 15, "max_chars": None},
    "tiktok":         {"max_duration": 2.0, "max_words": 8,  "max_chars": None},
    "instagram_reels":{"max_duration": 3.0, "max_words": 10, "max_chars": None},
    "twitter":        {"max_duration": None, "max_words": None, "max_chars": 50},
    "youtube":        {"max_duration": 5.0, "max_words": 15, "max_chars": None},
}

# Fallback hook templates — {topic} is substituted at runtime
_HOOK_TEMPLATES = {
    "curiosity":    "Most people don't know that {topic} can change everything.",
    "controversy":  "Stop ignoring {topic} immediately.",
    "statistic":    "97% of people fail at {topic}.",
    "question":     "What if I told you {topic} was the key?",
    "listicle":     "3 things that will change how you think about {topic}.",
}

_MAX_TOPIC_LEN = 300


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class HookResult:
    """Result of a single hook generation."""

    hook_text: str
    hook_category: str
    platform: str
    max_duration_seconds: float   # None stored as -1.0 internally; exposed as float
    estimated_word_count: int

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HookResult":
        """Deserialize from dictionary, ignoring unknown keys."""
        allowed = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class HookGenerator:
    """Generate AI-powered opening hooks for video scripts."""

    def __init__(self, platform: str = "youtube"):
        if platform not in _SUPPORTED_PLATFORMS:
            raise ValueError(
                f"Unsupported platform: {platform!r}. "
                f"Must be one of: {sorted(_SUPPORTED_PLATFORMS)}"
            )
        self.platform = platform
        self._constraints = _PLATFORM_CONSTRAINTS[platform]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_hook(self, topic: str, category: str = None) -> HookResult:
        """Generate a single hook for the given topic.

        Args:
            topic:    The subject of the video. Required, non-empty.
            category: One of the hook categories. If None, the LLM chooses
                      (or a random category is used in fallback).

        Returns:
            HookResult with hook_text, category, platform constraints, and
            estimated word count.

        Raises:
            ValueError: If topic is empty/blank or category is unrecognised.
        """
        topic = self._validate_topic(topic)

        # Normalise and validate category
        if category is not None:
            category = category.strip().lower()
            if category not in _HOOK_CATEGORIES:
                raise ValueError(
                    f"Unknown hook category: {category!r}. "
                    f"Must be one of: {list(_HOOK_CATEGORIES)}"
                )

        logger.info(
            f"Generating hook: platform={self.platform!r}, "
            f"category={category!r}, topic={topic[:60]!r}"
        )

        chosen_category = category or _HOOK_CATEGORIES[0]  # default for fallback

        if generate_text is None:
            logger.warning("LLM unavailable; using fallback hook.")
            return self.get_fallback_hook(topic, chosen_category)

        prompt = self._build_prompt(topic, category)

        try:
            raw = generate_text(prompt)
        except Exception as exc:
            logger.warning(f"LLM call failed ({exc}); using fallback hook.")
            return self.get_fallback_hook(topic, chosen_category)

        return self._parse_response(raw, topic, chosen_category)

    def generate_hooks(self, topic: str, count: int = 3) -> list:
        """Generate multiple hooks covering different categories.

        Args:
            topic: The subject of the video. Required, non-empty.
            count: Number of hooks to generate (1–len(_HOOK_CATEGORIES)).

        Returns:
            List of HookResult objects (up to *count* items).
        """
        topic = self._validate_topic(topic)
        count = max(1, min(count, len(_HOOK_CATEGORIES)))

        results = []
        for i in range(count):
            cat = _HOOK_CATEGORIES[i % len(_HOOK_CATEGORIES)]
            try:
                result = self.generate_hook(topic, category=cat)
            except Exception as exc:
                logger.warning(f"Hook generation failed for category={cat!r}: {exc}")
                result = self.get_fallback_hook(topic, cat)
            results.append(result)

        return results

    def get_fallback_hook(self, topic: str, category: str) -> HookResult:
        """Return a template-based hook without calling the LLM.

        Args:
            topic:    Subject text (already validated).
            category: Hook category key.

        Returns:
            HookResult built from the template for *category*.
        """
        # Normalise category; default to 'curiosity' if unknown
        cat = (category or "").strip().lower()
        if cat not in _HOOK_TEMPLATES:
            cat = "curiosity"

        template = _HOOK_TEMPLATES[cat]
        # Truncate topic so resulting hook stays within platform word limit
        topic_snippet = self._trim_topic_for_platform(topic)
        hook_text = template.format(topic=topic_snippet)

        return self._build_result(hook_text, cat)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_topic(self, topic: str) -> str:
        """Raise ValueError if topic is invalid; return stripped+truncated value."""
        if not topic or not str(topic).strip():
            raise ValueError("Topic must be a non-empty string.")
        return str(topic).strip()[:_MAX_TOPIC_LEN]

    def _trim_topic_for_platform(self, topic: str) -> str:
        """Shorten topic to a safe word count for the current platform."""
        max_words = self._constraints.get("max_words")
        if max_words is None:
            # Twitter: limit by chars
            max_chars = self._constraints.get("max_chars") or 50
            if len(topic) > max_chars // 2:
                topic = topic[: max_chars // 2]
            return topic

        words = topic.split()
        # Reserve ~half the word budget for the template text
        budget = max(1, max_words // 2)
        return " ".join(words[:budget])

    def _build_prompt(self, topic: str, category: str = None) -> str:
        """Construct the LLM prompt for hook generation."""
        constraints = self._constraints
        duration_note = (
            f"{constraints['max_duration']}s max" if constraints["max_duration"] else "no duration limit"
        )
        word_note = (
            f"{constraints['max_words']} words max" if constraints["max_words"] else "no word limit"
        )
        char_note = (
            f"{constraints['max_chars']} chars max" if constraints["max_chars"] else ""
        )
        limit_str = ", ".join(filter(None, [duration_note, word_note, char_note]))

        category_instruction = (
            f'Use the hook category: "{category}".'
            if category
            else "Choose the most effective hook category."
        )

        examples = "\n".join(
            f'  - {cat}: "{tmpl.format(topic="<topic>")}"'
            for cat, tmpl in _HOOK_TEMPLATES.items()
        )

        lines = [
            f"You are an expert video hook writer for {self.platform}.",
            "",
            f"Topic: {topic}",
            f"Platform constraints: {limit_str}",
            category_instruction,
            "",
            "Hook categories and examples:",
            examples,
            "",
            "Write ONE engaging hook that grabs attention in the first second.",
            "Keep it within the platform word/character limit.",
            "",
            "Respond in JSON format exactly:",
            '{"hook": "<hook text>", "category": "<category name>"}',
        ]
        return "\n".join(lines)

    def _parse_response(self, raw: str, topic: str, default_category: str) -> HookResult:
        """Parse LLM response; fall back to regex then template on failure."""
        hook_text = None
        category = default_category

        # --- Attempt 1: JSON parse ----------------------------------------
        try:
            json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                hook_text = data.get("hook", "").strip() or None
                cat_raw = str(data.get("category", "")).strip().lower()
                if cat_raw in _HOOK_CATEGORIES:
                    category = cat_raw
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug(f"JSON parse failed, falling back to regex: {exc}")

        # --- Attempt 2: regex fallback ------------------------------------
        if not hook_text:
            match = re.search(r'"hook"\s*:\s*"([^"]+)"', raw)
            if match:
                hook_text = match.group(1).strip()

        # --- Attempt 3: template fallback ---------------------------------
        if not hook_text:
            logger.debug("LLM response unparsable; using template fallback.")
            return self.get_fallback_hook(topic, category)

        return self._build_result(hook_text, category)

    def _build_result(self, hook_text: str, category: str) -> HookResult:
        """Construct a HookResult, enforcing platform constraints on the text."""
        hook_text = self._enforce_limits(hook_text)
        word_count = len(hook_text.split())
        duration = self._constraints["max_duration"]

        return HookResult(
            hook_text=hook_text,
            hook_category=category,
            platform=self.platform,
            max_duration_seconds=float(duration) if duration is not None else 0.0,
            estimated_word_count=word_count,
        )

    def _enforce_limits(self, text: str) -> str:
        """Trim hook text to respect platform word / character limits."""
        max_words = self._constraints.get("max_words")
        max_chars = self._constraints.get("max_chars")

        if max_words:
            words = text.split()
            if len(words) > max_words:
                text = " ".join(words[:max_words])

        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0]

        return text

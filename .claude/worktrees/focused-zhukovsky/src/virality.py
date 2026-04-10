"""
Virality scoring module for MoneyPrinter.

Analyzes generated content (scripts, titles, descriptions) and scores
engagement potential based on 2026 short-form video best practices:
- Hook effectiveness (first 3 seconds / ~30 words)
- Optimal length scoring (15-20 second sweet spot)
- Emotional trigger density
- Power word frequency
- Call-to-action quality
- Title effectiveness

Usage:
    from virality import score_content, ViralityScore

    result = score_content(
        script="Stop scrolling! Did you know 3 proven secrets can double your income?...",
        title="3 Secret Income Hacks Nobody Talks About",
    )
    print(result.overall)      # e.g. 74.5
    print(result.grade)        # e.g. "B"
    print(result.suggestions)  # list of improvement tips
"""

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Score thresholds
# ---------------------------------------------------------------------------

SCORE_EXCELLENT = 80
SCORE_GOOD = 60
SCORE_FAIR = 40

# Optimal short-form video word count for 15-20 second videos
_OPTIMAL_WORDS_MIN = 40
_OPTIMAL_WORDS_MAX = 80

# Power words proven to drive engagement and click-through
_POWER_WORDS = frozenset({
    "secret", "revealed", "shocking", "amazing", "incredible", "insane",
    "unbelievable", "exclusive", "limited", "proven", "guaranteed", "instant",
    "free", "hack", "trick", "simple", "easy", "fast", "quick", "now",
    "today", "new", "discover", "learn", "master", "transform", "change",
    "boost", "grow", "stop", "start", "never", "always", "everyone",
    "nobody", "mistake", "truth", "lies", "warning", "attention",
    "watch", "listen", "important", "urgent", "breaking", "best", "worst",
    "only", "must", "need", "want", "huge", "massive", "powerful",
})

# Emotional trigger word categories
_EMOTIONAL_TRIGGERS = {
    "curiosity": frozenset({
        "why", "how", "what", "mystery", "unknown", "discover", "wonder",
        "secret", "hidden", "revealed", "truth", "actually",
    }),
    "fear": frozenset({
        "lose", "fail", "wrong", "mistake", "avoid", "danger", "risk",
        "regret", "warning", "never", "stop", "before", "too late",
    }),
    "aspiration": frozenset({
        "success", "wealth", "rich", "freedom", "dream", "goal", "achieve",
        "earn", "grow", "level", "build", "create", "win",
    }),
    "social_proof": frozenset({
        "everyone", "millions", "popular", "trending", "viral", "proven",
        "people", "most", "best", "top",
    }),
}

# Strong opening verbs that hook immediately
_STRONG_OPENERS = frozenset({
    "stop", "wait", "watch", "listen", "look", "imagine", "picture",
    "think", "consider", "warning", "attention",
})

# Effective CTA phrases
_CTA_PHRASES = [
    "follow", "subscribe", "like", "share", "comment", "save",
    "click", "tap", "swipe", "check out", "link in bio", "dm me",
    "tag", "tell me", "let me know", "hit the",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ViralityScore:
    """Virality score breakdown for a piece of content."""

    overall: float
    hook_score: float = 0.0
    length_score: float = 0.0
    emotion_score: float = 0.0
    power_word_score: float = 0.0
    cta_score: float = 0.0
    title_score: float = 0.0
    suggestions: list = field(default_factory=list)

    @property
    def grade(self) -> str:
        """Letter grade: A / B / C / D."""
        if self.overall >= SCORE_EXCELLENT:
            return "A"
        elif self.overall >= SCORE_GOOD:
            return "B"
        elif self.overall >= SCORE_FAIR:
            return "C"
        return "D"

    @property
    def label(self) -> str:
        """Human-readable quality label."""
        if self.overall >= SCORE_EXCELLENT:
            return "High Virality"
        elif self.overall >= SCORE_GOOD:
            return "Good Engagement"
        elif self.overall >= SCORE_FAIR:
            return "Average"
        return "Low Engagement"


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------

def _score_hook(text: str) -> tuple:
    """Score hook effectiveness of the opening ~30 words (0-100)."""
    suggestions = []
    score = 0.0

    words = text.split()
    if not words:
        return 0.0, ["Script is empty."]

    hook_text = " ".join(words[:30]).lower()
    hook_words = set(re.findall(r"\b\w+\b", hook_text))

    # Question hook: +30 points
    question_starters = {
        "what", "why", "how", "did", "have", "do", "can", "are", "would",
        "will", "is", "should", "could",
    }
    has_question = "?" in hook_text or bool(
        question_starters & {hook_words.pop() for _ in range(min(3, len(hook_words)))}
        if hook_words else set()
    )
    # Re-compute — avoid mutating hook_words
    hook_words_fresh = set(re.findall(r"\b\w+\b", hook_text))
    first_words = set(words[:3]) if len(words) >= 3 else set(words)
    first_words_lower = {w.lower().rstrip(".,!?") for w in first_words}
    has_question = "?" in hook_text or bool(question_starters & first_words_lower)

    if has_question:
        score += 30
    else:
        suggestions.append("Start with a question to hook viewers in the first 3 seconds.")

    # Number/statistic in opening: +25 points
    if re.search(r"\b\d+\b", hook_text):
        score += 25
    else:
        suggestions.append("Add a number or statistic to your opening line for credibility.")

    # Power word in opening: +25 points
    if hook_words_fresh & _POWER_WORDS:
        score += 25

    # Strong imperative opener: +20 points
    first_word = words[0].lower().rstrip(".,!?") if words else ""
    if first_word in _STRONG_OPENERS:
        score += 20
    else:
        if score < 60:
            suggestions.append(
                "Open with a strong imperative verb (Stop, Watch, Imagine) to grab attention."
            )

    return min(score, 100.0), suggestions


def _score_length(text: str) -> tuple:
    """Score content length against the 15-20 second optimal window (0-100)."""
    suggestions = []
    word_count = len(text.split())

    if _OPTIMAL_WORDS_MIN <= word_count <= _OPTIMAL_WORDS_MAX:
        return 100.0, suggestions

    if word_count < _OPTIMAL_WORDS_MIN:
        score = max(0.0, (word_count / _OPTIMAL_WORDS_MIN) * 100)
        suggestions.append(
            f"Script is short ({word_count} words). "
            f"Target {_OPTIMAL_WORDS_MIN}-{_OPTIMAL_WORDS_MAX} words for a 15-20s video."
        )
    else:
        excess = word_count - _OPTIMAL_WORDS_MAX
        score = max(0.0, 100.0 - (excess * 2.0))
        suggestions.append(
            f"Script is long ({word_count} words). "
            f"Trim to under {_OPTIMAL_WORDS_MAX} words — completion rate drops sharply after 20s."
        )

    return score, suggestions


def _score_emotion(text: str) -> tuple:
    """Score emotional trigger density across four categories (0-100)."""
    suggestions = []
    words = set(re.findall(r"\b\w+\b", text.lower()))

    found_categories = {
        cat for cat, triggers in _EMOTIONAL_TRIGGERS.items() if words & triggers
    }

    score = min(len(found_categories) * 25.0, 100.0)

    if not found_categories:
        suggestions.append(
            "Add emotional triggers: curiosity ('why', 'secret'), "
            "aspiration ('achieve', 'grow'), or fear-of-missing-out."
        )
    elif len(found_categories) < 2:
        suggestions.append(
            "Layer 2+ emotional triggers for stronger impact "
            "(e.g., curiosity + aspiration)."
        )

    return score, suggestions


def _score_power_words(text: str) -> tuple:
    """Score power word density (optimal 3-8% of script, 0-100)."""
    suggestions = []
    words = re.findall(r"\b\w+\b", text.lower())

    if not words:
        return 0.0, ["Script is empty."]

    found_count = sum(1 for w in words if w in _POWER_WORDS)
    density = found_count / len(words)

    if 0.03 <= density <= 0.10:
        score = 100.0
    elif density < 0.03:
        score = (density / 0.03) * 100.0
        if found_count == 0:
            suggestions.append(
                "Add power words such as 'secret', 'instant', 'proven' to boost urgency."
            )
    else:
        # Over-saturated — feels spammy
        score = max(0.0, 100.0 - (density - 0.10) * 500.0)
        suggestions.append(
            "Too many power words can feel spammy. Keep power word density at 3-8%."
        )

    return score, suggestions


def _score_cta(text: str) -> tuple:
    """Score call-to-action quality (0-100)."""
    suggestions = []
    text_lower = text.lower()

    found_ctas = [cta for cta in _CTA_PHRASES if cta in text_lower]

    if len(found_ctas) >= 2:
        score = 100.0
    elif len(found_ctas) == 1:
        score = 60.0
        suggestions.append(
            "Add a second CTA (e.g., 'like AND save this') for stronger engagement signals."
        )
    else:
        score = 0.0
        suggestions.append(
            "Add a clear CTA: 'Follow for more', 'Save this video', "
            "or 'Share with someone who needs this'."
        )

    return score, suggestions


def _score_title(title: str) -> tuple:
    """Score title effectiveness (0-100)."""
    suggestions = []
    score = 0.0
    title_lower = title.lower()
    length = len(title)

    # Optimal length: 40-70 chars (+40)
    if 40 <= length <= 70:
        score += 40
    elif 20 <= length < 40 or 70 < length <= 100:
        score += 20
        if length < 40:
            suggestions.append("Title is short — aim for 40-70 characters for better SEO visibility.")
        else:
            suggestions.append("Title is long — trim to 70 characters to avoid truncation in feeds.")
    else:
        if length > 0:
            suggestions.append("Title length is not optimal. Target 40-70 characters.")

    # Contains a number (+20)
    if re.search(r"\b\d+\b", title):
        score += 20
    else:
        suggestions.append("Add a number to the title (e.g. '5 Ways', '3 Mistakes') for higher CTR.")

    # Contains a power word (+20)
    title_words = set(re.findall(r"\b\w+\b", title_lower))
    if title_words & _POWER_WORDS:
        score += 20

    # Contains a question (+20)
    if "?" in title:
        score += 20

    return min(score, 100.0), suggestions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_content(
    script: str,
    title: str = "",
    description: str = "",  # reserved for future description analysis
) -> ViralityScore:
    """
    Analyze content and return a ViralityScore.

    Args:
        script: The video script text to analyze.
        title: The video title (optional but recommended).
        description: The video description (reserved for future use).

    Returns:
        ViralityScore with an overall 0-100 score, per-component scores,
        a letter grade, a quality label, and a list of improvement suggestions.
    """
    all_suggestions: list = []

    hook_score, hook_sugg = _score_hook(script)
    length_score, length_sugg = _score_length(script)
    emotion_score, emotion_sugg = _score_emotion(script)
    power_score, power_sugg = _score_power_words(script)
    cta_score, cta_sugg = _score_cta(script)

    if title:
        title_score, title_sugg = _score_title(title)
    else:
        title_score = 50.0
        title_sugg = ["Provide a title to unlock title-specific scoring."]

    for sugg_list in (hook_sugg, length_sugg, emotion_sugg, power_sugg, cta_sugg, title_sugg):
        all_suggestions.extend(sugg_list)

    # Weighted composite: hook is most important (2026 research: first 3s critical)
    overall = (
        hook_score * 0.30
        + length_score * 0.15
        + emotion_score * 0.20
        + power_score * 0.15
        + cta_score * 0.10
        + title_score * 0.10
    )

    return ViralityScore(
        overall=round(overall, 1),
        hook_score=round(hook_score, 1),
        length_score=round(length_score, 1),
        emotion_score=round(emotion_score, 1),
        power_word_score=round(power_score, 1),
        cta_score=round(cta_score, 1),
        title_score=round(title_score, 1),
        suggestions=all_suggestions,
    )

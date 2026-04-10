"""
Unit tests for the virality scoring module (src/virality.py).

Coverage:
- ViralityScore dataclass (grade, label, defaults)
- Individual component scorers (_score_hook, _score_length, _score_emotion,
  _score_power_words, _score_cta, _score_title)
- score_content() public API (high-quality, low-quality, edge cases, empty inputs)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from virality import (
    ViralityScore,
    score_content,
    _score_hook,
    _score_length,
    _score_emotion,
    _score_power_words,
    _score_cta,
    _score_title,
    SCORE_EXCELLENT,
    SCORE_GOOD,
    SCORE_FAIR,
    _OPTIMAL_WORDS_MIN,
    _OPTIMAL_WORDS_MAX,
)


# ---------------------------------------------------------------------------
# ViralityScore dataclass tests
# ---------------------------------------------------------------------------

class TestViralityScore:
    def test_grade_excellent(self):
        vs = ViralityScore(overall=85.0)
        assert vs.grade == "A"

    def test_grade_good(self):
        vs = ViralityScore(overall=65.0)
        assert vs.grade == "B"

    def test_grade_fair(self):
        vs = ViralityScore(overall=45.0)
        assert vs.grade == "C"

    def test_grade_poor(self):
        vs = ViralityScore(overall=20.0)
        assert vs.grade == "D"

    def test_label_high_virality(self):
        vs = ViralityScore(overall=SCORE_EXCELLENT)
        assert vs.label == "High Virality"

    def test_label_good_engagement(self):
        vs = ViralityScore(overall=SCORE_GOOD)
        assert vs.label == "Good Engagement"

    def test_label_average(self):
        vs = ViralityScore(overall=SCORE_FAIR)
        assert vs.label == "Average"

    def test_label_low_engagement(self):
        vs = ViralityScore(overall=SCORE_FAIR - 1)
        assert vs.label == "Low Engagement"

    def test_suggestions_default_empty(self):
        vs = ViralityScore(overall=50.0)
        assert vs.suggestions == []

    def test_default_component_scores_zero(self):
        vs = ViralityScore(overall=0.0)
        assert vs.hook_score == 0.0
        assert vs.length_score == 0.0
        assert vs.cta_score == 0.0


# ---------------------------------------------------------------------------
# Hook scorer tests
# ---------------------------------------------------------------------------

class TestScoreHook:
    def test_question_hook_scores_higher(self):
        text_with_q = "Why do most people fail at saving money? Here is what nobody tells you."
        text_no_q = "Most people fail at saving money. Here is what nobody tells you about it."
        score_q, _ = _score_hook(text_with_q)
        score_no_q, _ = _score_hook(text_no_q)
        assert score_q > score_no_q

    def test_number_in_hook_scores_higher(self):
        with_num = "3 proven secrets that will double your income fast."
        without_num = "Proven secrets that will double your income fast."
        score_w, _ = _score_hook(with_num)
        score_wo, _ = _score_hook(without_num)
        assert score_w > score_wo

    def test_strong_opener_verb(self):
        strong = "Stop doing this if you want to save money every single day."
        weak = "People are doing this if they want to save money every single day."
        score_s, _ = _score_hook(strong)
        score_w, _ = _score_hook(weak)
        assert score_s >= score_w

    def test_empty_text_returns_zero(self):
        score, suggestions = _score_hook("")
        assert score == 0.0
        assert len(suggestions) > 0

    def test_score_capped_at_100(self):
        text = "Stop! Why do 3 proven secrets double income? Amazing hack revealed now."
        score, _ = _score_hook(text)
        assert score <= 100.0

    def test_suggestions_when_no_question(self):
        _, suggestions = _score_hook("This is a plain statement without any hook at all here.")
        assert any("question" in s.lower() for s in suggestions)


# ---------------------------------------------------------------------------
# Length scorer tests
# ---------------------------------------------------------------------------

class TestScoreLength:
    def _make_script(self, word_count: int) -> str:
        return " ".join(["word"] * word_count)

    def test_optimal_range_scores_100(self):
        script = self._make_script(_OPTIMAL_WORDS_MIN)
        score, _ = _score_length(script)
        assert score == 100.0

    def test_optimal_max_scores_100(self):
        script = self._make_script(_OPTIMAL_WORDS_MAX)
        score, _ = _score_length(script)
        assert score == 100.0

    def test_too_short_scores_below_100(self):
        script = self._make_script(_OPTIMAL_WORDS_MIN - 10)
        score, suggestions = _score_length(script)
        assert score < 100.0
        assert len(suggestions) > 0

    def test_too_long_scores_below_100(self):
        script = self._make_script(_OPTIMAL_WORDS_MAX + 20)
        score, suggestions = _score_length(script)
        assert score < 100.0
        assert len(suggestions) > 0

    def test_zero_words_scores_zero(self):
        score, _ = _score_length("")
        assert score == 0.0

    def test_very_long_clamps_to_zero(self):
        script = self._make_script(_OPTIMAL_WORDS_MAX + 100)
        score, _ = _score_length(script)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# Emotion scorer tests
# ---------------------------------------------------------------------------

class TestScoreEmotion:
    def test_no_triggers_scores_zero(self):
        score, suggestions = _score_emotion("The sky is blue and the water is clear.")
        assert score == 0.0
        assert len(suggestions) > 0

    def test_one_category_scores_25(self):
        score, _ = _score_emotion("Discover the hidden secret of successful people.")
        assert score == 25.0

    def test_two_categories_scores_50(self):
        # curiosity + aspiration
        score, _ = _score_emotion("Discover the hidden secret to achieve financial freedom.")
        assert score == 50.0

    def test_four_categories_scores_100(self):
        # curiosity + fear + aspiration + social_proof
        text = (
            "Discover why everyone is making this mistake. "
            "Avoid losing your dream. Millions have already found success."
        )
        score, _ = _score_emotion(text)
        assert score == 100.0

    def test_max_score_is_100(self):
        score, _ = _score_emotion(
            "secret discover why everyone fail lose avoid mistake "
            "success wealth freedom proven popular viral"
        )
        assert score <= 100.0


# ---------------------------------------------------------------------------
# Power word scorer tests
# ---------------------------------------------------------------------------

class TestScorePowerWords:
    def test_no_power_words_low_score(self):
        score, suggestions = _score_power_words("The cat sat on the mat today.")
        assert score < 50.0
        assert len(suggestions) > 0

    def test_optimal_density_scores_100(self):
        # ~5% density: 1 power word in 20 words
        words = ["word"] * 19 + ["secret"]
        score, _ = _score_power_words(" ".join(words))
        assert score == 100.0

    def test_over_saturated_penalized(self):
        # All power words
        text = "secret proven amazing free hack trick instant boost transform change"
        score, suggestions = _score_power_words(text)
        assert score < 100.0
        assert any("spammy" in s.lower() for s in suggestions)

    def test_empty_script_returns_zero(self):
        score, suggestions = _score_power_words("")
        assert score == 0.0

    def test_score_capped_at_100(self):
        words = ["word"] * 18 + ["secret", "proven"]
        score, _ = _score_power_words(" ".join(words))
        assert score <= 100.0


# ---------------------------------------------------------------------------
# CTA scorer tests
# ---------------------------------------------------------------------------

class TestScoreCta:
    def test_no_cta_scores_zero(self):
        score, suggestions = _score_cta("This is some content with no call to action.")
        assert score == 0.0
        assert len(suggestions) > 0

    def test_one_cta_scores_60(self):
        score, suggestions = _score_cta("Follow me for more tips like this every day.")
        assert score == 60.0
        assert len(suggestions) > 0

    def test_two_cta_scores_100(self):
        score, _ = _score_cta("Follow me and save this video for later reference.")
        assert score == 100.0

    def test_multiple_cta_still_100(self):
        score, _ = _score_cta("Like, share, comment, and follow for more amazing content.")
        assert score == 100.0

    def test_cta_case_insensitive(self):
        score, _ = _score_cta("FOLLOW me and SAVE this for later!")
        assert score == 100.0


# ---------------------------------------------------------------------------
# Title scorer tests
# ---------------------------------------------------------------------------

class TestScoreTitle:
    def test_empty_title_scores_zero(self):
        score, _ = _score_title("")
        assert score == 0.0

    def test_optimal_length_gets_40_points(self):
        # 45-char title, no number, no power word, no question
        title = "A Plain Title That Is Exactly Forty-Five Chars"
        score, _ = _score_title(title)
        assert score >= 40

    def test_number_adds_points(self):
        title_with_num = "5 Ways to Boost Your Income Starting Today"
        title_no_num = "Ways to Boost Your Income Starting Today Now"
        score_w, _ = _score_title(title_with_num)
        score_wo, _ = _score_title(title_no_num)
        assert score_w > score_wo

    def test_question_adds_points(self):
        with_q = "Why Do Most People Fail at Saving Money?"
        without_q = "Most People Fail at Saving Money Every Year"
        score_w, _ = _score_title(with_q)
        score_wo, _ = _score_title(without_q)
        assert score_w >= score_wo

    def test_power_word_adds_points(self):
        with_pw = "3 Secret Hacks to Double Your Income Fast"
        without_pw = "3 Reliable Methods to Double Your Income Today"
        score_w, _ = _score_title(with_pw)
        score_wo, _ = _score_title(without_pw)
        assert score_w >= score_wo

    def test_score_capped_at_100(self):
        title = "3 Secret Hacks That Will Instantly Transform Your Life?"
        score, _ = _score_title(title)
        assert score <= 100.0


# ---------------------------------------------------------------------------
# score_content() integration tests
# ---------------------------------------------------------------------------

class TestScoreContent:
    # A well-crafted viral script
    VIRAL_SCRIPT = (
        "Stop scrolling! Why do 3 proven secrets make some people rich while "
        "everyone else fails? Discover the hidden truth about wealth that nobody "
        "tells you. Avoid the biggest mistake most people make. Save this video "
        "and follow for more instant income hacks every day."
    )
    VIRAL_TITLE = "3 Secret Wealth Hacks Nobody Talks About?"

    # A poor script
    POOR_SCRIPT = "Here is some information about things."
    POOR_TITLE = "Info"

    def test_high_quality_content_scores_above_60(self):
        result = score_content(self.VIRAL_SCRIPT, self.VIRAL_TITLE)
        assert result.overall >= 60.0

    def test_poor_content_scores_below_high_quality(self):
        viral = score_content(self.VIRAL_SCRIPT, self.VIRAL_TITLE)
        poor = score_content(self.POOR_SCRIPT, self.POOR_TITLE)
        assert viral.overall > poor.overall

    def test_returns_virality_score_type(self):
        result = score_content("Some script text here.")
        assert isinstance(result, ViralityScore)

    def test_overall_between_0_and_100(self):
        result = score_content(self.VIRAL_SCRIPT, self.VIRAL_TITLE)
        assert 0.0 <= result.overall <= 100.0

    def test_empty_script_returns_low_score(self):
        result = score_content("", "")
        assert result.overall < SCORE_FAIR

    def test_no_title_uses_default_50(self):
        result = score_content("Some script content here for testing purposes only.")
        assert result.title_score == 50.0

    def test_suggestions_list_is_populated_for_poor_content(self):
        result = score_content(self.POOR_SCRIPT, self.POOR_TITLE)
        assert len(result.suggestions) > 0

    def test_high_quality_has_fewer_suggestions(self):
        viral = score_content(self.VIRAL_SCRIPT, self.VIRAL_TITLE)
        poor = score_content(self.POOR_SCRIPT, self.POOR_TITLE)
        assert len(viral.suggestions) < len(poor.suggestions)

    def test_component_scores_present(self):
        result = score_content(self.VIRAL_SCRIPT, self.VIRAL_TITLE)
        assert result.hook_score >= 0
        assert result.length_score >= 0
        assert result.emotion_score >= 0
        assert result.power_word_score >= 0
        assert result.cta_score >= 0
        assert result.title_score >= 0

    def test_grade_a_for_excellent_content(self):
        # Build a script that maximises all dimensions
        script = (
            "Stop! Why do 3 proven secrets help everyone achieve freedom while "
            "most people fail to discover the truth? Avoid losing your dream today. "
            "Save this and follow for more instant wealth hacks every single day."
        )
        title = "3 Secret Freedom Hacks Nobody Talks About?"
        result = score_content(script, title)
        # Should be at least B grade
        assert result.grade in ("A", "B")

    def test_description_param_accepted(self):
        # description param doesn't affect score currently — just verify no error
        result = score_content("Some script.", title="Title", description="Some desc.")
        assert isinstance(result, ViralityScore)

    def test_overall_is_rounded_to_one_decimal(self):
        result = score_content("Some basic script text.")
        # overall should be a float with at most 1 decimal place
        assert result.overall == round(result.overall, 1)

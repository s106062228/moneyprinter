"""
Tests for src/animated_captions.py — Animated Captions Module.

Covers:
1. WordTiming, CaptionSegment, CaptionStyle dataclass creation and validation
2. CaptionStyle validation (invalid style_type, position, font_size bounds, etc.)
3. CaptionSegment to_dict/from_dict round-trip
4. AnimatedCaptions.transcribe with mocked faster-whisper
5. _build_segment_clips for each style_type (karaoke, pop_on, scroll)
6. _render_word_clip with mocked TextClip
7. apply() full pipeline with mocked video/audio/whisper/moviepy
8. apply_to_clip() with mocked clip and segments
9. from_srt() parsing — valid SRT, empty SRT, malformed SRT
10. Edge cases: empty segments, single word, very long text, missing audio
"""

import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock, call, mock_open

# ---------------------------------------------------------------------------
# Pre-patch heavy optional dependencies before importing the module under test
# ---------------------------------------------------------------------------

_mock_faster_whisper = MagicMock()
sys.modules.setdefault("faster_whisper", _mock_faster_whisper)

# Save any pre-existing moviepy mock so other test files' setdefault still works.
_prev_moviepy = sys.modules.get("moviepy")
_mock_moviepy = MagicMock()
sys.modules["moviepy"] = _mock_moviepy

# ---------------------------------------------------------------------------
# Now import the module under test
# ---------------------------------------------------------------------------

from animated_captions import (
    WordTiming,
    CaptionSegment,
    CaptionStyle,
    AnimatedCaptions,
    _clamp,
    _srt_time_to_seconds,
    _SRT_TIMECODE_RE,
    _VALID_STYLE_TYPES,
    _VALID_POSITIONS,
    _MAX_FONT_SIZE,
    _MIN_FONT_SIZE,
    _MAX_STROKE_WIDTH,
    _MIN_STROKE_WIDTH,
    _MAX_WORDS_PER_LINE,
    _MIN_WORDS_PER_LINE,
)

# Restore previous moviepy entry so other test files (e.g. test_export_optimizer)
# can install their own mock via setdefault.
if _prev_moviepy is not None:
    sys.modules["moviepy"] = _prev_moviepy
else:
    sys.modules.pop("moviepy", None)


# ===========================================================================
# Helper factories
# ===========================================================================

def make_word(word="hello", start=0.0, end=0.5):
    return WordTiming(word=word, start=start, end=end)


def make_segment(text="hello world", words=None, start=0.0, end=1.0):
    if words is None:
        words = [
            WordTiming("hello", 0.0, 0.5),
            WordTiming("world", 0.5, 1.0),
        ]
    return CaptionSegment(text=text, words=words, start_time=start, end_time=end)


# ===========================================================================
# 1. WordTiming tests
# ===========================================================================

class TestWordTiming:
    def test_creation_basic(self):
        wt = WordTiming(word="hello", start=0.0, end=0.5)
        assert wt.word == "hello"
        assert wt.start == 0.0
        assert wt.end == 0.5

    def test_creation_unicode(self):
        wt = WordTiming(word="你好", start=1.0, end=2.0)
        assert wt.word == "你好"

    def test_creation_empty_word(self):
        wt = WordTiming(word="", start=0.0, end=0.0)
        assert wt.word == ""

    def test_creation_negative_start(self):
        # No validation on WordTiming — just store values
        wt = WordTiming(word="test", start=-1.0, end=0.5)
        assert wt.start == -1.0

    def test_creation_fractional_times(self):
        wt = WordTiming(word="test", start=1.234, end=2.567)
        assert abs(wt.start - 1.234) < 1e-9
        assert abs(wt.end - 2.567) < 1e-9


# ===========================================================================
# 2. CaptionSegment tests
# ===========================================================================

class TestCaptionSegment:
    def test_creation_defaults(self):
        seg = CaptionSegment(text="hello world")
        assert seg.text == "hello world"
        assert seg.words == []
        assert seg.start_time == 0.0
        assert seg.end_time == 0.0

    def test_creation_with_words(self):
        words = [WordTiming("hi", 0.0, 0.3), WordTiming("there", 0.3, 0.8)]
        seg = CaptionSegment(text="hi there", words=words, start_time=0.0, end_time=0.8)
        assert len(seg.words) == 2
        assert seg.words[0].word == "hi"

    def test_creation_empty_text(self):
        seg = CaptionSegment(text="")
        assert seg.text == ""

    def test_to_dict_empty(self):
        seg = CaptionSegment(text="test", words=[], start_time=1.0, end_time=2.0)
        d = seg.to_dict()
        assert d["text"] == "test"
        assert d["words"] == []
        assert d["start_time"] == 1.0
        assert d["end_time"] == 2.0

    def test_to_dict_with_words(self):
        words = [WordTiming("hello", 0.0, 0.5), WordTiming("world", 0.5, 1.0)]
        seg = CaptionSegment(text="hello world", words=words, start_time=0.0, end_time=1.0)
        d = seg.to_dict()
        assert len(d["words"]) == 2
        assert d["words"][0] == {"word": "hello", "start": 0.0, "end": 0.5}
        assert d["words"][1] == {"word": "world", "start": 0.5, "end": 1.0}

    def test_from_dict_basic(self):
        data = {
            "text": "hello world",
            "words": [{"word": "hello", "start": 0.0, "end": 0.5}],
            "start_time": 0.0,
            "end_time": 1.0,
        }
        seg = CaptionSegment.from_dict(data)
        assert seg.text == "hello world"
        assert len(seg.words) == 1
        assert seg.words[0].word == "hello"
        assert seg.start_time == 0.0
        assert seg.end_time == 1.0

    def test_from_dict_missing_words(self):
        data = {"text": "hi", "start_time": 0.0, "end_time": 1.0}
        seg = CaptionSegment.from_dict(data)
        assert seg.words == []

    def test_round_trip_empty_words(self):
        seg = CaptionSegment(text="test phrase", words=[], start_time=5.0, end_time=10.0)
        seg2 = CaptionSegment.from_dict(seg.to_dict())
        assert seg2.text == seg.text
        assert seg2.start_time == seg.start_time
        assert seg2.end_time == seg.end_time
        assert seg2.words == []

    def test_round_trip_with_words(self):
        words = [
            WordTiming("one", 0.0, 0.3),
            WordTiming("two", 0.3, 0.6),
            WordTiming("three", 0.6, 1.0),
        ]
        seg = CaptionSegment(text="one two three", words=words, start_time=0.0, end_time=1.0)
        d = seg.to_dict()
        seg2 = CaptionSegment.from_dict(d)
        assert seg2.text == "one two three"
        assert len(seg2.words) == 3
        assert seg2.words[2].word == "three"
        assert seg2.words[2].end == 1.0


# ===========================================================================
# 3. CaptionStyle validation tests
# ===========================================================================

class TestCaptionStyleDefaults:
    def test_default_values(self):
        cs = CaptionStyle()
        assert cs.font == "Arial-Bold"
        assert cs.font_size == 70
        assert cs.text_color == "#FFFFFF"
        assert cs.highlight_color == "#FFD700"
        assert cs.bg_color == "#00000080"
        assert cs.position == "bottom"
        assert cs.style_type == "karaoke"
        assert cs.stroke_color == "#000000"
        assert cs.stroke_width == 3
        assert cs.max_words_per_line == 5

    def test_valid_style_types(self):
        for st in ("karaoke", "pop_on", "scroll"):
            cs = CaptionStyle(style_type=st)
            assert cs.style_type == st

    def test_valid_positions(self):
        for pos in ("bottom", "center", "top"):
            cs = CaptionStyle(position=pos)
            assert cs.position == pos

    def test_invalid_style_type_raises(self):
        with pytest.raises(ValueError, match="style_type"):
            CaptionStyle(style_type="unknown")

    def test_invalid_style_type_empty_raises(self):
        with pytest.raises(ValueError, match="style_type"):
            CaptionStyle(style_type="")

    def test_invalid_position_raises(self):
        with pytest.raises(ValueError, match="position"):
            CaptionStyle(position="left")

    def test_invalid_position_empty_raises(self):
        with pytest.raises(ValueError, match="position"):
            CaptionStyle(position="")

    def test_font_size_clamp_low(self):
        cs = CaptionStyle(font_size=1)
        assert cs.font_size == _MIN_FONT_SIZE

    def test_font_size_clamp_high(self):
        cs = CaptionStyle(font_size=9999)
        assert cs.font_size == _MAX_FONT_SIZE

    def test_font_size_at_min(self):
        cs = CaptionStyle(font_size=_MIN_FONT_SIZE)
        assert cs.font_size == _MIN_FONT_SIZE

    def test_font_size_at_max(self):
        cs = CaptionStyle(font_size=_MAX_FONT_SIZE)
        assert cs.font_size == _MAX_FONT_SIZE

    def test_stroke_width_clamp_low(self):
        cs = CaptionStyle(stroke_width=-5)
        assert cs.stroke_width == _MIN_STROKE_WIDTH

    def test_stroke_width_clamp_high(self):
        cs = CaptionStyle(stroke_width=999)
        assert cs.stroke_width == _MAX_STROKE_WIDTH

    def test_stroke_width_zero(self):
        cs = CaptionStyle(stroke_width=0)
        assert cs.stroke_width == 0

    def test_max_words_per_line_clamp_low(self):
        cs = CaptionStyle(max_words_per_line=0)
        assert cs.max_words_per_line == _MIN_WORDS_PER_LINE

    def test_max_words_per_line_clamp_high(self):
        cs = CaptionStyle(max_words_per_line=100)
        assert cs.max_words_per_line == _MAX_WORDS_PER_LINE

    def test_custom_colors(self):
        cs = CaptionStyle(text_color="#FF0000", highlight_color="#00FF00")
        assert cs.text_color == "#FF0000"
        assert cs.highlight_color == "#00FF00"


# ===========================================================================
# 4. Module-level helper tests
# ===========================================================================

class TestHelpers:
    def test_clamp_in_range(self):
        assert _clamp(5, 0, 10) == 5

    def test_clamp_below_min(self):
        assert _clamp(-1, 0, 10) == 0

    def test_clamp_above_max(self):
        assert _clamp(20, 0, 10) == 10

    def test_clamp_at_boundary(self):
        assert _clamp(0, 0, 10) == 0
        assert _clamp(10, 0, 10) == 10

    def test_srt_time_to_seconds_zero(self):
        assert _srt_time_to_seconds(0, 0, 0, 0) == 0.0

    def test_srt_time_to_seconds_one_hour(self):
        assert _srt_time_to_seconds(1, 0, 0, 0) == 3600.0

    def test_srt_time_to_seconds_mixed(self):
        result = _srt_time_to_seconds(0, 1, 30, 500)
        assert abs(result - 90.5) < 1e-6

    def test_srt_timecode_re_matches(self):
        line = "00:01:23,456 --> 00:01:25,789"
        m = _SRT_TIMECODE_RE.search(line)
        assert m is not None
        assert m.group(1) == "00"
        assert m.group(4) == "456"


# ===========================================================================
# 5. AnimatedCaptions initialization
# ===========================================================================

class TestAnimatedCaptionsInit:
    def test_default_style(self):
        ac = AnimatedCaptions()
        assert isinstance(ac.style, CaptionStyle)
        assert ac.style.style_type == "karaoke"

    def test_custom_style(self):
        style = CaptionStyle(style_type="pop_on")
        ac = AnimatedCaptions(style=style)
        assert ac.style.style_type == "pop_on"

    def test_none_style_creates_default(self):
        ac = AnimatedCaptions(style=None)
        assert ac.style is not None

    def test_scroll_style(self):
        style = CaptionStyle(style_type="scroll")
        ac = AnimatedCaptions(style=style)
        assert ac.style.style_type == "scroll"


# ===========================================================================
# 6. AnimatedCaptions.transcribe tests (mocked faster-whisper)
# ===========================================================================

def _make_mock_word(word, start, end):
    w = MagicMock()
    w.word = word
    w.start = start
    w.end = end
    return w


def _make_mock_segment(words):
    seg = MagicMock()
    seg.words = words
    return seg


class TestTranscribe:
    def test_transcribes_basic(self):
        ac = AnimatedCaptions(style=CaptionStyle(max_words_per_line=5))

        mock_words = [
            _make_mock_word("Hello", 0.0, 0.3),
            _make_mock_word("world", 0.3, 0.6),
        ]
        mock_seg = _make_mock_segment(mock_words)
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_seg]), MagicMock())

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = ac.transcribe("/fake/audio.wav")

        assert len(result) == 1
        assert result[0].text == "Hello world"
        assert result[0].words[0].word == "Hello"
        assert result[0].words[1].word == "world"

    def test_transcribes_multiple_segments(self):
        ac = AnimatedCaptions(style=CaptionStyle(max_words_per_line=2))

        words_s1 = [
            _make_mock_word("one", 0.0, 0.3),
            _make_mock_word("two", 0.3, 0.6),
        ]
        words_s2 = [
            _make_mock_word("three", 0.6, 0.9),
            _make_mock_word("four", 0.9, 1.2),
        ]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([_make_mock_segment(words_s1), _make_mock_segment(words_s2)]),
            MagicMock(),
        )

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = ac.transcribe("/fake/audio.wav")

        assert len(result) == 2
        assert result[0].text == "one two"
        assert result[1].text == "three four"

    def test_transcribes_skips_empty_words(self):
        ac = AnimatedCaptions()
        mock_words = [
            _make_mock_word("  ", 0.0, 0.1),
            _make_mock_word("hello", 0.1, 0.5),
        ]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([_make_mock_segment(mock_words)]),
            MagicMock(),
        )

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = ac.transcribe("/fake/audio.wav")

        assert len(result) == 1
        assert result[0].words[0].word == "hello"

    def test_transcribes_empty_audio(self):
        ac = AnimatedCaptions()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([]), MagicMock())

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = ac.transcribe("/fake/audio.wav")

        assert result == []

    def test_transcribes_uses_word_timestamps(self):
        ac = AnimatedCaptions()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([]), MagicMock())

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model) as mock_cls:
            ac.transcribe("/fake/audio.wav")

        mock_model.transcribe.assert_called_once_with(
            "/fake/audio.wav", word_timestamps=True
        )

    def test_transcribes_word_grouping_by_max_words(self):
        ac = AnimatedCaptions(style=CaptionStyle(max_words_per_line=3))

        words = [_make_mock_word(f"w{i}", i * 0.1, (i + 1) * 0.1) for i in range(7)]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([_make_mock_segment(words)]),
            MagicMock(),
        )

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = ac.transcribe("/fake/audio.wav")

        # 7 words / 3 per line = 2 full groups + 1 remainder
        assert len(result) == 3
        assert len(result[0].words) == 3
        assert len(result[1].words) == 3
        assert len(result[2].words) == 1

    def test_transcribes_single_word(self):
        ac = AnimatedCaptions()
        mock_words = [_make_mock_word("single", 0.0, 0.5)]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([_make_mock_segment(mock_words)]),
            MagicMock(),
        )

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = ac.transcribe("/fake/audio.wav")

        assert len(result) == 1
        assert result[0].text == "single"

    def test_transcribes_segment_timing(self):
        ac = AnimatedCaptions(style=CaptionStyle(max_words_per_line=5))
        words = [
            _make_mock_word("a", 1.0, 1.3),
            _make_mock_word("b", 1.3, 1.6),
        ]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([_make_mock_segment(words)]),
            MagicMock(),
        )

        with patch("animated_captions.validate_path"), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = ac.transcribe("/fake/audio.wav")

        assert result[0].start_time == 1.0
        assert result[0].end_time == 1.6


# ===========================================================================
# 7. _render_word_clip tests (mocked TextClip)
# ===========================================================================

class TestRenderWordClip:
    def _make_mock_text_clip(self):
        clip = MagicMock()
        clip.with_start.return_value = clip
        clip.with_end.return_value = clip
        clip.with_position.return_value = clip
        return clip

    def test_render_highlighted_uses_highlight_color(self):
        style = CaptionStyle(
            text_color="#FFFFFF",
            highlight_color="#FFD700",
            font="Arial-Bold",
            font_size=70,
            stroke_color="#000000",
            stroke_width=3,
        )
        ac = AnimatedCaptions(style=style)
        mock_clip = self._make_mock_text_clip()

        with patch("moviepy.TextClip", return_value=mock_clip) as mock_cls:
            ac._render_word_clip(
                word="hello",
                start=0.0, end=0.5,
                is_highlighted=True,
                position=(100, 200),
                resolution=(1080, 1920),
            )

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["color"] == "#FFD700"

    def test_render_non_highlighted_uses_text_color(self):
        style = CaptionStyle(text_color="#FFFFFF", highlight_color="#FFD700")
        ac = AnimatedCaptions(style=style)
        mock_clip = self._make_mock_text_clip()

        with patch("moviepy.TextClip", return_value=mock_clip) as mock_cls:
            ac._render_word_clip(
                word="world",
                start=0.5, end=1.0,
                is_highlighted=False,
                position=(500, 200),
                resolution=(1080, 1920),
            )

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["color"] == "#FFFFFF"

    def test_render_uses_style_font(self):
        style = CaptionStyle(font="Impact", font_size=80)
        ac = AnimatedCaptions(style=style)
        mock_clip = self._make_mock_text_clip()

        with patch("moviepy.TextClip", return_value=mock_clip) as mock_cls:
            ac._render_word_clip("test", 0.0, 1.0, False, (0, 0), (1080, 1920))

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["font"] == "Impact"
        assert kwargs["font_size"] == 80

    def test_render_applies_timing(self):
        ac = AnimatedCaptions()
        mock_clip = self._make_mock_text_clip()

        with patch("moviepy.TextClip", return_value=mock_clip):
            result = ac._render_word_clip("test", 1.5, 2.5, False, (0, 0), (1080, 1920))

        mock_clip.with_start.assert_called_once_with(1.5)
        mock_clip.with_end.assert_called_once_with(2.5)

    def test_render_applies_position(self):
        ac = AnimatedCaptions()
        mock_clip = self._make_mock_text_clip()

        with patch("moviepy.TextClip", return_value=mock_clip):
            ac._render_word_clip("test", 0.0, 1.0, False, (300, 400), (1080, 1920))

        mock_clip.with_position.assert_called_once_with((300, 400))

    def test_render_stroke_params(self):
        style = CaptionStyle(stroke_color="#FF0000", stroke_width=5)
        ac = AnimatedCaptions(style=style)
        mock_clip = self._make_mock_text_clip()

        with patch("moviepy.TextClip", return_value=mock_clip) as mock_cls:
            ac._render_word_clip("test", 0.0, 1.0, False, (0, 0), (1080, 1920))

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["stroke_color"] == "#FF0000"
        assert kwargs["stroke_width"] == 5


# ===========================================================================
# 8. _build_segment_clips style routing tests
# ===========================================================================

class TestBuildSegmentClips:
    def _mock_render(self, ac):
        """Patch _render_word_clip to return a distinct MagicMock each call."""
        call_results = []

        def _side_effect(**kwargs):
            m = MagicMock()
            call_results.append(m)
            return m

        p = patch.object(ac, "_render_word_clip", side_effect=_side_effect)
        return p, call_results

    def test_empty_segment_returns_empty(self):
        ac = AnimatedCaptions()
        seg = CaptionSegment(text="", words=[], start_time=0.0, end_time=1.0)
        result = ac._build_segment_clips(seg, (1080, 1920))
        assert result == []

    def test_karaoke_produces_two_clips_per_word(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="karaoke"))
        seg = make_segment(words=[
            WordTiming("hello", 0.0, 0.5),
            WordTiming("world", 0.5, 1.0),
        ])
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        # 2 words × 2 clips (normal + highlighted) = 4
        assert len(clips) == 4

    def test_pop_on_produces_one_clip_per_word(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="pop_on"))
        seg = make_segment(words=[
            WordTiming("hello", 0.0, 0.5),
            WordTiming("world", 0.5, 1.0),
        ])
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        # 2 words × 1 clip each = 2
        assert len(clips) == 2

    def test_scroll_produces_base_plus_per_word(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="scroll"))
        seg = make_segment(words=[
            WordTiming("hello", 0.0, 0.5),
            WordTiming("world", 0.5, 1.0),
        ])
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        # 1 full-text clip + 2 highlight clips per word = 3
        assert len(clips) == 3

    def test_karaoke_single_word(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="karaoke"))
        seg = CaptionSegment(
            text="hey", words=[WordTiming("hey", 0.0, 0.5)],
            start_time=0.0, end_time=0.5
        )
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        assert len(clips) == 2  # 1 word × 2 clips

    def test_pop_on_single_word(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="pop_on"))
        seg = CaptionSegment(
            text="hey", words=[WordTiming("hey", 0.0, 0.5)],
            start_time=0.0, end_time=0.5
        )
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        assert len(clips) == 1

    def test_scroll_single_word(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="scroll"))
        seg = CaptionSegment(
            text="hey", words=[WordTiming("hey", 0.0, 0.5)],
            start_time=0.0, end_time=0.5
        )
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        assert len(clips) == 2  # 1 base + 1 highlight

    def test_position_bottom_uses_correct_y(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="pop_on", position="bottom"))
        seg = CaptionSegment(
            text="test", words=[WordTiming("test", 0.0, 1.0)],
            start_time=0.0, end_time=1.0
        )
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            ac._build_segment_clips(seg, (1080, 1920))

        pos_call = mock_clip.with_position.call_args[0][0]
        # y should be around 80% of height for bottom
        assert pos_call[1] > 1920 * 0.7

    def test_position_top_uses_correct_y(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="pop_on", position="top"))
        seg = CaptionSegment(
            text="test", words=[WordTiming("test", 0.0, 1.0)],
            start_time=0.0, end_time=1.0
        )
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            ac._build_segment_clips(seg, (1080, 1920))

        pos_call = mock_clip.with_position.call_args[0][0]
        assert pos_call[1] < 1920 * 0.5


# ===========================================================================
# 9. apply() full pipeline tests
# ===========================================================================

class TestApply:
    def _build_mocks(self, tmp_path, segments=None):
        """Return (video_clip_mock, composite_mock, patch_context)."""
        if segments is None:
            segments = [make_segment()]

        mock_audio = MagicMock()
        mock_audio.write_audiofile = MagicMock()

        mock_video = MagicMock()
        mock_video.w = 1080
        mock_video.h = 1920
        mock_video.audio = mock_audio

        mock_composite = MagicMock()
        mock_composite.write_videofile = MagicMock()

        return mock_video, mock_composite

    def test_apply_returns_output_path(self, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake")

        mock_video, mock_composite = self._build_mocks(tmp_path)
        ac = AnimatedCaptions()

        with patch("animated_captions.validate_path"), \
             patch("moviepy.VideoFileClip", return_value=mock_video), \
             patch("moviepy.CompositeVideoClip", return_value=mock_composite), \
             patch.object(ac, "transcribe", return_value=[]) as mock_t, \
             patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.close"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"), \
             patch("os.replace"):

            # Two calls to mkstemp: one for audio, one for output
            mock_mkstemp.side_effect = [
                (3, "/tmp/fake_audio.wav"),
                (4, "/tmp/fake_out.mp4"),
            ]

            result = ac.apply(str(video_file))

        assert result.endswith("_captioned.mp4")

    def test_apply_default_output_path(self, tmp_path):
        video_path = str(tmp_path / "myvideo.mp4")
        mock_video, mock_composite = self._build_mocks(tmp_path)
        ac = AnimatedCaptions()

        with patch("animated_captions.validate_path"), \
             patch("moviepy.VideoFileClip", return_value=mock_video), \
             patch("moviepy.CompositeVideoClip", return_value=mock_composite), \
             patch.object(ac, "transcribe", return_value=[]), \
             patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.close"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"), \
             patch("os.replace"):
            mock_mkstemp.side_effect = [
                (3, "/tmp/a.wav"),
                (4, "/tmp/b.mp4"),
            ]
            result = ac.apply(video_path)

        expected = video_path.replace(".mp4", "_captioned.mp4")
        assert result == expected

    def test_apply_custom_output_path(self, tmp_path):
        video_path = str(tmp_path / "vid.mp4")
        output_path = str(tmp_path / "out.mp4")
        mock_video, _ = self._build_mocks(tmp_path)
        mock_composite = MagicMock()
        mock_composite.write_videofile = MagicMock()
        ac = AnimatedCaptions()

        with patch("animated_captions.validate_path"), \
             patch("moviepy.VideoFileClip", return_value=mock_video), \
             patch("moviepy.CompositeVideoClip", return_value=mock_composite), \
             patch.object(ac, "transcribe", return_value=[]), \
             patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.close"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"), \
             patch("os.replace"):
            mock_mkstemp.side_effect = [
                (3, "/tmp/a.wav"),
                (4, "/tmp/b.mp4"),
            ]
            result = ac.apply(video_path, output_path=output_path)

        assert result == output_path

    def test_apply_calls_transcribe(self, tmp_path):
        video_path = str(tmp_path / "vid.mp4")
        mock_video, mock_composite = self._build_mocks(tmp_path)
        ac = AnimatedCaptions()

        with patch("animated_captions.validate_path"), \
             patch("moviepy.VideoFileClip", return_value=mock_video), \
             patch("moviepy.CompositeVideoClip", return_value=mock_composite), \
             patch.object(ac, "transcribe", return_value=[]) as mock_t, \
             patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.close"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"), \
             patch("os.replace"):
            mock_mkstemp.side_effect = [
                (3, "/tmp/a.wav"),
                (4, "/tmp/b.mp4"),
            ]
            ac.apply(video_path)

        mock_t.assert_called_once_with("/tmp/a.wav")

    def test_apply_composites_video_with_captions(self, tmp_path):
        video_path = str(tmp_path / "vid.mp4")
        mock_video, _ = self._build_mocks(tmp_path)
        mock_composite = MagicMock()
        mock_composite.write_videofile = MagicMock()
        ac = AnimatedCaptions()

        seg = make_segment()

        with patch("animated_captions.validate_path"), \
             patch("moviepy.VideoFileClip", return_value=mock_video), \
             patch("moviepy.CompositeVideoClip", return_value=mock_composite) as mock_comp, \
             patch.object(ac, "transcribe", return_value=[seg]), \
             patch.object(ac, "_build_segment_clips", return_value=[MagicMock()]) as mock_build, \
             patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.close"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"), \
             patch("os.replace"):
            mock_mkstemp.side_effect = [
                (3, "/tmp/a.wav"),
                (4, "/tmp/b.mp4"),
            ]
            ac.apply(video_path)

        mock_build.assert_called_once()
        mock_comp.assert_called_once()

    def test_apply_cleanup_temp_audio(self, tmp_path):
        video_path = str(tmp_path / "vid.mp4")
        mock_video, mock_composite = self._build_mocks(tmp_path)
        mock_composite.write_videofile = MagicMock()
        ac = AnimatedCaptions()

        with patch("animated_captions.validate_path"), \
             patch("moviepy.VideoFileClip", return_value=mock_video), \
             patch("moviepy.CompositeVideoClip", return_value=mock_composite), \
             patch.object(ac, "transcribe", return_value=[]), \
             patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.close"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_rm, \
             patch("os.replace"):
            mock_mkstemp.side_effect = [
                (3, "/tmp/a.wav"),
                (4, "/tmp/b.mp4"),
            ]
            ac.apply(video_path)

        # Should attempt to remove the temp audio
        mock_rm.assert_called_with("/tmp/a.wav")


# ===========================================================================
# 10. apply_to_clip() tests
# ===========================================================================

class TestApplyToClip:
    def test_returns_composite(self):
        ac = AnimatedCaptions()
        mock_clip = MagicMock()
        mock_clip.w = 1080
        mock_clip.h = 1920

        mock_composite = MagicMock()

        segs = [make_segment()]

        with patch("moviepy.CompositeVideoClip", return_value=mock_composite) as mock_comp, \
             patch.object(ac, "_build_segment_clips", return_value=[MagicMock()]):
            result = ac.apply_to_clip(mock_clip, segs)

        assert result is mock_composite

    def test_empty_segments_creates_composite_with_just_video(self):
        ac = AnimatedCaptions()
        mock_clip = MagicMock()
        mock_clip.w = 1080
        mock_clip.h = 1920

        mock_composite = MagicMock()

        with patch("moviepy.CompositeVideoClip", return_value=mock_composite) as mock_comp:
            result = ac.apply_to_clip(mock_clip, [])

        # CompositeVideoClip should be called with just the video clip
        call_args = mock_comp.call_args[0][0]
        assert call_args[0] is mock_clip

    def test_builds_clips_for_each_segment(self):
        ac = AnimatedCaptions()
        mock_clip = MagicMock()
        mock_clip.w = 1920
        mock_clip.h = 1080

        segs = [make_segment(), make_segment("test two")]

        with patch("moviepy.CompositeVideoClip", return_value=MagicMock()), \
             patch.object(ac, "_build_segment_clips", return_value=[]) as mock_build:
            ac.apply_to_clip(mock_clip, segs)

        assert mock_build.call_count == 2

    def test_resolution_passed_correctly(self):
        ac = AnimatedCaptions()
        mock_clip = MagicMock()
        mock_clip.w = 720
        mock_clip.h = 1280

        segs = [make_segment()]

        with patch("moviepy.CompositeVideoClip", return_value=MagicMock()), \
             patch.object(ac, "_build_segment_clips", return_value=[]) as mock_build:
            ac.apply_to_clip(mock_clip, segs)

        _, kwargs = mock_build.call_args
        assert mock_build.call_args[0][1] == (720, 1280) or \
               mock_build.call_args[1].get("resolution") == (720, 1280) or \
               mock_build.call_args[0][1] == (720, 1280)


# ===========================================================================
# 11. from_srt() tests
# ===========================================================================

_VALID_SRT = """\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:04,500 --> 00:00:06,000
How are you today

3
00:00:07,000 --> 00:00:09,000
Goodbye
"""

_EMPTY_SRT = ""

_SINGLE_BLOCK_SRT = """\
1
00:00:00,000 --> 00:00:02,000
Just one line
"""

_SRT_WITH_MULTI_LINE_TEXT = """\
1
00:00:01,000 --> 00:00:03,000
Hello
world
"""

_MALFORMED_SRT_NO_TIMECODE = """\
Just some text without timecodes
another line
"""

_SRT_LARGE_TIMESTAMP = """\
1
01:30:15,500 --> 01:30:17,000
Late segment
"""


class TestFromSrt:
    def test_valid_srt_three_segments(self, tmp_path):
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(_VALID_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert len(segments) == 3
        assert segments[0].text == "Hello world"
        assert segments[1].text == "How are you today"
        assert segments[2].text == "Goodbye"

    def test_valid_srt_timecodes(self, tmp_path):
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(_VALID_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert abs(segments[0].start_time - 1.0) < 1e-6
        assert abs(segments[0].end_time - 3.0) < 1e-6
        assert abs(segments[1].start_time - 4.5) < 1e-6

    def test_valid_srt_word_count(self, tmp_path):
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(_VALID_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert len(segments[0].words) == 2   # "Hello", "world"
        assert len(segments[1].words) == 4   # "How", "are", "you", "today"
        assert len(segments[2].words) == 1   # "Goodbye"

    def test_valid_srt_word_timings_estimated(self, tmp_path):
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(_VALID_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        # Words in seg[0] span 1.0 to 3.0 = 2 seconds / 2 words = 1s each
        w0 = segments[0].words[0]
        w1 = segments[0].words[1]
        assert abs(w0.start - 1.0) < 1e-6
        assert abs(w0.end - 2.0) < 1e-6
        assert abs(w1.start - 2.0) < 1e-6
        assert abs(w1.end - 3.0) < 1e-6

    def test_empty_srt_returns_empty_list(self, tmp_path):
        srt_file = tmp_path / "empty.srt"
        srt_file.write_text(_EMPTY_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert segments == []

    def test_single_block_srt(self, tmp_path):
        srt_file = tmp_path / "single.srt"
        srt_file.write_text(_SINGLE_BLOCK_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert len(segments) == 1
        assert segments[0].text == "Just one line"

    def test_malformed_srt_no_timecode_returns_empty(self, tmp_path):
        srt_file = tmp_path / "bad.srt"
        srt_file.write_text(_MALFORMED_SRT_NO_TIMECODE, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert segments == []

    def test_large_timestamp(self, tmp_path):
        srt_file = tmp_path / "large.srt"
        srt_file.write_text(_SRT_LARGE_TIMESTAMP, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert len(segments) == 1
        # 1*3600 + 30*60 + 15 + 0.5 = 5415.5
        assert abs(segments[0].start_time - 5415.5) < 1e-3

    def test_multi_line_text_joined(self, tmp_path):
        srt_file = tmp_path / "multi.srt"
        srt_file.write_text(_SRT_WITH_MULTI_LINE_TEXT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        assert len(segments) == 1
        # "Hello" and "world" joined with space
        assert "Hello" in segments[0].text
        assert "world" in segments[0].text

    def test_srt_words_have_correct_word_text(self, tmp_path):
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(_SINGLE_BLOCK_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        word_texts = [w.word for w in segments[0].words]
        assert word_texts == ["Just", "one", "line"]

    def test_srt_to_dict_round_trip(self, tmp_path):
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(_VALID_SRT, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        for seg in segments:
            d = seg.to_dict()
            seg2 = CaptionSegment.from_dict(d)
            assert seg2.text == seg.text
            assert len(seg2.words) == len(seg.words)


# ===========================================================================
# 12. Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_very_long_text_segment(self):
        ac = AnimatedCaptions()
        long_text = " ".join(f"word{i}" for i in range(50))
        words = [WordTiming(f"word{i}", i * 0.1, (i + 1) * 0.1) for i in range(50)]
        seg = CaptionSegment(text=long_text, words=words, start_time=0.0, end_time=5.0)

        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        # karaoke: 50 words × 2 clips each = 100
        assert len(clips) == 100

    def test_pop_on_very_long_text(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="pop_on"))
        words = [WordTiming(f"w{i}", i * 0.1, (i + 1) * 0.1) for i in range(30)]
        seg = CaptionSegment(
            text=" ".join(f"w{i}" for i in range(30)),
            words=words, start_time=0.0, end_time=3.0
        )

        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips = ac._build_segment_clips(seg, (1080, 1920))

        assert len(clips) == 30  # one per word

    def test_segment_from_dict_missing_all_fields(self):
        seg = CaptionSegment.from_dict({})
        assert seg.text == ""
        assert seg.words == []
        assert seg.start_time == 0.0
        assert seg.end_time == 0.0

    def test_style_with_all_valid_combinations(self):
        for st in _VALID_STYLE_TYPES:
            for pos in _VALID_POSITIONS:
                cs = CaptionStyle(style_type=st, position=pos)
                assert cs.style_type == st
                assert cs.position == pos

    def test_animated_captions_scroll_positions_vary_with_resolution(self):
        ac = AnimatedCaptions(style=CaptionStyle(style_type="pop_on", position="center"))
        seg = CaptionSegment(
            text="test", words=[WordTiming("test", 0.0, 1.0)],
            start_time=0.0, end_time=1.0
        )
        mock_clip = MagicMock()
        mock_clip.with_start.return_value = mock_clip
        mock_clip.with_end.return_value = mock_clip
        mock_clip.with_position.return_value = mock_clip

        with patch("moviepy.TextClip", return_value=mock_clip):
            clips_hd = ac._build_segment_clips(seg, (1920, 1080))

        pos_hd = mock_clip.with_position.call_args[0][0]
        # For center position, y should be ~50% of height
        assert abs(pos_hd[1] - int(0.50 * 1080)) <= 1

    def test_flush_word_buffer_empty(self):
        ac = AnimatedCaptions()
        words = [WordTiming("only", 0.5, 1.5)]
        seg = ac._flush_word_buffer(words)
        assert seg.text == "only"
        assert seg.start_time == 0.5
        assert seg.end_time == 1.5

    def test_flush_word_buffer_multi(self):
        ac = AnimatedCaptions()
        words = [
            WordTiming("a", 0.0, 0.3),
            WordTiming("b", 0.3, 0.6),
            WordTiming("c", 0.6, 1.0),
        ]
        seg = ac._flush_word_buffer(words)
        assert seg.text == "a b c"
        assert seg.start_time == 0.0
        assert seg.end_time == 1.0
        assert len(seg.words) == 3

    def test_from_srt_skips_empty_text_block(self, tmp_path):
        # SRT block with timecode but no text after it
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\n\n\n2\n00:00:04,000 --> 00:00:06,000\nHello\n"
        srt_file = tmp_path / "tricky.srt"
        srt_file.write_text(srt_content, encoding="utf-8")

        ac = AnimatedCaptions()
        with patch("animated_captions.validate_path"):
            segments = ac.from_srt(str(srt_file))

        # First block has no text so it should be skipped
        texts = [s.text for s in segments]
        assert "Hello" in texts
        # Empty-text block not present
        assert "" not in texts

    def test_apply_cleanup_on_write_failure(self, tmp_path):
        video_path = str(tmp_path / "vid.mp4")

        mock_audio = MagicMock()
        mock_video = MagicMock()
        mock_video.w = 1080
        mock_video.h = 1920
        mock_video.audio = mock_audio

        mock_composite = MagicMock()
        mock_composite.write_videofile.side_effect = RuntimeError("write failed")
        ac = AnimatedCaptions()

        with patch("animated_captions.validate_path"), \
             patch("moviepy.VideoFileClip", return_value=mock_video), \
             patch("moviepy.CompositeVideoClip", return_value=mock_composite), \
             patch.object(ac, "transcribe", return_value=[]), \
             patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.close"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_rm, \
             patch("os.replace"):
            mock_mkstemp.side_effect = [
                (3, "/tmp/a.wav"),
                (4, "/tmp/b.mp4"),
            ]
            with pytest.raises(RuntimeError, match="write failed"):
                ac.apply(video_path)

        # Should clean up the temp output file
        mock_rm.assert_any_call("/tmp/b.mp4")

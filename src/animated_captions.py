"""
Animated Captions Module for MoneyPrinter.

Adds word-level animated captions to video clips using faster-whisper for
transcription and MoviePy v2 for rendering. Supports three caption styles:
karaoke (highlight current word), pop_on (words appear one by one), and
scroll (full text with moving highlight).

Pipeline:
    1. Transcribe audio from video using faster-whisper (word timestamps)
    2. Group words into CaptionSegments
    3. Build per-word TextClip overlays based on style_type
    4. CompositeVideoClip to merge captions onto video
    5. Write result to output file

Usage:
    captions = AnimatedCaptions()
    output = captions.apply("video.mp4")

    # Or with custom style:
    style = CaptionStyle(style_type="pop_on", highlight_color="#FF0000")
    captions = AnimatedCaptions(style=style)
    segments = captions.from_srt("subtitles.srt")
    clip = captions.apply_to_clip(video_clip, segments)
"""

import os
import re
import tempfile
from dataclasses import dataclass, field

from mp_logger import get_logger
from validation import validate_path

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FONT_SIZE = 500
_MIN_FONT_SIZE = 8
_MAX_STROKE_WIDTH = 20
_MIN_STROKE_WIDTH = 0
_MAX_WORDS_PER_LINE = 20
_MIN_WORDS_PER_LINE = 1
_VALID_STYLE_TYPES = frozenset({"karaoke", "pop_on", "scroll"})
_VALID_POSITIONS = frozenset({"bottom", "center", "top"})
_POSITION_Y_RATIOS = {"bottom": 0.80, "center": 0.50, "top": 0.10}

# SRT timecode regex: HH:MM:SS,mmm
_SRT_TIMECODE_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value, lo, hi):
    """Return value clamped between lo and hi inclusive."""
    return max(lo, min(hi, value))


def _srt_time_to_seconds(h: int, m: int, s: int, ms: int) -> float:
    """Convert SRT time components to seconds."""
    return h * 3600 + m * 60 + s + ms / 1000.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WordTiming:
    """Word with its start/end timestamps from transcription."""
    word: str
    start: float
    end: float


@dataclass
class CaptionSegment:
    """
    A group of words forming a caption segment with timing information.

    Attributes:
        text:       Full text of the segment.
        words:      List of WordTiming for each word.
        start_time: Segment start time in seconds.
        end_time:   Segment end time in seconds.
    """
    text: str
    words: list = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary."""
        return {
            "text": self.text,
            "words": [
                {"word": w.word, "start": w.start, "end": w.end}
                for w in self.words
            ],
            "start_time": self.start_time,
            "end_time": self.end_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CaptionSegment":
        """Deserialize from a plain dictionary."""
        words = [
            WordTiming(word=w["word"], start=w["start"], end=w["end"])
            for w in data.get("words", [])
        ]
        return cls(
            text=data.get("text", ""),
            words=words,
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
        )


@dataclass
class CaptionStyle:
    """
    Visual style configuration for animated captions.

    Attributes:
        font:               Font name (default "Arial-Bold").
        font_size:          Font size in points, clamped to [8, 500].
        text_color:         Normal word color (default white "#FFFFFF").
        highlight_color:    Active/highlighted word color (default gold "#FFD700").
        bg_color:           Background color with optional alpha "#00000080".
        position:           Vertical placement: "bottom", "center", or "top".
        style_type:         Caption animation style: "karaoke", "pop_on", or "scroll".
        stroke_color:       Outline color for text (default black "#000000").
        stroke_width:       Outline width in pixels, clamped to [0, 20].
        max_words_per_line: Max words grouped per caption segment (clamped [1, 20]).
    """
    font: str = "Arial-Bold"
    font_size: int = 70
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFD700"
    bg_color: str = "#00000080"
    position: str = "bottom"
    style_type: str = "karaoke"
    stroke_color: str = "#000000"
    stroke_width: int = 3
    max_words_per_line: int = 5

    def __post_init__(self):
        """Validate and clamp style parameters."""
        if self.style_type not in _VALID_STYLE_TYPES:
            raise ValueError(
                f"style_type '{self.style_type}' is invalid. "
                f"Must be one of: {sorted(_VALID_STYLE_TYPES)}"
            )
        if self.position not in _VALID_POSITIONS:
            raise ValueError(
                f"position '{self.position}' is invalid. "
                f"Must be one of: {sorted(_VALID_POSITIONS)}"
            )
        self.font_size = _clamp(self.font_size, _MIN_FONT_SIZE, _MAX_FONT_SIZE)
        self.stroke_width = _clamp(self.stroke_width, _MIN_STROKE_WIDTH, _MAX_STROKE_WIDTH)
        self.max_words_per_line = _clamp(
            self.max_words_per_line, _MIN_WORDS_PER_LINE, _MAX_WORDS_PER_LINE
        )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class AnimatedCaptions:
    """
    Adds animated word-level captions to videos.

    Supports karaoke, pop_on, and scroll caption styles, with word-level
    timing derived from faster-whisper transcription or SRT files.
    """

    def __init__(self, style: CaptionStyle = None):
        self.style = style or CaptionStyle()
        logger.debug(
            f"AnimatedCaptions initialized with style_type={self.style.style_type}, "
            f"position={self.style.position}"
        )

    # ------------------------------------------------------------------
    # Public: transcription
    # ------------------------------------------------------------------

    def transcribe(self, audio_path: str) -> list:
        """
        Transcribe audio using faster-whisper with word-level timestamps.

        Args:
            audio_path: Path to an audio or video file.

        Returns:
            List of CaptionSegment objects with word-level timings.
        """
        logger.info(f"Transcribing audio: {audio_path}")
        validate_path(audio_path, must_exist=True)

        from faster_whisper import WhisperModel  # lazy import

        model = WhisperModel("base", device="auto", compute_type="int8")
        segments_iter, _info = model.transcribe(audio_path, word_timestamps=True)

        caption_segments = []
        word_buffer: list[WordTiming] = []

        for seg in segments_iter:
            words = getattr(seg, "words", None) or []
            for w in words:
                word_text = w.word.strip()
                if not word_text:
                    continue
                word_buffer.append(WordTiming(word=word_text, start=w.start, end=w.end))
                if len(word_buffer) >= self.style.max_words_per_line:
                    caption_segments.append(self._flush_word_buffer(word_buffer))
                    word_buffer = []

        if word_buffer:
            caption_segments.append(self._flush_word_buffer(word_buffer))

        logger.info(f"Transcribed {len(caption_segments)} caption segments")
        return caption_segments

    def _flush_word_buffer(self, words: list) -> CaptionSegment:
        """Convert a word buffer into a CaptionSegment."""
        text = " ".join(w.word for w in words)
        return CaptionSegment(
            text=text,
            words=list(words),
            start_time=words[0].start,
            end_time=words[-1].end,
        )

    # ------------------------------------------------------------------
    # Public: SRT parsing
    # ------------------------------------------------------------------

    def from_srt(self, srt_path: str) -> list:
        """
        Parse an SRT subtitle file into CaptionSegments.

        Words within each segment have their timings estimated by dividing
        the segment duration equally among words.

        Args:
            srt_path: Path to a .srt file.

        Returns:
            List of CaptionSegment objects.
        """
        logger.info(f"Parsing SRT file: {srt_path}")
        validate_path(srt_path, must_exist=True)

        with open(srt_path, "r", encoding="utf-8") as fh:
            content = fh.read()

        segments = []
        # Split on blank lines to get blocks
        blocks = re.split(r"\n\s*\n", content.strip())

        for block in blocks:
            lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
            if not lines:
                continue

            # Find the timecode line
            timecode_line = None
            text_lines = []
            for line in lines:
                m = _SRT_TIMECODE_RE.search(line)
                if m and timecode_line is None:
                    timecode_line = m
                elif timecode_line is not None:
                    # Skip index-only lines (pure digits) before timecode
                    text_lines.append(line)
                # if no timecode yet and line is a digit index, skip it

            if timecode_line is None:
                logger.debug(f"Skipping SRT block without timecode: {block[:60]!r}")
                continue

            start_time = _srt_time_to_seconds(
                int(timecode_line.group(1)), int(timecode_line.group(2)),
                int(timecode_line.group(3)), int(timecode_line.group(4)),
            )
            end_time = _srt_time_to_seconds(
                int(timecode_line.group(5)), int(timecode_line.group(6)),
                int(timecode_line.group(7)), int(timecode_line.group(8)),
            )

            text = " ".join(text_lines).strip()
            if not text:
                continue

            # Estimate per-word timings
            raw_words = text.split()
            duration = max(end_time - start_time, 0.001)
            time_per_word = duration / len(raw_words) if raw_words else 0.0
            words = []
            for idx, w in enumerate(raw_words):
                w_start = start_time + idx * time_per_word
                w_end = w_start + time_per_word
                words.append(WordTiming(word=w, start=w_start, end=w_end))

            segments.append(CaptionSegment(
                text=text,
                words=words,
                start_time=start_time,
                end_time=end_time,
            ))

        logger.info(f"Parsed {len(segments)} segments from SRT")
        return segments

    # ------------------------------------------------------------------
    # Public: apply to video file
    # ------------------------------------------------------------------

    def apply(self, video_path: str, output_path: str = None) -> str:
        """
        Full pipeline: load video, transcribe audio, overlay captions, write output.

        Args:
            video_path:  Path to the input video file.
            output_path: Path for the output. Defaults to <stem>_captioned.mp4.

        Returns:
            Absolute path to the output video file.
        """
        logger.info(f"apply() started: {video_path}")
        validate_path(video_path, must_exist=True)

        if output_path is None:
            base, _ = os.path.splitext(video_path)
            output_path = base + "_captioned.mp4"

        from moviepy import VideoFileClip, CompositeVideoClip  # lazy import

        video = VideoFileClip(video_path)
        resolution = (video.w, video.h)

        # Write audio to temp file for transcription
        tmp_fd, tmp_audio = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)
        try:
            video.audio.write_audiofile(tmp_audio, logger=None)
            segments = self.transcribe(tmp_audio)
        finally:
            if os.path.exists(tmp_audio):
                os.remove(tmp_audio)

        caption_clips = []
        for seg in segments:
            caption_clips.extend(self._build_segment_clips(seg, resolution))

        composite = CompositeVideoClip([video] + caption_clips)

        # Atomic write: write to temp then rename
        tmp_fd2, tmp_out = tempfile.mkstemp(suffix=".mp4", dir=os.path.dirname(output_path) or ".")
        os.close(tmp_fd2)
        try:
            composite.write_videofile(tmp_out, logger=None)
            os.replace(tmp_out, output_path)
        except Exception:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            raise

        logger.info(f"apply() complete: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Public: apply to in-memory clip
    # ------------------------------------------------------------------

    def apply_to_clip(self, clip, segments: list):
        """
        Overlay captions onto an existing MoviePy clip (in-memory).

        Args:
            clip:     A MoviePy VideoClip object.
            segments: List of CaptionSegment objects.

        Returns:
            A CompositeVideoClip with captions applied.
        """
        logger.info(f"apply_to_clip() with {len(segments)} segments")

        from moviepy import CompositeVideoClip  # lazy import

        resolution = (clip.w, clip.h)
        caption_clips = []
        for seg in segments:
            caption_clips.extend(self._build_segment_clips(seg, resolution))

        result = CompositeVideoClip([clip] + caption_clips)
        logger.debug(f"apply_to_clip() produced {len(caption_clips)} caption clips")
        return result

    # ------------------------------------------------------------------
    # Internal: clip building
    # ------------------------------------------------------------------

    def _build_segment_clips(self, segment: CaptionSegment, resolution: tuple) -> list:
        """
        Build TextClip overlays for one caption segment.

        Dispatches to per-style builders:
          - karaoke: all words shown, active word highlighted
          - pop_on:  words appear one at a time
          - scroll:  full text visible, highlighted word changes
        """
        if not segment.words:
            return []

        style_type = self.style.style_type
        if style_type == "karaoke":
            return self._build_karaoke_clips(segment, resolution)
        elif style_type == "pop_on":
            return self._build_pop_on_clips(segment, resolution)
        elif style_type == "scroll":
            return self._build_scroll_clips(segment, resolution)
        else:
            logger.warning(f"Unknown style_type '{style_type}', falling back to karaoke")
            return self._build_karaoke_clips(segment, resolution)

    def _build_karaoke_clips(self, segment: CaptionSegment, resolution: tuple) -> list:
        """
        Karaoke style: all words in the segment are visible throughout the
        segment duration; the currently-spoken word is highlighted.
        """
        clips = []
        w, h = resolution
        n = len(segment.words)

        # Compute per-word x positions spread across the frame
        for idx, wt in enumerate(segment.words):
            x_frac = (idx + 0.5) / n
            x_pos = int(x_frac * w)
            y_frac = _POSITION_Y_RATIOS.get(self.style.position, 0.80)
            y_pos = int(y_frac * h)

            # Non-highlighted version: visible for the whole segment
            clips.append(self._render_word_clip(
                word=wt.word,
                start=segment.start_time,
                end=segment.end_time,
                is_highlighted=False,
                position=(x_pos, y_pos),
                resolution=resolution,
            ))
            # Highlighted version: visible only during this word's timing
            clips.append(self._render_word_clip(
                word=wt.word,
                start=wt.start,
                end=wt.end,
                is_highlighted=True,
                position=(x_pos, y_pos),
                resolution=resolution,
            ))

        return clips

    def _build_pop_on_clips(self, segment: CaptionSegment, resolution: tuple) -> list:
        """
        Pop-on style: each word appears (highlighted) only during its own
        speaking window, not shown at any other time.
        """
        clips = []
        w, h = resolution
        y_frac = _POSITION_Y_RATIOS.get(self.style.position, 0.80)
        y_pos = int(y_frac * h)
        x_center = w // 2

        for wt in segment.words:
            clips.append(self._render_word_clip(
                word=wt.word,
                start=wt.start,
                end=wt.end,
                is_highlighted=True,
                position=(x_center, y_pos),
                resolution=resolution,
            ))

        return clips

    def _build_scroll_clips(self, segment: CaptionSegment, resolution: tuple) -> list:
        """
        Scroll style: full segment text is always shown; the current word
        is additionally rendered in highlight color on top.
        """
        clips = []
        w, h = resolution
        y_frac = _POSITION_Y_RATIOS.get(self.style.position, 0.80)
        y_pos = int(y_frac * h)
        x_center = w // 2

        # Full text, non-highlighted, visible for whole segment
        clips.append(self._render_word_clip(
            word=segment.text,
            start=segment.start_time,
            end=segment.end_time,
            is_highlighted=False,
            position=(x_center, y_pos),
            resolution=(w, h),
        ))

        # Per-word highlight overlay
        n = len(segment.words)
        for idx, wt in enumerate(segment.words):
            x_frac = (idx + 0.5) / n
            x_pos = int(x_frac * w)
            clips.append(self._render_word_clip(
                word=wt.word,
                start=wt.start,
                end=wt.end,
                is_highlighted=True,
                position=(x_pos, y_pos),
                resolution=(w, h),
            ))

        return clips

    def _render_word_clip(
        self,
        word: str,
        start: float,
        end: float,
        is_highlighted: bool,
        position: tuple,
        resolution: tuple,
    ):
        """
        Create a single TextClip for one word (or phrase).

        Args:
            word:           Text to render.
            start:          Clip start time in seconds.
            end:            Clip end time in seconds.
            is_highlighted: If True, use highlight_color; otherwise text_color.
            position:       (x, y) pixel position within the frame.
            resolution:     (width, height) of the video frame.

        Returns:
            A MoviePy TextClip positioned and timed appropriately.
        """
        from moviepy import TextClip  # lazy import

        color = self.style.highlight_color if is_highlighted else self.style.text_color

        clip = TextClip(
            text=word,
            font=self.style.font,
            font_size=self.style.font_size,
            color=color,
            stroke_color=self.style.stroke_color,
            stroke_width=self.style.stroke_width,
        )
        clip = clip.with_start(start).with_end(end).with_position(position)
        return clip

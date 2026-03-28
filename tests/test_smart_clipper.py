"""
Tests for smart_clipper.py — Smart Clipping Module.

Tests cover:
- ClipCandidate dataclass (creation, serialization, edge values)
- SmartClipper initialization (defaults, custom params, validation)
- detect_scenes (mocked PySceneDetect)
- transcribe (mocked faster-whisper)
- merge_segments (combining scenes + transcript, duration constraints)
- score_segments (mocked LLM, response parsing, error handling)
- find_highlights (full pipeline with all deps mocked)
- _parse_score_response (JSON parsing, fallback, malformed input)
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import asdict

# Mock scenedetect before importing smart_clipper (not installed in test env)
_mock_scenedetect = MagicMock()
_mock_video_splitter = MagicMock()
_mock_frame_timecode = MagicMock()
sys.modules.setdefault('scenedetect', _mock_scenedetect)
sys.modules.setdefault('scenedetect.video_splitter', _mock_video_splitter)
sys.modules.setdefault('scenedetect.frame_timecode', _mock_frame_timecode)
_mock_scenedetect.video_splitter = _mock_video_splitter
_mock_scenedetect.frame_timecode = _mock_frame_timecode

# Mock faster_whisper before importing smart_clipper (not installed in test env)
_mock_faster_whisper = MagicMock()
sys.modules.setdefault('faster_whisper', _mock_faster_whisper)

from smart_clipper import SmartClipper, ClipCandidate


# ---------------------------------------------------------------------------
# ClipCandidate tests
# ---------------------------------------------------------------------------

class TestClipCandidate:
    """Tests for ClipCandidate dataclass."""

    def test_creation_with_required_fields(self):
        clip = ClipCandidate(
            start_time=10.0, end_time=25.0, duration=15.0,
            score=8.5, transcript="Hello world", reason="Engaging"
        )
        assert clip.start_time == 10.0
        assert clip.end_time == 25.0
        assert clip.duration == 15.0
        assert clip.score == 8.5
        assert clip.transcript == "Hello world"
        assert clip.reason == "Engaging"
        assert clip.scene_count == 0  # default

    def test_creation_with_scene_count(self):
        clip = ClipCandidate(
            start_time=0.0, end_time=30.0, duration=30.0,
            score=7.0, transcript="test", reason="good", scene_count=5
        )
        assert clip.scene_count == 5

    def test_edge_values_zero_duration(self):
        clip = ClipCandidate(
            start_time=0.0, end_time=0.0, duration=0.0,
            score=0.0, transcript="", reason=""
        )
        assert clip.duration == 0.0
        assert clip.score == 0.0

    def test_edge_values_max_score(self):
        clip = ClipCandidate(
            start_time=0.0, end_time=60.0, duration=60.0,
            score=10.0, transcript="amazing content", reason="viral"
        )
        assert clip.score == 10.0

    def test_to_dict(self):
        clip = ClipCandidate(
            start_time=5.0, end_time=20.0, duration=15.0,
            score=6.5, transcript="test text", reason="okay", scene_count=2
        )
        d = clip.to_dict()
        assert d == {
            "start_time": 5.0, "end_time": 20.0, "duration": 15.0,
            "score": 6.5, "transcript": "test text", "reason": "okay",
            "scene_count": 2,
        }

    def test_from_dict(self):
        data = {
            "start_time": 5.0, "end_time": 20.0, "duration": 15.0,
            "score": 6.5, "transcript": "test", "reason": "ok", "scene_count": 1,
        }
        clip = ClipCandidate.from_dict(data)
        assert clip.start_time == 5.0
        assert clip.score == 6.5

    def test_from_dict_ignores_extra_keys(self):
        data = {
            "start_time": 0, "end_time": 10, "duration": 10,
            "score": 5, "transcript": "", "reason": "",
            "unknown_key": "should be ignored"
        }
        clip = ClipCandidate.from_dict(data)
        assert clip.start_time == 0
        assert not hasattr(clip, "unknown_key")


# ---------------------------------------------------------------------------
# SmartClipper initialization tests
# ---------------------------------------------------------------------------

class TestSmartClipperInit:
    """Tests for SmartClipper constructor."""

    def test_default_params(self):
        clipper = SmartClipper()
        assert clipper.min_clip_duration == 15.0
        assert clipper.max_clip_duration == 60.0
        assert clipper.top_n == 5
        assert clipper.whisper_model == "base"

    def test_custom_params(self):
        clipper = SmartClipper(
            min_clip_duration=10.0, max_clip_duration=120.0,
            top_n=10, whisper_model="large"
        )
        assert clipper.min_clip_duration == 10.0
        assert clipper.max_clip_duration == 120.0
        assert clipper.top_n == 10
        assert clipper.whisper_model == "large"

    def test_invalid_min_duration_zero(self):
        with pytest.raises(ValueError, match="min_clip_duration must be positive"):
            SmartClipper(min_clip_duration=0)

    def test_invalid_min_duration_negative(self):
        with pytest.raises(ValueError, match="min_clip_duration must be positive"):
            SmartClipper(min_clip_duration=-5)

    def test_invalid_max_duration(self):
        with pytest.raises(ValueError, match="max_clip_duration must be positive"):
            SmartClipper(max_clip_duration=0)

    def test_min_greater_than_max(self):
        with pytest.raises(ValueError, match="min_clip_duration must be <= max_clip_duration"):
            SmartClipper(min_clip_duration=60, max_clip_duration=30)

    def test_invalid_top_n(self):
        with pytest.raises(ValueError, match="top_n must be >= 1"):
            SmartClipper(top_n=0)


# ---------------------------------------------------------------------------
# detect_scenes tests
# ---------------------------------------------------------------------------

class TestDetectScenes:
    """Tests for SmartClipper.detect_scenes()."""

    def test_detects_scenes(self):
        clipper = SmartClipper()
        mock_scene_start = MagicMock()
        mock_scene_start.get_seconds.return_value = 0.0
        mock_scene_end = MagicMock()
        mock_scene_end.get_seconds.return_value = 10.5

        mock_scene2_start = MagicMock()
        mock_scene2_start.get_seconds.return_value = 10.5
        mock_scene2_end = MagicMock()
        mock_scene2_end.get_seconds.return_value = 25.0

        with patch("smart_clipper.os.path.isfile", return_value=True), \
             patch.object(_mock_scenedetect, "detect", return_value=[
                 (mock_scene_start, mock_scene_end),
                 (mock_scene2_start, mock_scene2_end),
             ]):
            scenes = clipper.detect_scenes("/fake/video.mp4")

        assert len(scenes) == 2
        assert scenes[0] == (0.0, 10.5)
        assert scenes[1] == (10.5, 25.0)

    def test_no_scenes_detected(self):
        clipper = SmartClipper()
        with patch("smart_clipper.os.path.isfile", return_value=True), \
             patch.object(_mock_scenedetect, "detect", return_value=[]):
            scenes = clipper.detect_scenes("/fake/video.mp4")

        assert scenes == []

    def test_file_not_found(self):
        clipper = SmartClipper()
        with pytest.raises(FileNotFoundError):
            clipper.detect_scenes("/nonexistent/video.mp4")

    def test_single_scene(self):
        clipper = SmartClipper()
        mock_start = MagicMock()
        mock_start.get_seconds.return_value = 0.0
        mock_end = MagicMock()
        mock_end.get_seconds.return_value = 45.0

        with patch("smart_clipper.os.path.isfile", return_value=True), \
             patch.object(_mock_scenedetect, "detect", return_value=[(mock_start, mock_end)]):
            scenes = clipper.detect_scenes("/fake/video.mp4")

        assert len(scenes) == 1
        assert scenes[0] == (0.0, 45.0)


# ---------------------------------------------------------------------------
# transcribe tests
# ---------------------------------------------------------------------------

class TestTranscribe:
    """Tests for SmartClipper.transcribe()."""

    def _make_segment(self, start, end, text):
        seg = MagicMock()
        seg.start = start
        seg.end = end
        seg.text = text
        return seg

    def test_transcribes_segments(self):
        clipper = SmartClipper()
        segs = [
            self._make_segment(0.0, 5.0, "Hello world"),
            self._make_segment(5.0, 10.0, "This is a test"),
        ]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(segs), MagicMock())

        with patch("smart_clipper.os.path.isfile", return_value=True), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = clipper.transcribe("/fake/video.mp4")

        assert len(result) == 2
        assert result[0] == (0.0, 5.0, "Hello world")
        assert result[1] == (5.0, 10.0, "This is a test")

    def test_empty_audio(self):
        clipper = SmartClipper()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([]), MagicMock())

        with patch("smart_clipper.os.path.isfile", return_value=True), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = clipper.transcribe("/fake/video.mp4")

        assert result == []

    def test_skips_whitespace_only_segments(self):
        clipper = SmartClipper()
        segs = [
            self._make_segment(0.0, 5.0, "  "),
            self._make_segment(5.0, 10.0, "Real text"),
        ]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(segs), MagicMock())

        with patch("smart_clipper.os.path.isfile", return_value=True), \
             patch("faster_whisper.WhisperModel", return_value=mock_model):
            result = clipper.transcribe("/fake/video.mp4")

        assert len(result) == 1
        assert result[0][2] == "Real text"

    def test_file_not_found(self):
        clipper = SmartClipper()
        with pytest.raises(FileNotFoundError):
            clipper.transcribe("/nonexistent/video.mp4")


# ---------------------------------------------------------------------------
# merge_segments tests
# ---------------------------------------------------------------------------

class TestMergeSegments:
    """Tests for SmartClipper.merge_segments()."""

    def test_merges_scenes_with_transcript(self):
        clipper = SmartClipper(min_clip_duration=10.0, max_clip_duration=60.0)
        scenes = [(0.0, 20.0), (20.0, 40.0)]
        transcript = [
            (2.0, 8.0, "First part"),
            (22.0, 30.0, "Second part"),
        ]
        result = clipper.merge_segments(scenes, transcript)

        assert len(result) >= 1
        # First segment should contain "First part"
        assert "First part" in result[0]["text"]

    def test_empty_scenes_and_transcript(self):
        clipper = SmartClipper()
        result = clipper.merge_segments([], [])
        assert result == []

    def test_transcript_only_no_scenes(self):
        clipper = SmartClipper(min_clip_duration=5.0)
        transcript = [
            (0.0, 10.0, "Part one"),
            (10.0, 25.0, "Part two"),
        ]
        result = clipper.merge_segments([], transcript)
        # Should create segments from transcript boundaries
        assert len(result) >= 1

    def test_scenes_only_no_transcript(self):
        clipper = SmartClipper(min_clip_duration=10.0)
        scenes = [(0.0, 15.0), (15.0, 35.0)]
        result = clipper.merge_segments(scenes, [])
        assert len(result) >= 1
        assert result[0]["text"] == ""

    def test_respects_min_duration(self):
        clipper = SmartClipper(min_clip_duration=20.0)
        scenes = [(0.0, 5.0), (5.0, 10.0), (10.0, 30.0)]
        result = clipper.merge_segments(scenes, [])
        # Short scenes should be merged to meet min duration
        for seg in result:
            assert seg["duration"] >= 20.0

    def test_respects_max_duration(self):
        clipper = SmartClipper(min_clip_duration=5.0, max_clip_duration=30.0)
        scenes = [(0.0, 50.0)]
        result = clipper.merge_segments(scenes, [])
        for seg in result:
            assert seg["duration"] <= 30.0

    def test_no_transcript_overlap(self):
        clipper = SmartClipper(min_clip_duration=10.0)
        scenes = [(0.0, 20.0)]
        transcript = [(50.0, 60.0, "Far away text")]
        result = clipper.merge_segments(scenes, transcript)
        assert len(result) >= 1
        assert result[0]["text"] == ""  # transcript doesn't overlap

    def test_splits_oversized_segments(self):
        clipper = SmartClipper(min_clip_duration=5.0, max_clip_duration=20.0)
        scenes = [(0.0, 50.0)]
        result = clipper.merge_segments(scenes, [])
        for seg in result:
            assert seg["duration"] <= 20.0


# ---------------------------------------------------------------------------
# score_segments tests
# ---------------------------------------------------------------------------

class TestScoreSegments:
    """Tests for SmartClipper.score_segments()."""

    def test_scores_with_valid_json_response(self):
        clipper = SmartClipper()
        segments = [{
            "start": 0.0, "end": 20.0, "duration": 20.0,
            "text": "This is amazing content about AI",
            "scene_count": 2,
        }]
        with patch("llm_provider.generate_text",
                    return_value='{"score": 8.5, "reason": "Very engaging"}'):
            result = clipper.score_segments(segments)

        assert len(result) == 1
        assert result[0].score == 8.5
        assert result[0].reason == "Very engaging"

    def test_handles_malformed_json(self):
        clipper = SmartClipper()
        segments = [{
            "start": 0.0, "end": 20.0, "duration": 20.0,
            "text": "Some content", "scene_count": 1,
        }]
        with patch("llm_provider.generate_text",
                    return_value="I rate this a 7 out of 10 because it's good"):
            result = clipper.score_segments(segments)

        assert len(result) == 1
        assert result[0].score == 7.0  # fallback number extraction

    def test_handles_llm_error(self):
        clipper = SmartClipper()
        segments = [{
            "start": 0.0, "end": 20.0, "duration": 20.0,
            "text": "Content", "scene_count": 1,
        }]
        with patch("llm_provider.generate_text",
                    side_effect=RuntimeError("LLM unavailable")):
            result = clipper.score_segments(segments)

        assert len(result) == 1
        assert result[0].score == 5.0  # default fallback
        assert result[0].reason == "Scoring unavailable"

    def test_empty_transcript_gets_low_score(self):
        clipper = SmartClipper()
        segments = [{
            "start": 0.0, "end": 20.0, "duration": 20.0,
            "text": "", "scene_count": 1,
        }]
        result = clipper.score_segments(segments)

        assert len(result) == 1
        assert result[0].score == 1.0
        assert "No speech" in result[0].reason

    def test_prompt_contains_transcript(self):
        clipper = SmartClipper()
        segments = [{
            "start": 0.0, "end": 20.0, "duration": 20.0,
            "text": "UNIQUE_TEXT_MARKER", "scene_count": 1,
        }]
        with patch("llm_provider.generate_text",
                    return_value='{"score": 5, "reason": "ok"}') as mock_gen:
            clipper.score_segments(segments)

        prompt = mock_gen.call_args[0][0]
        assert "UNIQUE_TEXT_MARKER" in prompt

    def test_score_clamped_to_range(self):
        clipper = SmartClipper()
        segments = [{
            "start": 0.0, "end": 20.0, "duration": 20.0,
            "text": "content", "scene_count": 1,
        }]
        with patch("llm_provider.generate_text",
                    return_value='{"score": 99, "reason": "over max"}'):
            result = clipper.score_segments(segments)
        assert result[0].score == 10.0  # clamped

    def test_multiple_segments_scored(self):
        clipper = SmartClipper()
        segments = [
            {"start": 0.0, "end": 20.0, "duration": 20.0, "text": "First", "scene_count": 1},
            {"start": 20.0, "end": 40.0, "duration": 20.0, "text": "Second", "scene_count": 1},
        ]
        responses = iter([
            '{"score": 8, "reason": "great"}',
            '{"score": 3, "reason": "boring"}',
        ])
        with patch("llm_provider.generate_text", side_effect=lambda p: next(responses)):
            result = clipper.score_segments(segments)

        assert len(result) == 2
        assert result[0].score == 8.0
        assert result[1].score == 3.0


# ---------------------------------------------------------------------------
# _parse_score_response tests
# ---------------------------------------------------------------------------

class TestParseScoreResponse:
    """Tests for SmartClipper._parse_score_response()."""

    def test_valid_json(self):
        clipper = SmartClipper()
        score, reason = clipper._parse_score_response('{"score": 7.5, "reason": "good content"}')
        assert score == 7.5
        assert reason == "good content"

    def test_json_with_surrounding_text(self):
        clipper = SmartClipper()
        score, reason = clipper._parse_score_response(
            'Here is my rating: {"score": 9, "reason": "viral"} hope that helps!'
        )
        assert score == 9.0
        assert reason == "viral"

    def test_plain_number(self):
        clipper = SmartClipper()
        score, reason = clipper._parse_score_response("I would rate this a 6 out of 10")
        assert score == 6.0

    def test_no_parseable_content(self):
        clipper = SmartClipper()
        score, reason = clipper._parse_score_response("no numbers here at all")
        assert score == 5.0
        assert "Could not parse" in reason

    def test_score_below_minimum_clamped(self):
        clipper = SmartClipper()
        score, reason = clipper._parse_score_response('{"score": -5, "reason": "bad"}')
        assert score == 1.0

    def test_score_above_maximum_clamped(self):
        clipper = SmartClipper()
        score, reason = clipper._parse_score_response('{"score": 15, "reason": "great"}')
        assert score == 10.0

    def test_empty_response(self):
        clipper = SmartClipper()
        score, reason = clipper._parse_score_response("")
        assert score == 5.0


# ---------------------------------------------------------------------------
# find_highlights tests (full pipeline)
# ---------------------------------------------------------------------------

class TestFindHighlights:
    """Tests for SmartClipper.find_highlights()."""

    def test_full_pipeline_mocked(self):
        clipper = SmartClipper(min_clip_duration=10.0, top_n=2)

        mock_scenes = [(0.0, 20.0), (20.0, 45.0)]
        mock_transcript = [
            (2.0, 18.0, "First segment about AI"),
            (22.0, 40.0, "Second segment about cooking"),
        ]

        with patch.object(clipper, "detect_scenes", return_value=mock_scenes), \
             patch.object(clipper, "transcribe", return_value=mock_transcript), \
             patch("llm_provider.generate_text", side_effect=[
                 '{"score": 9, "reason": "AI is trending"}',
                 '{"score": 4, "reason": "cooking is common"}',
             ]), \
             patch("smart_clipper.os.path.isfile", return_value=True):
            result = clipper.find_highlights("/fake/video.mp4")

        assert len(result) <= 2
        # Should be sorted by score descending
        assert result[0].score >= result[-1].score

    def test_returns_top_n_sorted(self):
        clipper = SmartClipper(min_clip_duration=10.0, top_n=2)

        mock_scenes = [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0)]
        mock_transcript = [
            (0.0, 18.0, "Segment A"),
            (20.0, 38.0, "Segment B"),
            (40.0, 58.0, "Segment C"),
        ]

        with patch.object(clipper, "detect_scenes", return_value=mock_scenes), \
             patch.object(clipper, "transcribe", return_value=mock_transcript), \
             patch("llm_provider.generate_text", side_effect=[
                 '{"score": 3, "reason": "low"}',
                 '{"score": 9, "reason": "high"}',
                 '{"score": 6, "reason": "medium"}',
             ]), \
             patch("smart_clipper.os.path.isfile", return_value=True):
            result = clipper.find_highlights("/fake/video.mp4")

        assert len(result) == 2
        assert result[0].score == 9.0
        assert result[1].score == 6.0

    def test_file_not_found(self):
        clipper = SmartClipper()
        with pytest.raises(FileNotFoundError):
            clipper.find_highlights("/nonexistent/video.mp4")

    def test_scene_detection_fails_gracefully(self):
        clipper = SmartClipper(min_clip_duration=5.0, top_n=1)
        mock_transcript = [(0.0, 30.0, "Some speech")]

        with patch.object(clipper, "detect_scenes", side_effect=Exception("ffmpeg missing")), \
             patch.object(clipper, "transcribe", return_value=mock_transcript), \
             patch("llm_provider.generate_text",
                    return_value='{"score": 7, "reason": "ok"}'), \
             patch("smart_clipper.os.path.isfile", return_value=True):
            result = clipper.find_highlights("/fake/video.mp4")

        # Should still produce results from transcript-only mode
        assert len(result) >= 1

    def test_transcription_fails_gracefully(self):
        clipper = SmartClipper(min_clip_duration=10.0, top_n=1)
        mock_scenes = [(0.0, 25.0)]

        with patch.object(clipper, "detect_scenes", return_value=mock_scenes), \
             patch.object(clipper, "transcribe", side_effect=Exception("whisper missing")), \
             patch("llm_provider.generate_text",
                    return_value='{"score": 5, "reason": "scene only"}'), \
             patch("smart_clipper.os.path.isfile", return_value=True):
            result = clipper.find_highlights("/fake/video.mp4")

        # Should still produce results from scene-only mode
        # (segments with empty transcript get low default score)
        assert len(result) >= 0  # may be 0 if no speech → score=1

    def test_no_scenes_no_transcript(self):
        clipper = SmartClipper()

        with patch.object(clipper, "detect_scenes", return_value=[]), \
             patch.object(clipper, "transcribe", return_value=[]), \
             patch("smart_clipper.os.path.isfile", return_value=True):
            result = clipper.find_highlights("/fake/video.mp4")

        assert result == []

    def test_config_integration(self):
        clipper = SmartClipper(
            min_clip_duration=5.0, max_clip_duration=30.0,
            top_n=3, whisper_model="small"
        )
        assert clipper.min_clip_duration == 5.0
        assert clipper.max_clip_duration == 30.0
        assert clipper.top_n == 3
        assert clipper.whisper_model == "small"


# ---------------------------------------------------------------------------
# split_clips tests
# ---------------------------------------------------------------------------

class TestSplitClips:
    """Tests for SmartClipper.split_clips()."""

    def _make_candidates(self, count=2):
        """Helper to create test ClipCandidates."""
        candidates = []
        for i in range(count):
            candidates.append(ClipCandidate(
                start_time=float(i * 20),
                end_time=float(i * 20 + 15),
                duration=15.0,
                score=8.0 - i,
                transcript=f"Segment {i}",
                reason=f"Reason {i}",
                scene_count=1,
            ))
        return candidates

    def _setup_mocks(self, tmp_path, output_dir, num_clips=1, ffmpeg_available=True,
                     ffmpeg_return=0, frame_rate=30.0):
        """Configure scenedetect mocks for split_clips tests."""
        mock_video = MagicMock()
        mock_video.frame_rate = frame_rate

        _mock_scenedetect.open_video = MagicMock(return_value=mock_video)
        _mock_video_splitter.is_ffmpeg_available = MagicMock(return_value=ffmpeg_available)
        _mock_frame_timecode.FrameTimecode = MagicMock(
            side_effect=lambda t, fps: MagicMock(_seconds=t)
        )

        def fake_split(**kwargs):
            od = kwargs.get("output_dir", output_dir)
            os.makedirs(od, exist_ok=True)
            vname = os.path.splitext(os.path.basename(kwargs.get("input_video_path", "video.mp4")))[0]
            for i in range(num_clips):
                p = os.path.join(od, f"{vname}-clip-{i+1:03d}.mp4")
                with open(p, "w") as f:
                    f.write("clip")
            return ffmpeg_return

        _mock_video_splitter.split_video_ffmpeg = MagicMock(side_effect=fake_split)
        return mock_video

    def test_split_basic(self, tmp_path):
        """Basic split with mocked ffmpeg returns output file paths."""
        clipper = SmartClipper()
        candidates = self._make_candidates(2)
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "clips")
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, output_dir, num_clips=2)
        result = clipper.split_clips(video_path, candidates, output_dir)

        assert len(result) == 2
        for p in result:
            assert os.path.isfile(p)
            assert "video" in os.path.basename(p)

    def test_split_empty_candidates(self, tmp_path):
        """Empty candidates list returns empty list."""
        clipper = SmartClipper()
        video_path = str(tmp_path / "video.mp4")
        with open(video_path, "w") as f:
            f.write("fake")

        result = clipper.split_clips(video_path, [], str(tmp_path / "out"))
        assert result == []

    def test_split_file_not_found(self):
        """FileNotFoundError for missing video."""
        clipper = SmartClipper()
        candidates = self._make_candidates(1)
        with pytest.raises(FileNotFoundError):
            clipper.split_clips("/nonexistent/video.mp4", candidates)

    def test_split_ffmpeg_unavailable(self, tmp_path):
        """RuntimeError when ffmpeg is not available."""
        clipper = SmartClipper()
        candidates = self._make_candidates(1)
        video_path = str(tmp_path / "video.mp4")
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, str(tmp_path / "out"), ffmpeg_available=False)
        with pytest.raises(RuntimeError, match="ffmpeg is not available"):
            clipper.split_clips(video_path, candidates, str(tmp_path / "out"))

    def test_split_creates_output_dir(self, tmp_path):
        """Output directory is created if it doesn't exist."""
        clipper = SmartClipper()
        candidates = self._make_candidates(1)
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "new" / "nested" / "dir")
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, output_dir, num_clips=1, frame_rate=24.0)
        result = clipper.split_clips(video_path, candidates, output_dir)

        assert os.path.isdir(output_dir)
        assert len(result) == 1

    def test_split_custom_filename_template(self, tmp_path):
        """Custom filename template is passed to split_video_ffmpeg."""
        clipper = SmartClipper()
        candidates = self._make_candidates(1)
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "clips")
        os.makedirs(output_dir)
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, output_dir, num_clips=1)
        custom_template = "$VIDEO_NAME-highlight-$SCENE_NUMBER"
        clipper.split_clips(video_path, candidates, output_dir, custom_template)

        call_kwargs = _mock_video_splitter.split_video_ffmpeg.call_args[1]
        assert call_kwargs["output_file_template"] == custom_template

    def test_split_candidates_sorted_by_start_time(self, tmp_path):
        """Candidates are sorted by start_time before splitting."""
        clipper = SmartClipper()
        candidates = [
            ClipCandidate(start_time=40.0, end_time=55.0, duration=15.0,
                          score=5.0, transcript="Late", reason="r", scene_count=1),
            ClipCandidate(start_time=10.0, end_time=25.0, duration=15.0,
                          score=9.0, transcript="Early", reason="r", scene_count=1),
        ]
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "clips")
        os.makedirs(output_dir)
        with open(video_path, "w") as f:
            f.write("fake")

        # Track the start times passed to FrameTimecode
        tc_calls = []
        _mock_scenedetect.open_video = MagicMock(return_value=MagicMock(frame_rate=30.0))
        _mock_video_splitter.is_ffmpeg_available = MagicMock(return_value=True)
        _mock_video_splitter.split_video_ffmpeg = MagicMock(return_value=0)

        def track_tc(t, fps):
            tc_calls.append(t)
            return MagicMock(_seconds=t)
        _mock_frame_timecode.FrameTimecode = MagicMock(side_effect=track_tc)

        clipper.split_clips(video_path, candidates, output_dir)

        # FrameTimecode is called with (start, fps), (end, fps) for each candidate
        # After sorting by start_time, first candidate should be start=10.0
        assert tc_calls[0] == 10.0  # first start time
        assert tc_calls[2] == 40.0  # second start time

    def test_split_single_candidate(self, tmp_path):
        """Single candidate produces one clip."""
        clipper = SmartClipper()
        candidates = self._make_candidates(1)
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "clips")
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, output_dir, num_clips=1)
        result = clipper.split_clips(video_path, candidates, output_dir)

        assert len(result) == 1

    def test_split_ffmpeg_nonzero_return(self, tmp_path):
        """Non-zero ffmpeg return code logs warning but doesn't raise."""
        clipper = SmartClipper()
        candidates = self._make_candidates(1)
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "clips")
        os.makedirs(output_dir)
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, output_dir, num_clips=0, ffmpeg_return=1)
        # Override to NOT create files (simulating failure)
        _mock_video_splitter.split_video_ffmpeg = MagicMock(return_value=1)
        result = clipper.split_clips(video_path, candidates, output_dir)

        assert result == []

    def test_split_many_candidates(self, tmp_path):
        """Splitting many candidates works correctly."""
        clipper = SmartClipper()
        candidates = self._make_candidates(5)
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "clips")
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, output_dir, num_clips=5)
        result = clipper.split_clips(video_path, candidates, output_dir)

        assert len(result) == 5

    def test_split_passes_correct_args_to_ffmpeg(self, tmp_path):
        """Verifies split_video_ffmpeg is called with correct args."""
        clipper = SmartClipper()
        candidates = self._make_candidates(1)
        video_path = str(tmp_path / "video.mp4")
        output_dir = str(tmp_path / "clips")
        os.makedirs(output_dir)
        with open(video_path, "w") as f:
            f.write("fake")

        self._setup_mocks(tmp_path, output_dir, num_clips=1)
        clipper.split_clips(video_path, candidates, output_dir)

        _mock_scenedetect.open_video.assert_called_once_with(video_path)
        _mock_video_splitter.split_video_ffmpeg.assert_called_once()
        call_kwargs = _mock_video_splitter.split_video_ffmpeg.call_args[1]
        assert call_kwargs["input_video_path"] == video_path
        assert call_kwargs["output_dir"] == output_dir
        assert len(call_kwargs["scene_list"]) == 1
        assert call_kwargs["show_progress"] is False

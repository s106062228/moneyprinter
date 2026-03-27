"""
Smart Clipping Module for MoneyPrinter.

Detects scene boundaries in video files using PySceneDetect, transcribes
audio via faster-whisper, scores transcript segments for engagement using
LLM, and outputs ranked clip candidates.

Pipeline:
    1. Scene detection (PySceneDetect ContentDetector)
    2. Audio transcription (faster-whisper)
    3. Segment merging (scenes + transcript → coherent segments)
    4. LLM engagement scoring (Ollama/any provider)
    5. Ranked output (top-N ClipCandidates sorted by score)

Usage:
    clipper = SmartClipper()
    highlights = clipper.find_highlights("video.mp4")
    for clip in highlights:
        print(f"{clip.start_time:.1f}-{clip.end_time:.1f}s  score={clip.score:.1f}  {clip.reason}")
"""

import os
import re
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import timezone, datetime

from mp_logger import get_logger

logger = get_logger(__name__)

_MAX_PROMPT_LENGTH = 10000  # Cap transcript length sent to LLM


@dataclass
class ClipCandidate:
    """A ranked candidate clip extracted from a video."""
    start_time: float       # seconds
    end_time: float         # seconds
    duration: float         # seconds
    score: float            # 0.0-10.0 engagement score
    transcript: str         # text content of the segment
    reason: str             # LLM explanation of score
    scene_count: int = 0    # number of scene cuts in this segment

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ClipCandidate":
        """Deserialize from dictionary."""
        allowed_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in allowed_keys}
        return cls(**filtered)


class SmartClipper:
    """Detects highlights in video using scene detection + LLM scoring."""

    def __init__(
        self,
        min_clip_duration: float = 15.0,
        max_clip_duration: float = 60.0,
        top_n: int = 5,
        whisper_model: str = "base",
    ):
        if min_clip_duration <= 0:
            raise ValueError("min_clip_duration must be positive")
        if max_clip_duration <= 0:
            raise ValueError("max_clip_duration must be positive")
        if min_clip_duration > max_clip_duration:
            raise ValueError("min_clip_duration must be <= max_clip_duration")
        if top_n < 1:
            raise ValueError("top_n must be >= 1")

        self.min_clip_duration = min_clip_duration
        self.max_clip_duration = max_clip_duration
        self.top_n = top_n
        self.whisper_model = whisper_model

    def detect_scenes(self, video_path: str) -> list[tuple[float, float]]:
        """
        Detect scene boundaries using PySceneDetect ContentDetector.

        Args:
            video_path: Path to video file.

        Returns:
            List of (start_time, end_time) tuples in seconds.
        """
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        from scenedetect import detect, ContentDetector

        scene_list = detect(video_path, ContentDetector())
        scenes = []
        for scene in scene_list:
            start = scene[0].get_seconds()
            end = scene[1].get_seconds()
            scenes.append((start, end))

        logger.info(f"Detected {len(scenes)} scenes in {video_path}")
        return scenes

    def transcribe(self, video_path: str) -> list[tuple[float, float, str]]:
        """
        Transcribe audio using faster-whisper.

        Args:
            video_path: Path to video file.

        Returns:
            List of (start_time, end_time, text) tuples.
        """
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        from faster_whisper import WhisperModel

        model = WhisperModel(self.whisper_model, device="auto", compute_type="int8")
        segments_iter, _info = model.transcribe(video_path)

        segments = []
        for seg in segments_iter:
            text = seg.text.strip()
            if text:
                segments.append((seg.start, seg.end, text))

        logger.info(f"Transcribed {len(segments)} segments from {video_path}")
        return segments

    def merge_segments(
        self,
        scenes: list[tuple[float, float]],
        transcript: list[tuple[float, float, str]],
    ) -> list[dict]:
        """
        Merge scene boundaries with transcript into coherent segments.

        Each merged segment has a time range, combined transcript text,
        and scene count. Segments are bounded by min/max clip duration.

        Args:
            scenes: List of (start, end) scene boundaries.
            transcript: List of (start, end, text) transcript segments.

        Returns:
            List of segment dicts with keys: start, end, text, scene_count.
        """
        if not scenes and not transcript:
            return []

        # Collect all boundary points
        boundaries = set()
        for start, end in scenes:
            boundaries.add(start)
            boundaries.add(end)

        # If no scenes, create boundaries from transcript
        if not boundaries and transcript:
            boundaries.add(transcript[0][0])
            boundaries.add(transcript[-1][1])

        boundaries = sorted(boundaries)

        # Create candidate time windows
        if len(boundaries) < 2:
            if transcript:
                boundaries = [transcript[0][0], transcript[-1][1]]
            else:
                return []

        # Build segments by grouping adjacent scenes within duration limits
        merged = []
        i = 0
        while i < len(boundaries) - 1:
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1]
            scene_count = 1
            j = i + 1

            # Extend segment if too short
            while (seg_end - seg_start) < self.min_clip_duration and j < len(boundaries) - 1:
                j += 1
                seg_end = boundaries[j]
                scene_count += 1

            # Cap at max duration
            if (seg_end - seg_start) > self.max_clip_duration:
                seg_end = seg_start + self.max_clip_duration

            # Collect transcript text for this time window
            text_parts = []
            for t_start, t_end, t_text in transcript:
                # Include if transcript segment overlaps with our window
                if t_start < seg_end and t_end > seg_start:
                    text_parts.append(t_text)

            duration = seg_end - seg_start
            if duration >= self.min_clip_duration:
                merged.append({
                    "start": seg_start,
                    "end": seg_end,
                    "text": " ".join(text_parts),
                    "scene_count": scene_count,
                    "duration": duration,
                })

            i = j  # advance past grouped scenes

        return merged

    def score_segments(self, segments: list[dict]) -> list[ClipCandidate]:
        """
        Score segments for engagement potential using LLM.

        Args:
            segments: List of segment dicts from merge_segments().

        Returns:
            List of ClipCandidate objects with engagement scores.
        """
        from llm_provider import generate_text

        candidates = []
        for seg in segments:
            transcript_text = seg["text"][:_MAX_PROMPT_LENGTH]

            if not transcript_text.strip():
                # No transcript — assign a low default score
                candidates.append(ClipCandidate(
                    start_time=seg["start"],
                    end_time=seg["end"],
                    duration=seg["duration"],
                    score=1.0,
                    transcript="",
                    reason="No speech detected in this segment",
                    scene_count=seg.get("scene_count", 0),
                ))
                continue

            prompt = (
                "Rate the following video transcript segment for viral potential "
                "on a scale of 1 to 10. Consider: Is it interesting, surprising, "
                "controversial, funny, or thought-provoking? Would someone share "
                "this clip?\n\n"
                f"TRANSCRIPT:\n{transcript_text}\n\n"
                "Respond with ONLY a JSON object: "
                '{"score": <number 1-10>, "reason": "<brief explanation>"}'
            )

            try:
                response = generate_text(prompt)
                score, reason = self._parse_score_response(response)
            except Exception as e:
                logger.warning(f"LLM scoring failed for segment at {seg['start']:.1f}s: {e}")
                score = 5.0
                reason = "Scoring unavailable"

            candidates.append(ClipCandidate(
                start_time=seg["start"],
                end_time=seg["end"],
                duration=seg["duration"],
                score=score,
                transcript=transcript_text,
                reason=reason,
                scene_count=seg.get("scene_count", 0),
            ))

        return candidates

    def _parse_score_response(self, response: str) -> tuple[float, str]:
        """Parse LLM response to extract score and reason."""
        # Try JSON parse first
        try:
            # Extract JSON from response (may have surrounding text)
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                data = json.loads(json_match.group())
                score = float(data.get("score", 5.0))
                reason = str(data.get("reason", ""))
                score = max(1.0, min(10.0, score))  # clamp
                return score, reason
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # Fallback: try to find a number in the response
        num_match = re.search(r'\b(\d+(?:\.\d+)?)\b', response)
        if num_match:
            score = float(num_match.group(1))
            score = max(1.0, min(10.0, score))
            return score, response[:200].strip()

        return 5.0, "Could not parse score"

    def find_highlights(self, video_path: str) -> list[ClipCandidate]:
        """
        Full pipeline: detect scenes → transcribe → merge → score → rank.

        Args:
            video_path: Path to video file.

        Returns:
            Top-N ClipCandidates sorted by engagement score (descending).
        """
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        logger.info(f"Finding highlights in {video_path}")

        # Step 1: Scene detection
        try:
            scenes = self.detect_scenes(video_path)
        except Exception as e:
            logger.warning(f"Scene detection failed: {e}. Using transcript-only mode.")
            scenes = []

        # Step 2: Transcription
        try:
            transcript = self.transcribe(video_path)
        except Exception as e:
            logger.warning(f"Transcription failed: {e}. Using scene-only mode.")
            transcript = []

        if not scenes and not transcript:
            logger.warning("No scenes or transcript found. No highlights to extract.")
            return []

        # Step 3: Merge
        segments = self.merge_segments(scenes, transcript)
        if not segments:
            logger.warning("No segments meeting duration criteria.")
            return []

        # Step 4: Score
        candidates = self.score_segments(segments)

        # Step 5: Rank and return top N
        candidates.sort(key=lambda c: c.score, reverse=True)
        top = candidates[:self.top_n]

        logger.info(
            f"Found {len(top)} highlights (top scores: "
            f"{', '.join(f'{c.score:.1f}' for c in top)})"
        )
        return top

    def split_clips(
        self,
        video_path: str,
        candidates: list[ClipCandidate],
        output_dir: str = ".",
        filename_template: str = "$VIDEO_NAME-clip-$SCENE_NUMBER",
    ) -> list[str]:
        """
        Split video into clips based on ClipCandidate metadata.

        Converts ClipCandidates to PySceneDetect scene_list format,
        then calls split_video_ffmpeg() for fast lossless extraction.

        Args:
            video_path: Path to source video file.
            candidates: List of ClipCandidates from find_highlights().
            output_dir: Directory for output clips.
            filename_template: Filename pattern with $VIDEO_NAME, $SCENE_NUMBER,
                $START_TIME, $END_TIME variables.

        Returns:
            List of output clip file paths (sorted by clip number).

        Raises:
            FileNotFoundError: If video_path doesn't exist.
            RuntimeError: If ffmpeg is not available.
        """
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if not candidates:
            logger.info("No candidates to split.")
            return []

        from scenedetect.video_splitter import split_video_ffmpeg, is_ffmpeg_available
        from scenedetect import open_video
        from scenedetect.frame_timecode import FrameTimecode

        if not is_ffmpeg_available():
            raise RuntimeError(
                "ffmpeg is not available. Install ffmpeg to use clip splitting."
            )

        os.makedirs(output_dir, exist_ok=True)

        # Open video to get framerate for FrameTimecode
        video = open_video(video_path)
        fps = video.frame_rate

        # Convert ClipCandidates to PySceneDetect scene_list format
        # Sort by start_time for sequential processing
        sorted_candidates = sorted(candidates, key=lambda c: c.start_time)
        scene_list = []
        for candidate in sorted_candidates:
            start_tc = FrameTimecode(candidate.start_time, fps=fps)
            end_tc = FrameTimecode(candidate.end_time, fps=fps)
            scene_list.append((start_tc, end_tc))

        logger.info(
            f"Splitting {len(scene_list)} clips from {video_path} "
            f"to {output_dir}"
        )

        ret = split_video_ffmpeg(
            input_video_path=video_path,
            scene_list=scene_list,
            output_dir=output_dir,
            output_file_template=filename_template,
            show_progress=False,
        )

        if ret != 0:
            logger.warning(f"ffmpeg returned non-zero exit code: {ret}")

        # Collect output files by scanning output_dir
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        output_files = sorted(
            f
            for f in (
                os.path.join(output_dir, name)
                for name in os.listdir(output_dir)
            )
            if os.path.isfile(f) and video_name in os.path.basename(f)
        )

        logger.info(f"Split complete: {len(output_files)} clips created.")
        return output_files

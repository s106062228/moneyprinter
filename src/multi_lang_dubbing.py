"""
Multi-Language Dubbing Module for MoneyPrinter.

Provides an automated pipeline to dub short-form videos into multiple
languages using:
  1. Speech-to-text (faster-whisper / AssemblyAI) for transcript extraction
  2. LLM-powered translation via the multi-provider system
  3. Text-to-speech synthesis in the target language
  4. Optional lip-sync via Wav2Lip (lazy import)
  5. FFmpeg-based audio replacement

Supported languages (ISO 639-1):
  en, es, fr, de, pt, ja, ko, zh, hi, ar, ru, it, nl, pl, tr, vi, th, id

Usage:
    dubber = VideoDubber()
    result = dubber.dub("video.mp4", target_lang="es", output_dir="/tmp/dubbed")
    results = dubber.batch_dub("video.mp4", ["es", "fr", "de"], "/tmp/dubbed")
"""

import os
import re
import json
import tempfile
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from mp_logger import get_logger
from validation import validate_path, validate_directory

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_SUPPORTED_LANGUAGES = frozenset({
    "en", "es", "fr", "de", "pt", "ja", "ko", "zh",
    "hi", "ar", "ru", "it", "nl", "pl", "tr", "vi", "th", "id",
})

_LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
    "hi": "Hindi", "ar": "Arabic", "ru": "Russian", "it": "Italian",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "vi": "Vietnamese",
    "th": "Thai", "id": "Indonesian",
}

_MAX_TRANSCRIPT_LENGTH = 50_000  # characters — safety cap for LLM translation
_MAX_VIDEO_DURATION = 600  # 10 minutes — cap for dubbing pipeline
_MAX_BATCH_LANGUAGES = 20  # prevent runaway batch jobs
_MAX_OUTPUT_PATH_LENGTH = 500


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TranscriptSegment:
    """A single segment of transcribed speech."""

    start: float  # seconds
    end: float    # seconds
    text: str

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text}

    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptSegment":
        start = float(data.get("start", 0))
        end = float(data.get("end", 0))
        text = str(data.get("text", ""))[:5000]
        if start < 0:
            start = 0
        if end < start:
            end = start
        return cls(start=start, end=end, text=text)


@dataclass
class DubResult:
    """Result of a dubbing operation for a single language."""

    source_path: str
    target_lang: str
    output_path: str
    success: bool
    transcript_segments: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DubResult":
        return cls(
            source_path=str(data.get("source_path", ""))[:_MAX_OUTPUT_PATH_LENGTH],
            target_lang=str(data.get("target_lang", "en"))[:10],
            output_path=str(data.get("output_path", ""))[:_MAX_OUTPUT_PATH_LENGTH],
            success=bool(data.get("success", False)),
            transcript_segments=min(int(data.get("transcript_segments", 0)), 10000),
            duration_seconds=min(float(data.get("duration_seconds", 0)), _MAX_VIDEO_DURATION),
            error=str(data.get("error", ""))[:500],
            created_at=str(data.get("created_at", ""))[:50],
        )


# ---------------------------------------------------------------------------
# Dubbing pipeline
# ---------------------------------------------------------------------------

class VideoDubber:
    """
    Automated video dubbing pipeline.

    Extracts speech from a video, translates it via the LLM provider,
    synthesizes speech in the target language, and merges the new audio
    back onto the original video.
    """

    def __init__(
        self,
        stt_backend: str = "faster_whisper",
        tts_backend: str = "kittentts",
        enable_lip_sync: bool = False,
    ):
        if stt_backend not in ("faster_whisper", "assemblyai"):
            raise ValueError(
                f"Unsupported STT backend: must be 'faster_whisper' or 'assemblyai'"
            )
        if tts_backend not in ("kittentts", "edge_tts"):
            raise ValueError(
                f"Unsupported TTS backend: must be 'kittentts' or 'edge_tts'"
            )

        self.stt_backend = stt_backend
        self.tts_backend = tts_backend
        self.enable_lip_sync = enable_lip_sync

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dub(
        self,
        video_path: str,
        target_lang: str,
        output_dir: str,
        source_lang: str = "en",
    ) -> DubResult:
        """
        Dub a video into a target language.

        Args:
            video_path: Path to the source video file.
            target_lang: ISO 639-1 language code for the target language.
            output_dir: Directory to save the dubbed video.
            source_lang: ISO 639-1 code of the source language (default: en).

        Returns:
            DubResult with success status and output path.
        """
        # --- Validate inputs ---
        video_path = self._validate_video_path(video_path)
        output_dir = self._validate_output_dir(output_dir)
        target_lang = self._validate_language(target_lang)
        source_lang = self._validate_language(source_lang)

        if target_lang == source_lang:
            return DubResult(
                source_path=video_path,
                target_lang=target_lang,
                output_path=video_path,
                success=True,
                error="Source and target languages are the same; no dubbing needed.",
            )

        logger.info(
            "Starting dub: %s → %s (%s → %s)",
            os.path.basename(video_path),
            target_lang,
            _LANGUAGE_NAMES.get(source_lang, source_lang),
            _LANGUAGE_NAMES.get(target_lang, target_lang),
        )

        try:
            # Step 1: Extract transcript
            segments = self._extract_transcript(video_path, source_lang)
            if not segments:
                return DubResult(
                    source_path=video_path,
                    target_lang=target_lang,
                    output_path="",
                    success=False,
                    error="No speech segments found in video.",
                )

            # Step 2: Translate transcript
            translated = self._translate_segments(segments, source_lang, target_lang)

            # Step 3: Synthesize speech
            audio_path = self._synthesize_speech(translated, target_lang, output_dir)

            # Step 4: Optional lip-sync
            if self.enable_lip_sync:
                audio_path = self._apply_lip_sync(video_path, audio_path, output_dir)

            # Step 5: Merge audio onto video
            output_filename = self._build_output_filename(video_path, target_lang)
            output_path = os.path.join(output_dir, output_filename)
            self._merge_audio(video_path, audio_path, output_path)

            # Step 6: Get duration
            duration = self._get_duration(output_path)

            logger.info("Dub complete: %s (%s)", output_filename, target_lang)

            return DubResult(
                source_path=video_path,
                target_lang=target_lang,
                output_path=output_path,
                success=True,
                transcript_segments=len(translated),
                duration_seconds=duration,
            )

        except Exception as exc:
            logger.error("Dub failed for %s: %s", target_lang, type(exc).__name__)
            return DubResult(
                source_path=video_path,
                target_lang=target_lang,
                output_path="",
                success=False,
                error=type(exc).__name__,
            )

    def batch_dub(
        self,
        video_path: str,
        target_langs: list[str],
        output_dir: str,
        source_lang: str = "en",
    ) -> list[DubResult]:
        """
        Dub a video into multiple languages.

        Args:
            video_path: Path to the source video file.
            target_langs: List of ISO 639-1 language codes.
            output_dir: Directory to save dubbed videos.
            source_lang: ISO 639-1 code of the source language.

        Returns:
            List of DubResult, one per target language.
        """
        if not isinstance(target_langs, list):
            raise ValueError("target_langs must be a list of language codes.")

        if len(target_langs) > _MAX_BATCH_LANGUAGES:
            raise ValueError(
                f"Too many languages ({len(target_langs)}); "
                f"maximum is {_MAX_BATCH_LANGUAGES}."
            )

        # Deduplicate while preserving order
        seen = set()
        unique_langs = []
        for lang in target_langs:
            lang_clean = str(lang).strip().lower()[:10]
            if lang_clean not in seen:
                seen.add(lang_clean)
                unique_langs.append(lang_clean)

        results = []
        for lang in unique_langs:
            result = self.dub(video_path, lang, output_dir, source_lang)
            results.append(result)

        return results

    def get_supported_languages(self) -> dict[str, str]:
        """Return a mapping of supported language codes to names."""
        return dict(_LANGUAGE_NAMES)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_video_path(path: str) -> str:
        if not path or not isinstance(path, str):
            raise ValueError("Video path must be a non-empty string.")
        if "\x00" in path:
            raise ValueError("Video path contains null bytes.")
        normalized = validate_path(path, must_exist=True)
        ext = os.path.splitext(normalized)[1].lower()
        if ext not in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
            raise ValueError(
                f"Unsupported video format: {ext}. "
                "Supported: .mp4, .mov, .webm, .mkv, .avi"
            )
        return normalized

    @staticmethod
    def _validate_output_dir(path: str) -> str:
        if not path or not isinstance(path, str):
            raise ValueError("Output directory must be a non-empty string.")
        if "\x00" in path:
            raise ValueError("Output directory contains null bytes.")
        if len(path) > _MAX_OUTPUT_PATH_LENGTH:
            raise ValueError("Output directory path is too long.")
        normalized = os.path.normpath(os.path.abspath(path))
        os.makedirs(normalized, exist_ok=True)
        return normalized

    @staticmethod
    def _validate_language(lang: str) -> str:
        if not lang or not isinstance(lang, str):
            raise ValueError("Language code must be a non-empty string.")
        lang = lang.strip().lower()[:10]
        if lang not in _SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language: '{lang}'. "
                f"Supported: {', '.join(sorted(_SUPPORTED_LANGUAGES))}"
            )
        return lang

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _extract_transcript(
        self, video_path: str, source_lang: str
    ) -> list[TranscriptSegment]:
        """Extract speech segments from video using the configured STT backend."""
        logger.info("Extracting transcript with %s...", self.stt_backend)

        if self.stt_backend == "faster_whisper":
            return self._extract_with_faster_whisper(video_path, source_lang)
        elif self.stt_backend == "assemblyai":
            return self._extract_with_assemblyai(video_path, source_lang)
        else:
            raise ValueError(f"Unknown STT backend: {self.stt_backend}")

    def _extract_with_faster_whisper(
        self, video_path: str, source_lang: str
    ) -> list[TranscriptSegment]:
        """Use faster-whisper for local speech-to-text."""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper is required for local STT. "
                "Install with: pip install faster-whisper"
            )

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments_iter, info = model.transcribe(
            video_path,
            language=source_lang if source_lang != "auto" else None,
            beam_size=5,
        )

        segments = []
        total_chars = 0
        for seg in segments_iter:
            text = seg.text.strip()
            if not text:
                continue
            total_chars += len(text)
            if total_chars > _MAX_TRANSCRIPT_LENGTH:
                logger.warning("Transcript length cap reached (%d chars).", _MAX_TRANSCRIPT_LENGTH)
                break
            segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=text,
            ))

        logger.info("Extracted %d segments (%d chars).", len(segments), total_chars)
        return segments

    def _extract_with_assemblyai(
        self, video_path: str, source_lang: str
    ) -> list[TranscriptSegment]:
        """Use AssemblyAI for cloud-based speech-to-text."""
        try:
            import assemblyai as aai
        except ImportError:
            raise ImportError(
                "assemblyai is required for cloud STT. "
                "Install with: pip install assemblyai"
            )

        from config import get_assembly_ai_api_key

        api_key = get_assembly_ai_api_key()
        if not api_key:
            raise ValueError("AssemblyAI API key not configured.")

        aai.settings.api_key = api_key
        config = aai.TranscriptionConfig(
            language_code=source_lang if source_lang != "auto" else None,
        )
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(video_path, config=config)

        if transcript.status == aai.TranscriptStatus.error:
            raise RuntimeError("AssemblyAI transcription failed.")

        segments = []
        total_chars = 0
        for utt in (transcript.utterances or []):
            text = utt.text.strip()
            if not text:
                continue
            total_chars += len(text)
            if total_chars > _MAX_TRANSCRIPT_LENGTH:
                break
            segments.append(TranscriptSegment(
                start=utt.start / 1000.0,
                end=utt.end / 1000.0,
                text=text,
            ))

        logger.info("Extracted %d segments via AssemblyAI.", len(segments))
        return segments

    def _translate_segments(
        self,
        segments: list[TranscriptSegment],
        source_lang: str,
        target_lang: str,
    ) -> list[TranscriptSegment]:
        """Translate transcript segments using the configured LLM provider."""
        logger.info(
            "Translating %d segments: %s → %s",
            len(segments), source_lang, target_lang,
        )

        from llm_provider import generate_text

        # Batch segments into a single translation prompt for efficiency
        source_lines = []
        for i, seg in enumerate(segments):
            source_lines.append(f"[{i}] {seg.text}")

        source_text = "\n".join(source_lines)
        if len(source_text) > _MAX_TRANSCRIPT_LENGTH:
            source_text = source_text[:_MAX_TRANSCRIPT_LENGTH]

        prompt = (
            f"Translate the following numbered text segments from "
            f"{_LANGUAGE_NAMES.get(source_lang, source_lang)} to "
            f"{_LANGUAGE_NAMES.get(target_lang, target_lang)}. "
            f"Preserve the segment numbers exactly as [N]. "
            f"Only output the translated segments, nothing else.\n\n"
            f"{source_text}"
        )

        response = generate_text(prompt)

        # Parse translated segments
        translated = self._parse_translation_response(response, segments)
        logger.info("Translated %d segments.", len(translated))
        return translated

    @staticmethod
    def _parse_translation_response(
        response: str,
        original_segments: list[TranscriptSegment],
    ) -> list[TranscriptSegment]:
        """Parse LLM translation response back into TranscriptSegment list."""
        if not response:
            return original_segments  # fallback to original

        # Parse lines matching [N] pattern
        translated_map: dict[int, str] = {}
        pattern = re.compile(r"^\[(\d+)\]\s*(.+)$", re.MULTILINE)
        for match in pattern.finditer(response):
            idx = int(match.group(1))
            text = match.group(2).strip()
            if 0 <= idx < len(original_segments) and text:
                translated_map[idx] = text[:5000]

        # Build translated segment list, falling back to original text
        result = []
        for i, seg in enumerate(original_segments):
            result.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=translated_map.get(i, seg.text),
            ))
        return result

    def _synthesize_speech(
        self,
        segments: list[TranscriptSegment],
        target_lang: str,
        output_dir: str,
    ) -> str:
        """Synthesize translated text into audio."""
        logger.info("Synthesizing speech in %s...", _LANGUAGE_NAMES.get(target_lang, target_lang))

        # Combine all segment text for full synthesis
        full_text = " ".join(seg.text for seg in segments)
        if not full_text.strip():
            raise ValueError("No text to synthesize.")

        if self.tts_backend == "kittentts":
            return self._synthesize_with_kittentts(full_text, target_lang, output_dir)
        elif self.tts_backend == "edge_tts":
            return self._synthesize_with_edge_tts(full_text, target_lang, output_dir)
        else:
            raise ValueError(f"Unknown TTS backend: {self.tts_backend}")

    def _synthesize_with_kittentts(
        self, text: str, target_lang: str, output_dir: str
    ) -> str:
        """Synthesize using KittenTTS."""
        try:
            from classes.Tts import Tts
        except ImportError:
            raise ImportError("KittenTTS is required. Install with: pip install kittentts")

        audio_path = os.path.join(output_dir, f"dubbed_audio_{target_lang}.wav")
        tts = Tts()
        tts.synthesize(text, audio_path)
        return audio_path

    def _synthesize_with_edge_tts(
        self, text: str, target_lang: str, output_dir: str
    ) -> str:
        """Synthesize using edge-tts (Microsoft Edge TTS, free, multi-language)."""
        try:
            import edge_tts
            import asyncio
        except ImportError:
            raise ImportError(
                "edge-tts is required for multi-language TTS. "
                "Install with: pip install edge-tts"
            )

        voice = _get_edge_tts_voice(target_lang)
        audio_path = os.path.join(output_dir, f"dubbed_audio_{target_lang}.mp3")

        async def _synthesize():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(audio_path)

        asyncio.run(_synthesize())
        return audio_path

    def _apply_lip_sync(
        self, video_path: str, audio_path: str, output_dir: str
    ) -> str:
        """Apply Wav2Lip lip-sync (optional, lazy import)."""
        logger.info("Applying lip-sync with Wav2Lip...")
        try:
            # Wav2Lip is expected as a local checkout or pip package
            from wav2lip import inference as wav2lip_inference
        except ImportError:
            logger.warning(
                "Wav2Lip not installed; skipping lip-sync. "
                "See https://github.com/Rudrabha/Wav2Lip for installation."
            )
            return audio_path

        output_path = os.path.join(output_dir, "lip_synced.mp4")
        wav2lip_inference.run(
            face=video_path,
            audio=audio_path,
            outfile=output_path,
        )
        return output_path

    @staticmethod
    def _merge_audio(
        video_path: str, audio_path: str, output_path: str
    ) -> None:
        """Replace video audio track using FFmpeg."""
        import subprocess

        from ffmpeg_utils import check_ffmpeg

        check_ffmpeg()

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError("FFmpeg audio merge failed.")

    @staticmethod
    def _get_duration(video_path: str) -> float:
        """Get video duration in seconds."""
        try:
            from ffmpeg_utils import get_video_info

            info = get_video_info(video_path)
            return info.duration if info else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _build_output_filename(video_path: str, target_lang: str) -> str:
        """Build a safe output filename for the dubbed video."""
        base = os.path.splitext(os.path.basename(video_path))[0]
        # Sanitize: keep only alphanumeric, dash, underscore
        safe_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", base)[:100]
        return f"{safe_base}_{target_lang}.mp4"


# ---------------------------------------------------------------------------
# Edge TTS voice mapping
# ---------------------------------------------------------------------------

_EDGE_TTS_VOICES = {
    "en": "en-US-AriaNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "hi": "hi-IN-SwaraNeural",
    "ar": "ar-SA-ZariyahNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "it": "it-IT-ElsaNeural",
    "nl": "nl-NL-ColetteNeural",
    "pl": "pl-PL-ZofiaNeural",
    "tr": "tr-TR-EmelNeural",
    "vi": "vi-VN-HoaiMyNeural",
    "th": "th-TH-PremwadeeNeural",
    "id": "id-ID-GadisNeural",
}


def _get_edge_tts_voice(lang: str) -> str:
    """Get the best Edge TTS voice for a language code."""
    voice = _EDGE_TTS_VOICES.get(lang)
    if not voice:
        raise ValueError(f"No Edge TTS voice configured for language: {lang}")
    return voice


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def get_dubbing_config() -> dict:
    """Read dubbing configuration from config.json."""
    from config import _get

    return _get("dubbing", {})


def get_dubbing_enabled() -> bool:
    """Check if dubbing is enabled in config."""
    return bool(get_dubbing_config().get("enabled", False))


def get_dubbing_default_languages() -> list[str]:
    """Get default target languages from config."""
    langs = get_dubbing_config().get("default_languages", ["es", "fr", "de"])
    if not isinstance(langs, list):
        return ["es", "fr", "de"]
    # Validate each
    valid = []
    for lang in langs[:_MAX_BATCH_LANGUAGES]:
        lang = str(lang).strip().lower()[:10]
        if lang in _SUPPORTED_LANGUAGES:
            valid.append(lang)
    return valid or ["es", "fr", "de"]


def get_dubbing_stt_backend() -> str:
    """Get configured STT backend."""
    backend = str(get_dubbing_config().get("stt_backend", "faster_whisper"))[:30]
    if backend not in ("faster_whisper", "assemblyai"):
        return "faster_whisper"
    return backend


def get_dubbing_tts_backend() -> str:
    """Get configured TTS backend."""
    backend = str(get_dubbing_config().get("tts_backend", "edge_tts"))[:30]
    if backend not in ("kittentts", "edge_tts"):
        return "edge_tts"
    return backend


def get_dubbing_lip_sync_enabled() -> bool:
    """Check if lip-sync is enabled."""
    return bool(get_dubbing_config().get("lip_sync", False))

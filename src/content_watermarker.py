"""
Content Watermarker for MoneyPrinter.

Embeds and detects invisible video watermarks using Meta's VideoSeal library.
VideoSeal is an optional heavy dependency — the module degrades gracefully when
it is not installed (embed/detect raise RuntimeError).

Usage:
    from content_watermarker import ContentWatermarker

    wm = ContentWatermarker(strength=0.2, message_prefix="MPV2")
    result = wm.embed("video.mp4", message="batch-001")
    print(result.embedded)   # True
    print(result.file_path)  # path to watermarked file

    result = wm.detect("video_wm.mp4")
    print(result.detected)   # True
    print(result.message)    # decoded watermark message
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from mp_logger import get_logger
from config import _get

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy optional imports — set to None if not available
# ---------------------------------------------------------------------------

try:
    import videoseal  # type: ignore
    _VIDEOSEAL_AVAILABLE = True
except Exception:
    videoseal = None  # type: ignore
    _VIDEOSEAL_AVAILABLE = False

try:
    import torch  # type: ignore
    _TORCH_AVAILABLE = True
except Exception:
    torch = None  # type: ignore
    _TORCH_AVAILABLE = False

try:
    import torchvision  # type: ignore
    _TORCHVISION_AVAILABLE = True
except Exception:
    torchvision = None  # type: ignore
    _TORCHVISION_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_MESSAGE_BYTES = 32          # 256 bits
_MIN_STRENGTH = 0.05
_MAX_STRENGTH = 1.0
_DEFAULT_STRENGTH = 0.2
_MAX_PATH_LENGTH = 1024
_SUPPORTED_FORMATS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})

_WM_SUFFIX = "_wm"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class WatermarkResult:
    """Result of a watermark embed or detect operation."""

    embedded: bool = False          # True if watermark was successfully embedded
    detected: bool = False          # True if watermark was detected
    message: str = ""               # The watermark message (embedded or decoded)
    strength: float = _DEFAULT_STRENGTH  # Watermark strength used
    file_path: str = ""             # Path to watermarked file or input file
    confidence: float = 0.0         # Detection confidence in [0.0, 1.0]
    error: str = ""                 # Empty string if no error


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ContentWatermarker:
    """Embed and detect invisible watermarks in video files via VideoSeal."""

    def __init__(
        self,
        strength: float = _DEFAULT_STRENGTH,
        message_prefix: str = "MPV2",
    ):
        """Initialise the watermarker.

        Args:
            strength:       Watermark strength in [_MIN_STRENGTH, _MAX_STRENGTH].
                            Overridden by config key "watermark.strength" when set.
            message_prefix: Prefix prepended to each watermark message.
                            Overridden by config key "watermark.message_prefix".
        """
        # Config overrides constructor defaults
        cfg_strength = _get("watermark.strength", None)
        if cfg_strength is not None:
            try:
                strength = float(cfg_strength)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid watermark.strength in config (%r); using default.", cfg_strength
                )

        cfg_prefix = _get("watermark.message_prefix", None)
        if cfg_prefix is not None and isinstance(cfg_prefix, str):
            message_prefix = cfg_prefix

        self.strength = self._clamp_strength(strength)
        self.message_prefix = message_prefix
        self._model = None  # lazy singleton

        logger.debug(
            "ContentWatermarker init: strength=%.3f prefix=%r",
            self.strength,
            self.message_prefix,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(
        self,
        video_path: str,
        message: str = "",
        output_path: str = "",
    ) -> WatermarkResult:
        """Embed an invisible watermark into *video_path*.

        Args:
            video_path:  Path to the source video file.
            message:     Watermark payload.  The final payload stored in the
                         video is ``message_prefix + message``.  If empty, only
                         the prefix is embedded.
            output_path: Destination path for the watermarked video.  When
                         omitted an auto-generated path is used (same directory,
                         ``_wm`` suffix before the extension).

        Returns:
            WatermarkResult with embedded=True and file_path set on success, or
            embedded=False and a non-empty error string on failure.
        """
        try:
            self._validate_path(video_path)
        except (ValueError, FileNotFoundError) as exc:
            return WatermarkResult(
                embedded=False,
                file_path=video_path,
                strength=self.strength,
                error=str(exc),
            )

        # Validate message
        full_message = self.message_prefix + message
        try:
            _validate_message(full_message)
        except ValueError as exc:
            return WatermarkResult(
                embedded=False,
                file_path=video_path,
                strength=self.strength,
                error=str(exc),
            )

        # Check dependency
        if not _VIDEOSEAL_AVAILABLE:
            raise RuntimeError(
                "videoseal is not installed. "
                "Install it to use watermarking: pip install videoseal"
            )

        # Resolve output path
        if not output_path:
            output_path = _auto_output_path(video_path)

        # Load model
        try:
            model = self._load_model()
        except Exception as exc:
            logger.error("Failed to load VideoSeal model: %s", exc)
            return WatermarkResult(
                embedded=False,
                file_path=video_path,
                strength=self.strength,
                error=f"Model load failed: {exc}",
            )

        # Read video frames
        try:
            frames, audio, info = torchvision.io.read_video(video_path, pts_unit="sec")
        except Exception as exc:
            logger.error("Failed to read video %r: %s", video_path, exc)
            return WatermarkResult(
                embedded=False,
                file_path=video_path,
                strength=self.strength,
                error=f"Video read failed: {exc}",
            )

        # Embed watermark
        try:
            # frames shape: (T, H, W, C) — convert to (T, C, H, W) float for model
            frames_float = frames.permute(0, 3, 1, 2).float() / 255.0
            wm_frames = model.embed(frames_float, full_message)
            # Convert back to uint8 (T, H, W, C)
            wm_frames_uint8 = (wm_frames.clamp(0, 1) * 255).byte().permute(0, 2, 3, 1)
        except Exception as exc:
            logger.error("Watermark embed failed: %s", exc)
            return WatermarkResult(
                embedded=False,
                file_path=video_path,
                strength=self.strength,
                error=f"Embed failed: {exc}",
            )

        # Write output
        try:
            fps = info.get("video_fps", 30)
            torchvision.io.write_video(output_path, wm_frames_uint8, fps)
        except Exception as exc:
            logger.error("Failed to write watermarked video to %r: %s", output_path, exc)
            return WatermarkResult(
                embedded=False,
                file_path=video_path,
                strength=self.strength,
                error=f"Video write failed: {exc}",
            )

        logger.info(
            "Watermark embedded: %r -> %r (strength=%.3f)",
            video_path,
            output_path,
            self.strength,
        )
        return WatermarkResult(
            embedded=True,
            detected=False,
            message=full_message,
            strength=self.strength,
            file_path=output_path,
            confidence=0.0,
            error="",
        )

    def detect(self, video_path: str) -> WatermarkResult:
        """Detect and decode a watermark from *video_path*.

        Args:
            video_path: Path to the video file to examine.

        Returns:
            WatermarkResult with detected=True and decoded message when a
            watermark is found, or detected=False when none is detected.
        """
        try:
            self._validate_path(video_path)
        except (ValueError, FileNotFoundError) as exc:
            return WatermarkResult(
                detected=False,
                file_path=video_path,
                strength=self.strength,
                error=str(exc),
            )

        if not _VIDEOSEAL_AVAILABLE:
            raise RuntimeError(
                "videoseal is not installed. "
                "Install it to use watermarking: pip install videoseal"
            )

        # Load model
        try:
            model = self._load_model()
        except Exception as exc:
            logger.error("Failed to load VideoSeal model: %s", exc)
            return WatermarkResult(
                detected=False,
                file_path=video_path,
                strength=self.strength,
                error=f"Model load failed: {exc}",
            )

        # Read video frames
        try:
            frames, _audio, _info = torchvision.io.read_video(video_path, pts_unit="sec")
        except Exception as exc:
            logger.error("Failed to read video %r: %s", video_path, exc)
            return WatermarkResult(
                detected=False,
                file_path=video_path,
                strength=self.strength,
                error=f"Video read failed: {exc}",
            )

        # Run detection
        try:
            frames_float = frames.permute(0, 3, 1, 2).float() / 255.0
            detection = model.detect(frames_float)

            # VideoSeal returns a dict with "detected" (bool) and "message" (str)
            # and optionally "confidence" (float).
            is_detected = bool(detection.get("detected", False))
            decoded_msg = str(detection.get("message", ""))
            confidence = float(detection.get("confidence", 1.0 if is_detected else 0.0))
        except Exception as exc:
            logger.error("Watermark detection failed: %s", exc)
            return WatermarkResult(
                detected=False,
                file_path=video_path,
                strength=self.strength,
                error=f"Detection failed: {exc}",
            )

        if is_detected:
            logger.info(
                "Watermark detected in %r: message=%r confidence=%.3f",
                video_path,
                decoded_msg,
                confidence,
            )
        else:
            logger.debug("No watermark detected in %r", video_path)

        return WatermarkResult(
            embedded=False,
            detected=is_detected,
            message=decoded_msg,
            strength=self.strength,
            file_path=video_path,
            confidence=confidence,
            error="",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self):
        """Lazy singleton: load the VideoSeal model once and cache it.

        Returns:
            The loaded videoseal model object.

        Raises:
            RuntimeError: If videoseal is not available.
        """
        if not _VIDEOSEAL_AVAILABLE:
            raise RuntimeError("videoseal is not installed.")

        if self._model is None:
            model_name = _get("watermark.model", "videoseal")
            logger.debug("Loading VideoSeal model %r …", model_name)
            self._model = videoseal.load(model_name)
            self._model.eval()
            logger.info("VideoSeal model %r loaded.", model_name)

        return self._model

    def _validate_path(self, path: str) -> None:
        """Validate a video file path.

        Args:
            path: Path string to validate.

        Raises:
            ValueError:       For null bytes, excessive length, unsupported extension.
            FileNotFoundError: When the file does not exist.
        """
        if not isinstance(path, str):
            raise ValueError(f"video_path must be a str, got {type(path).__name__}")
        if "\x00" in path:
            raise ValueError("video_path must not contain null bytes")
        if len(path) > _MAX_PATH_LENGTH:
            raise ValueError(
                f"video_path exceeds maximum length of {_MAX_PATH_LENGTH} characters"
            )
        ext = os.path.splitext(path)[1].lower()
        if ext not in _SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported video format {ext!r}. "
                f"Supported: {sorted(_SUPPORTED_FORMATS)}"
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"Video file not found: {path!r}")

    @staticmethod
    def _clamp_strength(strength: float) -> float:
        """Clamp *strength* to [_MIN_STRENGTH, _MAX_STRENGTH]."""
        return max(_MIN_STRENGTH, min(_MAX_STRENGTH, float(strength)))


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _validate_message(message: str) -> None:
    """Validate that *message* fits within _MAX_MESSAGE_BYTES when UTF-8 encoded.

    Args:
        message: Watermark payload string.

    Raises:
        ValueError: If the encoded message exceeds _MAX_MESSAGE_BYTES.
    """
    encoded = message.encode("utf-8")
    if len(encoded) > _MAX_MESSAGE_BYTES:
        raise ValueError(
            f"Watermark message is {len(encoded)} bytes after UTF-8 encoding; "
            f"maximum is {_MAX_MESSAGE_BYTES} bytes."
        )


def _auto_output_path(video_path: str) -> str:
    """Generate an output path by inserting *_wm* before the file extension.

    Example: ``/tmp/clip.mp4`` → ``/tmp/clip_wm.mp4``
    """
    base, ext = os.path.splitext(video_path)
    return base + _WM_SUFFIX + ext

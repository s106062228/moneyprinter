"""
Video Template System for MoneyPrinter.

Provides reusable video intro/outro templates rendered as MoviePy v2 clips.
Templates are defined as JSON configs and rendered via CompositeVideoClip with
text overlays, solid/gradient backgrounds, and fade transitions.

Stores template state in .mp/video_templates.json using the standard
atomic-write pattern.
"""

import os
import json
import uuid
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from config import ROOT_DIR
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_DURATION = 30.0
_MIN_DURATION = 0.5
_MAX_TEXT_LEN = 500
_MAX_FADE_DURATION = 5.0
_MIN_FADE_DURATION = 0.0
_MAX_FONT_SIZE = 500
_MIN_FONT_SIZE = 8
_DEFAULT_RESOLUTION = (1080, 1920)
_VALID_TEMPLATE_TYPES = frozenset({"intro", "outro"})
_STORAGE_FILE = ".mp/video_templates.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value, lo, hi):
    """Return value clamped between lo and hi (inclusive)."""
    return max(lo, min(hi, value))


def _is_valid_hex_color(color: str) -> bool:
    """Return True if color is a valid hex color string like #RRGGBB."""
    if not isinstance(color, str):
        return False
    s = color.strip()
    if not s.startswith("#"):
        return False
    body = s[1:]
    if len(body) not in (3, 6):
        return False
    return all(c in "0123456789abcdefABCDEF" for c in body)


def _normalize_hex(color: str) -> str:
    """Normalize 3-digit hex to 6-digit and uppercase."""
    s = color.strip()
    body = s[1:]
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    return "#" + body.upper()


def _hex_to_rgb(color: str) -> tuple:
    """Convert hex color string to (R, G, B) tuple."""
    s = _normalize_hex(color)
    body = s[1:]
    r = int(body[0:2], 16)
    g = int(body[2:4], 16)
    b = int(body[4:6], 16)
    return (r, g, b)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class VideoTemplate:
    """
    Represents a reusable video intro/outro template.

    Fields:
        template_id: Unique identifier for this template.
        name:        Human-readable name.
        template_type: "intro" or "outro".
        duration:    Clip duration in seconds (clamped to [0.5, 30]).
        text:        Text overlay to display.
        font_size:   Font size for the text overlay.
        text_color:  Hex color string for the text (e.g. "#FFFFFF").
        bg_color:    Hex color string for the background (e.g. "#000000").
        bg_gradient: Optional list of exactly 2 hex color strings for a
                     vertical gradient background.
        bg_image_path: Optional path to a background image.
        fade_duration: Fade-in / fade-out duration in seconds.
        resolution:  (width, height) tuple for the output clip.
    """

    template_id: str
    name: str
    template_type: str  # "intro" | "outro"
    text: str
    duration: float = 3.0
    font_size: int = 80
    text_color: str = "#FFFFFF"
    bg_color: str = "#000000"
    bg_gradient: Optional[list] = None  # list of 2 hex strings
    bg_image_path: Optional[str] = None
    fade_duration: float = 0.5
    resolution: tuple = field(default_factory=lambda: _DEFAULT_RESOLUTION)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to a JSON-serializable dict."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "template_type": self.template_type,
            "text": self.text,
            "duration": self.duration,
            "font_size": self.font_size,
            "text_color": self.text_color,
            "bg_color": self.bg_color,
            "bg_gradient": self.bg_gradient,
            "bg_image_path": self.bg_image_path,
            "fade_duration": self.fade_duration,
            "resolution": list(self.resolution),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VideoTemplate":
        """
        Deserialize from a dict with validation and value clamping.

        Raises:
            ValueError: If required fields are invalid or out of range.
        """
        if not isinstance(data, dict):
            raise ValueError("data must be a dict")

        template_id = str(data.get("template_id", "")).strip()
        name = str(data.get("name", "")).strip()

        template_type = str(data.get("template_type", "intro")).strip()
        if template_type not in _VALID_TEMPLATE_TYPES:
            raise ValueError(
                f"template_type must be one of {sorted(_VALID_TEMPLATE_TYPES)}, "
                f"got {template_type!r}"
            )

        text_raw = data.get("text", "")
        if not isinstance(text_raw, str):
            raise ValueError("text must be a string")
        text = text_raw[:_MAX_TEXT_LEN]

        # duration
        try:
            duration = float(data.get("duration", 3.0))
        except (TypeError, ValueError):
            raise ValueError("duration must be a number")
        duration = _clamp(duration, _MIN_DURATION, _MAX_DURATION)

        # font_size
        try:
            font_size = int(data.get("font_size", 80))
        except (TypeError, ValueError):
            raise ValueError("font_size must be an integer")
        font_size = _clamp(font_size, _MIN_FONT_SIZE, _MAX_FONT_SIZE)

        # text_color
        text_color = str(data.get("text_color", "#FFFFFF")).strip()
        if not _is_valid_hex_color(text_color):
            raise ValueError(f"text_color must be a valid hex color, got {text_color!r}")
        text_color = _normalize_hex(text_color)

        # bg_color
        bg_color = str(data.get("bg_color", "#000000")).strip()
        if not _is_valid_hex_color(bg_color):
            raise ValueError(f"bg_color must be a valid hex color, got {bg_color!r}")
        bg_color = _normalize_hex(bg_color)

        # bg_gradient (optional)
        bg_gradient = data.get("bg_gradient", None)
        if bg_gradient is not None:
            if not isinstance(bg_gradient, (list, tuple)) or len(bg_gradient) != 2:
                raise ValueError("bg_gradient must be a list of exactly 2 hex color strings")
            for i, c in enumerate(bg_gradient):
                if not _is_valid_hex_color(c):
                    raise ValueError(
                        f"bg_gradient[{i}] must be a valid hex color, got {c!r}"
                    )
            bg_gradient = [_normalize_hex(c) for c in bg_gradient]

        # bg_image_path (optional)
        bg_image_path = data.get("bg_image_path", None)
        if bg_image_path is not None:
            bg_image_path = str(bg_image_path)

        # fade_duration
        try:
            fade_duration = float(data.get("fade_duration", 0.5))
        except (TypeError, ValueError):
            raise ValueError("fade_duration must be a number")
        fade_duration = _clamp(fade_duration, _MIN_FADE_DURATION, _MAX_FADE_DURATION)

        # resolution
        raw_res = data.get("resolution", list(_DEFAULT_RESOLUTION))
        try:
            res = tuple(int(x) for x in raw_res)
            if len(res) != 2:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("resolution must be a sequence of two integers")
        if res[0] <= 0 or res[1] <= 0:
            raise ValueError("resolution dimensions must be positive integers")

        return cls(
            template_id=template_id,
            name=name,
            template_type=template_type,
            text=text,
            duration=duration,
            font_size=font_size,
            text_color=text_color,
            bg_color=bg_color,
            bg_gradient=bg_gradient,
            bg_image_path=bg_image_path,
            fade_duration=fade_duration,
            resolution=res,
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class VideoTemplateManager:
    """Manages video templates with JSON file persistence."""

    def __init__(self) -> None:
        self._path = os.path.join(ROOT_DIR, _STORAGE_FILE)

    # ------------------------------------------------------------------
    # Internal persistence helpers
    # ------------------------------------------------------------------

    def _load_templates(self) -> list:
        """Read all templates from disk. Returns empty list on missing/corrupt file."""
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            raw = data.get("templates", []) if isinstance(data, dict) else []
            result = []
            for item in raw:
                try:
                    result.append(VideoTemplate.from_dict(item))
                except (ValueError, TypeError):
                    logger.warning("Skipped invalid template record during load.")
            return result
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            return []

    def _save_templates(self, templates: list) -> None:
        """Atomically persist all templates to disk using tempfile + os.replace."""
        dir_name = os.path.dirname(self._path)
        os.makedirs(dir_name, exist_ok=True)
        payload = {"templates": [t.to_dict() for t in templates]}
        raw = json.dumps(payload, indent=2, default=str)
        fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            os.write(fd, raw.encode())
            os.close(fd)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    # ------------------------------------------------------------------
    # Public CRUD API
    # ------------------------------------------------------------------

    def save_template(self, template: VideoTemplate) -> None:
        """
        Persist a template. Overwrites any existing template with the same
        template_id; otherwise appends.
        """
        all_templates = self._load_templates()
        # Replace existing or append
        replaced = False
        for i, t in enumerate(all_templates):
            if t.template_id == template.template_id:
                all_templates[i] = template
                replaced = True
                break
        if not replaced:
            all_templates.append(template)
        self._save_templates(all_templates)
        logger.info(
            "%s template %s (%s).",
            "Updated" if replaced else "Saved",
            template.template_id,
            template.name,
        )

    def get_template(self, template_id: str) -> Optional[VideoTemplate]:
        """Return the VideoTemplate with the given ID, or None if not found."""
        for t in self._load_templates():
            if t.template_id == template_id:
                return t
        return None

    def list_templates(self, template_type: Optional[str] = None) -> list:
        """
        Return all templates, optionally filtered by template_type.

        Args:
            template_type: If provided, only return templates of this type
                           ("intro" or "outro").
        """
        all_templates = self._load_templates()
        if template_type is not None:
            all_templates = [t for t in all_templates if t.template_type == template_type]
        return all_templates

    def delete_template(self, template_id: str) -> bool:
        """
        Delete a template by ID.

        Returns:
            True if the template was found and removed, False otherwise.
        """
        all_templates = self._load_templates()
        new_templates = [t for t in all_templates if t.template_id != template_id]
        if len(new_templates) == len(all_templates):
            return False
        self._save_templates(new_templates)
        logger.info("Deleted template %s.", template_id)
        return True

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_clip(self, template: VideoTemplate):
        """
        Render a VideoTemplate as a MoviePy v2 VideoClip.

        Lazy-imports moviepy so this module can be imported in test environments
        without moviepy installed.

        Steps:
          1. Build a background: gradient ImageClip, bg ImageClip, or ColorClip.
          2. Add a centered TextClip overlay.
          3. Compose with CompositeVideoClip.
          4. Apply fade in/out effects.

        Returns:
            A moviepy VideoClip instance.
        """
        try:
            from moviepy import (
                ColorClip,
                ImageClip,
                TextClip,
                CompositeVideoClip,
            )
            import moviepy.video.fx as vfx
        except ImportError as exc:
            raise ImportError(
                "moviepy is required to render clips. "
                "Install it with: pip install moviepy"
            ) from exc

        width, height = template.resolution
        duration = template.duration

        # --- Background ---
        if template.bg_gradient is not None:
            # Build a vertical gradient as a numpy array
            try:
                import numpy as np
            except ImportError as exc:
                raise ImportError(
                    "numpy is required for gradient backgrounds."
                ) from exc

            color1 = _hex_to_rgb(template.bg_gradient[0])
            color2 = _hex_to_rgb(template.bg_gradient[1])
            gradient = np.zeros((height, width, 3), dtype="uint8")
            for row in range(height):
                t_frac = row / max(height - 1, 1)
                r = int(color1[0] + (color2[0] - color1[0]) * t_frac)
                g = int(color1[1] + (color2[1] - color1[1]) * t_frac)
                b = int(color1[2] + (color2[2] - color1[2]) * t_frac)
                gradient[row, :] = [r, g, b]
            bg_clip = ImageClip(gradient).with_duration(duration)

        elif template.bg_image_path is not None:
            bg_clip = (
                ImageClip(template.bg_image_path)
                .resized((width, height))
                .with_duration(duration)
            )

        else:
            # Solid color background
            bg_rgb = _hex_to_rgb(template.bg_color)
            bg_clip = ColorClip(size=(width, height), color=bg_rgb).with_duration(duration)

        # --- Text overlay ---
        text_rgb = _hex_to_rgb(template.text_color)
        text_clip = (
            TextClip(
                text=template.text,
                font_size=template.font_size,
                color=text_rgb,
                size=(width, None),
                method="caption",
            )
            .with_duration(duration)
            .with_position("center")
        )

        # --- Compose ---
        composite = CompositeVideoClip([bg_clip, text_clip], size=(width, height))

        # --- Fade in / out ---
        if template.fade_duration > 0:
            composite = composite.with_effects(
                [
                    vfx.CrossFadeIn(template.fade_duration),
                    vfx.CrossFadeOut(template.fade_duration),
                ]
            )

        return composite

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def get_preset(self, name: str) -> VideoTemplate:
        """
        Return a built-in preset VideoTemplate.

        Available presets:
            "minimal"  — solid black background, white text, 3 s, 0.5 s fade.
            "gradient" — two-color gradient background, yellow text, 4 s, 0.5 s fade.
            "branded"  — image background placeholder, white text, 5 s, 1.0 s fade.

        Raises:
            ValueError: If the preset name is not recognized.
        """
        presets = {
            "minimal": VideoTemplate(
                template_id=f"preset-minimal-{uuid.uuid4().hex[:6]}",
                name="Minimal",
                template_type="intro",
                text="",
                duration=3.0,
                font_size=80,
                text_color="#FFFFFF",
                bg_color="#000000",
                bg_gradient=None,
                bg_image_path=None,
                fade_duration=0.5,
                resolution=_DEFAULT_RESOLUTION,
            ),
            "gradient": VideoTemplate(
                template_id=f"preset-gradient-{uuid.uuid4().hex[:6]}",
                name="Gradient",
                template_type="intro",
                text="",
                duration=4.0,
                font_size=80,
                text_color="#FFFF00",
                bg_color="#FF0050",
                bg_gradient=["#FF0050", "#FF00FF"],
                bg_image_path=None,
                fade_duration=0.5,
                resolution=_DEFAULT_RESOLUTION,
            ),
            "branded": VideoTemplate(
                template_id=f"preset-branded-{uuid.uuid4().hex[:6]}",
                name="Branded",
                template_type="intro",
                text="",
                duration=5.0,
                font_size=80,
                text_color="#FFFFFF",
                bg_color="#000000",
                bg_gradient=None,
                bg_image_path=None,
                fade_duration=1.0,
                resolution=_DEFAULT_RESOLUTION,
            ),
        }
        if name not in presets:
            raise ValueError(
                f"Unknown preset {name!r}. Available: {sorted(presets.keys())}"
            )
        return presets[name]

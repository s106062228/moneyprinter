"""
Thumbnail generator for MoneyPrinter.

Generates professional, click-worthy YouTube/TikTok thumbnails using Pillow.
Supports text overlays with outlines, gradient backgrounds, video frame
extraction, and multiple layout templates optimized for engagement.

Usage:
    from thumbnail import ThumbnailGenerator

    gen = ThumbnailGenerator()
    path = gen.generate(
        title="How I Made $10K in 30 Days",
        output_path="/path/to/thumbnail.png",
        style="bold",
    )

Configuration (config.json):
    "thumbnail": {
        "width": 1280,
        "height": 720,
        "font": "bold_font.ttf",
        "style": "bold",
        "gradient_colors": ["#FF0000", "#FF6600"],
        "text_color": "#FFFFFF",
        "outline_color": "#000000",
        "outline_width": 4
    }
"""

import os
import random
import tempfile
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import _get, ROOT_DIR, get_font, get_fonts_dir
from mp_logger import get_logger
from validation import validate_path, sanitize_filename

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants and limits
# ---------------------------------------------------------------------------

_MAX_TITLE_LENGTH = 200
_MAX_DIMENSION = 4096
_MIN_DIMENSION = 100
_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 720

# Predefined color palettes for different moods
_GRADIENT_PALETTES = {
    "bold": [("#FF0000", "#FF6600"), ("#FF0050", "#FF00FF"), ("#0066FF", "#00CCFF")],
    "calm": [("#1A1A2E", "#16213E"), ("#0F3460", "#533483"), ("#2C3E50", "#3498DB")],
    "money": [("#00C853", "#FFD700"), ("#1B5E20", "#4CAF50"), ("#FFD700", "#FF6F00")],
    "dark": [("#000000", "#333333"), ("#1A1A1A", "#4A4A4A"), ("#0D0D0D", "#2D2D2D")],
    "vibrant": [("#FF006E", "#8338EC"), ("#3A86FF", "#FF006E"), ("#FFBE0B", "#FB5607")],
}

_STYLES = {"bold", "calm", "money", "dark", "vibrant"}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_thumbnail_config() -> dict:
    """Returns the thumbnail configuration block."""
    return _get("thumbnail", {})


def get_thumbnail_width() -> int:
    """Returns configured thumbnail width (clamped to safe bounds)."""
    val = int(_get_thumbnail_config().get("width", _DEFAULT_WIDTH))
    return max(_MIN_DIMENSION, min(val, _MAX_DIMENSION))


def get_thumbnail_height() -> int:
    """Returns configured thumbnail height (clamped to safe bounds)."""
    val = int(_get_thumbnail_config().get("height", _DEFAULT_HEIGHT))
    return max(_MIN_DIMENSION, min(val, _MAX_DIMENSION))


def get_thumbnail_style() -> str:
    """Returns the configured thumbnail style."""
    style = _get_thumbnail_config().get("style", "bold")
    return style if style in _STYLES else "bold"


def get_text_color() -> str:
    """Returns the configured text color."""
    return _get_thumbnail_config().get("text_color", "#FFFFFF")


def get_outline_color() -> str:
    """Returns the configured outline color."""
    return _get_thumbnail_config().get("outline_color", "#000000")


def get_outline_width() -> int:
    """Returns the configured outline width (clamped 0-20)."""
    val = int(_get_thumbnail_config().get("outline_width", 4))
    return max(0, min(val, 20))


# ---------------------------------------------------------------------------
# Color utilities
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Converts a hex color string to an RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (255, 255, 255)
    try:
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def _interpolate_color(
    color1: Tuple[int, int, int],
    color2: Tuple[int, int, int],
    factor: float,
) -> Tuple[int, int, int]:
    """Linearly interpolates between two RGB colors."""
    return tuple(
        int(c1 + (c2 - c1) * factor) for c1, c2 in zip(color1, color2)
    )


# ---------------------------------------------------------------------------
# Drawing utilities
# ---------------------------------------------------------------------------

def _create_gradient(
    width: int,
    height: int,
    color1: str,
    color2: str,
    direction: str = "diagonal",
) -> Image.Image:
    """
    Creates a gradient background image.

    Args:
        width: Image width.
        height: Image height.
        color1: Start hex color.
        color2: End hex color.
        direction: 'horizontal', 'vertical', or 'diagonal'.

    Returns:
        PIL Image with gradient fill.
    """
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    rgb1 = _hex_to_rgb(color1)
    rgb2 = _hex_to_rgb(color2)

    if direction == "horizontal":
        for x in range(width):
            factor = x / max(width - 1, 1)
            color = _interpolate_color(rgb1, rgb2, factor)
            draw.line([(x, 0), (x, height)], fill=color)
    elif direction == "vertical":
        for y in range(height):
            factor = y / max(height - 1, 1)
            color = _interpolate_color(rgb1, rgb2, factor)
            draw.line([(0, y), (width, y)], fill=color)
    else:  # diagonal
        for y in range(height):
            for x in range(width):
                factor = (x / max(width - 1, 1) + y / max(height - 1, 1)) / 2
                color = _interpolate_color(rgb1, rgb2, factor)
                draw.point((x, y), fill=color)

    return img


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Loads the configured font at the given size.

    Falls back to default font if the configured font is not found.
    """
    font_name = get_font()
    fonts_dir = get_fonts_dir()

    if font_name:
        font_path = os.path.join(fonts_dir, font_name)
        if os.path.isfile(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except (IOError, OSError):
                logger.warning("Failed to load configured font, using default.")

    # Try common bold fonts
    fallback_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]

    for fallback in fallback_fonts:
        if os.path.isfile(fallback):
            try:
                return ImageFont.truetype(fallback, size)
            except (IOError, OSError):
                continue

    # Last resort: Pillow default font
    return ImageFont.load_default()


def _draw_text_with_outline(
    draw: ImageDraw.Draw,
    position: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str = "#FFFFFF",
    outline_color: str = "#000000",
    outline_width: int = 4,
) -> None:
    """
    Draws text with an outline/stroke effect for readability.

    Args:
        draw: ImageDraw instance.
        position: (x, y) position for the text.
        text: Text to draw.
        font: Font to use.
        fill: Text fill color (hex).
        outline_color: Outline color (hex).
        outline_width: Outline thickness in pixels.
    """
    x, y = position

    # Draw outline by rendering text offset in all directions
    if outline_width > 0:
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx * dx + dy * dy <= outline_width * outline_width:
                    draw.text(
                        (x + dx, y + dy),
                        text,
                        font=font,
                        fill=outline_color,
                    )

    # Draw main text on top
    draw.text(position, text, font=font, fill=fill)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """
    Word-wraps text to fit within a maximum pixel width.

    Args:
        text: The text to wrap.
        font: The font used for measurement.
        max_width: Maximum width in pixels.

    Returns:
        List of text lines.
    """
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = font.getbbox(test_line)
        line_width = bbox[2] - bbox[0]

        if line_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines if lines else [text]


# ---------------------------------------------------------------------------
# Thumbnail Generator
# ---------------------------------------------------------------------------

class ThumbnailGenerator:
    """
    Generates professional thumbnails for video content.

    Supports gradient backgrounds, text overlays with outlines,
    video frame extraction as backgrounds, and multiple layout styles.
    """

    def __init__(self):
        self.width = get_thumbnail_width()
        self.height = get_thumbnail_height()
        self.style = get_thumbnail_style()
        self.text_color = get_text_color()
        self.outline_color = get_outline_color()
        self.outline_width = get_outline_width()

    def generate(
        self,
        title: str,
        output_path: str,
        style: Optional[str] = None,
        video_path: Optional[str] = None,
        subtitle: Optional[str] = None,
    ) -> str:
        """
        Generates a thumbnail image.

        Args:
            title: Main text to display on the thumbnail.
            output_path: Where to save the generated thumbnail.
            style: Style preset ('bold', 'calm', 'money', 'dark', 'vibrant').
            video_path: Optional video file to extract a frame from as background.
            subtitle: Optional smaller text below the title.

        Returns:
            The absolute path to the generated thumbnail.

        Raises:
            ValueError: If title is empty or too long.
        """
        # Validate inputs
        if not title or not isinstance(title, str):
            raise ValueError("Title must be a non-empty string.")
        if len(title) > _MAX_TITLE_LENGTH:
            raise ValueError(
                f"Title exceeds maximum length of {_MAX_TITLE_LENGTH}."
            )
        if "\x00" in title or "\x00" in output_path:
            raise ValueError("Input contains null bytes.")

        active_style = style if style and style in _STYLES else self.style

        # Create background
        if video_path and os.path.isfile(video_path):
            bg = self._extract_frame(video_path)
        else:
            bg = self._create_styled_background(active_style)

        # Apply darkening overlay for text readability
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 140))
        bg = bg.convert("RGBA")
        bg = Image.alpha_composite(bg, overlay)
        bg = bg.convert("RGB")

        draw = ImageDraw.Draw(bg)

        # Calculate font sizes
        title_font_size = max(self.height // 8, 24)
        title_font = _load_font(title_font_size)

        # Wrap and center title text
        margin = int(self.width * 0.08)
        max_text_width = self.width - (margin * 2)
        lines = _wrap_text(title.upper(), title_font, max_text_width)

        # Limit to 4 lines max
        if len(lines) > 4:
            lines = lines[:4]
            lines[-1] = lines[-1][:50] + "..."

        # Calculate total text height
        line_heights = []
        for line in lines:
            bbox = title_font.getbbox(line)
            line_heights.append(bbox[3] - bbox[1])

        line_spacing = int(title_font_size * 0.3)
        total_text_height = (
            sum(line_heights) + line_spacing * (len(lines) - 1)
        )

        # Position text (vertically centered, with subtitle offset)
        subtitle_offset = self.height // 12 if subtitle else 0
        start_y = (self.height - total_text_height - subtitle_offset) // 2

        # Draw each line centered
        current_y = start_y
        for i, line in enumerate(lines):
            bbox = title_font.getbbox(line)
            line_width = bbox[2] - bbox[0]
            x = (self.width - line_width) // 2

            _draw_text_with_outline(
                draw,
                (x, current_y),
                line,
                title_font,
                fill=self.text_color,
                outline_color=self.outline_color,
                outline_width=self.outline_width,
            )
            current_y += line_heights[i] + line_spacing

        # Draw subtitle if provided
        if subtitle:
            sub_font_size = max(title_font_size // 2, 16)
            sub_font = _load_font(sub_font_size)
            sub_text = subtitle[:100]  # Limit subtitle length
            sub_bbox = sub_font.getbbox(sub_text)
            sub_width = sub_bbox[2] - sub_bbox[0]
            sub_x = (self.width - sub_width) // 2
            sub_y = current_y + line_spacing * 2

            _draw_text_with_outline(
                draw,
                (sub_x, sub_y),
                sub_text,
                sub_font,
                fill="#FFDD00",
                outline_color=self.outline_color,
                outline_width=max(self.outline_width // 2, 1),
            )

        # Add accent bar at bottom
        accent_color = _hex_to_rgb(
            _GRADIENT_PALETTES[active_style][0][0]
        )
        bar_height = max(self.height // 60, 4)
        draw.rectangle(
            [(0, self.height - bar_height), (self.width, self.height)],
            fill=accent_color,
        )

        # Ensure output directory exists
        output_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(output_dir, exist_ok=True)

        # Save atomically via temp file
        fd, tmp_path = tempfile.mkstemp(
            dir=output_dir, suffix=".png.tmp"
        )
        try:
            os.close(fd)
            bg.save(tmp_path, "PNG", optimize=True)
            os.replace(tmp_path, output_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(f"Thumbnail generated: {os.path.basename(output_path)}")
        return os.path.abspath(output_path)

    def generate_from_metadata(
        self,
        metadata: dict,
        output_dir: str,
        video_path: Optional[str] = None,
    ) -> str:
        """
        Generates a thumbnail from video metadata dict.

        Args:
            metadata: Dict with 'title' and optionally 'description'.
            output_dir: Directory to save the thumbnail in.
            video_path: Optional video to extract frame from.

        Returns:
            Path to the generated thumbnail.

        Raises:
            ValueError: If output_dir is invalid or contains null bytes.
        """
        if not output_dir or not isinstance(output_dir, str):
            raise ValueError("output_dir must be a non-empty string.")
        if "\x00" in output_dir:
            raise ValueError("output_dir contains null bytes.")

        title = metadata.get("title", "Untitled Video")
        description = metadata.get("description", "")

        # Use first sentence of description as subtitle
        subtitle = None
        if description:
            first_sentence = description.split(".")[0].strip()
            if len(first_sentence) <= 80:
                subtitle = first_sentence

        safe_name = "thumbnail_" + title[:30].replace(" ", "_")
        safe_name = "".join(
            c for c in safe_name if c.isalnum() or c in ("_", "-")
        )
        output_path = os.path.join(output_dir, f"{safe_name}.png")

        return self.generate(
            title=title,
            output_path=output_path,
            video_path=video_path,
            subtitle=subtitle,
        )

    def _create_styled_background(self, style: str) -> Image.Image:
        """Creates a gradient background in the specified style."""
        palettes = _GRADIENT_PALETTES.get(style, _GRADIENT_PALETTES["bold"])
        color1, color2 = random.choice(palettes)

        directions = ["horizontal", "vertical", "diagonal"]
        direction = random.choice(directions)

        return _create_gradient(
            self.width, self.height, color1, color2, direction
        )

    def _extract_frame(self, video_path: str) -> Image.Image:
        """
        Extracts a frame from a video file for use as thumbnail background.

        Uses moviepy to grab a frame from 30% into the video.
        Falls back to gradient background on failure.
        """
        try:
            from moviepy.editor import VideoFileClip

            clip = VideoFileClip(video_path)
            # Get frame at 30% of the video duration
            time_point = clip.duration * 0.3
            frame = clip.get_frame(time_point)
            clip.close()

            img = Image.fromarray(frame)
            img = img.resize(
                (self.width, self.height), Image.LANCZOS
            )

            # Apply slight blur for a cleaner background
            img = img.filter(ImageFilter.GaussianBlur(radius=2))

            return img

        except Exception as e:
            logger.warning(
                f"Failed to extract video frame: {type(e).__name__}. "
                f"Using gradient background."
            )
            return self._create_styled_background(self.style)

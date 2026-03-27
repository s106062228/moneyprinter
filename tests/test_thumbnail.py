"""Tests for the thumbnail generator module."""

import os
import json
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock

# Ensure src is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from thumbnail import (
    ThumbnailGenerator,
    _hex_to_rgb,
    _interpolate_color,
    _wrap_text,
    _load_font,
    _create_gradient,
    _draw_text_with_outline,
    get_thumbnail_width,
    get_thumbnail_height,
    get_thumbnail_style,
    get_text_color,
    get_outline_color,
    get_outline_width,
    _MAX_TITLE_LENGTH,
    _MAX_DIMENSION,
    _MIN_DIMENSION,
    _STYLES,
    _GRADIENT_PALETTES,
)
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    """Creates a temporary directory for test outputs."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def generator():
    """Creates a ThumbnailGenerator with default config."""
    with patch("thumbnail._get", return_value={}):
        return ThumbnailGenerator()


@pytest.fixture
def mock_config():
    """Returns a mock thumbnail config."""
    return {
        "width": 1280,
        "height": 720,
        "style": "money",
        "text_color": "#FF0000",
        "outline_color": "#00FF00",
        "outline_width": 6,
    }


# ---------------------------------------------------------------------------
# Color utility tests
# ---------------------------------------------------------------------------

class TestHexToRgb:
    def test_valid_hex(self):
        assert _hex_to_rgb("#FF0000") == (255, 0, 0)
        assert _hex_to_rgb("#00FF00") == (0, 255, 0)
        assert _hex_to_rgb("#0000FF") == (0, 0, 255)

    def test_without_hash(self):
        assert _hex_to_rgb("FF0000") == (255, 0, 0)

    def test_black_and_white(self):
        assert _hex_to_rgb("#000000") == (0, 0, 0)
        assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)

    def test_invalid_hex_returns_white(self):
        assert _hex_to_rgb("#GGG") == (255, 255, 255)
        assert _hex_to_rgb("") == (255, 255, 255)
        assert _hex_to_rgb("#12") == (255, 255, 255)

    def test_mixed_case(self):
        assert _hex_to_rgb("#ff6600") == (255, 102, 0)
        assert _hex_to_rgb("#Ff6600") == (255, 102, 0)


class TestInterpolateColor:
    def test_start(self):
        result = _interpolate_color((0, 0, 0), (255, 255, 255), 0.0)
        assert result == (0, 0, 0)

    def test_end(self):
        result = _interpolate_color((0, 0, 0), (255, 255, 255), 1.0)
        assert result == (255, 255, 255)

    def test_midpoint(self):
        result = _interpolate_color((0, 0, 0), (200, 100, 50), 0.5)
        assert result == (100, 50, 25)

    def test_same_colors(self):
        result = _interpolate_color((128, 128, 128), (128, 128, 128), 0.5)
        assert result == (128, 128, 128)


# ---------------------------------------------------------------------------
# Gradient tests
# ---------------------------------------------------------------------------

class TestCreateGradient:
    def test_horizontal_gradient(self):
        img = _create_gradient(100, 50, "#000000", "#FFFFFF", "horizontal")
        assert img.size == (100, 50)
        assert img.mode == "RGB"

    def test_vertical_gradient(self):
        img = _create_gradient(100, 50, "#FF0000", "#0000FF", "vertical")
        assert img.size == (100, 50)

    def test_diagonal_gradient(self):
        img = _create_gradient(50, 50, "#FF0000", "#00FF00", "diagonal")
        assert img.size == (50, 50)

    def test_minimum_size(self):
        img = _create_gradient(1, 1, "#000000", "#FFFFFF", "horizontal")
        assert img.size == (1, 1)


# ---------------------------------------------------------------------------
# Font tests
# ---------------------------------------------------------------------------

class TestLoadFont:
    def test_returns_font_object(self):
        font = _load_font(36)
        assert font is not None

    def test_different_sizes(self):
        small = _load_font(12)
        large = _load_font(72)
        assert small is not None
        assert large is not None

    @patch("thumbnail.get_font", return_value="nonexistent_font.ttf")
    def test_fallback_on_missing_font(self, mock_font):
        font = _load_font(36)
        assert font is not None


# ---------------------------------------------------------------------------
# Text wrapping tests
# ---------------------------------------------------------------------------

class TestWrapText:
    def test_short_text_no_wrap(self):
        font = _load_font(24)
        lines = _wrap_text("Hello", font, 1000)
        assert len(lines) == 1
        assert lines[0] == "Hello"

    def test_long_text_wraps(self):
        font = _load_font(48)
        long_text = "This is a very long title that should wrap across multiple lines"
        lines = _wrap_text(long_text, font, 300)
        assert len(lines) > 1

    def test_single_word(self):
        font = _load_font(24)
        lines = _wrap_text("Supercalifragilisticexpialidocious", font, 100)
        assert len(lines) >= 1

    def test_empty_text(self):
        font = _load_font(24)
        lines = _wrap_text("", font, 500)
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------

class TestConfig:
    @patch("thumbnail._get", return_value={"width": 1920, "height": 1080})
    def test_custom_dimensions(self, mock_get):
        assert get_thumbnail_width() == 1920
        assert get_thumbnail_height() == 1080

    @patch("thumbnail._get", return_value={"width": 99999})
    def test_width_clamped_to_max(self, mock_get):
        assert get_thumbnail_width() == _MAX_DIMENSION

    @patch("thumbnail._get", return_value={"width": 10})
    def test_width_clamped_to_min(self, mock_get):
        assert get_thumbnail_width() == _MIN_DIMENSION

    @patch("thumbnail._get", return_value={})
    def test_default_dimensions(self, mock_get):
        assert get_thumbnail_width() == 1280
        assert get_thumbnail_height() == 720

    @patch("thumbnail._get", return_value={"style": "money"})
    def test_valid_style(self, mock_get):
        assert get_thumbnail_style() == "money"

    @patch("thumbnail._get", return_value={"style": "invalid_style"})
    def test_invalid_style_falls_back(self, mock_get):
        assert get_thumbnail_style() == "bold"

    @patch("thumbnail._get", return_value={"text_color": "#FF0000"})
    def test_text_color(self, mock_get):
        assert get_text_color() == "#FF0000"

    @patch("thumbnail._get", return_value={})
    def test_default_text_color(self, mock_get):
        assert get_text_color() == "#FFFFFF"

    @patch("thumbnail._get", return_value={"outline_width": 25})
    def test_outline_width_clamped(self, mock_get):
        assert get_outline_width() == 20

    @patch("thumbnail._get", return_value={"outline_width": -5})
    def test_outline_width_min_zero(self, mock_get):
        assert get_outline_width() == 0


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------

class TestThumbnailGenerator:
    def test_init_defaults(self, generator):
        assert generator.width == 1280
        assert generator.height == 720
        assert generator.style in _STYLES

    def test_generate_creates_file(self, generator, tmp_dir):
        output = os.path.join(tmp_dir, "test_thumb.png")
        result = generator.generate("Test Title", output)
        assert os.path.isfile(result)
        # Verify it's a valid PNG
        img = Image.open(result)
        assert img.size == (generator.width, generator.height)

    def test_generate_with_style(self, generator, tmp_dir):
        output = os.path.join(tmp_dir, "money_thumb.png")
        result = generator.generate("Money Title", output, style="money")
        assert os.path.isfile(result)

    def test_generate_with_subtitle(self, generator, tmp_dir):
        output = os.path.join(tmp_dir, "sub_thumb.png")
        result = generator.generate(
            "Main Title", output, subtitle="A cool subtitle"
        )
        assert os.path.isfile(result)

    def test_generate_all_styles(self, generator, tmp_dir):
        for style in _STYLES:
            output = os.path.join(tmp_dir, f"{style}_thumb.png")
            result = generator.generate(f"{style} Title", output, style=style)
            assert os.path.isfile(result)

    def test_generate_long_title_wraps(self, generator, tmp_dir):
        output = os.path.join(tmp_dir, "long_thumb.png")
        long_title = "This Is A Very Long Title That Should Wrap Across Multiple Lines On The Thumbnail"
        result = generator.generate(long_title, output)
        assert os.path.isfile(result)

    def test_generate_creates_output_dir(self, generator, tmp_dir):
        nested = os.path.join(tmp_dir, "nested", "deep", "dir")
        output = os.path.join(nested, "thumb.png")
        result = generator.generate("Test", output)
        assert os.path.isfile(result)

    def test_generate_empty_title_raises(self, generator, tmp_dir):
        with pytest.raises(ValueError, match="non-empty"):
            generator.generate("", os.path.join(tmp_dir, "fail.png"))

    def test_generate_none_title_raises(self, generator, tmp_dir):
        with pytest.raises(ValueError, match="non-empty"):
            generator.generate(None, os.path.join(tmp_dir, "fail.png"))

    def test_generate_too_long_title_raises(self, generator, tmp_dir):
        with pytest.raises(ValueError, match="maximum length"):
            generator.generate(
                "X" * (_MAX_TITLE_LENGTH + 1),
                os.path.join(tmp_dir, "fail.png"),
            )

    def test_generate_null_byte_title_raises(self, generator, tmp_dir):
        with pytest.raises(ValueError, match="null bytes"):
            generator.generate(
                "bad\x00title", os.path.join(tmp_dir, "fail.png")
            )

    def test_generate_null_byte_path_raises(self, generator, tmp_dir):
        with pytest.raises(ValueError, match="null bytes"):
            generator.generate(
                "Good Title", os.path.join(tmp_dir, "bad\x00.png")
            )

    def test_generate_invalid_style_uses_default(self, generator, tmp_dir):
        output = os.path.join(tmp_dir, "default_style.png")
        result = generator.generate("Test", output, style="nonexistent")
        assert os.path.isfile(result)


class TestGenerateFromMetadata:
    def test_basic_metadata(self, generator, tmp_dir):
        metadata = {"title": "My Video", "description": "A great video."}
        result = generator.generate_from_metadata(metadata, tmp_dir)
        assert os.path.isfile(result)
        assert "My_Video" in result

    def test_metadata_without_description(self, generator, tmp_dir):
        metadata = {"title": "No Description"}
        result = generator.generate_from_metadata(metadata, tmp_dir)
        assert os.path.isfile(result)

    def test_metadata_without_title(self, generator, tmp_dir):
        metadata = {}
        result = generator.generate_from_metadata(metadata, tmp_dir)
        assert os.path.isfile(result)
        assert "Untitled" in result

    def test_metadata_long_description_subtitle(self, generator, tmp_dir):
        metadata = {
            "title": "Test",
            "description": "Short subtitle. Then more details here that should not appear.",
        }
        result = generator.generate_from_metadata(metadata, tmp_dir)
        assert os.path.isfile(result)


class TestExtractFrame:
    def test_fallback_on_missing_video(self, generator):
        result = generator._extract_frame("/nonexistent/video.mp4")
        assert isinstance(result, Image.Image)
        assert result.size == (generator.width, generator.height)

    @patch("moviepy.editor.VideoFileClip", side_effect=ImportError)
    def test_fallback_on_import_error(self, mock_clip, generator):
        result = generator._extract_frame("/some/video.mp4")
        assert isinstance(result, Image.Image)


class TestStyledBackground:
    def test_all_styles_produce_images(self, generator):
        for style in _STYLES:
            bg = generator._create_styled_background(style)
            assert isinstance(bg, Image.Image)
            assert bg.size == (generator.width, generator.height)


# ---------------------------------------------------------------------------
# Draw text with outline tests
# ---------------------------------------------------------------------------

class TestDrawTextWithOutline:
    def test_draws_without_error(self):
        img = Image.new("RGB", (200, 100), "black")
        draw = ImageDraw.Draw(img)
        font = _load_font(24)
        # Should not raise
        _draw_text_with_outline(
            draw, (10, 10), "Test", font,
            fill="#FFFFFF", outline_color="#000000", outline_width=2,
        )

    def test_zero_outline_width(self):
        img = Image.new("RGB", (200, 100), "black")
        draw = ImageDraw.Draw(img)
        font = _load_font(24)
        _draw_text_with_outline(
            draw, (10, 10), "Test", font,
            fill="#FFFFFF", outline_color="#000000", outline_width=0,
        )


# ---------------------------------------------------------------------------
# Palette coverage
# ---------------------------------------------------------------------------

class TestPalettes:
    def test_all_styles_have_palettes(self):
        for style in _STYLES:
            assert style in _GRADIENT_PALETTES
            assert len(_GRADIENT_PALETTES[style]) >= 1

    def test_palette_colors_are_valid_hex(self):
        for style, palettes in _GRADIENT_PALETTES.items():
            for c1, c2 in palettes:
                assert c1.startswith("#")
                assert c2.startswith("#")
                assert len(c1) == 7
                assert len(c2) == 7

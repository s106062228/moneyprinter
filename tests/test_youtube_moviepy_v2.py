"""
Tests for YouTube.py MoviePy v2 migration.

Validates that the combine() method uses MoviePy v2 APIs:
- from moviepy import X (not moviepy.editor)
- clip.with_fps() instead of clip.set_fps()
- clip.cropped() instead of crop()
- clip.resized() instead of clip.resize()
- MultiplyVolume instead of afx.volumex
- TextClip with text= and font_size= kwargs
- No change_settings / ImageMagick dependency
"""

import os
import sys
import ast
import pytest

# Path to YouTube.py source
YOUTUBE_PY = os.path.join(
    os.path.dirname(__file__), "..", "src", "classes", "YouTube.py"
)


class TestMoviePyV2Imports:
    """Verify YouTube.py uses MoviePy v2 import style."""

    def setup_method(self):
        with open(YOUTUBE_PY, "r") as f:
            self.source = f.read()
        self.tree = ast.parse(self.source)

    def test_no_moviepy_editor_import(self):
        """moviepy.editor namespace was removed in v2."""
        assert "from moviepy.editor import" not in self.source
        assert "import moviepy.editor" not in self.source

    def test_no_moviepy_fx_all_import(self):
        """moviepy.video.fx.all was removed in v2."""
        assert "from moviepy.video.fx.all import" not in self.source

    def test_no_moviepy_config_import(self):
        """moviepy.config.change_settings was removed in v2."""
        assert "from moviepy.config import" not in self.source

    def test_imports_from_moviepy_directly(self):
        """v2 uses 'from moviepy import X'."""
        assert "from moviepy import" in self.source

    def test_imports_audifileclip(self):
        assert "AudioFileClip" in self.source

    def test_imports_compositeaudioclip(self):
        assert "CompositeAudioClip" in self.source

    def test_imports_compositevideoclip(self):
        assert "CompositeVideoClip" in self.source

    def test_imports_imageclip(self):
        assert "ImageClip" in self.source

    def test_imports_textclip(self):
        assert "TextClip" in self.source

    def test_imports_concatenate_videoclips(self):
        assert "concatenate_videoclips" in self.source

    def test_imports_multiplyvolume(self):
        """v2 uses class-based effects."""
        assert "from moviepy.audio.fx import MultiplyVolume" in self.source

    def test_imports_subtitlesclip(self):
        """SubtitlesClip import path unchanged in v2."""
        assert "from moviepy.video.tools.subtitles import SubtitlesClip" in self.source


class TestMoviePyV2MethodCalls:
    """Verify combine() uses v2 method names."""

    def setup_method(self):
        with open(YOUTUBE_PY, "r") as f:
            self.source = f.read()

    def test_no_set_fps(self):
        """v2 uses with_fps() instead of set_fps()."""
        assert ".set_fps(" not in self.source

    def test_uses_with_fps(self):
        assert ".with_fps(" in self.source

    def test_no_set_audio(self):
        """v2 uses with_audio() instead of set_audio()."""
        assert ".set_audio(" not in self.source

    def test_uses_with_audio(self):
        assert ".with_audio(" in self.source

    def test_no_set_duration(self):
        """v2 uses with_duration() instead of set_duration()."""
        assert ".set_duration(" not in self.source

    def test_uses_with_duration(self):
        assert ".with_duration(" in self.source

    def test_no_set_pos(self):
        """v2 uses with_position() instead of set_pos()."""
        assert ".set_pos(" not in self.source

    def test_uses_with_position(self):
        assert ".with_position(" in self.source

    def test_no_resize(self):
        """v2 uses resized() instead of resize()."""
        # Make sure .resize( is not used (but .resized( is ok)
        lines = self.source.split("\n")
        for line in lines:
            stripped = line.strip()
            if ".resize(" in stripped and ".resized(" not in stripped:
                pytest.fail(f"Found v1 .resize() call: {stripped}")

    def test_uses_resized(self):
        assert ".resized(" in self.source

    def test_no_crop_function(self):
        """v2 uses clip.cropped() method, not crop() function."""
        lines = self.source.split("\n")
        for line in lines:
            stripped = line.strip()
            # crop( as standalone function call (not .cropped( or # crop)
            if stripped.startswith("clip = crop(") or "= crop(" in stripped:
                pytest.fail(f"Found v1 crop() function call: {stripped}")

    def test_uses_cropped_method(self):
        assert ".cropped(" in self.source

    def test_no_fx_volumex(self):
        """v2 uses MultiplyVolume class, not afx.volumex."""
        assert "afx.volumex" not in self.source
        assert ".fx(afx" not in self.source

    def test_uses_multiply_volume(self):
        assert "MultiplyVolume(" in self.source

    def test_no_change_settings(self):
        """v2 removed ImageMagick dependency."""
        assert "change_settings(" not in self.source


class TestMoviePyV2TextClip:
    """Verify TextClip uses v2 argument names."""

    def setup_method(self):
        with open(YOUTUBE_PY, "r") as f:
            self.source = f.read()

    def test_textclip_uses_text_keyword(self):
        """v2 TextClip uses text= keyword, not positional."""
        assert "text=txt" in self.source or "text=text" in self.source

    def test_textclip_uses_font_size(self):
        """v2 uses font_size, not fontsize."""
        assert "font_size=" in self.source
        # Ensure old fontsize is not used (check it's not a substring of font_size)
        lines = self.source.split("\n")
        for line in lines:
            stripped = line.strip()
            if "fontsize=" in stripped and "font_size=" not in stripped:
                pytest.fail(f"Found v1 fontsize= argument: {stripped}")

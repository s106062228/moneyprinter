"""
Tests for src/video_templates.py — Video Template System.

Covers:
- VideoTemplate dataclass: creation, to_dict, from_dict, validation edge cases
- VideoTemplateManager: CRUD operations, persistence, atomic writes
- Presets: all 3 presets return valid templates
- render_clip: mock MoviePy, verify clip construction
- Edge cases: empty text, max values, invalid types, missing fields
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock, call

import video_templates as vt_module
from video_templates import (
    VideoTemplate,
    VideoTemplateManager,
    _is_valid_hex_color,
    _normalize_hex,
    _hex_to_rgb,
    _clamp,
    _MAX_DURATION,
    _MIN_DURATION,
    _MAX_TEXT_LEN,
    _MAX_FONT_SIZE,
    _MIN_FONT_SIZE,
    _DEFAULT_RESOLUTION,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect ROOT_DIR to a temp path for each test."""
    monkeypatch.setattr(vt_module, "ROOT_DIR", str(tmp_path))
    mp_dir = tmp_path / ".mp"
    mp_dir.mkdir()
    return mp_dir


@pytest.fixture
def manager(tmp_path):
    """Return a VideoTemplateManager pointing to tmp_path."""
    mgr = VideoTemplateManager()
    return mgr


@pytest.fixture
def minimal_template():
    return VideoTemplate(
        template_id="tmpl-001",
        name="My Intro",
        template_type="intro",
        text="Hello World",
    )


@pytest.fixture
def full_template():
    return VideoTemplate(
        template_id="tmpl-002",
        name="Full Outro",
        template_type="outro",
        text="Thanks for watching!",
        duration=5.0,
        font_size=120,
        text_color="#FFFF00",
        bg_color="#FF0050",
        bg_gradient=["#FF0050", "#FF00FF"],
        bg_image_path="/path/to/bg.png",
        fade_duration=1.0,
        resolution=(1080, 1920),
    )


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


class TestHexHelpers:
    def test_is_valid_hex_color_6digit(self):
        assert _is_valid_hex_color("#FFFFFF") is True
        assert _is_valid_hex_color("#000000") is True
        assert _is_valid_hex_color("#FF0050") is True

    def test_is_valid_hex_color_3digit(self):
        assert _is_valid_hex_color("#FFF") is True
        assert _is_valid_hex_color("#000") is True

    def test_is_valid_hex_color_lowercase(self):
        assert _is_valid_hex_color("#abcdef") is True

    def test_is_valid_hex_color_missing_hash(self):
        assert _is_valid_hex_color("FFFFFF") is False

    def test_is_valid_hex_color_wrong_length(self):
        assert _is_valid_hex_color("#FFFFF") is False
        assert _is_valid_hex_color("#FFFFFFF") is False

    def test_is_valid_hex_color_invalid_chars(self):
        assert _is_valid_hex_color("#GGGGGG") is False
        assert _is_valid_hex_color("#12345Z") is False

    def test_is_valid_hex_color_non_string(self):
        assert _is_valid_hex_color(None) is False
        assert _is_valid_hex_color(123) is False

    def test_normalize_hex_6digit(self):
        assert _normalize_hex("#abcdef") == "#ABCDEF"
        assert _normalize_hex("#FF0050") == "#FF0050"

    def test_normalize_hex_3digit_expands(self):
        assert _normalize_hex("#FFF") == "#FFFFFF"
        assert _normalize_hex("#000") == "#000000"
        assert _normalize_hex("#F0F") == "#FF00FF"

    def test_hex_to_rgb_white(self):
        assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)

    def test_hex_to_rgb_black(self):
        assert _hex_to_rgb("#000000") == (0, 0, 0)

    def test_hex_to_rgb_red(self):
        assert _hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_hex_to_rgb_green(self):
        assert _hex_to_rgb("#00FF00") == (0, 255, 0)

    def test_clamp_within_range(self):
        assert _clamp(5, 0, 10) == 5

    def test_clamp_below_min(self):
        assert _clamp(-1, 0, 10) == 0

    def test_clamp_above_max(self):
        assert _clamp(100, 0, 10) == 10


# ---------------------------------------------------------------------------
# VideoTemplate — creation
# ---------------------------------------------------------------------------


class TestVideoTemplateCreation:
    def test_minimal_creation(self, minimal_template):
        t = minimal_template
        assert t.template_id == "tmpl-001"
        assert t.name == "My Intro"
        assert t.template_type == "intro"
        assert t.text == "Hello World"

    def test_default_duration(self, minimal_template):
        assert minimal_template.duration == 3.0

    def test_default_font_size(self, minimal_template):
        assert minimal_template.font_size == 80

    def test_default_text_color(self, minimal_template):
        assert minimal_template.text_color == "#FFFFFF"

    def test_default_bg_color(self, minimal_template):
        assert minimal_template.bg_color == "#000000"

    def test_default_bg_gradient_none(self, minimal_template):
        assert minimal_template.bg_gradient is None

    def test_default_bg_image_path_none(self, minimal_template):
        assert minimal_template.bg_image_path is None

    def test_default_fade_duration(self, minimal_template):
        assert minimal_template.fade_duration == 0.5

    def test_default_resolution(self, minimal_template):
        assert minimal_template.resolution == _DEFAULT_RESOLUTION

    def test_full_template_fields(self, full_template):
        t = full_template
        assert t.template_type == "outro"
        assert t.duration == 5.0
        assert t.font_size == 120
        assert t.text_color == "#FFFF00"
        assert t.bg_gradient == ["#FF0050", "#FF00FF"]
        assert t.bg_image_path == "/path/to/bg.png"
        assert t.fade_duration == 1.0

    def test_resolution_defaults_independent(self):
        t1 = VideoTemplate(template_id="a", name="A", template_type="intro", text="A")
        t2 = VideoTemplate(template_id="b", name="B", template_type="intro", text="B")
        assert t1.resolution == t2.resolution
        # Modifying one should not affect the other
        t1.resolution = (720, 1280)
        assert t2.resolution == _DEFAULT_RESOLUTION


# ---------------------------------------------------------------------------
# VideoTemplate — to_dict
# ---------------------------------------------------------------------------


class TestVideoTemplateToDict:
    def test_to_dict_contains_all_keys(self, minimal_template):
        d = minimal_template.to_dict()
        expected_keys = {
            "template_id", "name", "template_type", "text",
            "duration", "font_size", "text_color", "bg_color",
            "bg_gradient", "bg_image_path", "fade_duration", "resolution",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self, minimal_template):
        d = minimal_template.to_dict()
        assert d["template_id"] == "tmpl-001"
        assert d["name"] == "My Intro"
        assert d["template_type"] == "intro"
        assert d["text"] == "Hello World"
        assert d["duration"] == 3.0
        assert d["font_size"] == 80

    def test_to_dict_resolution_is_list(self, minimal_template):
        d = minimal_template.to_dict()
        assert isinstance(d["resolution"], list)
        assert d["resolution"] == [1080, 1920]

    def test_to_dict_gradient(self, full_template):
        d = full_template.to_dict()
        assert d["bg_gradient"] == ["#FF0050", "#FF00FF"]

    def test_to_dict_none_fields(self, minimal_template):
        d = minimal_template.to_dict()
        assert d["bg_gradient"] is None
        assert d["bg_image_path"] is None

    def test_to_dict_is_json_serializable(self, full_template):
        d = full_template.to_dict()
        serialized = json.dumps(d)
        assert len(serialized) > 0


# ---------------------------------------------------------------------------
# VideoTemplate — from_dict
# ---------------------------------------------------------------------------


class TestVideoTemplateFromDict:
    def _base_data(self):
        return {
            "template_id": "t1",
            "name": "Test",
            "template_type": "intro",
            "text": "Welcome",
        }

    def test_from_dict_minimal(self):
        t = VideoTemplate.from_dict(self._base_data())
        assert t.template_id == "t1"
        assert t.name == "Test"
        assert t.template_type == "intro"
        assert t.text == "Welcome"

    def test_from_dict_uses_defaults(self):
        t = VideoTemplate.from_dict(self._base_data())
        assert t.duration == 3.0
        assert t.font_size == 80
        assert t.text_color == "#FFFFFF"
        assert t.bg_color == "#000000"

    def test_from_dict_full(self):
        data = {
            "template_id": "t2",
            "name": "Full",
            "template_type": "outro",
            "text": "Bye",
            "duration": 5.0,
            "font_size": 100,
            "text_color": "#FFFF00",
            "bg_color": "#FF0050",
            "bg_gradient": ["#FF0050", "#FF00FF"],
            "bg_image_path": "/bg.png",
            "fade_duration": 1.0,
            "resolution": [720, 1280],
        }
        t = VideoTemplate.from_dict(data)
        assert t.template_type == "outro"
        assert t.duration == 5.0
        assert t.font_size == 100
        assert t.text_color == "#FFFF00"
        assert t.bg_gradient == ["#FF0050", "#FF00FF"]
        assert t.bg_image_path == "/bg.png"
        assert t.resolution == (720, 1280)

    def test_from_dict_normalizes_hex_colors(self):
        data = self._base_data()
        data["text_color"] = "#fff"
        data["bg_color"] = "#000"
        t = VideoTemplate.from_dict(data)
        assert t.text_color == "#FFFFFF"
        assert t.bg_color == "#000000"

    def test_from_dict_clamps_duration_too_small(self):
        data = self._base_data()
        data["duration"] = 0.0
        t = VideoTemplate.from_dict(data)
        assert t.duration == _MIN_DURATION

    def test_from_dict_clamps_duration_too_large(self):
        data = self._base_data()
        data["duration"] = 999.0
        t = VideoTemplate.from_dict(data)
        assert t.duration == _MAX_DURATION

    def test_from_dict_clamps_font_size_min(self):
        data = self._base_data()
        data["font_size"] = 1
        t = VideoTemplate.from_dict(data)
        assert t.font_size == _MIN_FONT_SIZE

    def test_from_dict_clamps_font_size_max(self):
        data = self._base_data()
        data["font_size"] = 9999
        t = VideoTemplate.from_dict(data)
        assert t.font_size == _MAX_FONT_SIZE

    def test_from_dict_truncates_text(self):
        data = self._base_data()
        data["text"] = "x" * (_MAX_TEXT_LEN + 100)
        t = VideoTemplate.from_dict(data)
        assert len(t.text) == _MAX_TEXT_LEN

    def test_from_dict_raises_invalid_template_type(self):
        data = self._base_data()
        data["template_type"] = "middle"
        with pytest.raises(ValueError, match="template_type"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_text_color(self):
        data = self._base_data()
        data["text_color"] = "notacolor"
        with pytest.raises(ValueError, match="text_color"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_bg_color(self):
        data = self._base_data()
        data["bg_color"] = "ZZZZZZ"
        with pytest.raises(ValueError, match="bg_color"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_duration_type(self):
        data = self._base_data()
        data["duration"] = "long"
        with pytest.raises(ValueError, match="duration"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_font_size_type(self):
        data = self._base_data()
        data["font_size"] = "big"
        with pytest.raises(ValueError, match="font_size"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_non_dict(self):
        with pytest.raises(ValueError):
            VideoTemplate.from_dict("not a dict")

    def test_from_dict_raises_invalid_bg_gradient_wrong_count(self):
        data = self._base_data()
        data["bg_gradient"] = ["#FF0000"]
        with pytest.raises(ValueError, match="bg_gradient"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_bg_gradient_bad_color(self):
        data = self._base_data()
        data["bg_gradient"] = ["#FF0000", "notacolor"]
        with pytest.raises(ValueError, match="bg_gradient"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_resolution_wrong_count(self):
        data = self._base_data()
        data["resolution"] = [1080]
        with pytest.raises(ValueError, match="resolution"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_resolution_non_positive(self):
        data = self._base_data()
        data["resolution"] = [0, 1920]
        with pytest.raises(ValueError, match="resolution"):
            VideoTemplate.from_dict(data)

    def test_from_dict_raises_invalid_text_type(self):
        data = self._base_data()
        data["text"] = 12345
        with pytest.raises(ValueError, match="text"):
            VideoTemplate.from_dict(data)

    def test_from_dict_empty_text_allowed(self):
        data = self._base_data()
        data["text"] = ""
        t = VideoTemplate.from_dict(data)
        assert t.text == ""

    def test_from_dict_round_trip(self, full_template):
        d = full_template.to_dict()
        restored = VideoTemplate.from_dict(d)
        assert restored.template_id == full_template.template_id
        assert restored.name == full_template.name
        assert restored.template_type == full_template.template_type
        assert restored.text == full_template.text
        assert restored.duration == full_template.duration
        assert restored.font_size == full_template.font_size
        assert restored.bg_gradient == full_template.bg_gradient
        assert restored.fade_duration == full_template.fade_duration
        assert restored.resolution == full_template.resolution


# ---------------------------------------------------------------------------
# VideoTemplateManager — CRUD
# ---------------------------------------------------------------------------


class TestVideoTemplateManagerCRUD:
    def test_save_and_get_template(self, manager, minimal_template):
        manager.save_template(minimal_template)
        retrieved = manager.get_template("tmpl-001")
        assert retrieved is not None
        assert retrieved.template_id == "tmpl-001"
        assert retrieved.name == "My Intro"

    def test_get_nonexistent_returns_none(self, manager):
        result = manager.get_template("does-not-exist")
        assert result is None

    def test_save_creates_file(self, manager, tmp_path, minimal_template):
        manager.save_template(minimal_template)
        expected_path = tmp_path / ".mp" / "video_templates.json"
        assert expected_path.exists()

    def test_saved_file_is_valid_json(self, manager, tmp_path, minimal_template):
        manager.save_template(minimal_template)
        path = tmp_path / ".mp" / "video_templates.json"
        with open(path) as f:
            data = json.load(f)
        assert "templates" in data
        assert len(data["templates"]) == 1

    def test_save_multiple_templates(self, manager, minimal_template, full_template):
        manager.save_template(minimal_template)
        manager.save_template(full_template)
        templates = manager.list_templates()
        assert len(templates) == 2

    def test_update_existing_template(self, manager, minimal_template):
        manager.save_template(minimal_template)
        minimal_template.name = "Updated Name"
        manager.save_template(minimal_template)
        templates = manager.list_templates()
        assert len(templates) == 1
        assert templates[0].name == "Updated Name"

    def test_delete_existing_template(self, manager, minimal_template):
        manager.save_template(minimal_template)
        result = manager.delete_template("tmpl-001")
        assert result is True
        assert manager.get_template("tmpl-001") is None

    def test_delete_nonexistent_returns_false(self, manager):
        result = manager.delete_template("no-such-id")
        assert result is False

    def test_delete_reduces_count(self, manager, minimal_template, full_template):
        manager.save_template(minimal_template)
        manager.save_template(full_template)
        manager.delete_template("tmpl-001")
        templates = manager.list_templates()
        assert len(templates) == 1
        assert templates[0].template_id == "tmpl-002"

    def test_list_templates_empty(self, manager):
        result = manager.list_templates()
        assert result == []

    def test_list_templates_no_filter(self, manager, minimal_template, full_template):
        manager.save_template(minimal_template)
        manager.save_template(full_template)
        result = manager.list_templates()
        assert len(result) == 2

    def test_list_templates_filter_intro(self, manager, minimal_template, full_template):
        # minimal is intro, full is outro
        manager.save_template(minimal_template)
        manager.save_template(full_template)
        intros = manager.list_templates(template_type="intro")
        assert len(intros) == 1
        assert intros[0].template_type == "intro"

    def test_list_templates_filter_outro(self, manager, minimal_template, full_template):
        manager.save_template(minimal_template)
        manager.save_template(full_template)
        outros = manager.list_templates(template_type="outro")
        assert len(outros) == 1
        assert outros[0].template_type == "outro"

    def test_list_templates_filter_returns_empty_when_no_match(self, manager, minimal_template):
        manager.save_template(minimal_template)
        outros = manager.list_templates(template_type="outro")
        assert outros == []

    def test_persistence_round_trip(self, manager, full_template):
        manager.save_template(full_template)
        # Create a fresh manager pointing to the same path
        mgr2 = VideoTemplateManager()
        retrieved = mgr2.get_template("tmpl-002")
        assert retrieved is not None
        assert retrieved.name == "Full Outro"
        assert retrieved.bg_gradient == ["#FF0050", "#FF00FF"]

    def test_load_from_missing_file_returns_empty(self, manager):
        result = manager._load_templates()
        assert result == []

    def test_load_from_corrupt_file(self, tmp_path):
        path = tmp_path / ".mp" / "video_templates.json"
        path.write_text("not valid json{{{")
        mgr = VideoTemplateManager()
        result = mgr._load_templates()
        assert result == []

    def test_atomic_write_uses_temp_file(self, manager, minimal_template, tmp_path):
        """Verify that no .tmp file lingers after a successful save."""
        manager.save_template(minimal_template)
        mp_dir = tmp_path / ".mp"
        tmp_files = list(mp_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_save_overwrites_only_same_id(self, manager):
        t1 = VideoTemplate(
            template_id="a", name="A", template_type="intro", text="A"
        )
        t2 = VideoTemplate(
            template_id="b", name="B", template_type="outro", text="B"
        )
        manager.save_template(t1)
        manager.save_template(t2)
        t1_updated = VideoTemplate(
            template_id="a", name="A-updated", template_type="intro", text="A"
        )
        manager.save_template(t1_updated)
        templates = manager.list_templates()
        assert len(templates) == 2
        a = manager.get_template("a")
        assert a.name == "A-updated"
        b = manager.get_template("b")
        assert b.name == "B"


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


class TestPresets:
    def test_get_preset_minimal(self, manager):
        t = manager.get_preset("minimal")
        assert isinstance(t, VideoTemplate)
        assert t.name == "Minimal"
        assert t.bg_color == "#000000"
        assert t.text_color == "#FFFFFF"
        assert t.duration == 3.0
        assert t.fade_duration == 0.5
        assert t.bg_gradient is None

    def test_get_preset_gradient(self, manager):
        t = manager.get_preset("gradient")
        assert isinstance(t, VideoTemplate)
        assert t.name == "Gradient"
        assert t.text_color == "#FFFF00"
        assert t.duration == 4.0
        assert t.fade_duration == 0.5
        assert t.bg_gradient is not None
        assert len(t.bg_gradient) == 2
        assert t.bg_gradient[0] == "#FF0050"
        assert t.bg_gradient[1] == "#FF00FF"

    def test_get_preset_branded(self, manager):
        t = manager.get_preset("branded")
        assert isinstance(t, VideoTemplate)
        assert t.name == "Branded"
        assert t.text_color == "#FFFFFF"
        assert t.duration == 5.0
        assert t.fade_duration == 1.0

    def test_get_preset_unknown_raises_value_error(self, manager):
        with pytest.raises(ValueError, match="Unknown preset"):
            manager.get_preset("nonexistent")

    def test_presets_have_valid_template_types(self, manager):
        for name in ("minimal", "gradient", "branded"):
            t = manager.get_preset(name)
            assert t.template_type in ("intro", "outro")

    def test_presets_have_unique_ids(self, manager):
        t1 = manager.get_preset("minimal")
        t2 = manager.get_preset("minimal")
        # Each call should produce a fresh unique ID
        assert t1.template_id != t2.template_id

    def test_presets_have_valid_resolution(self, manager):
        for name in ("minimal", "gradient", "branded"):
            t = manager.get_preset(name)
            assert len(t.resolution) == 2
            assert t.resolution[0] > 0
            assert t.resolution[1] > 0

    def test_preset_from_dict_round_trip(self, manager):
        t = manager.get_preset("gradient")
        d = t.to_dict()
        restored = VideoTemplate.from_dict(d)
        assert restored.text_color == t.text_color
        assert restored.bg_gradient == t.bg_gradient


# ---------------------------------------------------------------------------
# render_clip — mocked MoviePy
# ---------------------------------------------------------------------------


class TestRenderClip:
    """Verify render_clip constructs the clip correctly using mocked MoviePy."""

    def _make_mock_clip(self):
        mock = MagicMock()
        mock.with_duration.return_value = mock
        mock.with_position.return_value = mock
        mock.resized.return_value = mock
        mock.with_effects.return_value = mock
        return mock

    def _patch_moviepy(self, manager, template):
        """Helper: patch moviepy imports and call render_clip, return (result, mocks)."""
        mock_color_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_vfx = MagicMock()

        ColorClipClass = MagicMock(return_value=mock_color_clip)
        ImageClipClass = MagicMock(return_value=self._make_mock_clip())
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)

        with patch.dict("sys.modules", {
            "moviepy": MagicMock(
                ColorClip=ColorClipClass,
                ImageClip=ImageClipClass,
                TextClip=TextClipClass,
                CompositeVideoClip=CompositeVideoClipClass,
            ),
            "moviepy.video.fx": mock_vfx,
        }):
            result = manager.render_clip(template)

        return result, {
            "ColorClip": ColorClipClass,
            "TextClip": TextClipClass,
            "CompositeVideoClip": CompositeVideoClipClass,
            "vfx": mock_vfx,
        }

    def test_render_clip_returns_composite(self, manager, minimal_template):
        mock_color_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_composite.with_effects.return_value = mock_composite

        ColorClipClass = MagicMock(return_value=mock_color_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            result = manager.render_clip(minimal_template)

        assert result is not None

    def test_render_clip_uses_color_clip_for_solid_bg(self, manager, minimal_template):
        mock_color_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_composite.with_effects.return_value = mock_composite

        ColorClipClass = MagicMock(return_value=mock_color_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            manager.render_clip(minimal_template)

        # ColorClip should have been called (solid background)
        assert ColorClipClass.called

    def test_render_clip_uses_text_clip(self, manager, minimal_template):
        mock_color_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_composite.with_effects.return_value = mock_composite

        ColorClipClass = MagicMock(return_value=mock_color_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            manager.render_clip(minimal_template)

        assert TextClipClass.called
        call_kwargs = TextClipClass.call_args.kwargs
        assert call_kwargs["text"] == "Hello World"
        assert call_kwargs["font_size"] == 80

    def test_render_clip_uses_composite_video_clip(self, manager, minimal_template):
        mock_color_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_composite.with_effects.return_value = mock_composite

        ColorClipClass = MagicMock(return_value=mock_color_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            manager.render_clip(minimal_template)

        assert CompositeVideoClipClass.called

    def test_render_clip_applies_fade_effects_when_positive(self, manager, minimal_template):
        mock_color_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_composite.with_effects.return_value = mock_composite

        ColorClipClass = MagicMock(return_value=mock_color_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        minimal_template.fade_duration = 0.5

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            manager.render_clip(minimal_template)

        assert mock_composite.with_effects.called

    def test_render_clip_no_fade_when_zero(self, manager):
        template = VideoTemplate(
            template_id="t-nofade",
            name="No Fade",
            template_type="intro",
            text="Test",
            fade_duration=0.0,
        )

        mock_color_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()

        ColorClipClass = MagicMock(return_value=mock_color_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            manager.render_clip(template)

        # with_effects should NOT have been called
        assert not mock_composite.with_effects.called

    def test_render_clip_uses_image_clip_for_bg_image(self, manager):
        template = VideoTemplate(
            template_id="t-bgimg",
            name="BG Image",
            template_type="intro",
            text="Test",
            bg_image_path="/fake/bg.png",
        )

        mock_image_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_composite.with_effects.return_value = mock_composite

        ImageClipClass = MagicMock(return_value=mock_image_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        ColorClipClass = MagicMock()
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.ImageClip = ImageClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            manager.render_clip(template)

        # ImageClip should have been called for background
        assert ImageClipClass.called
        # ColorClip should NOT have been called
        assert not ColorClipClass.called

    def test_render_clip_gradient_bg_uses_numpy_array(self, manager):
        template = VideoTemplate(
            template_id="t-grad",
            name="Grad",
            template_type="intro",
            text="Test",
            bg_gradient=["#FF0050", "#FF00FF"],
        )

        mock_image_clip = self._make_mock_clip()
        mock_text_clip = self._make_mock_clip()
        mock_composite = self._make_mock_clip()
        mock_composite.with_effects.return_value = mock_composite

        ImageClipClass = MagicMock(return_value=mock_image_clip)
        TextClipClass = MagicMock(return_value=mock_text_clip)
        CompositeVideoClipClass = MagicMock(return_value=mock_composite)
        ColorClipClass = MagicMock()
        mock_vfx = MagicMock()

        moviepy_mock = MagicMock()
        moviepy_mock.ColorClip = ColorClipClass
        moviepy_mock.ImageClip = ImageClipClass
        moviepy_mock.TextClip = TextClipClass
        moviepy_mock.CompositeVideoClip = CompositeVideoClipClass

        with patch.dict("sys.modules", {
            "moviepy": moviepy_mock,
            "moviepy.video.fx": mock_vfx,
        }):
            manager.render_clip(template)

        # ImageClip should be called with a numpy array (for gradient)
        assert ImageClipClass.called
        # ColorClip should NOT have been called
        assert not ColorClipClass.called

    def test_render_clip_raises_import_error_without_moviepy(self, manager, minimal_template):
        import sys
        # Remove moviepy from sys.modules so the import inside render_clip fails
        saved = sys.modules.pop("moviepy", None)
        saved_vfx = sys.modules.pop("moviepy.video.fx", None)
        try:
            with patch.dict("sys.modules", {"moviepy": None, "moviepy.video.fx": None}):
                with pytest.raises((ImportError, TypeError)):
                    manager.render_clip(minimal_template)
        finally:
            if saved is not None:
                sys.modules["moviepy"] = saved
            if saved_vfx is not None:
                sys.modules["moviepy.video.fx"] = saved_vfx


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_text_in_template(self, manager):
        t = VideoTemplate(
            template_id="empty-text",
            name="Empty",
            template_type="intro",
            text="",
        )
        manager.save_template(t)
        retrieved = manager.get_template("empty-text")
        assert retrieved.text == ""

    def test_max_text_length(self):
        data = {
            "template_id": "t",
            "name": "N",
            "template_type": "intro",
            "text": "a" * _MAX_TEXT_LEN,
        }
        t = VideoTemplate.from_dict(data)
        assert len(t.text) == _MAX_TEXT_LEN

    def test_from_dict_with_both_gradient_and_bg_image(self):
        data = {
            "template_id": "t",
            "name": "N",
            "template_type": "intro",
            "text": "hi",
            "bg_gradient": ["#000000", "#FFFFFF"],
            "bg_image_path": "/img.png",
        }
        # Should succeed — both fields set is the caller's concern
        t = VideoTemplate.from_dict(data)
        assert t.bg_gradient is not None
        assert t.bg_image_path is not None

    def test_template_type_outro_valid(self):
        data = {
            "template_id": "t",
            "name": "N",
            "template_type": "outro",
            "text": "bye",
        }
        t = VideoTemplate.from_dict(data)
        assert t.template_type == "outro"

    def test_manager_handles_no_mp_dir(self, tmp_path, monkeypatch):
        """Manager should create .mp directory on first save."""
        import shutil
        mp_dir = tmp_path / ".mp"
        if mp_dir.exists():
            shutil.rmtree(str(mp_dir))
        monkeypatch.setattr(vt_module, "ROOT_DIR", str(tmp_path))
        mgr = VideoTemplateManager()
        t = VideoTemplate(
            template_id="x", name="X", template_type="intro", text="hi"
        )
        mgr.save_template(t)
        assert (tmp_path / ".mp" / "video_templates.json").exists()

    def test_resolution_tuple_stored_correctly(self):
        data = {
            "template_id": "t",
            "name": "N",
            "template_type": "intro",
            "text": "hi",
            "resolution": [720, 1280],
        }
        t = VideoTemplate.from_dict(data)
        assert t.resolution == (720, 1280)

    def test_fade_duration_clamped_below_zero(self):
        data = {
            "template_id": "t",
            "name": "N",
            "template_type": "intro",
            "text": "hi",
            "fade_duration": -1.0,
        }
        t = VideoTemplate.from_dict(data)
        assert t.fade_duration == 0.0

    def test_fade_duration_clamped_above_max(self):
        data = {
            "template_id": "t",
            "name": "N",
            "template_type": "intro",
            "text": "hi",
            "fade_duration": 999.0,
        }
        t = VideoTemplate.from_dict(data)
        assert t.fade_duration == 5.0

    def test_list_filter_none_returns_all(self, manager):
        for i in range(3):
            t = VideoTemplate(
                template_id=f"t{i}",
                name=f"T{i}",
                template_type="intro" if i % 2 == 0 else "outro",
                text="hi",
            )
            manager.save_template(t)
        result = manager.list_templates(template_type=None)
        assert len(result) == 3

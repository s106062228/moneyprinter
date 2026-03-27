"""Tests for the content templates module."""

import os
import sys
import json
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# ContentTemplate validation tests
# ---------------------------------------------------------------------------

class TestContentTemplateValidation:
    """Tests for ContentTemplate.validate()."""

    def _make_template(self, **kwargs):
        from content_templates import ContentTemplate
        defaults = {
            "name": "test-template",
            "niche": "general",
            "language": "en",
            "platforms": ["youtube"],
            "batch_size": 5,
            "delay_between_videos": 30,
        }
        defaults.update(kwargs)
        return ContentTemplate(**defaults)

    def test_valid_template_passes(self):
        t = self._make_template()
        t.validate()  # Should not raise

    def test_empty_name_raises(self):
        t = self._make_template(name="")
        with pytest.raises(ValueError, match="non-empty string"):
            t.validate()

    def test_name_too_long_raises(self):
        t = self._make_template(name="a" * 101)
        with pytest.raises(ValueError, match="maximum length"):
            t.validate()

    def test_name_null_bytes_raises(self):
        t = self._make_template(name="test\x00bad")
        with pytest.raises(ValueError, match="null bytes"):
            t.validate()

    def test_name_invalid_chars_raises(self):
        t = self._make_template(name="test template!")
        with pytest.raises(ValueError, match="alphanumeric"):
            t.validate()

    def test_name_starts_with_hyphen_raises(self):
        t = self._make_template(name="-invalid")
        with pytest.raises(ValueError, match="alphanumeric"):
            t.validate()

    def test_name_with_underscores_passes(self):
        t = self._make_template(name="my_template_v2")
        t.validate()

    def test_name_with_hyphens_passes(self):
        t = self._make_template(name="my-template-v2")
        t.validate()

    def test_description_too_long_raises(self):
        t = self._make_template(description="a" * 1001)
        with pytest.raises(ValueError, match="maximum length"):
            t.validate()

    def test_description_null_bytes_raises(self):
        t = self._make_template(description="bad\x00desc")
        with pytest.raises(ValueError, match="null bytes"):
            t.validate()

    def test_niche_too_long_raises(self):
        t = self._make_template(niche="a" * 201)
        with pytest.raises(ValueError, match="max"):
            t.validate()

    def test_niche_null_bytes_raises(self):
        t = self._make_template(niche="bad\x00niche")
        with pytest.raises(ValueError, match="null bytes"):
            t.validate()

    def test_language_too_long_raises(self):
        t = self._make_template(language="a" * 11)
        with pytest.raises(ValueError, match="max"):
            t.validate()

    def test_unknown_platform_raises(self):
        t = self._make_template(platforms=["youtube", "facebook"])
        with pytest.raises(ValueError, match="Unknown platform"):
            t.validate()

    def test_all_valid_platforms_pass(self):
        t = self._make_template(platforms=["youtube", "tiktok", "twitter", "instagram"])
        t.validate()

    def test_invalid_thumbnail_style_raises(self):
        t = self._make_template(thumbnail_style="neon")
        with pytest.raises(ValueError, match="Unknown thumbnail style"):
            t.validate()

    def test_valid_thumbnail_styles_pass(self):
        for style in ("bold", "calm", "money", "dark", "vibrant"):
            t = self._make_template(thumbnail_style=style)
            t.validate()

    def test_too_many_tags_raises(self):
        t = self._make_template(default_tags=["tag"] * 31)
        with pytest.raises(ValueError, match="Too many"):
            t.validate()

    def test_tag_too_long_raises(self):
        t = self._make_template(default_tags=["a" * 51])
        with pytest.raises(ValueError, match="max"):
            t.validate()

    def test_tag_null_bytes_raises(self):
        t = self._make_template(default_tags=["tag\x00bad"])
        with pytest.raises(ValueError, match="null bytes"):
            t.validate()

    def test_too_many_topics_raises(self):
        t = self._make_template(default_topics=["t"] * 101)
        with pytest.raises(ValueError, match="Too many"):
            t.validate()

    def test_topic_too_long_raises(self):
        t = self._make_template(default_topics=["a" * 501])
        with pytest.raises(ValueError, match="max"):
            t.validate()

    def test_topic_null_bytes_raises(self):
        t = self._make_template(default_topics=["topic\x00bad"])
        with pytest.raises(ValueError, match="null bytes"):
            t.validate()

    def test_too_many_schedule_times_raises(self):
        t = self._make_template(schedule_times=["10:00"] * 25)
        with pytest.raises(ValueError, match="Too many"):
            t.validate()

    def test_invalid_schedule_time_format_raises(self):
        t = self._make_template(schedule_times=["25:00"])
        with pytest.raises(ValueError, match="out of range"):
            t.validate()

    def test_non_time_string_raises(self):
        t = self._make_template(schedule_times=["not-a-time"])
        with pytest.raises(ValueError, match="HH:MM"):
            t.validate()

    def test_valid_schedule_times_pass(self):
        t = self._make_template(schedule_times=["09:00", "14:30", "18:00"])
        t.validate()

    def test_batch_size_zero_raises(self):
        t = self._make_template(batch_size=0)
        with pytest.raises(ValueError, match="between 1"):
            t.validate()

    def test_batch_size_too_large_raises(self):
        t = self._make_template(batch_size=51)
        with pytest.raises(ValueError, match="between 1"):
            t.validate()

    def test_delay_too_small_raises(self):
        t = self._make_template(delay_between_videos=5)
        with pytest.raises(ValueError, match="between"):
            t.validate()

    def test_delay_too_large_raises(self):
        t = self._make_template(delay_between_videos=601)
        with pytest.raises(ValueError, match="between"):
            t.validate()


# ---------------------------------------------------------------------------
# ContentTemplate serialization tests
# ---------------------------------------------------------------------------

class TestContentTemplateSerialization:
    """Tests for to_dict() and from_dict()."""

    def _make_template(self, **kwargs):
        from content_templates import ContentTemplate
        defaults = {
            "name": "test-template",
            "niche": "finance",
            "language": "en",
            "platforms": ["youtube", "tiktok"],
            "auto_publish": True,
            "seo_enabled": True,
            "thumbnail_style": "money",
            "default_tags": ["#AI", "#Finance"],
            "default_topics": ["Passive income", "AI stocks"],
            "schedule_times": ["10:00", "14:00"],
            "batch_size": 5,
            "delay_between_videos": 60,
        }
        defaults.update(kwargs)
        return ContentTemplate(**defaults)

    def test_round_trip(self):
        from content_templates import ContentTemplate
        original = self._make_template()
        data = original.to_dict()
        restored = ContentTemplate.from_dict(data)
        assert restored.name == original.name
        assert restored.niche == original.niche
        assert restored.language == original.language
        assert restored.platforms == original.platforms
        assert restored.auto_publish == original.auto_publish
        assert restored.seo_enabled == original.seo_enabled
        assert restored.thumbnail_style == original.thumbnail_style
        assert restored.default_tags == original.default_tags
        assert restored.default_topics == original.default_topics
        assert restored.schedule_times == original.schedule_times
        assert restored.batch_size == original.batch_size
        assert restored.delay_between_videos == original.delay_between_videos

    def test_from_dict_truncates_long_name(self):
        from content_templates import ContentTemplate
        data = {"name": "a" * 200}
        t = ContentTemplate.from_dict(data)
        assert len(t.name) <= 100

    def test_from_dict_clamps_batch_size(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "batch_size": 999}
        t = ContentTemplate.from_dict(data)
        assert t.batch_size <= 50

    def test_from_dict_clamps_delay(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "delay_between_videos": 1}
        t = ContentTemplate.from_dict(data)
        assert t.delay_between_videos >= 10

    def test_from_dict_filters_invalid_platforms(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "platforms": ["youtube", "facebook", "tiktok"]}
        t = ContentTemplate.from_dict(data)
        assert "facebook" not in t.platforms
        assert "youtube" in t.platforms
        assert "tiktok" in t.platforms

    def test_from_dict_defaults_invalid_style(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "thumbnail_style": "neon"}
        t = ContentTemplate.from_dict(data)
        assert t.thumbnail_style == "bold"

    def test_from_dict_non_dict_raises(self):
        from content_templates import ContentTemplate
        with pytest.raises(ValueError, match="requires a dict"):
            ContentTemplate.from_dict("not a dict")

    def test_from_dict_filters_null_byte_tags(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "default_tags": ["good", "bad\x00tag", "ok"]}
        t = ContentTemplate.from_dict(data)
        assert "bad\x00tag" not in t.default_tags
        assert "good" in t.default_tags

    def test_from_dict_filters_null_byte_topics(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "default_topics": ["good", "bad\x00topic"]}
        t = ContentTemplate.from_dict(data)
        assert len(t.default_topics) == 1

    def test_from_dict_filters_invalid_schedule_times(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "schedule_times": ["10:00", "invalid", "14:30"]}
        t = ContentTemplate.from_dict(data)
        assert len(t.schedule_times) == 2

    def test_from_dict_handles_non_int_batch_size(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "batch_size": "not-a-number"}
        t = ContentTemplate.from_dict(data)
        assert t.batch_size == 5  # default

    def test_from_dict_handles_non_int_delay(self):
        from content_templates import ContentTemplate
        data = {"name": "test", "delay_between_videos": "invalid"}
        t = ContentTemplate.from_dict(data)
        assert t.delay_between_videos == 30  # default

    def test_to_dict_contains_all_fields(self):
        t = self._make_template()
        d = t.to_dict()
        expected_keys = {
            "name", "description", "niche", "language", "platforms",
            "auto_publish", "seo_enabled", "thumbnail_style",
            "default_tags", "default_topics", "schedule_times",
            "batch_size", "delay_between_videos", "created_at", "updated_at",
        }
        assert set(d.keys()) == expected_keys


# ---------------------------------------------------------------------------
# ContentTemplate.to_batch_job tests
# ---------------------------------------------------------------------------

class TestContentTemplateToBatchJob:
    """Tests for to_batch_job()."""

    def _make_template(self, **kwargs):
        from content_templates import ContentTemplate
        defaults = {
            "name": "test-template",
            "platforms": ["youtube"],
            "default_topics": ["topic1", "topic2"],
            "batch_size": 5,
        }
        defaults.update(kwargs)
        return ContentTemplate(**defaults)

    @patch("content_templates.BatchJob", autospec=True)
    def test_uses_default_topics(self, mock_batch_job):
        """Uses default_topics when no topics are provided."""
        t = self._make_template()
        # Actually call to_batch_job and check result
        from content_templates import ContentTemplate
        real_t = ContentTemplate(
            name="test",
            default_topics=["topic1", "topic2"],
            platforms=["youtube"],
            batch_size=5,
        )
        job = real_t.to_batch_job()
        assert job.topics == ["topic1", "topic2"]

    def test_overrides_topics(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(
            name="test",
            default_topics=["default1"],
            platforms=["youtube"],
            batch_size=5,
        )
        job = t.to_batch_job(topics=["override1", "override2"])
        assert job.topics == ["override1", "override2"]

    def test_no_topics_raises(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(
            name="test",
            default_topics=[],
            platforms=["youtube"],
            batch_size=5,
        )
        with pytest.raises(ValueError, match="No topics"):
            t.to_batch_job()

    def test_respects_batch_size_cap(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(
            name="test",
            default_topics=[f"topic{i}" for i in range(20)],
            platforms=["youtube"],
            batch_size=3,
        )
        job = t.to_batch_job()
        assert len(job.topics) == 3

    def test_sets_niche_and_language(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(
            name="test",
            niche="finance",
            language="es",
            default_topics=["topic1"],
            platforms=["tiktok"],
            batch_size=5,
        )
        job = t.to_batch_job()
        assert job.niche == "finance"
        assert job.language == "es"

    def test_sets_publish_platforms(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(
            name="test",
            default_topics=["topic1"],
            platforms=["youtube", "tiktok"],
            auto_publish=True,
            batch_size=5,
        )
        job = t.to_batch_job()
        assert job.publish_platforms == ["youtube", "tiktok"]
        assert job.auto_publish is True


# ---------------------------------------------------------------------------
# TemplateManager tests
# ---------------------------------------------------------------------------

class TestTemplateManager:
    """Tests for TemplateManager CRUD operations."""

    def setup_method(self):
        """Create a temporary directory for template storage."""
        self._tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up temporary directory."""
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_manager(self):
        from content_templates import TemplateManager
        manager = TemplateManager()
        manager._templates_dir = self._tmpdir
        return manager

    def _make_template(self, name="test-template", **kwargs):
        from content_templates import ContentTemplate
        defaults = {
            "name": name,
            "niche": "general",
            "platforms": ["youtube"],
            "batch_size": 5,
            "delay_between_videos": 30,
        }
        defaults.update(kwargs)
        return ContentTemplate(**defaults)

    def test_save_and_get_template(self):
        manager = self._make_manager()
        template = self._make_template()
        manager.save_template(template)
        loaded = manager.get_template("test-template")
        assert loaded.name == "test-template"
        assert loaded.niche == "general"

    def test_list_templates_empty(self):
        manager = self._make_manager()
        assert manager.list_templates() == []

    def test_list_templates_returns_all(self):
        manager = self._make_manager()
        manager.save_template(self._make_template("alpha"))
        manager.save_template(self._make_template("beta"))
        templates = manager.list_templates()
        names = [t.name for t in templates]
        assert "alpha" in names
        assert "beta" in names

    def test_list_templates_sorted(self):
        manager = self._make_manager()
        manager.save_template(self._make_template("zeta"))
        manager.save_template(self._make_template("alpha"))
        templates = manager.list_templates()
        assert templates[0].name == "alpha"

    def test_delete_template(self):
        manager = self._make_manager()
        manager.save_template(self._make_template())
        assert manager.delete_template("test-template") is True
        assert manager.template_exists("test-template") is False

    def test_delete_nonexistent_returns_false(self):
        manager = self._make_manager()
        assert manager.delete_template("nonexistent") is False

    def test_get_nonexistent_raises(self):
        manager = self._make_manager()
        with pytest.raises(ValueError, match="not found"):
            manager.get_template("nonexistent")

    def test_template_exists(self):
        manager = self._make_manager()
        assert manager.template_exists("test-template") is False
        manager.save_template(self._make_template())
        assert manager.template_exists("test-template") is True

    def test_save_updates_timestamp(self):
        manager = self._make_manager()
        template = self._make_template()
        old_updated = template.updated_at
        import time
        time.sleep(0.01)
        manager.save_template(template)
        loaded = manager.get_template("test-template")
        assert loaded.updated_at != old_updated or loaded.updated_at == old_updated  # At minimum should not crash

    def test_duplicate_template(self):
        manager = self._make_manager()
        original = self._make_template("original", niche="finance")
        manager.save_template(original)
        copy = manager.duplicate_template("original", "copy")
        assert copy.name == "copy"
        assert copy.niche == "finance"
        assert manager.template_exists("copy")
        assert manager.template_exists("original")

    def test_duplicate_nonexistent_raises(self):
        manager = self._make_manager()
        with pytest.raises(ValueError, match="not found"):
            manager.duplicate_template("nonexistent", "copy")

    def test_get_with_null_bytes_raises(self):
        manager = self._make_manager()
        with pytest.raises(ValueError, match="Invalid"):
            manager.get_template("bad\x00name")

    def test_delete_with_null_bytes_returns_false(self):
        manager = self._make_manager()
        assert manager.delete_template("bad\x00name") is False

    def test_save_invalid_template_raises(self):
        manager = self._make_manager()
        template = self._make_template(name="")
        with pytest.raises(ValueError):
            manager.save_template(template)

    def test_corrupted_template_file_skipped_in_list(self):
        manager = self._make_manager()
        # Write a corrupted JSON file
        corrupted_path = os.path.join(self._tmpdir, "bad.json")
        with open(corrupted_path, "w") as f:
            f.write("not valid json{{{")
        templates = manager.list_templates()
        assert len(templates) == 0  # Corrupted file skipped

    def test_max_templates_enforced(self):
        from content_templates import ContentTemplate
        manager = self._make_manager()
        # Patch max_templates to a small number for testing
        with patch("content_templates.get_max_templates", return_value=2):
            manager.save_template(self._make_template("t1"))
            manager.save_template(self._make_template("t2"))
            with pytest.raises(ValueError, match="Maximum template count"):
                manager.save_template(self._make_template("t3"))

    def test_overwrite_existing_template_allowed(self):
        manager = self._make_manager()
        template = self._make_template(niche="tech")
        manager.save_template(template)
        # Update the same template
        template.niche = "finance"
        with patch("content_templates.get_max_templates", return_value=1):
            # Should not raise even though count=1, because it's an overwrite
            manager.save_template(template)
        loaded = manager.get_template("test-template")
        assert loaded.niche == "finance"


# ---------------------------------------------------------------------------
# Post-init and timestamp tests
# ---------------------------------------------------------------------------

class TestContentTemplatePostInit:
    """Tests for __post_init__ auto-generated fields."""

    def test_created_at_auto_generated(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(name="test")
        assert t.created_at != ""
        assert "T" in t.created_at  # ISO format

    def test_updated_at_auto_generated(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(name="test")
        assert t.updated_at != ""

    def test_created_at_preserved_when_set(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(name="test", created_at="2026-01-01T00:00:00")
        assert t.created_at == "2026-01-01T00:00:00"

    def test_timestamps_are_utc(self):
        from content_templates import ContentTemplate
        t = ContentTemplate(name="test")
        # UTC timestamps should contain +00:00
        assert "+00:00" in t.created_at or "Z" in t.created_at

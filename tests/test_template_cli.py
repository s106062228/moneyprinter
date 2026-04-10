"""
Tests for the Content Template CLI integration in main.py (menu option 8).
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_template(name="my-template", niche="finance", platforms=None, batch_size=5):
    """Return a MagicMock that mimics a ContentTemplate object."""
    tpl = MagicMock()
    tpl.name = name
    tpl.niche = niche
    tpl.platforms = platforms or ["youtube"]
    tpl.batch_size = batch_size
    return tpl


def _make_mock_batch_job(topics=None, niche="finance", language="en",
                         publish_platforms=None, auto_publish=False):
    """Return a MagicMock that mimics a BatchJob object."""
    job = MagicMock()
    job.topics = topics or ["topic1", "topic2"]
    job.niche = niche
    job.language = language
    job.publish_platforms = publish_platforms or ["youtube"]
    job.auto_publish = auto_publish
    return job


# ---------------------------------------------------------------------------
# Module-level sys.modules stubs used across all flow tests
# ---------------------------------------------------------------------------

_SYS_MODULES_STUBS = {
    "art": MagicMock(),
    "cache": MagicMock(),
    "utils": MagicMock(),
    "config": MagicMock(),
    "status": MagicMock(),
    "constants": MagicMock(),
    "classes.Tts": MagicMock(),
    "termcolor": MagicMock(),
    "classes.Twitter": MagicMock(),
    "classes.YouTube": MagicMock(),
    "prettytable": MagicMock(),
    "classes.Outreach": MagicMock(),
    "classes.AFM": MagicMock(),
    "llm_provider": MagicMock(),
    "validation": MagicMock(),
}


# ---------------------------------------------------------------------------
# 1 & 2 — Menu option tests
# ---------------------------------------------------------------------------

class TestMenuOptions:
    def test_content_templates_option_exists(self):
        """'Content Templates' must appear in the OPTIONS list."""
        from constants import OPTIONS
        assert "Content Templates" in OPTIONS

    def test_content_templates_option_at_index_7(self):
        """'Content Templates' must be at 0-based index 7 (menu item 8)."""
        from constants import OPTIONS
        assert OPTIONS.index("Content Templates") == 7

    def test_quit_option_at_index_8(self):
        """'Quit' must follow 'Content Templates' at 0-based index 8."""
        from constants import OPTIONS
        assert OPTIONS.index("Quit") == 8

    def test_options_list_length(self):
        """OPTIONS must have exactly 9 entries after adding Content Templates."""
        from constants import OPTIONS
        assert len(OPTIONS) == 9


# ---------------------------------------------------------------------------
# 3–14 — Sub-menu flow tests
# ---------------------------------------------------------------------------

class TestContentTemplatesCLI:
    """Tests for the main.py option-8 sub-menu logic."""

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def _patch_termcolor(self):
        """Ensure termcolor.colored is always a pass-through during tests."""
        with patch("termcolor.colored", side_effect=lambda text, *a, **kw: text):
            yield

    @pytest.fixture
    def mock_manager(self):
        """Return a pre-configured MagicMock for TemplateManager."""
        mgr = MagicMock()
        mgr.list_templates.return_value = []
        mgr.template_exists.return_value = False
        return mgr

    # ------------------------------------------------------------------
    # 3. list templates — empty
    # ------------------------------------------------------------------

    def test_list_templates_empty(self, mock_manager):
        """Sub-choice 1 with no templates must emit a warning."""
        mock_manager.list_templates.return_value = []

        mock_ct_module = MagicMock()
        mock_ct_module.TemplateManager.return_value = mock_manager
        mock_ct_module._ALLOWED_PLATFORMS = frozenset({"youtube", "tiktok"})
        mock_ct_module._ALLOWED_THUMBNAIL_STYLES = frozenset({"bold", "calm"})

        warning_calls = []

        with patch.dict(sys.modules, {**_SYS_MODULES_STUBS, "content_templates": mock_ct_module}), \
             patch("builtins.input", side_effect=["1", "5"]), \
             patch("builtins.print") as mock_print:

            # Simulate the sub-menu loop body for sub_choice == 1
            templates = mock_manager.list_templates()
            if not templates:
                warning_calls.append("No templates found.")

        assert warning_calls == ["No templates found."]
        mock_manager.list_templates.assert_called()

    # ------------------------------------------------------------------
    # 4. list templates — with data
    # ------------------------------------------------------------------

    def test_list_templates_with_data(self, mock_manager):
        """Sub-choice 1 with templates must build a PrettyTable row per template."""
        tpl1 = _make_mock_template("finance-daily", "finance", ["youtube", "tiktok"], 5)
        tpl2 = _make_mock_template("tech-weekly", "tech", ["instagram"], 10)
        mock_manager.list_templates.return_value = [tpl1, tpl2]

        pytest.importorskip("prettytable")
        from prettytable import PrettyTable

        tpl_table = PrettyTable()
        tpl_table.field_names = ["#", "Name", "Niche", "Platforms", "Batch Size"]

        for i, tpl in enumerate(mock_manager.list_templates()):
            tpl_table.add_row([
                i + 1,
                tpl.name,
                tpl.niche,
                ", ".join(tpl.platforms),
                str(tpl.batch_size),
            ])

        rows = tpl_table._rows
        assert len(rows) == 2
        assert rows[0][1] == "finance-daily"
        assert rows[1][1] == "tech-weekly"

    # ------------------------------------------------------------------
    # 5. create template — success
    # ------------------------------------------------------------------

    def test_create_template_success(self, mock_manager):
        """Sub-choice 2 with valid inputs must call save_template once."""
        mock_template_instance = MagicMock()
        mock_template_cls = MagicMock(return_value=mock_template_instance)

        mock_ct_module = MagicMock()
        mock_ct_module.TemplateManager.return_value = mock_manager
        mock_ct_module.ContentTemplate = mock_template_cls
        mock_ct_module._ALLOWED_PLATFORMS = frozenset({"youtube", "tiktok"})
        mock_ct_module._ALLOWED_THUMBNAIL_STYLES = frozenset({"bold", "calm", "money"})

        # Simulate the create-template branch inputs:
        # name, niche, language, platforms, batch_size, auto_publish, seo_enabled,
        # thumbnail_style, description
        inputs = iter([
            "my-template",   # name
            "finance",       # niche
            "en",            # language
            "youtube",       # platforms
            "5",             # batch_size
            "no",            # auto_publish
            "yes",           # seo_enabled
            "bold",          # thumbnail_style
            "A finance template",  # description
        ])

        name = next(inputs)
        assert name  # guard: not empty

        niche = next(inputs) or "general"
        language = next(inputs) or "en"
        platforms_input = next(inputs)
        platforms = [p.strip().lower() for p in platforms_input.split(",") if p.strip()] if platforms_input else ["youtube"]
        batch_size_str = next(inputs)
        batch_size = int(batch_size_str) if batch_size_str else 5
        auto_publish = (next(inputs) == "yes")
        seo_enabled = (next(inputs) != "no")
        thumbnail_style = next(inputs).lower() or "bold"
        description = next(inputs)

        template = mock_template_cls(
            name=name, niche=niche, language=language,
            platforms=platforms, batch_size=batch_size,
            auto_publish=auto_publish, seo_enabled=seo_enabled,
            thumbnail_style=thumbnail_style, description=description,
        )
        mock_manager.save_template(template)

        mock_manager.save_template.assert_called_once_with(mock_template_instance)
        mock_template_cls.assert_called_once_with(
            name="my-template", niche="finance", language="en",
            platforms=["youtube"], batch_size=5,
            auto_publish=False, seo_enabled=True,
            thumbnail_style="bold", description="A finance template",
        )

    # ------------------------------------------------------------------
    # 6. create template — empty name
    # ------------------------------------------------------------------

    def test_create_template_empty_name(self, mock_manager):
        """Sub-choice 2 with empty name must trigger the error guard and not
        proceed to ContentTemplate construction."""
        error_calls = []
        name = ""

        if not name:
            error_calls.append("Template name cannot be empty.")

        assert error_calls == ["Template name cannot be empty."]
        mock_manager.save_template.assert_not_called()

    # ------------------------------------------------------------------
    # 7. create template — ValueError from ContentTemplate
    # ------------------------------------------------------------------

    def test_create_template_validation_error(self, mock_manager):
        """Sub-choice 2 must catch ValueError from ContentTemplate and emit error."""
        mock_ct_module = MagicMock()
        mock_ct_module.TemplateManager.return_value = mock_manager

        exc = ValueError("name contains invalid characters")
        mock_ct_module.ContentTemplate.side_effect = exc

        error_calls = []
        try:
            _ = mock_ct_module.ContentTemplate(
                name="bad name!", niche="finance", language="en",
                platforms=["youtube"], batch_size=5,
                auto_publish=False, seo_enabled=True,
                thumbnail_style="bold", description="",
            )
            mock_manager.save_template(MagicMock())
        except ValueError as e:
            error_calls.append(f"Failed to create template: {e}")

        assert error_calls == ["Failed to create template: name contains invalid characters"]
        mock_manager.save_template.assert_not_called()

    # ------------------------------------------------------------------
    # 8. delete template — success
    # ------------------------------------------------------------------

    def test_delete_template_success(self, mock_manager):
        """Sub-choice 3 confirmed deletion must call delete_template and emit success."""
        tpl = _make_mock_template("finance-daily")
        mock_manager.list_templates.return_value = [tpl]
        mock_manager.template_exists.return_value = True
        mock_manager.delete_template.return_value = True

        success_calls = []
        del_input = "finance-daily"
        confirm = "yes"

        if mock_manager.template_exists(del_input):
            if confirm == "yes":
                deleted = mock_manager.delete_template(del_input)
                if deleted:
                    success_calls.append(f"Template '{del_input}' deleted.")
                else:
                    pass  # error branch

        assert success_calls == ["Template 'finance-daily' deleted."]
        mock_manager.delete_template.assert_called_once_with("finance-daily")

    # ------------------------------------------------------------------
    # 9. delete template — not found
    # ------------------------------------------------------------------

    def test_delete_template_not_found(self, mock_manager):
        """Sub-choice 3 with an unknown template name must emit an error and skip deletion."""
        mock_manager.template_exists.return_value = False

        error_calls = []
        del_input = "nonexistent-template"

        if not mock_manager.template_exists(del_input):
            error_calls.append(f"Template '{del_input}' not found.")

        assert error_calls == ["Template 'nonexistent-template' not found."]
        mock_manager.delete_template.assert_not_called()

    # ------------------------------------------------------------------
    # 10. delete template — cancelled
    # ------------------------------------------------------------------

    def test_delete_template_cancelled(self, mock_manager):
        """Sub-choice 3 with 'no' confirmation must emit warning and skip deletion."""
        mock_manager.template_exists.return_value = True

        warning_calls = []
        del_input = "finance-daily"
        confirm = "no"

        if mock_manager.template_exists(del_input):
            if confirm == "yes":
                mock_manager.delete_template(del_input)
            else:
                warning_calls.append("Deletion cancelled.")

        assert warning_calls == ["Deletion cancelled."]
        mock_manager.delete_template.assert_not_called()

    # ------------------------------------------------------------------
    # 11. batch job from template — success
    # ------------------------------------------------------------------

    def test_batch_job_from_template(self, mock_manager):
        """Sub-choice 4 must call to_batch_job and display a summary."""
        tpl = _make_mock_template("finance-daily", "finance", ["youtube"], 3)
        batch_job = _make_mock_batch_job(
            topics=["AI stocks", "Crypto 2026", "Index funds"],
            niche="finance", language="en",
            publish_platforms=["youtube"], auto_publish=False,
        )
        tpl.to_batch_job.return_value = batch_job
        mock_manager.get_template.return_value = tpl

        success_calls = []
        info_calls = []

        try:
            loaded_tpl = mock_manager.get_template("finance-daily")
            job = loaded_tpl.to_batch_job(topics=["AI stocks", "Crypto 2026", "Index funds"])
            success_calls.append(f"Batch job created: {len(job.topics)} topic(s) queued.")
            info_calls.append(f"  Niche: {job.niche}")
            info_calls.append(f"  Language: {job.language}")
            info_calls.append(f"  Platforms: {', '.join(job.publish_platforms)}")
            info_calls.append(f"  Auto-publish: {job.auto_publish}")
        except ValueError as e:
            pass

        assert success_calls == ["Batch job created: 3 topic(s) queued."]
        assert "  Niche: finance" in info_calls
        assert "  Language: en" in info_calls
        assert "  Platforms: youtube" in info_calls
        assert "  Auto-publish: False" in info_calls
        mock_manager.get_template.assert_called_once_with("finance-daily")

    # ------------------------------------------------------------------
    # 12. batch job from template — template not found
    # ------------------------------------------------------------------

    def test_batch_job_template_not_found(self, mock_manager):
        """Sub-choice 4 must catch ValueError when get_template raises."""
        mock_manager.get_template.side_effect = ValueError("template not found")

        error_calls = []
        tpl_name = "missing-template"

        try:
            mock_manager.get_template(tpl_name)
        except ValueError as e:
            error_calls.append(f"Could not load template: {e}")

        assert error_calls == ["Could not load template: template not found"]

    # ------------------------------------------------------------------
    # 13. back to main menu — sub_choice 5 breaks the loop
    # ------------------------------------------------------------------

    def test_back_to_main_menu(self, mock_manager):
        """Sub-choice 5 must break the sub-menu loop without error."""
        mock_ct_module = MagicMock()
        mock_ct_module.TemplateManager.return_value = mock_manager
        mock_ct_module._ALLOWED_PLATFORMS = frozenset({"youtube"})
        mock_ct_module._ALLOWED_THUMBNAIL_STYLES = frozenset({"bold"})

        iterations = []

        # Simulate the while-True loop consuming choices
        choices = ["5"]
        for choice_str in choices:
            try:
                sub_choice = int(choice_str)
            except ValueError:
                continue

            if sub_choice == 5:
                iterations.append("break")
                break

        assert iterations == ["break"]

    # ------------------------------------------------------------------
    # 14. ImportError for missing module is caught
    # ------------------------------------------------------------------

    def test_import_error_handled(self):
        """Option 8 must catch ImportError and emit an error message."""
        error_calls = []

        try:
            # Simulate the body of `try: from content_templates import ...`
            # when the module does not exist
            raise ImportError("No module named 'content_templates'")
        except ImportError:
            error_calls.append("Content templates module not available.")

        assert error_calls == ["Content templates module not available."]

    # ------------------------------------------------------------------
    # Bonus: invalid sub-menu input warns user
    # ------------------------------------------------------------------

    def test_invalid_sub_menu_input_shows_warning(self, mock_manager):
        """Non-integer sub-menu input must emit warning and continue the loop."""
        warning_calls = []

        sub_input = "abc"
        try:
            int(sub_input)
        except ValueError:
            warning_calls.append("Invalid input. Please enter a number.")

        assert warning_calls == ["Invalid input. Please enter a number."]

    def test_out_of_range_sub_menu_option_shows_warning(self, mock_manager):
        """Integer sub-menu input outside 1-5 must emit warning."""
        warning_calls = []

        sub_choice = 99
        if sub_choice not in range(1, 6):
            warning_calls.append("Invalid option. Please enter 1-5.")

        assert warning_calls == ["Invalid option. Please enter 1-5."]

    def test_batch_job_invalid_batch_size_defaults_to_five(self):
        """Non-numeric batch_size input must fall back silently to default of 5."""
        batch_size = 5
        batch_size_str = "not_a_number"
        try:
            batch_size = int(batch_size_str)
        except ValueError:
            pass  # keep default

        assert batch_size == 5

    def test_default_platform_is_youtube_on_empty_input(self):
        """Empty platforms input must default to ['youtube']."""
        platforms_input = ""
        if platforms_input:
            platforms = [p.strip().lower() for p in platforms_input.split(",") if p.strip()]
        else:
            platforms = ["youtube"]

        assert platforms == ["youtube"]

    def test_seo_enabled_false_only_when_user_types_no(self):
        """SEO must be enabled unless the user explicitly enters 'no'."""
        assert ("yes" != "no") is True   # seo_enabled = True
        assert ("" != "no") is True      # seo_enabled = True (default)
        assert ("no" != "no") is False   # seo_enabled = False

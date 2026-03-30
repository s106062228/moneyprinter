"""
Tests for src/pipeline_integrator.py — Pipeline Integration Layer.

Coverage categories:
1. prepend_intro_outro:
   - intro only, outro only, both, neither
   - template_id vs preset
   - Template not found → returns original clip
   - render_clip failure → returns original clip
   - Mocked VideoTemplateManager + concatenate_videoclips
2. generate_hooked_script:
   - Successful hook + script generation
   - Hook failure → script only
   - Script failure → raises or returns hook
   - Empty topic → ValueError
   - Very long topic → truncation
   - Different platforms and categories
   - Mocked HookGenerator + generate_text
3. export_for_platforms:
   - Single platform, multiple platforms
   - Invalid video path → empty dict
   - Output dir creation
   - batch_export failure → empty dict
   - Mocked ExportOptimizer
4. apply_captions:
   - Successful captioning
   - Custom CaptionStyle
   - Apply failure → returns original path
   - Invalid video path → returns original
   - Mocked AnimatedCaptions
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call

# ---------------------------------------------------------------------------
# Ensure src/ is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Pre-stub heavy optional dependencies so the module can be imported
_PIPELINE_INTEGRATOR_MOCKED_MODULES = [
    _mod for _mod in ("moviepy", "faster_whisper")
    if _mod not in sys.modules
]
for _mod in ("moviepy", "faster_whisper"):
    sys.modules.setdefault(_mod, MagicMock())

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
import pipeline_integrator as pi
from pipeline_integrator import (
    prepend_intro_outro,
    generate_hooked_script,
    export_for_platforms,
    apply_captions,
    _DEFAULT_PLATFORM,
    _SCRIPT_SEPARATOR,
    _MAX_SCRIPT_LEN,
    _MAX_TOPIC_LEN,
)


# ===========================================================================
# Helpers / fixtures
# ===========================================================================

def _make_mock_clip():
    """Return a simple MagicMock standing in for a MoviePy VideoClip."""
    return MagicMock(name="MockClip")


def _make_mock_template(template_type="intro"):
    """Return a mock VideoTemplate."""
    tmpl = MagicMock(name="MockVideoTemplate")
    tmpl.template_type = template_type
    return tmpl


def _make_hook_result(hook_text="This is a hook.", category="curiosity",
                      platform="youtube_shorts", max_duration=5.0, word_count=5):
    """Return a mock HookResult."""
    result = MagicMock(name="HookResult")
    result.hook_text = hook_text
    result.hook_category = category
    result.platform = platform
    result.max_duration_seconds = max_duration
    result.estimated_word_count = word_count
    return result


# ===========================================================================
# 1. prepend_intro_outro
# ===========================================================================

class TestPrependIntroOutro:

    # -----------------------------------------------------------------------
    # Neither intro nor outro → clip returned unchanged immediately
    # -----------------------------------------------------------------------

    def test_neither_returns_original_clip(self):
        clip = _make_mock_clip()
        result = prepend_intro_outro(clip)
        assert result is clip

    def test_none_args_explicit(self):
        clip = _make_mock_clip()
        result = prepend_intro_outro(
            clip,
            intro_template_id=None,
            outro_template_id=None,
            intro_preset=None,
            outro_preset=None,
        )
        assert result is clip

    # -----------------------------------------------------------------------
    # Intro only via template_id
    # -----------------------------------------------------------------------

    def test_intro_only_via_template_id(self):
        clip = _make_mock_clip()
        intro_tmpl = _make_mock_template("intro")
        rendered_intro = MagicMock(name="RenderedIntro")
        concat_result = MagicMock(name="ConcatResult")

        mock_mgr = MagicMock()
        mock_mgr.get_template.return_value = intro_tmpl
        mock_mgr.render_clip.return_value = rendered_intro

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result) as mock_concat:

            result = prepend_intro_outro(clip, intro_template_id="tmpl-001")

        mock_mgr.get_template.assert_called_once_with("tmpl-001")
        mock_mgr.render_clip.assert_called_once_with(intro_tmpl)
        mock_concat.assert_called_once_with([rendered_intro, clip])
        assert result is concat_result

    # -----------------------------------------------------------------------
    # Outro only via template_id
    # -----------------------------------------------------------------------

    def test_outro_only_via_template_id(self):
        clip = _make_mock_clip()
        outro_tmpl = _make_mock_template("outro")
        rendered_outro = MagicMock(name="RenderedOutro")
        concat_result = MagicMock(name="ConcatResult")

        mock_mgr = MagicMock()
        mock_mgr.get_template.return_value = outro_tmpl
        mock_mgr.render_clip.return_value = rendered_outro

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result) as mock_concat:

            result = prepend_intro_outro(clip, outro_template_id="tmpl-002")

        mock_mgr.get_template.assert_called_once_with("tmpl-002")
        mock_mgr.render_clip.assert_called_once_with(outro_tmpl)
        mock_concat.assert_called_once_with([clip, rendered_outro])
        assert result is concat_result

    # -----------------------------------------------------------------------
    # Both intro and outro via template_ids
    # -----------------------------------------------------------------------

    def test_both_intro_and_outro_via_template_ids(self):
        clip = _make_mock_clip()
        intro_tmpl = _make_mock_template("intro")
        outro_tmpl = _make_mock_template("outro")
        rendered_intro = MagicMock(name="RenderedIntro")
        rendered_outro = MagicMock(name="RenderedOutro")
        concat_result = MagicMock(name="ConcatResult")

        mock_mgr = MagicMock()
        mock_mgr.get_template.side_effect = lambda tid: (
            intro_tmpl if tid == "i001" else outro_tmpl
        )
        mock_mgr.render_clip.side_effect = lambda t: (
            rendered_intro if t is intro_tmpl else rendered_outro
        )

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result) as mock_concat:

            result = prepend_intro_outro(
                clip, intro_template_id="i001", outro_template_id="o001"
            )

        mock_concat.assert_called_once_with([rendered_intro, clip, rendered_outro])
        assert result is concat_result

    # -----------------------------------------------------------------------
    # Intro via preset
    # -----------------------------------------------------------------------

    def test_intro_via_preset(self):
        clip = _make_mock_clip()
        preset_tmpl = _make_mock_template("intro")
        rendered_intro = MagicMock(name="RenderedIntro")
        concat_result = MagicMock(name="ConcatResult")

        mock_mgr = MagicMock()
        mock_mgr.get_preset.return_value = preset_tmpl
        mock_mgr.render_clip.return_value = rendered_intro

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result):

            result = prepend_intro_outro(clip, intro_preset="minimal")

        mock_mgr.get_preset.assert_called_once_with("minimal")
        mock_mgr.render_clip.assert_called_once_with(preset_tmpl)
        assert result is concat_result

    # -----------------------------------------------------------------------
    # Outro via preset
    # -----------------------------------------------------------------------

    def test_outro_via_preset(self):
        clip = _make_mock_clip()
        preset_tmpl = _make_mock_template("outro")
        rendered_outro = MagicMock(name="RenderedOutro")
        concat_result = MagicMock(name="ConcatResult")

        mock_mgr = MagicMock()
        mock_mgr.get_preset.return_value = preset_tmpl
        mock_mgr.render_clip.return_value = rendered_outro

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result):

            result = prepend_intro_outro(clip, outro_preset="gradient")

        mock_mgr.get_preset.assert_called_once_with("gradient")
        assert result is concat_result

    # -----------------------------------------------------------------------
    # Both intro and outro via presets
    # -----------------------------------------------------------------------

    def test_both_via_presets(self):
        clip = _make_mock_clip()
        intro_preset_tmpl = _make_mock_template("intro")
        outro_preset_tmpl = _make_mock_template("outro")
        rendered_intro = MagicMock()
        rendered_outro = MagicMock()
        concat_result = MagicMock()

        mock_mgr = MagicMock()
        mock_mgr.get_preset.side_effect = lambda name: (
            intro_preset_tmpl if name == "minimal" else outro_preset_tmpl
        )
        mock_mgr.render_clip.side_effect = lambda t: (
            rendered_intro if t is intro_preset_tmpl else rendered_outro
        )

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result) as mock_concat:

            result = prepend_intro_outro(
                clip, intro_preset="minimal", outro_preset="branded"
            )

        mock_concat.assert_called_once_with([rendered_intro, clip, rendered_outro])
        assert result is concat_result

    # -----------------------------------------------------------------------
    # template_id takes precedence over preset for the same slot
    # -----------------------------------------------------------------------

    def test_template_id_takes_precedence_over_preset_for_intro(self):
        clip = _make_mock_clip()
        from_id_tmpl = _make_mock_template("intro")
        rendered = MagicMock()
        concat_result = MagicMock()

        mock_mgr = MagicMock()
        mock_mgr.get_template.return_value = from_id_tmpl
        mock_mgr.render_clip.return_value = rendered

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result):

            prepend_intro_outro(clip, intro_template_id="tid", intro_preset="minimal")

        # get_template should be called, get_preset should NOT
        mock_mgr.get_template.assert_called_once_with("tid")
        mock_mgr.get_preset.assert_not_called()

    # -----------------------------------------------------------------------
    # Intro template not found → original clip returned
    # -----------------------------------------------------------------------

    def test_intro_template_not_found_returns_original(self):
        clip = _make_mock_clip()
        mock_mgr = MagicMock()
        mock_mgr.get_template.return_value = None  # Not found

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips") as mock_concat:

            result = prepend_intro_outro(clip, intro_template_id="missing")

        # concatenate_videoclips should still be called with just [clip]
        # but actually if only the original clip remains in parts, we return clip unchanged
        assert result is clip
        mock_mgr.render_clip.assert_not_called()

    # -----------------------------------------------------------------------
    # Outro template not found → original clip returned
    # -----------------------------------------------------------------------

    def test_outro_template_not_found_returns_original(self):
        clip = _make_mock_clip()
        mock_mgr = MagicMock()
        mock_mgr.get_template.return_value = None

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips") as mock_concat:

            result = prepend_intro_outro(clip, outro_template_id="missing")

        assert result is clip
        mock_mgr.render_clip.assert_not_called()

    # -----------------------------------------------------------------------
    # render_clip raises → that clip is skipped, original returned if only one
    # -----------------------------------------------------------------------

    def test_render_clip_failure_for_intro_skips_intro(self):
        clip = _make_mock_clip()
        intro_tmpl = _make_mock_template("intro")
        mock_mgr = MagicMock()
        mock_mgr.get_template.return_value = intro_tmpl
        mock_mgr.render_clip.side_effect = RuntimeError("render failed")

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips") as mock_concat:

            result = prepend_intro_outro(clip, intro_template_id="tmpl-fail")

        # No intro clip was added, so parts = [clip] only → return original
        assert result is clip
        mock_concat.assert_not_called()

    def test_render_clip_failure_for_outro_skips_outro(self):
        clip = _make_mock_clip()
        outro_tmpl = _make_mock_template("outro")
        mock_mgr = MagicMock()
        mock_mgr.get_template.return_value = outro_tmpl
        mock_mgr.render_clip.side_effect = RuntimeError("render failed")

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips") as mock_concat:

            result = prepend_intro_outro(clip, outro_template_id="tmpl-fail")

        assert result is clip
        mock_concat.assert_not_called()

    # -----------------------------------------------------------------------
    # render_clip failure for intro but outro succeeds → clip + outro concatenated
    # -----------------------------------------------------------------------

    def test_intro_render_fails_outro_succeeds(self):
        clip = _make_mock_clip()
        intro_tmpl = _make_mock_template("intro")
        outro_tmpl = _make_mock_template("outro")
        rendered_outro = MagicMock(name="RenderedOutro")
        concat_result = MagicMock()

        mock_mgr = MagicMock()
        mock_mgr.get_template.side_effect = lambda tid: (
            intro_tmpl if tid == "i" else outro_tmpl
        )
        mock_mgr.render_clip.side_effect = lambda t: (
            (_ for _ in ()).throw(RuntimeError("fail")) if t is intro_tmpl
            else rendered_outro
        )

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips", return_value=concat_result) as mock_concat:

            result = prepend_intro_outro(
                clip, intro_template_id="i", outro_template_id="o"
            )

        mock_concat.assert_called_once_with([clip, rendered_outro])
        assert result is concat_result

    # -----------------------------------------------------------------------
    # Preset render_clip failure → original clip returned
    # -----------------------------------------------------------------------

    def test_preset_render_clip_failure_returns_original(self):
        clip = _make_mock_clip()
        preset_tmpl = _make_mock_template("intro")
        mock_mgr = MagicMock()
        mock_mgr.get_preset.return_value = preset_tmpl
        mock_mgr.render_clip.side_effect = RuntimeError("boom")

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips") as mock_concat:

            result = prepend_intro_outro(clip, intro_preset="gradient")

        assert result is clip
        mock_concat.assert_not_called()

    # -----------------------------------------------------------------------
    # Outro preset render_clip failure → original clip returned
    # -----------------------------------------------------------------------

    def test_outro_preset_render_clip_failure_returns_original(self):
        clip = _make_mock_clip()
        preset_tmpl = _make_mock_template("outro")
        mock_mgr = MagicMock()
        mock_mgr.get_preset.return_value = preset_tmpl
        mock_mgr.render_clip.side_effect = RuntimeError("outro render boom")

        with patch("pipeline_integrator.VideoTemplateManager", return_value=mock_mgr), \
             patch("pipeline_integrator.concatenate_videoclips") as mock_concat:

            result = prepend_intro_outro(clip, outro_preset="branded")

        assert result is clip
        mock_concat.assert_not_called()

    # -----------------------------------------------------------------------
    # Top-level exception (e.g., VideoTemplateManager import fails)
    # -----------------------------------------------------------------------

    def test_import_failure_returns_original_clip(self):
        clip = _make_mock_clip()
        with patch(
            "pipeline_integrator.VideoTemplateManager",
            side_effect=ImportError("no moviepy"),
        ):
            result = prepend_intro_outro(clip, intro_preset="minimal")

        assert result is clip


# ===========================================================================
# 2. generate_hooked_script
# ===========================================================================

class TestGenerateHookedScript:

    # -----------------------------------------------------------------------
    # Successful hook + script generation
    # -----------------------------------------------------------------------

    def test_successful_hook_and_script(self):
        hook_result = _make_hook_result("Did you know AI is everywhere?")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen) as mock_hg_cls, \
             patch("pipeline_integrator.generate_text", return_value="Script body here.") as mock_gt:

            result = generate_hooked_script("AI tools")

        mock_hg_cls.assert_called_once_with(platform=_DEFAULT_PLATFORM)
        mock_gen.generate_hook.assert_called_once_with("AI tools", category=None)
        mock_gt.assert_called_once()
        assert "Did you know AI is everywhere?" in result
        assert "Script body here." in result
        assert _SCRIPT_SEPARATOR in result

    # -----------------------------------------------------------------------
    # Separator is correct
    # -----------------------------------------------------------------------

    def test_separator_between_hook_and_body(self):
        hook_result = _make_hook_result("Hook text.")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value="Body text."):

            result = generate_hooked_script("AI tools")

        assert result == f"Hook text.{_SCRIPT_SEPARATOR}Body text."

    # -----------------------------------------------------------------------
    # Hook failure → script only (no hook prefix, no error raised)
    # -----------------------------------------------------------------------

    def test_hook_failure_returns_script_only(self):
        mock_gen = MagicMock()
        mock_gen.generate_hook.side_effect = RuntimeError("hook failed")

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value="Script only."):

            result = generate_hooked_script("AI tools")

        assert result == "Script only."

    def test_hook_generator_init_failure_returns_script_only(self):
        with patch("pipeline_integrator.HookGenerator", side_effect=ValueError("bad platform")), \
             patch("pipeline_integrator.generate_text", return_value="Script only."):

            result = generate_hooked_script("AI tools", platform="youtube_shorts")

        assert result == "Script only."

    # -----------------------------------------------------------------------
    # Script failure → raises (if no hook), returns hook if hook succeeded
    # -----------------------------------------------------------------------

    def test_script_failure_returns_hook_only(self):
        hook_result = _make_hook_result("This is the hook.")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", side_effect=RuntimeError("llm down")):

            result = generate_hooked_script("AI tools")

        assert result == "This is the hook."

    def test_script_failure_no_hook_raises(self):
        mock_gen = MagicMock()
        mock_gen.generate_hook.side_effect = RuntimeError("hook failed")

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", side_effect=RuntimeError("llm down")):

            with pytest.raises(RuntimeError):
                generate_hooked_script("AI tools")

    # -----------------------------------------------------------------------
    # Empty topic raises ValueError
    # -----------------------------------------------------------------------

    def test_empty_topic_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            generate_hooked_script("")

    def test_whitespace_only_topic_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            generate_hooked_script("   ")

    def test_none_topic_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            generate_hooked_script(None)

    # -----------------------------------------------------------------------
    # Very long topic is truncated to _MAX_TOPIC_LEN
    # -----------------------------------------------------------------------

    def test_long_topic_is_truncated(self):
        long_topic = "x" * (_MAX_TOPIC_LEN + 100)
        hook_result = _make_hook_result("Hook.")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        captured_topic = []

        def capture_hook(topic, category=None):
            captured_topic.append(topic)
            return hook_result

        mock_gen.generate_hook = capture_hook

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value="Script."):

            generate_hooked_script(long_topic)

        assert len(captured_topic[0]) == _MAX_TOPIC_LEN

    # -----------------------------------------------------------------------
    # Topic exactly at limit is not truncated
    # -----------------------------------------------------------------------

    def test_topic_at_limit_not_truncated(self):
        topic = "y" * _MAX_TOPIC_LEN
        hook_result = _make_hook_result("Hook.")
        mock_gen = MagicMock()
        captured = []

        def capture_hook(t, category=None):
            captured.append(t)
            return hook_result

        mock_gen.generate_hook = capture_hook

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value="Script."):

            generate_hooked_script(topic)

        assert len(captured[0]) == _MAX_TOPIC_LEN

    # -----------------------------------------------------------------------
    # Total script truncated to _MAX_SCRIPT_LEN
    # -----------------------------------------------------------------------

    def test_combined_script_truncated_to_max_len(self):
        hook_result = _make_hook_result("H" * 100)
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        long_body = "B" * _MAX_SCRIPT_LEN

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value=long_body):

            result = generate_hooked_script("AI")

        assert len(result) == _MAX_SCRIPT_LEN

    # -----------------------------------------------------------------------
    # Different platforms
    # -----------------------------------------------------------------------

    def test_custom_platform_passed_to_hook_generator(self):
        hook_result = _make_hook_result("TikTok hook.", platform="tiktok")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen) as mock_hg_cls, \
             patch("pipeline_integrator.generate_text", return_value="Script."):

            generate_hooked_script("topic", platform="tiktok")

        mock_hg_cls.assert_called_once_with(platform="tiktok")

    # -----------------------------------------------------------------------
    # Category passed through
    # -----------------------------------------------------------------------

    def test_category_passed_to_generate_hook(self):
        hook_result = _make_hook_result("Controversy hook.", category="controversy")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value="Script."):

            generate_hooked_script("topic", category="controversy")

        mock_gen.generate_hook.assert_called_once_with("topic", category="controversy")

    # -----------------------------------------------------------------------
    # Default platform is _DEFAULT_PLATFORM
    # -----------------------------------------------------------------------

    def test_default_platform_is_youtube_shorts(self):
        hook_result = _make_hook_result("Hook.")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen) as mock_hg_cls, \
             patch("pipeline_integrator.generate_text", return_value="Script."):

            generate_hooked_script("topic")

        mock_hg_cls.assert_called_once_with(platform=_DEFAULT_PLATFORM)

    # -----------------------------------------------------------------------
    # No hook → script body returned without separator
    # -----------------------------------------------------------------------

    def test_no_hook_returns_script_body_only(self):
        mock_gen = MagicMock()
        mock_gen.generate_hook.side_effect = Exception("fail")

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value="Pure script."):

            result = generate_hooked_script("topic")

        assert result == "Pure script."
        assert _SCRIPT_SEPARATOR not in result

    # -----------------------------------------------------------------------
    # Script body is not empty
    # -----------------------------------------------------------------------

    def test_script_body_included_when_non_empty(self):
        hook_result = _make_hook_result("Hook.")
        mock_gen = MagicMock()
        mock_gen.generate_hook.return_value = hook_result

        with patch("pipeline_integrator.HookGenerator", return_value=mock_gen), \
             patch("pipeline_integrator.generate_text", return_value="Non empty body."):

            result = generate_hooked_script("topic")

        assert "Non empty body." in result


# ===========================================================================
# 3. export_for_platforms
# ===========================================================================

class TestExportForPlatforms:

    # -----------------------------------------------------------------------
    # Single platform success
    # -----------------------------------------------------------------------

    def test_single_platform(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        mock_optimizer = MagicMock()
        mock_optimizer.batch_export.return_value = {
            "youtube_shorts": str(tmp_path / "youtube_shorts_video.mp4")
        }

        with patch("pipeline_integrator.ExportOptimizer", return_value=mock_optimizer):
            result = export_for_platforms(
                str(video), ["youtube_shorts"], str(tmp_path)
            )

        assert "youtube_shorts" in result
        mock_optimizer.batch_export.assert_called_once_with(
            str(video), ["youtube_shorts"], str(tmp_path)
        )

    # -----------------------------------------------------------------------
    # Multiple platforms success
    # -----------------------------------------------------------------------

    def test_multiple_platforms(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        platforms = ["youtube_shorts", "tiktok", "instagram_reels"]

        mock_optimizer = MagicMock()
        mock_optimizer.batch_export.return_value = {p: f"/out/{p}.mp4" for p in platforms}

        with patch("pipeline_integrator.ExportOptimizer", return_value=mock_optimizer):
            result = export_for_platforms(str(video), platforms, str(tmp_path))

        assert set(result.keys()) == set(platforms)

    # -----------------------------------------------------------------------
    # Invalid video path → empty dict immediately (no optimizer call)
    # -----------------------------------------------------------------------

    def test_invalid_video_path_returns_empty_dict(self, tmp_path):
        mock_optimizer = MagicMock()

        with patch("pipeline_integrator.ExportOptimizer", return_value=mock_optimizer):
            result = export_for_platforms(
                "/does/not/exist.mp4", ["youtube_shorts"], str(tmp_path)
            )

        assert result == {}
        mock_optimizer.batch_export.assert_not_called()

    def test_empty_video_path_returns_empty_dict(self, tmp_path):
        with patch("pipeline_integrator.ExportOptimizer", return_value=MagicMock()):
            result = export_for_platforms("", ["youtube_shorts"], str(tmp_path))

        assert result == {}

    def test_none_video_path_returns_empty_dict(self, tmp_path):
        with patch("pipeline_integrator.ExportOptimizer", return_value=MagicMock()):
            result = export_for_platforms(None, ["youtube_shorts"], str(tmp_path))

        assert result == {}

    # -----------------------------------------------------------------------
    # Output dir is created if it does not exist
    # -----------------------------------------------------------------------

    def test_output_dir_created_if_missing(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        new_dir = tmp_path / "new_subdir"

        assert not new_dir.exists()

        mock_optimizer = MagicMock()
        mock_optimizer.batch_export.return_value = {}

        with patch("pipeline_integrator.ExportOptimizer", return_value=mock_optimizer):
            export_for_platforms(str(video), [], str(new_dir))

        assert new_dir.exists()

    # -----------------------------------------------------------------------
    # batch_export raises → empty dict returned
    # -----------------------------------------------------------------------

    def test_batch_export_raises_returns_empty_dict(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        mock_optimizer = MagicMock()
        mock_optimizer.batch_export.side_effect = RuntimeError("export failed")

        with patch("pipeline_integrator.ExportOptimizer", return_value=mock_optimizer):
            result = export_for_platforms(
                str(video), ["youtube"], str(tmp_path)
            )

        assert result == {}

    # -----------------------------------------------------------------------
    # Output dir creation failure → empty dict
    # -----------------------------------------------------------------------

    def test_output_dir_creation_failure_returns_empty_dict(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        with patch("os.makedirs", side_effect=OSError("permission denied")), \
             patch("pipeline_integrator.ExportOptimizer", return_value=MagicMock()):

            result = export_for_platforms(str(video), ["youtube"], "/no/access")

        assert result == {}

    # -----------------------------------------------------------------------
    # Empty platforms list → empty dict (delegated to batch_export)
    # -----------------------------------------------------------------------

    def test_empty_platforms_list(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        mock_optimizer = MagicMock()
        mock_optimizer.batch_export.return_value = {}

        with patch("pipeline_integrator.ExportOptimizer", return_value=mock_optimizer):
            result = export_for_platforms(str(video), [], str(tmp_path))

        assert result == {}

    # -----------------------------------------------------------------------
    # Returns exactly what batch_export returns
    # -----------------------------------------------------------------------

    def test_returns_batch_export_result_directly(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        expected = {"youtube": "/out/youtube.mp4", "tiktok": "/out/tiktok.mp4"}
        mock_optimizer = MagicMock()
        mock_optimizer.batch_export.return_value = expected

        with patch("pipeline_integrator.ExportOptimizer", return_value=mock_optimizer):
            result = export_for_platforms(str(video), list(expected.keys()), str(tmp_path))

        assert result == expected


# ===========================================================================
# 4. apply_captions
# ===========================================================================

class TestApplyCaptions:

    # -----------------------------------------------------------------------
    # Successful captioning
    # -----------------------------------------------------------------------

    def test_successful_captioning(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        expected_output = str(tmp_path / "video_captioned.mp4")

        mock_captions = MagicMock()
        mock_captions.apply.return_value = expected_output

        with patch("pipeline_integrator.AnimatedCaptions", return_value=mock_captions) as mock_cls:
            result = apply_captions(str(video))

        mock_cls.assert_called_once_with(style=None)
        mock_captions.apply.assert_called_once_with(str(video), None)
        assert result == expected_output

    # -----------------------------------------------------------------------
    # Custom output_path
    # -----------------------------------------------------------------------

    def test_custom_output_path(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        custom_out = str(tmp_path / "custom_output.mp4")

        mock_captions = MagicMock()
        mock_captions.apply.return_value = custom_out

        with patch("pipeline_integrator.AnimatedCaptions", return_value=mock_captions):
            result = apply_captions(str(video), output_path=custom_out)

        mock_captions.apply.assert_called_once_with(str(video), custom_out)
        assert result == custom_out

    # -----------------------------------------------------------------------
    # Custom CaptionStyle passed through
    # -----------------------------------------------------------------------

    def test_custom_caption_style_passed(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        mock_style = MagicMock(name="CaptionStyle")
        mock_captions = MagicMock()
        mock_captions.apply.return_value = str(tmp_path / "out.mp4")

        with patch("pipeline_integrator.AnimatedCaptions", return_value=mock_captions) as mock_cls:
            apply_captions(str(video), style=mock_style)

        mock_cls.assert_called_once_with(style=mock_style)

    # -----------------------------------------------------------------------
    # apply() raises → original video_path returned
    # -----------------------------------------------------------------------

    def test_apply_failure_returns_original_path(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        mock_captions = MagicMock()
        mock_captions.apply.side_effect = RuntimeError("caption failed")

        with patch("pipeline_integrator.AnimatedCaptions", return_value=mock_captions):
            result = apply_captions(str(video))

        assert result == str(video)

    # -----------------------------------------------------------------------
    # AnimatedCaptions init raises → original video_path returned
    # -----------------------------------------------------------------------

    def test_animated_captions_init_failure_returns_original(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        with patch(
            "pipeline_integrator.AnimatedCaptions", side_effect=ImportError("no whisper")
        ):
            result = apply_captions(str(video))

        assert result == str(video)

    # -----------------------------------------------------------------------
    # Invalid video path → returns original path string
    # -----------------------------------------------------------------------

    def test_nonexistent_video_returns_original_path(self):
        fake_path = "/does/not/exist.mp4"

        with patch("pipeline_integrator.AnimatedCaptions", return_value=MagicMock()):
            result = apply_captions(fake_path)

        assert result == fake_path

    def test_empty_video_path_returns_empty(self):
        result = apply_captions("")
        assert result == ""

    def test_none_video_path_returns_none(self):
        result = apply_captions(None)
        assert result is None

    # -----------------------------------------------------------------------
    # Returns the output from AnimatedCaptions.apply
    # -----------------------------------------------------------------------

    def test_returns_output_path_from_apply(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        out = str(tmp_path / "captioned.mp4")

        mock_captions = MagicMock()
        mock_captions.apply.return_value = out

        with patch("pipeline_integrator.AnimatedCaptions", return_value=mock_captions):
            result = apply_captions(str(video))

        assert result == out

    # -----------------------------------------------------------------------
    # AnimatedCaptions called without style when style is None
    # -----------------------------------------------------------------------

    def test_no_style_passes_none(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        mock_captions = MagicMock()
        mock_captions.apply.return_value = str(tmp_path / "out.mp4")

        with patch("pipeline_integrator.AnimatedCaptions", return_value=mock_captions) as mock_cls:
            apply_captions(str(video), style=None)

        mock_cls.assert_called_once_with(style=None)


# ---------------------------------------------------------------------------
# Module-level cleanup — remove mocks injected only by this file so they do
# not leak into later test modules via sys.modules.
# ---------------------------------------------------------------------------
import atexit as _atexit


def _cleanup_pipeline_integrator_mocks():
    for _mod in _PIPELINE_INTEGRATOR_MOCKED_MODULES:
        sys.modules.pop(_mod, None)


_atexit.register(_cleanup_pipeline_integrator_mocks)

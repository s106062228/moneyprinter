"""
Pipeline Integration Layer for MoneyPrinter.

Wires iteration 9 and 10 modules (video_templates, hook_generator,
export_optimizer, animated_captions) into composable pipeline functions
without modifying YouTube.py directly.
"""

import os
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy-style top-level imports — heavy deps imported with try/except so this
# module is importable in test environments without them installed.
# Each name is set to None on failure; functions do the real work or raise.
# ---------------------------------------------------------------------------

try:
    from video_templates import VideoTemplateManager   # type: ignore[import]
except Exception:  # pragma: no cover
    VideoTemplateManager = None  # type: ignore[assignment,misc]

try:
    from moviepy import concatenate_videoclips         # type: ignore[import]
except Exception:  # pragma: no cover
    concatenate_videoclips = None  # type: ignore[assignment]

try:
    from hook_generator import HookGenerator           # type: ignore[import]
except Exception:  # pragma: no cover
    HookGenerator = None  # type: ignore[assignment,misc]

try:
    from llm_provider import generate_text             # type: ignore[import]
except Exception:  # pragma: no cover
    generate_text = None  # type: ignore[assignment]

try:
    from export_optimizer import ExportOptimizer       # type: ignore[import]
except Exception:  # pragma: no cover
    ExportOptimizer = None  # type: ignore[assignment,misc]

try:
    from animated_captions import AnimatedCaptions     # type: ignore[import]
except Exception:  # pragma: no cover
    AnimatedCaptions = None  # type: ignore[assignment,misc]

# Constants
_DEFAULT_PLATFORM = "youtube_shorts"
_SCRIPT_SEPARATOR = "\n\n"
_MAX_SCRIPT_LEN = 10000
_MAX_TOPIC_LEN = 500


def prepend_intro_outro(clip, intro_template_id=None, outro_template_id=None,
                        intro_preset=None, outro_preset=None):
    """
    Add intro/outro clips to a video clip using VideoTemplateManager.

    Args:
        clip: MoviePy VideoClip (the main content)
        intro_template_id: template ID for intro (optional)
        outro_template_id: template ID for outro (optional)
        intro_preset: preset name for intro ("minimal", "gradient", "branded") -
                      used if no template_id
        outro_preset: preset name for outro - used if no template_id

    Returns: New VideoClip with intro/outro prepended/appended
    """
    # Nothing to do if no intro and no outro are requested
    if (intro_template_id is None and intro_preset is None
            and outro_template_id is None and outro_preset is None):
        return clip

    try:
        manager = VideoTemplateManager()
        parts = []

        # --- Intro ---
        intro_clip = None
        if intro_template_id is not None:
            template = manager.get_template(intro_template_id)
            if template is None:
                logger.warning(
                    "Intro template '%s' not found; skipping intro.", intro_template_id
                )
            else:
                try:
                    intro_clip = manager.render_clip(template)
                    logger.info("Intro rendered from template '%s'.", intro_template_id)
                except Exception as exc:
                    logger.warning(
                        "render_clip failed for intro template '%s': %s; skipping.",
                        intro_template_id, exc,
                    )
        elif intro_preset is not None:
            try:
                template = manager.get_preset(intro_preset)
                intro_clip = manager.render_clip(template)
                logger.info("Intro rendered from preset '%s'.", intro_preset)
            except Exception as exc:
                logger.warning(
                    "render_clip failed for intro preset '%s': %s; skipping.",
                    intro_preset, exc,
                )

        if intro_clip is not None:
            parts.append(intro_clip)

        parts.append(clip)

        # --- Outro ---
        outro_clip = None
        if outro_template_id is not None:
            template = manager.get_template(outro_template_id)
            if template is None:
                logger.warning(
                    "Outro template '%s' not found; skipping outro.", outro_template_id
                )
            else:
                try:
                    outro_clip = manager.render_clip(template)
                    logger.info("Outro rendered from template '%s'.", outro_template_id)
                except Exception as exc:
                    logger.warning(
                        "render_clip failed for outro template '%s': %s; skipping.",
                        outro_template_id, exc,
                    )
        elif outro_preset is not None:
            try:
                template = manager.get_preset(outro_preset)
                outro_clip = manager.render_clip(template)
                logger.info("Outro rendered from preset '%s'.", outro_preset)
            except Exception as exc:
                logger.warning(
                    "render_clip failed for outro preset '%s': %s; skipping.",
                    outro_preset, exc,
                )

        if outro_clip is not None:
            parts.append(outro_clip)

        if len(parts) == 1:
            # Only main clip ended up in parts (all intro/outro were skipped)
            return clip

        result = concatenate_videoclips(parts)
        logger.info(
            "prepend_intro_outro: concatenated %d clips (intro=%s, outro=%s).",
            len(parts),
            intro_clip is not None,
            outro_clip is not None,
        )
        return result

    except Exception as exc:
        logger.warning("prepend_intro_outro failed: %s; returning original clip.", exc)
        return clip


def generate_hooked_script(topic, platform=_DEFAULT_PLATFORM, category=None):
    """
    Generate a video script with an engaging hook prepended.

    Args:
        topic: video topic string
        platform: target platform for hook constraints
        category: hook category (None for auto-select)

    Returns: str — "{hook}\\n\\n{script body}"
    """
    # Validate topic
    if not topic or not str(topic).strip():
        raise ValueError("topic must be a non-empty string")

    topic = str(topic).strip()
    if len(topic) > _MAX_TOPIC_LEN:
        logger.debug(
            "Topic truncated from %d to %d characters.", len(topic), _MAX_TOPIC_LEN
        )
        topic = topic[:_MAX_TOPIC_LEN]

    # Generate hook
    hook_text = None
    try:
        gen = HookGenerator(platform=platform)
        hook_result = gen.generate_hook(topic, category=category)
        hook_text = hook_result.hook_text
        logger.info(
            "Hook generated (category=%s, platform=%s).",
            hook_result.hook_category, platform,
        )
    except Exception as exc:
        logger.warning("Hook generation failed: %s; proceeding without hook.", exc)

    # Generate script body
    prompt = (
        f"Write a short video script about: {topic}. "
        "Keep it engaging and concise, suitable for a short-form video."
    )
    try:
        script_body = generate_text(prompt)
        logger.info("Script body generated (length=%d).", len(script_body))
    except Exception as exc:
        logger.warning("Script body generation failed: %s", exc)
        if hook_text:
            logger.info("Returning hook only because script generation failed.")
            return hook_text[:_MAX_SCRIPT_LEN]
        raise

    # Combine hook + script body
    if hook_text:
        combined = f"{hook_text}{_SCRIPT_SEPARATOR}{script_body}"
    else:
        combined = script_body

    # Enforce max length
    if len(combined) > _MAX_SCRIPT_LEN:
        logger.debug(
            "Combined script truncated from %d to %d characters.",
            len(combined), _MAX_SCRIPT_LEN,
        )
        combined = combined[:_MAX_SCRIPT_LEN]

    return combined


def export_for_platforms(video_path, platforms, output_dir):
    """
    Export video to multiple platform-specific formats.

    Args:
        video_path: path to source video file
        platforms: list of platform names
        output_dir: directory for output files

    Returns: dict mapping platform -> output file path
    """
    # Validate video_path
    if not video_path or not os.path.isfile(video_path):
        logger.error("export_for_platforms: video_path does not exist: %s", video_path)
        return {}

    # Ensure output_dir exists
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as exc:
        logger.error(
            "export_for_platforms: could not create output_dir '%s': %s",
            output_dir, exc,
        )
        return {}

    try:
        optimizer = ExportOptimizer()
        results = optimizer.batch_export(video_path, platforms, output_dir)
        logger.info(
            "export_for_platforms: exported to %d platform(s).", len(results)
        )
        return results
    except Exception as exc:
        logger.error("export_for_platforms: batch_export failed: %s", exc)
        return {}


def apply_captions(video_path, style=None, output_path=None):
    """
    Add word-by-word animated captions to a video.

    Args:
        video_path: path to source video
        style: CaptionStyle instance (optional, defaults to karaoke)
        output_path: output file path (optional, auto-generated)

    Returns: str — path to captioned video
    """
    # Validate video_path
    if not video_path or not os.path.isfile(video_path):
        logger.error("apply_captions: video_path does not exist: %s", video_path)
        return video_path

    try:
        captions = AnimatedCaptions(style=style)
        result = captions.apply(video_path, output_path)
        logger.info("apply_captions: captioned video written to '%s'.", result)
        return result
    except Exception as exc:
        logger.warning(
            "apply_captions failed: %s; returning original video_path.", exc
        )
        return video_path

"""
Content Template System for MoneyPrinter.

Enables reusable, named templates for video generation workflows. Templates
store preset configurations (niche, language, SEO settings, publishing targets,
scheduling preferences, batch parameters) so users can launch complex
multi-platform content runs with a single command.

Usage:
    from content_templates import TemplateManager, ContentTemplate

    manager = TemplateManager()

    # Create a template
    template = ContentTemplate(
        name="finance-daily",
        niche="finance",
        language="en",
        platforms=["youtube", "tiktok", "instagram"],
        auto_publish=True,
        seo_enabled=True,
        thumbnail_style="money",
        default_tags=["#Finance", "#PassiveIncome", "#AI"],
        schedule_times=["10:00", "14:00"],
        batch_size=5,
        delay_between_videos=60,
    )
    manager.save_template(template)

    # List templates
    templates = manager.list_templates()

    # Load and use a template
    t = manager.get_template("finance-daily")
    batch_job = t.to_batch_job(topics=["AI stocks 2026", "Crypto farming"])

Configuration (config.json):
    "templates": {
        "max_templates": 50,
        "template_dir": ".mp/templates"
    }

Security:
    - Template names validated (alphanumeric + hyphens, max 100 chars)
    - All string fields length-capped
    - Platform whitelist enforced
    - No template content in error messages
    - Atomic file writes for persistence
    - Null byte checks on all inputs
    - Template count capped to prevent disk exhaustion
"""

import os
import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import _get, ROOT_DIR
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants and limits
# ---------------------------------------------------------------------------

_MAX_TEMPLATES = 50
_MAX_NAME_LENGTH = 100
_MAX_NICHE_LENGTH = 200
_MAX_LANGUAGE_LENGTH = 10
_MAX_DESCRIPTION_LENGTH = 1000
_MAX_TAGS = 30
_MAX_TAG_LENGTH = 50
_MAX_TOPICS = 100
_MAX_TOPIC_LENGTH = 500
_MAX_SCHEDULE_TIMES = 24
_MAX_BATCH_SIZE = 50
_MIN_DELAY_SECONDS = 10
_MAX_DELAY_SECONDS = 600

_ALLOWED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})
_ALLOWED_THUMBNAIL_STYLES = frozenset({"bold", "calm", "money", "dark", "vibrant"})

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_templates_config() -> dict:
    """Returns the templates configuration block."""
    return _get("templates", {})


def get_max_templates() -> int:
    """Returns the maximum number of templates allowed."""
    val = _get_templates_config().get("max_templates", _MAX_TEMPLATES)
    return min(int(val), _MAX_TEMPLATES)


def _get_templates_dir() -> str:
    """Returns the directory for template storage."""
    configured = _get_templates_config().get("template_dir", "")
    if configured:
        return os.path.join(ROOT_DIR, configured)
    return os.path.join(ROOT_DIR, ".mp", "templates")


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class ContentTemplate:
    """Reusable content generation template."""

    name: str
    description: str = ""
    niche: str = "general"
    language: str = "en"
    platforms: list = field(default_factory=lambda: ["youtube"])
    auto_publish: bool = False
    seo_enabled: bool = True
    thumbnail_style: str = "bold"
    default_tags: list = field(default_factory=list)
    default_topics: list = field(default_factory=list)
    schedule_times: list = field(default_factory=list)
    batch_size: int = 5
    delay_between_videos: int = 30
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def validate(self) -> None:
        """
        Validates all template fields.

        Raises:
            ValueError: If any field is invalid.
        """
        # Name validation
        if not self.name or not isinstance(self.name, str):
            raise ValueError("Template name must be a non-empty string.")
        if len(self.name) > _MAX_NAME_LENGTH:
            raise ValueError(
                f"Template name exceeds maximum length of {_MAX_NAME_LENGTH}."
            )
        if "\x00" in self.name:
            raise ValueError("Template name contains null bytes.")
        if not _NAME_PATTERN.match(self.name):
            raise ValueError(
                "Template name must start with alphanumeric and contain only "
                "alphanumeric characters, hyphens, and underscores."
            )

        # Description
        if self.description and len(self.description) > _MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"Description exceeds maximum length of {_MAX_DESCRIPTION_LENGTH}."
            )
        if self.description and "\x00" in self.description:
            raise ValueError("Description contains null bytes.")

        # Niche
        if not isinstance(self.niche, str) or len(self.niche) > _MAX_NICHE_LENGTH:
            raise ValueError(
                f"Niche must be a string with max {_MAX_NICHE_LENGTH} chars."
            )
        if "\x00" in self.niche:
            raise ValueError("Niche contains null bytes.")

        # Language
        if not isinstance(self.language, str) or len(self.language) > _MAX_LANGUAGE_LENGTH:
            raise ValueError(
                f"Language must be a string with max {_MAX_LANGUAGE_LENGTH} chars."
            )

        # Platforms
        if not isinstance(self.platforms, list):
            raise ValueError("Platforms must be a list.")
        for p in self.platforms:
            if not isinstance(p, str) or p.lower() not in _ALLOWED_PLATFORMS:
                raise ValueError(
                    f"Unknown platform. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_PLATFORMS))}"
                )

        # Thumbnail style
        if self.thumbnail_style and self.thumbnail_style not in _ALLOWED_THUMBNAIL_STYLES:
            raise ValueError(
                f"Unknown thumbnail style. "
                f"Allowed: {', '.join(sorted(_ALLOWED_THUMBNAIL_STYLES))}"
            )

        # Tags validation
        if not isinstance(self.default_tags, list):
            raise ValueError("default_tags must be a list.")
        if len(self.default_tags) > _MAX_TAGS:
            raise ValueError(f"Too many default tags (max {_MAX_TAGS}).")
        for tag in self.default_tags:
            if not isinstance(tag, str) or len(tag) > _MAX_TAG_LENGTH:
                raise ValueError(
                    f"Each tag must be a string with max {_MAX_TAG_LENGTH} chars."
                )
            if "\x00" in tag:
                raise ValueError("Tag contains null bytes.")

        # Topics validation
        if not isinstance(self.default_topics, list):
            raise ValueError("default_topics must be a list.")
        if len(self.default_topics) > _MAX_TOPICS:
            raise ValueError(f"Too many default topics (max {_MAX_TOPICS}).")
        for topic in self.default_topics:
            if not isinstance(topic, str) or len(topic) > _MAX_TOPIC_LENGTH:
                raise ValueError(
                    f"Each topic must be a string with max {_MAX_TOPIC_LENGTH} chars."
                )
            if "\x00" in topic:
                raise ValueError("Topic contains null bytes.")

        # Schedule times
        if not isinstance(self.schedule_times, list):
            raise ValueError("schedule_times must be a list.")
        if len(self.schedule_times) > _MAX_SCHEDULE_TIMES:
            raise ValueError(
                f"Too many schedule times (max {_MAX_SCHEDULE_TIMES})."
            )
        for t in self.schedule_times:
            if not isinstance(t, str) or not _TIME_PATTERN.match(t):
                raise ValueError(
                    "Each schedule time must be in HH:MM format."
                )
            parts = t.split(":")
            hour, minute = int(parts[0]), int(parts[1])
            if hour > 23 or minute > 59:
                raise ValueError("Schedule time out of range.")

        # Batch size
        if not isinstance(self.batch_size, int):
            raise ValueError("batch_size must be an integer.")
        if self.batch_size < 1 or self.batch_size > _MAX_BATCH_SIZE:
            raise ValueError(
                f"batch_size must be between 1 and {_MAX_BATCH_SIZE}."
            )

        # Delay
        if not isinstance(self.delay_between_videos, int):
            raise ValueError("delay_between_videos must be an integer.")
        if (self.delay_between_videos < _MIN_DELAY_SECONDS or
                self.delay_between_videos > _MAX_DELAY_SECONDS):
            raise ValueError(
                f"delay_between_videos must be between "
                f"{_MIN_DELAY_SECONDS} and {_MAX_DELAY_SECONDS} seconds."
            )

    def to_dict(self) -> dict:
        """Serializes template to a dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "niche": self.niche,
            "language": self.language,
            "platforms": self.platforms,
            "auto_publish": self.auto_publish,
            "seo_enabled": self.seo_enabled,
            "thumbnail_style": self.thumbnail_style,
            "default_tags": self.default_tags,
            "default_topics": self.default_topics,
            "schedule_times": self.schedule_times,
            "batch_size": self.batch_size,
            "delay_between_videos": self.delay_between_videos,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContentTemplate":
        """
        Deserializes from a dictionary with validation.

        All fields are truncated/clamped to safe limits before construction.
        """
        if not isinstance(data, dict):
            raise ValueError("ContentTemplate.from_dict requires a dict")

        name = str(data.get("name", ""))[:_MAX_NAME_LENGTH]
        description = str(data.get("description", ""))[:_MAX_DESCRIPTION_LENGTH]
        niche = str(data.get("niche", "general"))[:_MAX_NICHE_LENGTH]
        language = str(data.get("language", "en"))[:_MAX_LANGUAGE_LENGTH]

        # Validate platforms
        raw_platforms = data.get("platforms", ["youtube"])
        platforms = [
            str(p).lower() for p in (raw_platforms if isinstance(raw_platforms, list) else [])
            if str(p).lower() in _ALLOWED_PLATFORMS
        ][:10]
        if not platforms:
            platforms = ["youtube"]

        # Validate thumbnail style
        raw_style = str(data.get("thumbnail_style", "bold"))
        style = raw_style if raw_style in _ALLOWED_THUMBNAIL_STYLES else "bold"

        # Validate tags
        raw_tags = data.get("default_tags", [])
        tags = [
            str(t)[:_MAX_TAG_LENGTH] for t in (raw_tags if isinstance(raw_tags, list) else [])
            if isinstance(t, str) and "\x00" not in t
        ][:_MAX_TAGS]

        # Validate topics
        raw_topics = data.get("default_topics", [])
        topics = [
            str(t)[:_MAX_TOPIC_LENGTH] for t in (raw_topics if isinstance(raw_topics, list) else [])
            if isinstance(t, str) and "\x00" not in t
        ][:_MAX_TOPICS]

        # Validate schedule times
        raw_times = data.get("schedule_times", [])
        times = [
            str(t) for t in (raw_times if isinstance(raw_times, list) else [])
            if isinstance(t, str) and _TIME_PATTERN.match(str(t))
        ][:_MAX_SCHEDULE_TIMES]

        # Clamp numeric values
        try:
            batch_size = int(data.get("batch_size", 5))
        except (ValueError, TypeError):
            batch_size = 5
        batch_size = min(max(batch_size, 1), _MAX_BATCH_SIZE)

        try:
            delay = int(data.get("delay_between_videos", 30))
        except (ValueError, TypeError):
            delay = 30
        delay = min(max(delay, _MIN_DELAY_SECONDS), _MAX_DELAY_SECONDS)

        return cls(
            name=name,
            description=description,
            niche=niche,
            language=language,
            platforms=platforms,
            auto_publish=bool(data.get("auto_publish", False)),
            seo_enabled=bool(data.get("seo_enabled", True)),
            thumbnail_style=style,
            default_tags=tags,
            default_topics=topics,
            schedule_times=times,
            batch_size=batch_size,
            delay_between_videos=delay,
            created_at=str(data.get("created_at", ""))[:50],
            updated_at=str(data.get("updated_at", ""))[:50],
        )

    def to_batch_job(self, topics: Optional[list] = None):
        """
        Creates a BatchJob from this template.

        Args:
            topics: Override topics. Uses default_topics if not provided.

        Returns:
            A BatchJob instance configured from this template.
        """
        from batch_generator import BatchJob

        job_topics = topics if topics else self.default_topics
        if not job_topics:
            raise ValueError(
                "No topics provided and template has no default_topics."
            )

        return BatchJob(
            topics=job_topics[:self.batch_size],
            niche=self.niche,
            language=self.language,
            auto_publish=self.auto_publish,
            publish_platforms=list(self.platforms),
        )


# ---------------------------------------------------------------------------
# Template Manager
# ---------------------------------------------------------------------------

class TemplateManager:
    """
    Manages content templates with file-based persistence.

    Templates are stored as individual JSON files in the templates directory
    for easy inspection and version control.
    """

    def __init__(self):
        self._templates_dir = _get_templates_dir()

    def _ensure_dir(self) -> None:
        """Ensures the templates directory exists."""
        os.makedirs(self._templates_dir, exist_ok=True)

    def _template_path(self, name: str) -> str:
        """Returns the file path for a named template."""
        # Sanitize name for filesystem safety
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", name)
        if not safe_name:
            raise ValueError("Invalid template name for filesystem.")
        return os.path.join(self._templates_dir, f"{safe_name}.json")

    def save_template(self, template: ContentTemplate) -> str:
        """
        Saves a template to disk.

        Args:
            template: The ContentTemplate to save.

        Returns:
            The template name.

        Raises:
            ValueError: If the template is invalid or limit exceeded.
        """
        template.validate()

        self._ensure_dir()

        # Check template count (only for new templates)
        existing_path = self._template_path(template.name)
        if not os.path.isfile(existing_path):
            current_count = len(self.list_templates())
            if current_count >= get_max_templates():
                raise ValueError(
                    f"Maximum template count ({get_max_templates()}) reached. "
                    f"Delete unused templates first."
                )

        # Update timestamp
        template.updated_at = datetime.now(timezone.utc).isoformat()

        # Atomic write
        file_path = self._template_path(template.name)
        dir_name = os.path.dirname(file_path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(template.to_dict(), f, indent=2)
            os.replace(tmp_path, file_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info("Template saved: %s", template.name)
        return template.name

    def get_template(self, name: str) -> ContentTemplate:
        """
        Loads a template by name.

        Args:
            name: The template name.

        Returns:
            The loaded ContentTemplate.

        Raises:
            ValueError: If the template doesn't exist or is invalid.
        """
        if not name or "\x00" in name:
            raise ValueError("Invalid template name.")

        file_path = self._template_path(name)

        try:
            with open(file_path, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise ValueError("Template not found.")
        except (json.JSONDecodeError, IOError):
            raise ValueError("Template file is corrupted.")

        if not isinstance(data, dict):
            raise ValueError("Template data is not a valid dictionary.")

        return ContentTemplate.from_dict(data)

    def delete_template(self, name: str) -> bool:
        """
        Deletes a template by name.

        Args:
            name: The template name.

        Returns:
            True if the template was deleted, False if not found.
        """
        if not name or "\x00" in name:
            return False

        file_path = self._template_path(name)

        try:
            os.unlink(file_path)
            logger.info("Template deleted: %s", name)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            logger.warning("Failed to delete template: %s", type(OSError).__name__)
            return False

    def list_templates(self) -> list:
        """
        Lists all saved templates.

        Returns:
            List of ContentTemplate objects, sorted by name.
        """
        self._ensure_dir()
        templates = []

        try:
            entries = os.listdir(self._templates_dir)
        except OSError:
            return []

        for filename in sorted(entries):
            if not filename.endswith(".json"):
                continue

            file_path = os.path.join(self._templates_dir, filename)
            if not os.path.isfile(file_path):
                continue

            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    templates.append(ContentTemplate.from_dict(data))
            except (json.JSONDecodeError, IOError, ValueError):
                # Skip corrupted template files
                continue

        return templates

    def template_exists(self, name: str) -> bool:
        """Checks if a template with the given name exists."""
        if not name or "\x00" in name:
            return False
        return os.path.isfile(self._template_path(name))

    def duplicate_template(
        self, source_name: str, new_name: str
    ) -> ContentTemplate:
        """
        Creates a copy of an existing template with a new name.

        Args:
            source_name: Name of the template to copy.
            new_name: Name for the new template.

        Returns:
            The new ContentTemplate.

        Raises:
            ValueError: If source doesn't exist or new name is invalid.
        """
        source = self.get_template(source_name)
        source.name = new_name
        source.created_at = datetime.now(timezone.utc).isoformat()
        source.updated_at = datetime.now(timezone.utc).isoformat()
        self.save_template(source)
        return source

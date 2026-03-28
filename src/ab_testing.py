"""
A/B Testing module for MoneyPrinter.

Provides variant testing for YouTube video titles and thumbnails.
Supports round-robin rotation, metric tracking, and winner evaluation.

Stores test state in .mp/ab_tests.json using the standard atomic-write pattern.
"""

import os
import json
import uuid
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import ROOT_DIR
from mp_logger import get_logger

logger = get_logger(__name__)

# Module-level reference to LLM generate function.
# Imported here (not inside the method) so tests can patch "ab_testing.generate_text".
try:
    from llm_provider import generate_text  # noqa: F401
except Exception:  # pragma: no cover
    generate_text = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_METRICS = frozenset({"watch_time", "ctr", "views"})
_MAX_TITLE_LEN = 500
_MAX_VIDEO_ID_LEN = 200
_MIN_VARIANTS = 2

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ABVariant:
    """Represents a single variant in an A/B test."""

    variant_id: str
    title: str
    thumbnail_path: str = ""
    metrics: dict = field(default_factory=lambda: {"views": 0, "ctr": 0.0, "watch_time": 0})
    active: bool = False

    def to_dict(self) -> dict:
        """Serialize to a JSON-serializable dict."""
        return {
            "variant_id": self.variant_id,
            "title": self.title,
            "thumbnail_path": self.thumbnail_path,
            "metrics": dict(self.metrics),
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ABVariant":
        """Deserialize from a dict (missing fields get defaults)."""
        return cls(
            variant_id=data.get("variant_id", ""),
            title=data.get("title", ""),
            thumbnail_path=data.get("thumbnail_path", ""),
            metrics=data.get("metrics", {"views": 0, "ctr": 0.0, "watch_time": 0}),
            active=data.get("active", False),
        )


@dataclass
class ABTest:
    """Represents a full A/B test with multiple variants."""

    test_id: str
    video_id: str
    variants: list  # list[ABVariant]
    schedule_hours: int = 24
    metric: str = "watch_time"
    status: str = "running"
    winner_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        """Serialize to a JSON-serializable dict."""
        return {
            "test_id": self.test_id,
            "video_id": self.video_id,
            "variants": [v.to_dict() for v in self.variants],
            "schedule_hours": self.schedule_hours,
            "metric": self.metric,
            "status": self.status,
            "winner_id": self.winner_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ABTest":
        """Deserialize from a dict (missing fields get defaults)."""
        raw_variants = data.get("variants", [])
        variants = [ABVariant.from_dict(v) for v in raw_variants]
        return cls(
            test_id=data.get("test_id", ""),
            video_id=data.get("video_id", ""),
            variants=variants,
            schedule_hours=data.get("schedule_hours", 24),
            metric=data.get("metric", "watch_time"),
            status=data.get("status", "running"),
            winner_id=data.get("winner_id", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ABTestManager:
    """Manages A/B tests with JSON file persistence."""

    def __init__(self) -> None:
        self._cache_path = os.path.join(ROOT_DIR, ".mp", "ab_tests.json")

    # ------------------------------------------------------------------
    # Internal persistence helpers
    # ------------------------------------------------------------------

    def _load_tests(self) -> list:
        """Read all tests from disk. Returns empty list on missing / corrupt file."""
        try:
            with open(self._cache_path, "r") as f:
                data = json.load(f)
                raw = data.get("tests", []) if isinstance(data, dict) else []
                return [ABTest.from_dict(t) for t in raw]
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            return []

    def _save_tests(self, tests: list) -> None:
        """Atomically persist all tests to disk using tempfile + os.replace."""
        dir_name = os.path.dirname(self._cache_path)
        os.makedirs(dir_name, exist_ok=True)
        payload = {"tests": [t.to_dict() for t in tests]}
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self._cache_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_test(
        self,
        video_id: str,
        variants: list,
        schedule_hours: int = 24,
        metric: str = "watch_time",
    ) -> "ABTest":
        """
        Create and persist a new A/B test.

        Args:
            video_id: Non-empty identifier for the video under test.
            variants: List of dicts, each with at least a "title" key.
                      Minimum 2 variants required.
            schedule_hours: Positive integer hours per variant rotation.
            metric: One of "watch_time", "ctr", "views".

        Returns:
            The newly created ABTest.

        Raises:
            ValueError: For any invalid input.
        """
        # --- Input validation ---
        if not video_id or not isinstance(video_id, str):
            raise ValueError("video_id must be a non-empty string.")
        video_id = video_id.strip()
        if not video_id:
            raise ValueError("video_id must be a non-empty string.")
        if len(video_id) > _MAX_VIDEO_ID_LEN:
            raise ValueError(
                f"video_id exceeds maximum length of {_MAX_VIDEO_ID_LEN} characters."
            )

        if not isinstance(variants, list) or len(variants) < _MIN_VARIANTS:
            raise ValueError(
                f"At least {_MIN_VARIANTS} variants are required."
            )

        if metric not in _ALLOWED_METRICS:
            raise ValueError(
                f"Invalid metric '{metric}'. Must be one of: {sorted(_ALLOWED_METRICS)}"
            )

        if not isinstance(schedule_hours, int) or schedule_hours <= 0:
            raise ValueError("schedule_hours must be a positive integer.")

        # --- Build variant objects ---
        built_variants: list[ABVariant] = []
        for i, v in enumerate(variants):
            title = str(v.get("title", "")).strip()
            if not title:
                raise ValueError(f"Variant at index {i} is missing a non-empty 'title'.")
            if len(title) > _MAX_TITLE_LEN:
                raise ValueError(
                    f"Variant title at index {i} exceeds {_MAX_TITLE_LEN} characters."
                )
            built_variants.append(
                ABVariant(
                    variant_id=uuid.uuid4().hex[:8],
                    title=title,
                    thumbnail_path=str(v.get("thumbnail_path", "")),
                    active=(i == 0),
                )
            )

        now = self._now_iso()
        test = ABTest(
            test_id=uuid.uuid4().hex[:8],
            video_id=video_id,
            variants=built_variants,
            schedule_hours=schedule_hours,
            metric=metric,
            status="running",
            created_at=now,
            updated_at=now,
        )

        all_tests = self._load_tests()
        all_tests.append(test)
        self._save_tests(all_tests)

        logger.info("Created A/B test %s for video %s with %d variants.",
                    test.test_id, video_id, len(built_variants))
        return test

    def get_test(self, test_id: str) -> Optional[ABTest]:
        """Return the ABTest with the given ID, or None if not found."""
        for t in self._load_tests():
            if t.test_id == test_id:
                return t
        return None

    def get_active_tests(self) -> list:
        """Return all tests with status == 'running'."""
        return [t for t in self._load_tests() if t.status == "running"]

    def delete_test(self, test_id: str) -> bool:
        """
        Delete a test by ID.

        Returns:
            True if the test was found and removed, False otherwise.
        """
        all_tests = self._load_tests()
        new_tests = [t for t in all_tests if t.test_id != test_id]
        if len(new_tests) == len(all_tests):
            return False
        self._save_tests(new_tests)
        logger.info("Deleted A/B test %s.", test_id)
        return True

    def rotate_variant(self, test_id: str) -> Optional[ABVariant]:
        """
        Deactivate the current active variant and activate the next one (round-robin).

        Returns:
            The newly active ABVariant, or None if the test is not found.
        """
        all_tests = self._load_tests()
        target: Optional[ABTest] = None
        idx = -1
        for i, t in enumerate(all_tests):
            if t.test_id == test_id:
                target = t
                idx = i
                break

        if target is None:
            logger.warning("rotate_variant: test %s not found.", test_id)
            return None

        variants = target.variants
        if len(variants) <= 1:
            # Nothing to rotate — return the single variant unchanged
            return variants[0] if variants else None

        # Find the currently active index
        active_idx = next(
            (i for i, v in enumerate(variants) if v.active), 0
        )
        next_idx = (active_idx + 1) % len(variants)

        variants[active_idx].active = False
        variants[next_idx].active = True
        target.updated_at = self._now_iso()

        self._save_tests(all_tests)
        logger.info(
            "Rotated test %s from variant %s to %s.",
            test_id,
            variants[active_idx].variant_id,
            variants[next_idx].variant_id,
        )
        return variants[next_idx]

    def record_metrics(
        self, test_id: str, variant_id: str, metrics: dict
    ) -> bool:
        """
        Merge the provided metrics dict into the specified variant's metrics.

        Returns:
            True if the variant was found and updated, False otherwise.
        """
        all_tests = self._load_tests()
        for test in all_tests:
            if test.test_id != test_id:
                continue
            for variant in test.variants:
                if variant.variant_id != variant_id:
                    continue
                variant.metrics.update(metrics)
                test.updated_at = self._now_iso()
                self._save_tests(all_tests)
                logger.info(
                    "Recorded metrics for test %s variant %s: %s",
                    test_id, variant_id, metrics,
                )
                return True
        logger.warning(
            "record_metrics: test %s or variant %s not found.",
            test_id, variant_id,
        )
        return False

    def evaluate_winner(self, test_id: str) -> Optional[str]:
        """
        Determine the winning variant by comparing on the configured metric.

        Sets the test status to 'completed' and records the winner_id.

        Returns:
            The winner's variant_id, or None if the test is not found.
        """
        all_tests = self._load_tests()
        target: Optional[ABTest] = None
        for t in all_tests:
            if t.test_id == test_id:
                target = t
                break

        if target is None:
            logger.warning("evaluate_winner: test %s not found.", test_id)
            return None

        metric = target.metric
        best_variant: Optional[ABVariant] = None
        best_value: float = float("-inf")

        for variant in target.variants:
            value = float(variant.metrics.get(metric, 0))
            if value > best_value:
                best_value = value
                best_variant = variant

        if best_variant is None:
            return None

        target.status = "completed"
        target.winner_id = best_variant.variant_id
        target.updated_at = self._now_iso()

        self._save_tests(all_tests)
        logger.info(
            "Evaluated winner for test %s: variant %s (metric=%s, value=%s).",
            test_id, best_variant.variant_id, metric, best_value,
        )
        return best_variant.variant_id

    def generate_variants(self, title: str, count: int = 3) -> list:
        """
        Use the configured LLM to generate title variants.

        Args:
            title: The original video title to riff on.
            count: Number of variants to generate (minimum 1).

        Returns:
            List of dicts: [{"title": "...", "thumbnail_path": ""}, ...]

        Raises:
            ValueError: If title is empty or count < 1.
        """
        if not title or not isinstance(title, str):
            raise ValueError("title must be a non-empty string.")
        title = title.strip()
        if not title:
            raise ValueError("title must be a non-empty string.")
        if len(title) > _MAX_TITLE_LEN:
            raise ValueError(
                f"title exceeds maximum length of {_MAX_TITLE_LEN} characters."
            )
        if not isinstance(count, int) or count < 1:
            raise ValueError("count must be a positive integer.")

        prompt = (
            f"Generate {count} alternative YouTube video title variants for the following title.\n"
            f"Original title: {title}\n\n"
            "Requirements:\n"
            "- Each variant should be engaging and click-worthy.\n"
            "- Keep each title under 100 characters.\n"
            "- Output ONLY a JSON array of strings, no explanation.\n"
            "- Example format: [\"Title one\", \"Title two\", \"Title three\"]\n"
        )

        try:
            raw = generate_text(prompt)
            # Extract the JSON array from the response
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                raise ValueError("LLM response did not contain a JSON array.")
            titles = json.loads(raw[start:end])
            if not isinstance(titles, list):
                raise ValueError("LLM response was not a JSON array.")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("generate_variants: failed to parse LLM response: %s", exc)
            # Graceful fallback: return the original title repeated
            titles = [title] * count

        result = [
            {"title": str(t)[:_MAX_TITLE_LEN], "thumbnail_path": ""}
            for t in titles[:count]
        ]
        # Pad if LLM returned fewer items than requested
        while len(result) < count:
            result.append({"title": title, "thumbnail_path": ""})

        return result

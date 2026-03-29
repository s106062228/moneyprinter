"""
Uniqueness Scorer for MoneyPrinter.

Scores generated content for uniqueness to avoid YouTube's 2026 "inauthentic
content" demonetization policy. Compares new content against a rolling history
of recent outputs across four dimensions:

  1. Title similarity   — difflib SequenceMatcher vs. recent titles
  2. Script variation   — structural fingerprint (sentence stats) vs. history
  3. Metadata diversity — tag overlap + description template detection
  4. Posting regularity — time-gap variance (irregular = less robotic)

Usage:
    from uniqueness_scorer import UniquenessScorer

    scorer = UniquenessScorer()
    result = scorer.score_content(
        title="10 AI Tools That Will Replace Your Job",
        script="Did you know... These are the tools...",
        tags=["ai", "tools"],
        description="In this video we explore...",
    )
    print(result.overall)   # e.g. 0.82
    print(result.flagged)   # False (above threshold)

    scorer.add_to_history(title, script, tags, description)
"""

import hashlib
import json
import os
import re
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional

from mp_logger import get_logger
from config import ROOT_DIR

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_HISTORY = 200
_DEFAULT_THRESHOLD = 0.6

_TITLE_WEIGHT = 0.30
_SCRIPT_WEIGHT = 0.30
_METADATA_WEIGHT = 0.20
_REGULARITY_WEIGHT = 0.20

_MAX_TITLE_LENGTH = 500
_MAX_TAGS = 50

_HISTORY_FILE = os.path.join(ROOT_DIR, ".mp", "uniqueness_history.json")

# Number of history entries to compare against for title / metadata scoring
_COMPARE_WINDOW = 20


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class UniquenessScore:
    """Result of a uniqueness evaluation."""

    overall: float               # 0-1 weighted composite
    title_similarity: float      # 0-1; lower = more unique (less similar to history)
    script_variation: float      # 0-1; higher = more varied
    metadata_diversity: float    # 0-1; higher = more diverse
    posting_regularity: float    # 0-1; lower = more robotic (fixed intervals)
    flagged: bool                # True if overall < threshold
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256_prefix(text: str, chars: int = 500) -> str:
    """Return SHA-256 hex digest of the first *chars* characters of *text*."""
    return hashlib.sha256(text[:chars].encode("utf-8", errors="replace")).hexdigest()


def _sentence_split(text: str) -> list[str]:
    """Split *text* into sentences on '.', '!', '?' boundaries."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _script_fingerprint(script: str) -> dict:
    """Return a lightweight structural fingerprint for *script*."""
    sentences = _sentence_split(script)
    count = len(sentences)
    if count == 0:
        return {
            "sentence_count": 0,
            "avg_length": 0.0,
            "question_ratio": 0.0,
            "exclamation_ratio": 0.0,
        }

    avg_len = sum(len(s) for s in sentences) / count
    question_ratio = sum(1 for s in sentences if "?" in s) / count
    exclamation_ratio = sum(1 for s in sentences if "!" in s) / count

    return {
        "sentence_count": count,
        "avg_length": round(avg_len, 2),
        "question_ratio": round(question_ratio, 4),
        "exclamation_ratio": round(exclamation_ratio, 4),
    }


def _description_hash(description: str) -> str:
    """Return SHA-256 of the first 500 chars of description."""
    return _sha256_prefix(description, 500)


def _atomic_write_json(path: str, data) -> None:
    """Atomically write *data* as JSON to *path* using tempfile + os.replace."""
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_history(path: str) -> list[dict]:
    """Load history list from *path*; return [] on missing / corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return []


def _validate_str(value, name: str, max_len: Optional[int] = None) -> str:
    """Validate that *value* is a non-null-byte string, with optional length cap."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if "\x00" in value:
        raise ValueError(f"{name} must not contain null bytes")
    if max_len is not None:
        value = value[:max_len]
    return value


def _validate_tags(tags) -> list[str]:
    """Validate and truncate tags list."""
    if not isinstance(tags, list):
        raise TypeError(f"tags must be a list, got {type(tags).__name__}")
    result = []
    for t in tags[:_MAX_TAGS]:
        if not isinstance(t, str):
            raise TypeError(f"Each tag must be a str, got {type(t).__name__}")
        if "\x00" in t:
            raise ValueError("Tags must not contain null bytes")
        result.append(t)
    return result


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_title_similarity(title: str, history: list[dict]) -> float:
    """
    Compute 1.0 - max_similarity against recent history titles.

    Returns 1.0 if no history is available.
    """
    if not history:
        return 1.0

    recent = history[-_COMPARE_WINDOW:]
    max_sim = 0.0
    for entry in recent:
        hist_title = entry.get("title", "")
        if not hist_title:
            continue
        sim = SequenceMatcher(None, title.lower(), hist_title.lower()).ratio()
        if sim > max_sim:
            max_sim = sim

    return round(1.0 - max_sim, 6)


def _score_script_variation(fingerprint: dict, history: list[dict]) -> float:
    """
    Compare *fingerprint* against structural fingerprints in history.

    Uses the standard deviation of the absolute differences across metrics.
    Returns 1.0 if no history fingerprints are available.
    """
    fp_entries = [
        e.get("script_fingerprint")
        for e in history
        if isinstance(e.get("script_fingerprint"), dict)
    ]
    if not fp_entries:
        return 1.0

    keys = ("sentence_count", "avg_length", "question_ratio", "exclamation_ratio")

    # Normalise each metric to [0, 1] using crude ranges
    normalisers = {
        "sentence_count": 50.0,   # assume 50 sentences is "max"
        "avg_length": 200.0,      # 200 chars per sentence is "max"
        "question_ratio": 1.0,
        "exclamation_ratio": 1.0,
    }

    diffs: list[float] = []
    for hist_fp in fp_entries[-_COMPARE_WINDOW:]:
        for k in keys:
            norm = normalisers[k]
            cur = fingerprint.get(k, 0) / norm
            his = hist_fp.get(k, 0) / norm
            diffs.append(abs(cur - his))

    if not diffs:
        return 1.0

    # Mean distance — higher mean = more varied
    mean_diff = statistics.mean(diffs)
    # Clamp to [0, 1]
    return round(min(1.0, mean_diff * 4.0), 6)  # scale factor so ~0.25 diff → score 1.0


def _score_metadata_diversity(
    tags: list[str], description: str, history: list[dict]
) -> float:
    """
    Score metadata diversity based on tag overlap and description similarity.

    Returns 1.0 if no history.
    """
    if not history:
        return 1.0

    recent = history[-_COMPARE_WINDOW:]
    tag_set = set(t.lower() for t in tags)
    desc_words = set(description.lower().split()) if description.strip() else set()

    max_overlap = 0.0

    for entry in recent:
        # Tag overlap
        hist_tags = set(t.lower() for t in entry.get("tags", []))
        if tag_set or hist_tags:
            union = len(tag_set | hist_tags)
            inter = len(tag_set & hist_tags)
            tag_overlap = inter / union if union else 0.0
        else:
            tag_overlap = 0.0

        # Description template detection: word overlap ratio
        hist_desc_words = set(entry.get("description_words", []))
        if desc_words and hist_desc_words:
            union_d = len(desc_words | hist_desc_words)
            inter_d = len(desc_words & hist_desc_words)
            desc_overlap = inter_d / union_d if union_d else 0.0
        else:
            desc_overlap = 0.0

        combined_overlap = max(tag_overlap, desc_overlap)
        if combined_overlap > max_overlap:
            max_overlap = combined_overlap

    return round(1.0 - max_overlap, 6)


def _score_posting_regularity(history: list[dict]) -> float:
    """
    Compute regularity score from time-gap variance between posts.

    Higher variance = less robotic = higher score.
    Returns 1.0 if fewer than 3 posts in history.
    """
    timestamps = []
    for entry in history:
        ts_str = entry.get("timestamp")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str)
            timestamps.append(dt.timestamp())
        except (ValueError, TypeError):
            continue

    if len(timestamps) < 3:
        return 1.0

    timestamps.sort()
    gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]

    if len(gaps) < 2:
        return 1.0

    try:
        stdev = statistics.stdev(gaps)
        mean_gap = statistics.mean(gaps)
    except statistics.StatisticsError:
        return 1.0

    if mean_gap == 0:
        return 0.0

    # Coefficient of variation: higher = more irregular = better
    cv = stdev / mean_gap
    # Clamp: CV of 1.0 → score 1.0
    return round(min(1.0, cv), 6)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class UniquenessScorer:
    """Score content for uniqueness against a rolling history of recent outputs."""

    def __init__(
        self,
        history_path: Optional[str] = None,
        threshold: float = _DEFAULT_THRESHOLD,
        max_history: int = _MAX_HISTORY,
    ):
        self._history_path = history_path or _HISTORY_FILE
        self._threshold = threshold
        self._max_history = max_history

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_content(
        self,
        title: str,
        script: str,
        tags: list,
        description: str,
        platform: str = "youtube",
    ) -> UniquenessScore:
        """Score *content* for uniqueness against historical outputs.

        Args:
            title:       Content title. Required.
            script:      Full script text. Required.
            tags:        List of keyword tags.
            description: Content description.
            platform:    Target platform (default 'youtube').

        Returns:
            UniquenessScore with per-dimension scores and overall composite.

        Raises:
            TypeError:  If any argument has the wrong type.
            ValueError: If title is empty, or inputs contain null bytes.
        """
        # --- Input validation ---
        title = _validate_str(title, "title", _MAX_TITLE_LENGTH)
        if not title.strip():
            raise ValueError("title must not be empty or blank")

        script = _validate_str(script, "script")
        description = _validate_str(description, "description")
        tags = _validate_tags(tags)
        platform = _validate_str(platform, "platform")

        logger.info(
            f"Scoring uniqueness for platform={platform!r}, "
            f"title={title[:60]!r}"
        )

        history = _read_history(self._history_path)

        # --- Dimension 1: title similarity ---
        title_sim = _score_title_similarity(title, history)

        # --- Dimension 2: script variation ---
        fp = _script_fingerprint(script)
        script_var = _score_script_variation(fp, history)

        # --- Dimension 3: metadata diversity ---
        meta_div = _score_metadata_diversity(tags, description, history)

        # --- Dimension 4: posting regularity ---
        regularity = _score_posting_regularity(history)

        # --- Weighted overall ---
        overall = (
            title_sim * _TITLE_WEIGHT
            + script_var * _SCRIPT_WEIGHT
            + meta_div * _METADATA_WEIGHT
            + regularity * _REGULARITY_WEIGHT
        )
        overall = round(min(1.0, max(0.0, overall)), 6)
        flagged = overall < self._threshold

        details = {
            "platform": platform,
            "history_size": len(history),
            "script_fingerprint": fp,
        }

        score = UniquenessScore(
            overall=overall,
            title_similarity=title_sim,
            script_variation=script_var,
            metadata_diversity=meta_div,
            posting_regularity=regularity,
            flagged=flagged,
            details=details,
        )

        logger.info(
            f"Uniqueness score: overall={overall:.3f} flagged={flagged} "
            f"platform={platform}"
        )
        return score

    def add_to_history(
        self,
        title: str,
        script: str,
        tags: list,
        description: str,
        platform: str = "youtube",
    ) -> None:
        """Append the content to the rolling history and persist to disk.

        Trims oldest entries when history exceeds *max_history*.

        Args:
            title:       Content title.
            script:      Full script text.
            tags:        List of keyword tags.
            description: Content description.
            platform:    Target platform.
        """
        title = _validate_str(title, "title", _MAX_TITLE_LENGTH)
        if not title.strip():
            raise ValueError("title must not be empty or blank")
        script = _validate_str(script, "script")
        description = _validate_str(description, "description")
        tags = _validate_tags(tags)
        platform = _validate_str(platform, "platform")

        fp = _script_fingerprint(script)
        desc_words = list(set(description.lower().split()))

        entry = {
            "title": title,
            "script_hash": _sha256_prefix(script, 500),
            "tags": tags,
            "description_hash": _description_hash(description),
            "description_words": desc_words,
            "platform": platform,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "script_fingerprint": fp,
        }

        history = _read_history(self._history_path)
        history.append(entry)

        # Trim to max_history (keep most recent)
        if len(history) > self._max_history:
            history = history[-self._max_history:]

        _atomic_write_json(self._history_path, history)
        logger.debug(f"Added entry to uniqueness history (size={len(history)})")

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return up to *limit* most-recent history entries.

        Args:
            limit: Maximum number of entries to return (most recent first).

        Returns:
            List of history entry dicts.
        """
        history = _read_history(self._history_path)
        return history[-limit:] if limit > 0 else []

    def clear_history(self) -> None:
        """Delete all history entries and persist the empty list."""
        _atomic_write_json(self._history_path, [])
        logger.info("Uniqueness history cleared")

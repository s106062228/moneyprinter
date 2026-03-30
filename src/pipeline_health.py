"""
Pipeline Health Monitor for MoneyPrinter.

Tracks operational health across all pipeline modules. Each module can
register itself and report health status. The monitor persists state
to .mp/pipeline_health.json and provides summary views.

Usage:
    from pipeline_health import PipelineHealthMonitor

    monitor = PipelineHealthMonitor()
    monitor.register_module("publisher")
    monitor.report_health("publisher", "ok")
    monitor.report_health("publisher", "error", error_msg="Connection timeout")
    summary = monitor.get_summary()
    # {"total": 1, "ok": 0, "degraded": 0, "error": 1, "unknown": 0}
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from mp_logger import get_logger
from config import _get

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_STATUSES = frozenset({"ok", "degraded", "error", "unknown"})
_MAX_MODULES = 100
_MAX_MODULE_NAME_LENGTH = 200
_MAX_ERROR_LENGTH = 1000
_MAX_METADATA_KEYS = 20

_DEFAULT_PERSIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".mp",
    "pipeline_health.json",
)


# ---------------------------------------------------------------------------
# ModuleHealth dataclass
# ---------------------------------------------------------------------------


@dataclass
class ModuleHealth:
    """Represents the health state of a single pipeline module."""

    module_name: str
    status: str = "unknown"
    last_check: str = ""
    error_count: int = 0
    success_count: int = 0
    last_error: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON persistence."""
        return {
            "module_name": self.module_name,
            "status": self.status,
            "last_check": self.last_check,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "last_error": self.last_error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleHealth":
        """Deserialize from a plain dict, with validation and safe defaults.

        Unknown extra fields in *data* are silently ignored.
        Missing fields fall back to safe defaults so that older persisted
        entries can still be loaded without error.
        """
        module_name = str(data.get("module_name", ""))
        status = str(data.get("status", "unknown"))
        if status not in _VALID_STATUSES:
            status = "unknown"

        error_count = data.get("error_count", 0)
        if not isinstance(error_count, int) or error_count < 0:
            error_count = 0

        success_count = data.get("success_count", 0)
        if not isinstance(success_count, int) or success_count < 0:
            success_count = 0

        last_error = str(data.get("last_error", ""))
        last_check = str(data.get("last_check", ""))

        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        return cls(
            module_name=module_name,
            status=status,
            last_check=last_check,
            error_count=error_count,
            success_count=success_count,
            last_error=last_error,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# PipelineHealthMonitor
# ---------------------------------------------------------------------------


class PipelineHealthMonitor:
    """Tracks and persists health status for all registered pipeline modules."""

    def __init__(self, persist_path: str = "") -> None:
        if persist_path:
            self._persist_path = persist_path
        else:
            # Allow config override, fall back to default
            try:
                cfg_path = _get("pipeline_health_path")
                self._persist_path = cfg_path if cfg_path else _DEFAULT_PERSIST_PATH
            except Exception:
                self._persist_path = _DEFAULT_PERSIST_PATH

        self._modules: dict[str, ModuleHealth] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_module(self, name: str) -> None:
        """Register a module with "unknown" status if not already registered.

        Args:
            name: Module name. Must be a non-empty string with no null bytes,
                  max _MAX_MODULE_NAME_LENGTH characters.

        Raises:
            ValueError: If the name is invalid or the module cap is reached.
        """
        _validate_module_name(name)
        if name in self._modules:
            return  # idempotent — duplicate registration is a no-op
        if len(self._modules) >= _MAX_MODULES:
            raise ValueError(
                f"Cannot register '{name}': maximum of {_MAX_MODULES} modules reached."
            )
        self._modules[name] = ModuleHealth(module_name=name)
        logger.debug("Registered pipeline module: %s", name)

    # ------------------------------------------------------------------
    # Health reporting
    # ------------------------------------------------------------------

    def report_health(
        self,
        name: str,
        status: str,
        error_msg: str = "",
        metadata: Optional[dict] = None,
    ) -> None:
        """Update the health status for a module.

        Auto-registers the module if it has not been registered yet.

        Args:
            name:      Module name.
            status:    One of "ok", "degraded", "error", "unknown".
            error_msg: Optional error description (truncated to _MAX_ERROR_LENGTH).
            metadata:  Optional dict of extra key-value pairs
                       (max _MAX_METADATA_KEYS keys, values must be JSON-serialisable).

        Raises:
            ValueError: If status is not in _VALID_STATUSES or metadata is invalid.
        """
        _validate_module_name(name)
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}"
            )

        # Auto-register
        if name not in self._modules:
            self.register_module(name)

        mod = self._modules[name]

        # Update counters
        if status == "ok":
            mod.success_count += 1
        elif status in ("error", "degraded"):
            mod.error_count += 1
            mod.last_error = error_msg[:_MAX_ERROR_LENGTH] if error_msg else ""

        # Update metadata
        if metadata is not None:
            _validate_metadata(metadata)
            mod.metadata = dict(metadata)

        mod.status = status
        mod.last_check = datetime.now(timezone.utc).isoformat()

        logger.debug("Module '%s' reported status: %s", name, status)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_module_health(self, name: str) -> ModuleHealth:
        """Return the ModuleHealth for *name*.

        Raises:
            KeyError: If the module has not been registered.
        """
        if name not in self._modules:
            raise KeyError(f"Module '{name}' is not registered.")
        return self._modules[name]

    def check_all(self) -> dict[str, ModuleHealth]:
        """Return a shallow copy of the full module registry."""
        return dict(self._modules)

    def get_summary(self) -> dict:
        """Return aggregate counts per status.

        Returns:
            {"total": N, "ok": N, "degraded": N, "error": N, "unknown": N}
        """
        counts: dict[str, int] = {s: 0 for s in _VALID_STATUSES}
        for mod in self._modules.values():
            counts[mod.status] = counts.get(mod.status, 0) + 1
        return {
            "total": len(self._modules),
            "ok": counts["ok"],
            "degraded": counts["degraded"],
            "error": counts["error"],
            "unknown": counts["unknown"],
        }

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all registered modules."""
        self._modules.clear()
        logger.debug("Pipeline health monitor reset.")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Atomically persist the current health state to JSON.

        Uses the tempfile + os.replace pattern to avoid partial writes.
        """
        data = {name: mod.to_dict() for name, mod in self._modules.items()}
        persist_dir = os.path.dirname(self._persist_path)
        os.makedirs(persist_dir, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=persist_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._persist_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.debug("Pipeline health saved to %s", self._persist_path)

    def load(self) -> None:
        """Load persisted health state from JSON.

        Fail-soft: if the file is missing or corrupt the monitor starts empty.
        """
        try:
            with open(self._persist_path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            logger.debug("pipeline_health load skipped (%s): %s", type(exc).__name__, exc)
            return

        if not isinstance(data, dict):
            logger.warning("pipeline_health.json has unexpected format; ignoring.")
            return

        loaded: dict[str, ModuleHealth] = {}
        for name, raw in data.items():
            if not isinstance(raw, dict):
                continue
            try:
                mod = ModuleHealth.from_dict(raw)
                loaded[name] = mod
            except Exception as exc:  # pragma: no cover
                logger.warning("Skipping corrupt module entry '%s': %s", name, exc)

        self._modules = loaded
        logger.debug("Pipeline health loaded from %s (%d modules)", self._persist_path, len(loaded))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_module_name(name: str) -> None:
    """Raise ValueError if *name* is not a valid module name."""
    if not name or not isinstance(name, str):
        raise ValueError("Module name must be a non-empty string.")
    if "\x00" in name:
        raise ValueError("Module name must not contain null bytes.")
    if len(name) > _MAX_MODULE_NAME_LENGTH:
        raise ValueError(
            f"Module name exceeds maximum length of {_MAX_MODULE_NAME_LENGTH} characters."
        )


def _validate_metadata(metadata: dict) -> None:
    """Raise ValueError if *metadata* violates the allowed constraints."""
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a dict.")
    if len(metadata) > _MAX_METADATA_KEYS:
        raise ValueError(
            f"metadata exceeds maximum of {_MAX_METADATA_KEYS} keys."
        )
    # Verify all values are JSON-serialisable
    try:
        json.dumps(metadata)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata contains non-JSON-serialisable value: {exc}") from exc

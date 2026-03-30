"""
Pluggy-based plugin system for MoneyPrinter.

Provides a structured hook specification for extensible platform integrations,
including publishing lifecycle events, content generation notifications, analytics
events, and description transformation.

Usage:
    from plugin_manager import PluginManager, hookimpl

    class MyPlugin:
        @hookimpl
        def on_before_publish(self, job):
            job['title'] = job['title'].upper()
            return job

        @hookimpl
        def transform_description(self, description, platform):
            return description + ' #shorts'

    pm = PluginManager()
    pm.register(MyPlugin())
    results = pm.hook.on_before_publish(job={'title': 'hello'})
"""

import importlib.util
import os
import threading
from typing import Optional

import pluggy

from config import _get
from mp_logger import get_logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_NAME = "moneyprinter"
_MAX_PLUGINS = 50

# ---------------------------------------------------------------------------
# Markers — module-level exports so plugin authors can import them directly:
#   from plugin_manager import hookimpl
# ---------------------------------------------------------------------------

hookspec = pluggy.HookspecMarker(_PROJECT_NAME)
hookimpl = pluggy.HookimplMarker(_PROJECT_NAME)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Hook Specification
# ---------------------------------------------------------------------------


class MoneyPrinterSpec:
    """
    Hook specification class for MoneyPrinter plugin hooks.

    Plugin authors implement these hooks using the @hookimpl decorator.
    All methods have default no-op implementations so plugins only need to
    implement the hooks they care about.
    """

    @hookspec
    def on_before_publish(self, job: dict) -> Optional[dict]:
        """
        Called before a publish job is submitted to a platform.

        Plugins can inspect or modify the job dict. Return a modified copy
        of the job dict, or None to leave it unchanged. The first non-None
        return value wins (firstresult semantics).

        Args:
            job: Publish job metadata (title, description, tags, platform, etc.)

        Returns:
            Modified job dict, or None to pass through unchanged.
        """

    @hookspec
    def on_after_publish(self, job: dict, results: dict) -> None:
        """
        Called after a publish job completes (success or failure).

        Args:
            job:     The original job metadata dict.
            results: Outcome data (status, url, error, elapsed_seconds, etc.)
        """

    @hookspec
    def on_content_generated(self, content_type: str, metadata: dict) -> None:
        """
        Called when new content is generated (script, image, video, etc.).

        Args:
            content_type: One of 'script', 'image', 'video', 'audio', 'subtitle'.
            metadata:     Content-specific metadata (path, duration, dimensions…).
        """

    @hookspec
    def on_analytics_event(self, event_type: str, data: dict) -> None:
        """
        Called when an analytics event is emitted anywhere in the pipeline.

        Args:
            event_type: Dot-separated event name, e.g. 'video.upload.success'.
            data:       Arbitrary event payload.
        """

    @hookspec
    def transform_description(self, description: str, platform: str) -> str:
        """
        Transform a video/post description before it is submitted.

        Each plugin that implements this hook returns a transformed string.
        The results are chained: each plugin receives the output of the
        previous one. The final result is used.

        Args:
            description: Current description text.
            platform:    Target platform ('youtube', 'twitter', 'tiktok', …).

        Returns:
            Transformed description string.
        """

    # ------------------------------------------------------------------
    # Lifecycle hooks — fired once per publish/schedule/batch operation
    # ------------------------------------------------------------------

    @hookspec
    def on_pre_publish(self, job: dict) -> None:
        """Called before the publish loop starts (after validation)."""

    @hookspec
    def on_post_publish(self, job: dict, results: list) -> None:
        """Called after all platforms in a publish job have been attempted."""

    @hookspec
    def on_pre_schedule(self, job: dict) -> None:
        """Called before a ScheduledJob is persisted to the queue."""

    @hookspec
    def on_post_schedule(self, job: dict, job_id: str) -> None:
        """Called after a ScheduledJob has been added to the queue."""

    @hookspec
    def on_batch_start(self, job: dict) -> None:
        """Called when a BatchGenerator.run() begins."""

    @hookspec
    def on_batch_complete(self, job: dict, result: dict) -> None:
        """Called when a BatchGenerator.run() finishes."""


# ---------------------------------------------------------------------------
# Plugin Manager
# ---------------------------------------------------------------------------


class PluginManager:
    """
    Core manager for the MoneyPrinter plugin lifecycle.

    Handles plugin registration, discovery from directories, and provides
    access to the pluggy HookRelay for calling hooks.

    Thread-safety:
        register() and unregister() are protected by an internal threading.Lock.
        Hook calls themselves are thread-safe per pluggy's guarantees.

    Example:
        pm = PluginManager()
        pm.register(my_plugin_instance)
        modified_job = pm.hook.on_before_publish(job=job_dict)
    """

    def __init__(self, project_name: str = _PROJECT_NAME) -> None:
        """
        Initialise the PluginManager.

        Args:
            project_name: pluggy project name (must match hookspec/hookimpl markers).
        """
        if not project_name or not isinstance(project_name, str):
            raise ValueError("project_name must be a non-empty string")

        self._project_name = project_name
        self._pm = pluggy.PluginManager(project_name)
        self._pm.add_hookspecs(MoneyPrinterSpec)
        self._lock = threading.Lock()
        logger.debug("PluginManager initialised (project=%s)", project_name)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: object) -> None:
        """
        Register a plugin object.

        The plugin must be an object (class instance or module) that contains
        at least one method decorated with @hookimpl.

        Args:
            plugin: Plugin object to register.

        Raises:
            ValueError: If plugin is None, already registered, or the plugin
                        limit has been reached.
        """
        if plugin is None:
            raise ValueError("plugin must not be None")

        with self._lock:
            if self._pm.is_registered(plugin):
                raise ValueError(
                    f"Plugin {plugin!r} is already registered"
                )
            current_count = len(self._pm.get_plugins())
            if current_count >= _MAX_PLUGINS:
                raise ValueError(
                    f"Cannot register plugin: limit of {_MAX_PLUGINS} plugins reached"
                )
            self._pm.register(plugin)
            logger.info(
                "Plugin registered: %s (total=%d)",
                getattr(plugin, "__class__", type(plugin)).__name__,
                current_count + 1,
            )

    def unregister(self, plugin: object) -> None:
        """
        Unregister a previously registered plugin.

        Args:
            plugin: Plugin object to unregister.

        Raises:
            ValueError: If plugin is None or not currently registered.
        """
        if plugin is None:
            raise ValueError("plugin must not be None")

        with self._lock:
            if not self._pm.is_registered(plugin):
                raise ValueError(
                    f"Plugin {plugin!r} is not registered"
                )
            self._pm.unregister(plugin)
            logger.info(
                "Plugin unregistered: %s",
                getattr(plugin, "__class__", type(plugin)).__name__,
            )

    def is_registered(self, plugin: object) -> bool:
        """
        Check whether a plugin is currently registered.

        Args:
            plugin: Plugin object to check.

        Returns:
            True if registered, False otherwise.
        """
        return self._pm.is_registered(plugin)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def load_from_directory(self, path: str) -> int:
        """
        Discover and load .py plugin files from a directory.

        Each .py file is imported as a module. If the module contains any
        class whose instances have at least one @hookimpl-decorated method,
        that class is instantiated (zero-argument constructor required) and
        registered.

        Files that raise exceptions during import are logged and skipped.
        Modules that define no hookimpl methods are silently skipped.

        Args:
            path: Filesystem path to the plugin directory.

        Returns:
            Number of plugins successfully registered from this directory.

        Raises:
            ValueError: If path is None/empty or is not a directory.
        """
        if not path or not isinstance(path, str):
            raise ValueError("path must be a non-empty string")
        if not os.path.isdir(path):
            raise ValueError(f"Plugin directory does not exist: {path!r}")

        loaded = 0
        for filename in sorted(os.listdir(path)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            module_name = filename[:-3]
            filepath = os.path.join(path, filename)

            try:
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                if spec is None or spec.loader is None:
                    logger.warning("Could not create module spec for %s", filepath)
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]
            except Exception as exc:
                logger.warning(
                    "Failed to import plugin module %s: %s: %s",
                    filepath,
                    type(exc).__name__,
                    exc,
                )
                continue

            # Find class definitions in the module that have hookimpl methods
            for attr_name in dir(module):
                obj = getattr(module, attr_name, None)
                if not isinstance(obj, type):
                    continue
                # Check if any method on the class carries a hookimpl mark
                if not self._has_hookimpl(obj):
                    continue
                try:
                    instance = obj()
                    self.register(instance)
                    loaded += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate/register plugin class %s.%s: %s: %s",
                        module_name,
                        attr_name,
                        type(exc).__name__,
                        exc,
                    )

        logger.info(
            "load_from_directory(%r): registered %d plugin(s)", path, loaded
        )
        return loaded

    def _has_hookimpl(self, cls: type) -> bool:
        """Return True if any method on cls carries a pluggy hookimpl mark."""
        for name in dir(cls):
            try:
                method = getattr(cls, name, None)
            except Exception:
                continue
            if callable(method) and hasattr(method, self._project_name + "_impl"):
                return True
        return False

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_plugins(self) -> list:
        """
        Return a list of all currently registered plugin objects.

        Returns:
            List of registered plugin instances/modules.
        """
        return list(self._pm.get_plugins())

    @property
    def hook(self) -> pluggy.HookRelay:
        """
        Access the pluggy HookRelay to call hooks directly.

        Example:
            results = pm.hook.on_before_publish(job=my_job)
            pm.hook.on_after_publish(job=my_job, results=outcome)

        Returns:
            pluggy.HookRelay bound to this manager's project.
        """
        return self._pm.hook


# ---------------------------------------------------------------------------
# Shared singleton — all modules should import this instead of creating
# their own PluginManager instances.
# ---------------------------------------------------------------------------


def get_plugin_manager():
    """Lazy singleton for a shared PluginManager instance.

    Returns the same PluginManager on every call. Returns None if
    pluggy is unavailable or initialisation fails (fail-soft).
    """
    if get_plugin_manager._instance is None:
        try:
            get_plugin_manager._instance = PluginManager()
        except Exception:
            return None
    return get_plugin_manager._instance


get_plugin_manager._instance = None


# ---------------------------------------------------------------------------
# Example plugin — demonstrates how to implement a plugin
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    class ExamplePlugin:
        """
        Example (Mastodon stub) plugin that demonstrates the MoneyPrinter
        plugin interface.

        In a real plugin file this class would be the only top-level class,
        the file would live in a plugins/ directory, and it would be loaded
        automatically via PluginManager.load_from_directory().
        """

        @hookimpl
        def on_before_publish(self, job: dict) -> Optional[dict]:
            """Append a hashtag to the title before publishing."""
            modified = dict(job)
            title = modified.get("title", "")
            if title and not title.endswith("#moneyprinter"):
                modified["title"] = title + " #moneyprinter"
            return modified

        @hookimpl
        def on_after_publish(self, job: dict, results: dict) -> None:
            """Log a summary after each publish attempt."""
            status = results.get("status", "unknown")
            platform = job.get("platform", "unknown")
            print(f"[ExamplePlugin] publish on {platform} → {status}")

        @hookimpl
        def on_content_generated(self, content_type: str, metadata: dict) -> None:
            """Print a notice whenever new content is generated."""
            path = metadata.get("path", "")
            print(f"[ExamplePlugin] content generated: {content_type} → {path}")

        @hookimpl
        def on_analytics_event(self, event_type: str, data: dict) -> None:
            """Forward analytics events to stdout (replace with real sink)."""
            print(f"[ExamplePlugin] analytics: {event_type} | {data}")

        @hookimpl
        def transform_description(self, description: str, platform: str) -> str:
            """Append a platform-specific call-to-action to the description."""
            cta = {
                "youtube": "\n\nSubscribe for more!",
                "twitter": " 🔔 Follow for daily tips!",
                "tiktok": "\n\nFollow for more content!",
            }.get(platform, "")
            return description + cta

    # --- Demo ---
    pm = PluginManager()
    plugin = ExamplePlugin()
    pm.register(plugin)

    job = {"title": "My First Short", "platform": "youtube"}
    modified_jobs = pm.hook.on_before_publish(job=job)
    print("on_before_publish results:", modified_jobs)

    pm.hook.on_after_publish(job=job, results={"status": "success", "url": "https://youtu.be/xyz"})

    description = "Check out this amazing video."
    # chain transform_description results manually
    parts = pm.hook.transform_description(description=description, platform="youtube")
    final_desc = parts[-1] if parts else description
    print("transform_description:", final_desc)

    pm.unregister(plugin)
    print("Plugins after unregister:", pm.get_plugins())

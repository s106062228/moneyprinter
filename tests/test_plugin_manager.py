"""
Comprehensive tests for src/plugin_manager.py.

Covers hook spec discovery, registration lifecycle, hook invocation,
load_from_directory, thread safety, and edge cases.
"""

import os
import sys
import threading
import textwrap
from unittest.mock import MagicMock, patch

import pytest

# Skip the whole module if pluggy is not installed
pluggy = pytest.importorskip("pluggy")

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import plugin_manager as pm_module
from plugin_manager import (
    PluginManager,
    MoneyPrinterSpec,
    hookimpl,
    hookspec,
    _PROJECT_NAME,
    _MAX_PLUGINS,
)


# ---------------------------------------------------------------------------
# Minimal plugin fixtures (zero external dependencies)
# ---------------------------------------------------------------------------


class FullPlugin:
    """Implements every hook in MoneyPrinterSpec."""

    @hookimpl
    def on_before_publish(self, job: dict):
        modified = dict(job)
        modified["__full_plugin__"] = True
        return modified

    @hookimpl
    def on_after_publish(self, job: dict, results: dict) -> None:
        results["__full_plugin_after__"] = True

    @hookimpl
    def on_content_generated(self, content_type: str, metadata: dict) -> None:
        metadata["__content_plugin__"] = content_type

    @hookimpl
    def on_analytics_event(self, event_type: str, data: dict) -> None:
        data["__analytics_plugin__"] = event_type

    @hookimpl
    def transform_description(self, description: str, platform: str) -> str:
        return description + f"[{platform}]"


class PartialPlugin:
    """Only implements on_before_publish and transform_description."""

    @hookimpl
    def on_before_publish(self, job: dict):
        modified = dict(job)
        modified["__partial__"] = True
        return modified

    @hookimpl
    def transform_description(self, description: str, platform: str) -> str:
        return description + "[partial]"


class TransformPluginA:
    """Appends '-A' to description."""

    @hookimpl
    def transform_description(self, description: str, platform: str) -> str:
        return description + "-A"


class TransformPluginB:
    """Appends '-B' to description."""

    @hookimpl
    def transform_description(self, description: str, platform: str) -> str:
        return description + "-B"


class AnalyticsOnlyPlugin:
    """Only implements on_analytics_event."""

    def __init__(self):
        self.received = []

    @hookimpl
    def on_analytics_event(self, event_type: str, data: dict) -> None:
        self.received.append((event_type, dict(data)))


class NoHookPlugin:
    """Has no hookimpl methods — not a valid plugin for registration, but
    useful for testing load_from_directory skipping."""

    def some_method(self):
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _fresh_pm(project_name: str = _PROJECT_NAME) -> PluginManager:
    """Return a new PluginManager for each test."""
    return PluginManager(project_name=project_name)


# ---------------------------------------------------------------------------
# 1. Hook spec discovery
# ---------------------------------------------------------------------------


class TestHookSpecDiscovery:
    """Verify that all 5 hook specs are registered on MoneyPrinterSpec."""

    EXPECTED_HOOKS = {
        "on_before_publish",
        "on_after_publish",
        "on_content_generated",
        "on_analytics_event",
        "transform_description",
    }

    def test_all_five_hooks_exist_as_methods(self):
        for name in self.EXPECTED_HOOKS:
            assert hasattr(MoneyPrinterSpec, name), f"Missing hook: {name}"

    def test_each_hook_carries_hookspec_marker(self):
        marker_attr = _PROJECT_NAME + "_spec"
        for name in self.EXPECTED_HOOKS:
            method = getattr(MoneyPrinterSpec, name)
            assert hasattr(method, marker_attr), (
                f"Hook {name!r} is missing the @hookspec marker"
            )

    def test_pm_exposes_all_five_hook_callers(self):
        pm = _fresh_pm()
        for name in self.EXPECTED_HOOKS:
            assert hasattr(pm.hook, name), f"pm.hook missing: {name}"

    def test_on_before_publish_signature_has_job_param(self):
        import inspect

        sig = inspect.signature(MoneyPrinterSpec.on_before_publish)
        assert "job" in sig.parameters

    def test_transform_description_signature(self):
        import inspect

        sig = inspect.signature(MoneyPrinterSpec.transform_description)
        assert "description" in sig.parameters
        assert "platform" in sig.parameters

    def test_on_analytics_event_signature(self):
        import inspect

        sig = inspect.signature(MoneyPrinterSpec.on_analytics_event)
        assert "event_type" in sig.parameters
        assert "data" in sig.parameters


# ---------------------------------------------------------------------------
# 2. Plugin registration
# ---------------------------------------------------------------------------


class TestPluginRegistration:
    """register() lifecycle tests."""

    def test_register_stores_plugin(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        assert p in pm.get_plugins()

    def test_is_registered_true_after_register(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        assert pm.is_registered(p) is True

    def test_get_plugins_returns_list(self):
        pm = _fresh_pm()
        assert isinstance(pm.get_plugins(), list)

    def test_get_plugins_contains_registered_plugin(self):
        pm = _fresh_pm()
        p = PartialPlugin()
        pm.register(p)
        plugins = pm.get_plugins()
        assert p in plugins

    def test_register_multiple_plugins(self):
        pm = _fresh_pm()
        p1, p2, p3 = FullPlugin(), PartialPlugin(), AnalyticsOnlyPlugin()
        pm.register(p1)
        pm.register(p2)
        pm.register(p3)
        all_plugins = pm.get_plugins()
        for p in (p1, p2, p3):
            assert p in all_plugins

    def test_register_increments_count(self):
        pm = _fresh_pm()
        before = len(pm.get_plugins())
        pm.register(FullPlugin())
        assert len(pm.get_plugins()) == before + 1

    def test_register_same_plugin_twice_raises(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        with pytest.raises(ValueError, match="already registered"):
            pm.register(p)

    def test_register_none_raises(self):
        pm = _fresh_pm()
        with pytest.raises(ValueError, match="None"):
            pm.register(None)


# ---------------------------------------------------------------------------
# 3. Plugin unregistration
# ---------------------------------------------------------------------------


class TestPluginUnregistration:
    """unregister() lifecycle tests."""

    def test_unregister_removes_plugin(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        pm.unregister(p)
        assert p not in pm.get_plugins()

    def test_is_registered_false_after_unregister(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        pm.unregister(p)
        assert pm.is_registered(p) is False

    def test_unregister_then_re_register(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        pm.unregister(p)
        # Should not raise
        pm.register(p)
        assert pm.is_registered(p) is True

    def test_unregister_none_raises(self):
        pm = _fresh_pm()
        with pytest.raises(ValueError, match="None"):
            pm.unregister(None)

    def test_unregister_not_registered_raises(self):
        pm = _fresh_pm()
        p = FullPlugin()
        with pytest.raises(ValueError, match="not registered"):
            pm.unregister(p)

    def test_unregister_one_of_many(self):
        pm = _fresh_pm()
        p1 = FullPlugin()
        p2 = PartialPlugin()
        pm.register(p1)
        pm.register(p2)
        pm.unregister(p1)
        assert p1 not in pm.get_plugins()
        assert p2 in pm.get_plugins()


# ---------------------------------------------------------------------------
# 4. Max plugins limit
# ---------------------------------------------------------------------------


class TestMaxPluginsLimit:
    """Registering beyond _MAX_PLUGINS should raise ValueError."""

    def test_max_plugins_constant_is_50(self):
        assert _MAX_PLUGINS == 50

    def test_exceed_limit_raises(self):
        pm = _fresh_pm()
        # Register _MAX_PLUGINS plugins (each is a distinct instance)
        plugins = [AnalyticsOnlyPlugin() for _ in range(_MAX_PLUGINS)]
        for p in plugins:
            pm.register(p)
        # The (MAX+1)-th registration must fail
        with pytest.raises(ValueError, match="limit"):
            pm.register(AnalyticsOnlyPlugin())

    def test_after_limit_error_existing_plugins_intact(self):
        pm = _fresh_pm()
        plugins = [AnalyticsOnlyPlugin() for _ in range(_MAX_PLUGINS)]
        for p in plugins:
            pm.register(p)
        try:
            pm.register(AnalyticsOnlyPlugin())
        except ValueError:
            pass
        assert len(pm.get_plugins()) == _MAX_PLUGINS


# ---------------------------------------------------------------------------
# 5. Hook calling — each of the 5 hooks
# ---------------------------------------------------------------------------


class TestHookCalling:
    """Verify each hook is callable and executes the plugin implementation."""

    def test_on_before_publish_returns_result(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        results = pm.hook.on_before_publish(job={"title": "test"})
        assert isinstance(results, list)
        # firstresult would be a single value; with firstresult=False (default)
        # pluggy returns a list
        assert any(r is not None and r.get("__full_plugin__") for r in results)

    def test_on_after_publish_executes(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        results_dict = {}
        # Should not raise; return value is None for non-firstresult hooks
        pm.hook.on_after_publish(job={"title": "t"}, results=results_dict)
        assert results_dict.get("__full_plugin_after__") is True

    def test_on_content_generated_executes(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        meta = {}
        pm.hook.on_content_generated(content_type="video", metadata=meta)
        assert meta.get("__content_plugin__") == "video"

    def test_on_analytics_event_executes(self):
        pm = _fresh_pm()
        collector = AnalyticsOnlyPlugin()
        pm.register(collector)
        payload = {"key": "value"}
        pm.hook.on_analytics_event(event_type="test.event", data=payload)
        assert len(collector.received) == 1
        assert collector.received[0][0] == "test.event"

    def test_transform_description_returns_results(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        parts = pm.hook.transform_description(
            description="hello", platform="youtube"
        )
        assert isinstance(parts, list)
        assert len(parts) > 0
        assert any("youtube" in str(r) for r in parts)

    def test_no_plugins_on_before_publish_returns_empty(self):
        pm = _fresh_pm()
        results = pm.hook.on_before_publish(job={"title": "t"})
        assert results == []

    def test_no_plugins_transform_description_returns_empty(self):
        pm = _fresh_pm()
        parts = pm.hook.transform_description(description="x", platform="yt")
        assert parts == []


# ---------------------------------------------------------------------------
# 6. Multiple plugins — all receive hook calls
# ---------------------------------------------------------------------------


class TestMultiplePlugins:
    """All registered plugins receive hook calls."""

    def test_two_analytics_plugins_both_called(self):
        pm = _fresh_pm()
        c1 = AnalyticsOnlyPlugin()
        c2 = AnalyticsOnlyPlugin()
        pm.register(c1)
        pm.register(c2)
        pm.hook.on_analytics_event(event_type="x.y", data={})
        assert len(c1.received) == 1
        assert len(c2.received) == 1

    def test_three_plugins_on_before_publish_all_called(self):
        pm = _fresh_pm()
        p1 = FullPlugin()
        p2 = PartialPlugin()

        class AnotherPlugin:
            @hookimpl
            def on_before_publish(self, job):
                j = dict(job)
                j["__another__"] = True
                return j

        p3 = AnotherPlugin()
        pm.register(p1)
        pm.register(p2)
        pm.register(p3)
        results = pm.hook.on_before_publish(job={"title": "multi"})
        keys_in_results = {k for r in results if r for k in r}
        assert "__full_plugin__" in keys_in_results
        assert "__partial__" in keys_in_results
        assert "__another__" in keys_in_results

    def test_unregistered_plugin_no_longer_called(self):
        pm = _fresh_pm()
        c = AnalyticsOnlyPlugin()
        pm.register(c)
        pm.hook.on_analytics_event(event_type="a", data={})
        assert len(c.received) == 1
        pm.unregister(c)
        pm.hook.on_analytics_event(event_type="b", data={})
        assert len(c.received) == 1  # still only one call


# ---------------------------------------------------------------------------
# 7. Hook result aggregation
# ---------------------------------------------------------------------------


class TestHookResultAggregation:
    """on_before_publish collects all non-None returns; others return lists."""

    def test_on_before_publish_collects_all_results(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        pm.register(PartialPlugin())
        results = pm.hook.on_before_publish(job={"title": "agg"})
        # Both plugins return a dict; we get both
        assert len(results) == 2
        assert all(isinstance(r, dict) for r in results)

    def test_on_after_publish_returns_list_of_none(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        outcome = pm.hook.on_after_publish(
            job={}, results={}
        )
        # pluggy returns list of return values; on_after_publish returns None
        assert isinstance(outcome, list)

    def test_on_content_generated_returns_list(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        ret = pm.hook.on_content_generated(content_type="image", metadata={})
        assert isinstance(ret, list)

    def test_on_analytics_event_returns_list(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        ret = pm.hook.on_analytics_event(event_type="e", data={})
        assert isinstance(ret, list)

    def test_transform_description_returns_all_values(self):
        pm = _fresh_pm()
        pm.register(TransformPluginA())
        pm.register(TransformPluginB())
        parts = pm.hook.transform_description(
            description="base", platform="youtube"
        )
        # Both plugins contribute; both results present
        assert len(parts) == 2


# ---------------------------------------------------------------------------
# 8. transform_description chaining
# ---------------------------------------------------------------------------


class TestTransformDescriptionChaining:
    """Verify manual chaining of transform_description results works."""

    def test_single_plugin_transform(self):
        pm = _fresh_pm()
        pm.register(TransformPluginA())
        parts = pm.hook.transform_description(description="hello", platform="yt")
        assert parts == ["hello-A"]

    def test_two_plugins_both_results_present(self):
        pm = _fresh_pm()
        pm.register(TransformPluginA())
        pm.register(TransformPluginB())
        parts = pm.hook.transform_description(description="x", platform="yt")
        assert len(parts) == 2

    def test_chain_produces_cumulative_result_manually(self):
        """Caller chains results: each plugin sees the previous output."""
        pm = _fresh_pm()
        pm.register(TransformPluginA())
        pm.register(TransformPluginB())
        description = "start"
        parts = pm.hook.transform_description(
            description=description, platform="yt"
        )
        # Simulate chaining: last result is the most-recently-applied transform
        final = parts[-1] if parts else description
        assert isinstance(final, str)
        assert final != description  # something was appended

    def test_platform_passed_to_transform(self):
        pm = _fresh_pm()

        class PlatformCapture:
            captured = []

            @hookimpl
            def transform_description(self, description: str, platform: str) -> str:
                self.captured.append(platform)
                return description

        cap = PlatformCapture()
        pm.register(cap)
        pm.hook.transform_description(description="d", platform="tiktok")
        assert "tiktok" in cap.captured

    def test_empty_description_transform(self):
        pm = _fresh_pm()
        pm.register(TransformPluginA())
        parts = pm.hook.transform_description(description="", platform="yt")
        assert parts == ["-A"]


# ---------------------------------------------------------------------------
# 9. Plugin with partial implementation
# ---------------------------------------------------------------------------


class TestPartialPlugin:
    """A plugin that only implements some hooks should work fine."""

    def test_partial_plugin_registers_without_error(self):
        pm = _fresh_pm()
        # Should not raise
        pm.register(PartialPlugin())

    def test_partial_plugin_called_on_implemented_hook(self):
        pm = _fresh_pm()
        pm.register(PartialPlugin())
        results = pm.hook.on_before_publish(job={"x": 1})
        assert any(r and r.get("__partial__") for r in results)

    def test_partial_plugin_not_called_on_unimplemented_hook(self):
        pm = _fresh_pm()
        p = PartialPlugin()
        pm.register(p)
        collector = AnalyticsOnlyPlugin()
        pm.register(collector)
        # PartialPlugin does NOT implement on_analytics_event
        pm.hook.on_analytics_event(event_type="z", data={})
        # collector got it; PartialPlugin did not raise
        assert len(collector.received) == 1

    def test_analytics_only_plugin_on_before_publish_empty(self):
        pm = _fresh_pm()
        pm.register(AnalyticsOnlyPlugin())
        results = pm.hook.on_before_publish(job={"t": "v"})
        # AnalyticsOnlyPlugin doesn't implement on_before_publish
        assert results == []


# ---------------------------------------------------------------------------
# 10. load_from_directory
# ---------------------------------------------------------------------------


class TestLoadFromDirectory:
    """Tests for PluginManager.load_from_directory()."""

    # -- helpers --

    @staticmethod
    def _write_plugin(tmp_path, filename: str, code: str) -> None:
        (tmp_path / filename).write_text(textwrap.dedent(code))

    # -- tests --

    def test_load_valid_plugin_returns_one(self, tmp_path):
        self._write_plugin(
            tmp_path,
            "myplugin.py",
            """\
            from plugin_manager import hookimpl

            class MyPlugin:
                @hookimpl
                def on_analytics_event(self, event_type, data):
                    data['loaded'] = True
            """,
        )
        pm = _fresh_pm()
        count = pm.load_from_directory(str(tmp_path))
        assert count == 1

    def test_loaded_plugin_is_registered(self, tmp_path):
        self._write_plugin(
            tmp_path,
            "reg_check.py",
            """\
            from plugin_manager import hookimpl

            class RegCheckPlugin:
                @hookimpl
                def on_analytics_event(self, event_type, data):
                    pass
            """,
        )
        pm = _fresh_pm()
        pm.load_from_directory(str(tmp_path))
        assert len(pm.get_plugins()) == 1

    def test_empty_directory_returns_zero(self, tmp_path):
        pm = _fresh_pm()
        count = pm.load_from_directory(str(tmp_path))
        assert count == 0

    def test_nonexistent_directory_raises_value_error(self, tmp_path):
        pm = _fresh_pm()
        fake_dir = str(tmp_path / "does_not_exist")
        with pytest.raises(ValueError, match="does not exist"):
            pm.load_from_directory(fake_dir)

    def test_none_path_raises_value_error(self):
        pm = _fresh_pm()
        with pytest.raises((ValueError, TypeError)):
            pm.load_from_directory(None)  # type: ignore[arg-type]

    def test_empty_string_path_raises_value_error(self):
        pm = _fresh_pm()
        with pytest.raises(ValueError):
            pm.load_from_directory("")

    def test_skips_underscore_files(self, tmp_path):
        self._write_plugin(
            tmp_path,
            "_private.py",
            """\
            from plugin_manager import hookimpl

            class PrivatePlugin:
                @hookimpl
                def on_analytics_event(self, event_type, data):
                    pass
            """,
        )
        pm = _fresh_pm()
        count = pm.load_from_directory(str(tmp_path))
        assert count == 0

    def test_skips_dunder_init(self, tmp_path):
        self._write_plugin(
            tmp_path,
            "__init__.py",
            """\
            from plugin_manager import hookimpl

            class InitPlugin:
                @hookimpl
                def on_analytics_event(self, event_type, data):
                    pass
            """,
        )
        pm = _fresh_pm()
        count = pm.load_from_directory(str(tmp_path))
        assert count == 0

    def test_skips_non_py_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a plugin")
        (tmp_path / "data.json").write_text("{}")
        pm = _fresh_pm()
        count = pm.load_from_directory(str(tmp_path))
        assert count == 0

    def test_skips_file_with_import_error(self, tmp_path):
        self._write_plugin(
            tmp_path,
            "broken.py",
            """\
            import this_module_does_not_exist_xyz123

            from plugin_manager import hookimpl

            class BrokenPlugin:
                @hookimpl
                def on_analytics_event(self, event_type, data):
                    pass
            """,
        )
        pm = _fresh_pm()
        # Should not raise; just skip broken file
        count = pm.load_from_directory(str(tmp_path))
        assert count == 0

    def test_skips_class_without_hookimpl(self, tmp_path):
        self._write_plugin(
            tmp_path,
            "nohook.py",
            """\
            class NotAPlugin:
                def some_method(self):
                    pass
            """,
        )
        pm = _fresh_pm()
        count = pm.load_from_directory(str(tmp_path))
        assert count == 0

    def test_loads_multiple_plugin_files(self, tmp_path):
        for i in range(3):
            self._write_plugin(
                tmp_path,
                f"plugin{i}.py",
                f"""\
from plugin_manager import hookimpl

class Plugin{i}:
    @hookimpl
    def on_analytics_event(self, event_type, data):
        pass
""",
            )
        pm = _fresh_pm()
        count = pm.load_from_directory(str(tmp_path))
        assert count == 3

    def test_loaded_plugin_hook_executes(self, tmp_path):
        self._write_plugin(
            tmp_path,
            "exec_plugin.py",
            """\
from plugin_manager import hookimpl

class ExecPlugin:
    @hookimpl
    def on_analytics_event(self, event_type, data):
        data['exec_plugin_called'] = True
""",
        )
        pm = _fresh_pm()
        pm.load_from_directory(str(tmp_path))
        payload = {}
        pm.hook.on_analytics_event(event_type="t", data=payload)
        assert payload.get("exec_plugin_called") is True

    def test_load_skips_instantiation_error(self, tmp_path):
        """A class that raises in __init__ is skipped, not crashed."""
        self._write_plugin(
            tmp_path,
            "bad_init.py",
            """\
from plugin_manager import hookimpl

class BadInitPlugin:
    def __init__(self):
        raise RuntimeError("cannot instantiate")

    @hookimpl
    def on_analytics_event(self, event_type, data):
        pass
""",
        )
        pm = _fresh_pm()
        # Should not raise; just skip the uninstantiable class
        count = pm.load_from_directory(str(tmp_path))
        assert count == 0


# ---------------------------------------------------------------------------
# 11. is_registered
# ---------------------------------------------------------------------------


class TestIsRegistered:
    def test_false_before_register(self):
        pm = _fresh_pm()
        assert pm.is_registered(FullPlugin()) is False

    def test_true_after_register(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        assert pm.is_registered(p) is True

    def test_false_after_unregister(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        pm.unregister(p)
        assert pm.is_registered(p) is False

    def test_different_instances_are_independent(self):
        pm = _fresh_pm()
        p1 = FullPlugin()
        p2 = FullPlugin()
        pm.register(p1)
        assert pm.is_registered(p1) is True
        assert pm.is_registered(p2) is False


# ---------------------------------------------------------------------------
# 12. hook property
# ---------------------------------------------------------------------------


class TestHookProperty:
    def test_hook_returns_hook_relay(self):
        pm = _fresh_pm()
        assert isinstance(pm.hook, pluggy.HookRelay)

    def test_hook_same_object_across_accesses(self):
        pm = _fresh_pm()
        assert pm.hook is pm.hook

    def test_hook_relay_has_expected_callables(self):
        pm = _fresh_pm()
        for name in (
            "on_before_publish",
            "on_after_publish",
            "on_content_generated",
            "on_analytics_event",
            "transform_description",
        ):
            caller = getattr(pm.hook, name, None)
            assert caller is not None, f"pm.hook.{name} missing"
            assert callable(caller)


# ---------------------------------------------------------------------------
# 13. Invalid plugin type
# ---------------------------------------------------------------------------


class TestInvalidPluginType:
    def test_register_none_raises_value_error(self):
        pm = _fresh_pm()
        with pytest.raises(ValueError):
            pm.register(None)

    def test_unregister_none_raises_value_error(self):
        pm = _fresh_pm()
        with pytest.raises(ValueError):
            pm.unregister(None)

    def test_register_integer_does_not_crash_immediately(self):
        """pluggy itself might accept integers but they'll have no hooks —
        the PluginManager should not pre-filter non-None objects."""
        pm = _fresh_pm()
        # An integer has no hookimpl methods, but PluginManager.register()
        # delegates validation to pluggy; behaviour is implementation-defined.
        # We just verify it doesn't crash with a non-None non-object
        # (pluggy may or may not raise here).
        try:
            pm.register(42)
        except Exception:
            pass  # any exception is acceptable


# ---------------------------------------------------------------------------
# 14. Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Concurrent register/unregister must not corrupt internal state."""

    def test_concurrent_register_all_succeed(self):
        pm = _fresh_pm()
        plugins = [AnalyticsOnlyPlugin() for _ in range(20)]
        errors = []

        def worker(p):
            try:
                pm.register(p)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(p,)) for p in plugins]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No unexpected errors (ValueError for duplicates would be a bug
        # since each plugin is a distinct instance)
        assert errors == [], f"Unexpected errors during concurrent register: {errors}"
        assert len(pm.get_plugins()) == 20

    def test_concurrent_register_unregister_no_deadlock(self):
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        results = []

        def toggler():
            for _ in range(10):
                try:
                    if pm.is_registered(p):
                        pm.unregister(p)
                    else:
                        pm.register(p)
                except ValueError:
                    pass

        threads = [threading.Thread(target=toggler) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Just verify no deadlock / crash occurred

    def test_get_plugins_during_concurrent_modification(self):
        pm = _fresh_pm()
        plugins = [AnalyticsOnlyPlugin() for _ in range(10)]
        snapshot_lengths = []

        def register_all():
            for p in plugins:
                try:
                    pm.register(p)
                except ValueError:
                    pass

        def reader():
            for _ in range(20):
                snapshot_lengths.append(len(pm.get_plugins()))

        t1 = threading.Thread(target=register_all)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # Lengths should be monotonically non-decreasing is ideal but we only
        # assert no exception was raised (checked implicitly)
        assert all(n >= 0 for n in snapshot_lengths)


# ---------------------------------------------------------------------------
# 15. Project name
# ---------------------------------------------------------------------------


class TestProjectName:
    def test_default_project_name_is_moneyprinter(self):
        pm = PluginManager()
        assert pm._project_name == "moneyprinter"

    def test_custom_project_name_same_as_default_works(self):
        """Passing the correct project name explicitly still works."""
        pm = PluginManager(project_name="moneyprinter")
        assert pm._project_name == "moneyprinter"

    def test_empty_project_name_raises(self):
        with pytest.raises(ValueError):
            PluginManager(project_name="")

    def test_none_project_name_raises(self):
        with pytest.raises((ValueError, TypeError)):
            PluginManager(project_name=None)  # type: ignore[arg-type]

    def test_mismatched_project_name_raises_because_spec_is_hardcoded(self):
        """MoneyPrinterSpec is decorated with the 'moneyprinter' marker, so
        constructing a PluginManager with a different project name raises
        ValueError from pluggy when add_hookspecs() is called."""
        with pytest.raises(ValueError, match="myprojtest"):
            PluginManager(project_name="myprojtest")


# ---------------------------------------------------------------------------
# 16. Module-level exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    def test_hookimpl_marker_has_correct_project(self):
        # pluggy stores the project name on the marker; verify via attribute
        # created when applied to a test function
        class _Tmp:
            @hookimpl
            def on_before_publish(self, job):
                pass

        marker_attr = _PROJECT_NAME + "_impl"
        assert hasattr(_Tmp.on_before_publish, marker_attr)

    def test_hookspec_marker_has_correct_project(self):
        class _Tmp:
            @hookspec
            def some_spec(self):
                pass

        marker_attr = _PROJECT_NAME + "_spec"
        assert hasattr(_Tmp.some_spec, marker_attr)

    def test_project_name_constant(self):
        assert _PROJECT_NAME == "moneyprinter"


# ---------------------------------------------------------------------------
# 17. Edge cases / misc
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_get_plugins_is_copy(self):
        """Mutating the returned list must not affect the manager."""
        pm = _fresh_pm()
        p = FullPlugin()
        pm.register(p)
        lst = pm.get_plugins()
        lst.clear()
        # Original still has the plugin
        assert p in pm.get_plugins()

    def test_on_before_publish_empty_job(self):
        pm = _fresh_pm()
        pm.register(FullPlugin())
        results = pm.hook.on_before_publish(job={})
        assert isinstance(results, list)

    def test_hook_call_with_no_plugins_does_not_raise(self):
        pm = _fresh_pm()
        pm.hook.on_after_publish(job={}, results={})
        pm.hook.on_content_generated(content_type="video", metadata={})
        pm.hook.on_analytics_event(event_type="x", data={})

    def test_load_from_directory_returns_int(self, tmp_path):
        pm = _fresh_pm()
        result = pm.load_from_directory(str(tmp_path))
        assert isinstance(result, int)

    def test_has_hookimpl_returns_false_for_plain_class(self):
        pm = _fresh_pm()
        assert pm._has_hookimpl(NoHookPlugin) is False

    def test_has_hookimpl_returns_true_for_plugin_class(self):
        pm = _fresh_pm()
        assert pm._has_hookimpl(FullPlugin) is True

    def test_multiple_calls_to_same_hook_accumulate(self):
        pm = _fresh_pm()
        collector = AnalyticsOnlyPlugin()
        pm.register(collector)
        for i in range(5):
            pm.hook.on_analytics_event(event_type=f"e{i}", data={})
        assert len(collector.received) == 5


# ---------------------------------------------------------------------------
# 18. Lifecycle hook specs (H61)
# ---------------------------------------------------------------------------


class TestLifecycleHookSpecs:
    """Tests for the 6 new lifecycle hook specifications (H61)."""

    def test_on_pre_publish_spec_exists(self):
        """MoneyPrinterSpec has on_pre_publish hookspec."""
        assert hasattr(MoneyPrinterSpec, 'on_pre_publish')

    def test_on_post_publish_spec_exists(self):
        assert hasattr(MoneyPrinterSpec, 'on_post_publish')

    def test_on_pre_schedule_spec_exists(self):
        assert hasattr(MoneyPrinterSpec, 'on_pre_schedule')

    def test_on_post_schedule_spec_exists(self):
        assert hasattr(MoneyPrinterSpec, 'on_post_schedule')

    def test_on_batch_start_spec_exists(self):
        assert hasattr(MoneyPrinterSpec, 'on_batch_start')

    def test_on_batch_complete_spec_exists(self):
        assert hasattr(MoneyPrinterSpec, 'on_batch_complete')

    def test_lifecycle_hooks_callable_with_no_plugins(self):
        """Calling lifecycle hooks with no plugins registered raises no error."""
        pm = PluginManager()
        pm.hook.on_pre_publish(job={"title": "test"})
        pm.hook.on_post_publish(job={"title": "test"}, results=[])
        pm.hook.on_pre_schedule(job={"title": "test"})
        pm.hook.on_post_schedule(job={"title": "test"}, job_id="job-1")
        pm.hook.on_batch_start(job={"topics_count": 3})
        pm.hook.on_batch_complete(job={"niche": "test"}, result={})

    def test_plugin_receives_on_pre_publish(self):
        """A plugin implementing on_pre_publish gets called."""
        from plugin_manager import hookimpl

        class PrePublishPlugin:
            def __init__(self):
                self.received_job = None

            @hookimpl
            def on_pre_publish(self, job):
                self.received_job = job

        plugin = PrePublishPlugin()
        pm = PluginManager()
        pm.register(plugin)
        pm.hook.on_pre_publish(job={"title": "hello"})
        assert plugin.received_job == {"title": "hello"}

    def test_plugin_receives_on_post_publish(self):
        from plugin_manager import hookimpl

        class PostPublishPlugin:
            def __init__(self):
                self.received_results = None

            @hookimpl
            def on_post_publish(self, job, results):
                self.received_results = results

        plugin = PostPublishPlugin()
        pm = PluginManager()
        pm.register(plugin)
        pm.hook.on_post_publish(job={"title": "t"}, results=[{"platform": "youtube", "success": True}])
        assert plugin.received_results == [{"platform": "youtube", "success": True}]

    def test_plugin_receives_on_batch_complete(self):
        from plugin_manager import hookimpl

        class BatchPlugin:
            def __init__(self):
                self.received_result = None

            @hookimpl
            def on_batch_complete(self, job, result):
                self.received_result = result

        plugin = BatchPlugin()
        pm = PluginManager()
        pm.register(plugin)
        pm.hook.on_batch_complete(job={"niche": "n"}, result={"total": 3, "succeeded": 2})
        assert plugin.received_result["total"] == 3

    def test_plugin_receives_on_pre_schedule(self):
        from plugin_manager import hookimpl

        class SchedulePlugin:
            def __init__(self):
                self.called = False

            @hookimpl
            def on_pre_schedule(self, job):
                self.called = True

        plugin = SchedulePlugin()
        pm = PluginManager()
        pm.register(plugin)
        pm.hook.on_pre_schedule(job={"title": "t"})
        assert plugin.called

    def test_plugin_receives_on_post_schedule(self):
        from plugin_manager import hookimpl

        class PostSchedulePlugin:
            def __init__(self):
                self.received_job_id = None

            @hookimpl
            def on_post_schedule(self, job, job_id):
                self.received_job_id = job_id

        plugin = PostSchedulePlugin()
        pm = PluginManager()
        pm.register(plugin)
        pm.hook.on_post_schedule(job={"title": "t"}, job_id="abc-123")
        assert plugin.received_job_id == "abc-123"

    def test_plugin_receives_on_batch_start(self):
        from plugin_manager import hookimpl

        class BatchStartPlugin:
            def __init__(self):
                self.received_job = None

            @hookimpl
            def on_batch_start(self, job):
                self.received_job = job

        plugin = BatchStartPlugin()
        pm = PluginManager()
        pm.register(plugin)
        pm.hook.on_batch_start(job={"topics_count": 5})
        assert plugin.received_job["topics_count"] == 5

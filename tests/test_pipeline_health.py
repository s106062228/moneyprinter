"""
Comprehensive tests for src/pipeline_health.py
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

# Ensure src/ is on the path (mirrors conftest.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pipeline_health import (
    ModuleHealth,
    PipelineHealthMonitor,
    _MAX_ERROR_LENGTH,
    _MAX_METADATA_KEYS,
    _MAX_MODULE_NAME_LENGTH,
    _MAX_MODULES,
    _VALID_STATUSES,
    _validate_metadata,
    _validate_module_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_monitor(tmp_path) -> PipelineHealthMonitor:
    """Return a fresh monitor that persists to a temp file."""
    return PipelineHealthMonitor(persist_path=str(tmp_path / "pipeline_health.json"))


# ===========================================================================
# ModuleHealth.to_dict / from_dict
# ===========================================================================


class TestModuleHealthToDict:
    def test_to_dict_returns_all_fields(self):
        mod = ModuleHealth(
            module_name="pub",
            status="ok",
            last_check="2026-01-01T00:00:00+00:00",
            error_count=2,
            success_count=5,
            last_error="oops",
            metadata={"key": "val"},
        )
        d = mod.to_dict()
        assert d["module_name"] == "pub"
        assert d["status"] == "ok"
        assert d["last_check"] == "2026-01-01T00:00:00+00:00"
        assert d["error_count"] == 2
        assert d["success_count"] == 5
        assert d["last_error"] == "oops"
        assert d["metadata"] == {"key": "val"}

    def test_to_dict_default_values(self):
        mod = ModuleHealth(module_name="x")
        d = mod.to_dict()
        assert d["status"] == "unknown"
        assert d["error_count"] == 0
        assert d["success_count"] == 0
        assert d["last_error"] == ""
        assert d["metadata"] == {}

    def test_to_dict_is_plain_dict(self):
        mod = ModuleHealth(module_name="x")
        d = mod.to_dict()
        assert type(d) is dict  # not a subclass


class TestModuleHealthFromDict:
    def test_from_dict_roundtrip(self):
        mod = ModuleHealth(
            module_name="pub",
            status="degraded",
            last_check="2026-01-01T00:00:00+00:00",
            error_count=3,
            success_count=10,
            last_error="timeout",
            metadata={"retries": 1},
        )
        mod2 = ModuleHealth.from_dict(mod.to_dict())
        assert mod2.module_name == mod.module_name
        assert mod2.status == mod.status
        assert mod2.last_check == mod.last_check
        assert mod2.error_count == mod.error_count
        assert mod2.success_count == mod.success_count
        assert mod2.last_error == mod.last_error
        assert mod2.metadata == mod.metadata

    def test_from_dict_missing_optional_fields_uses_defaults(self):
        mod = ModuleHealth.from_dict({"module_name": "slim"})
        assert mod.module_name == "slim"
        assert mod.status == "unknown"
        assert mod.error_count == 0
        assert mod.success_count == 0
        assert mod.last_error == ""
        assert mod.metadata == {}

    def test_from_dict_invalid_status_falls_back_to_unknown(self):
        mod = ModuleHealth.from_dict({"module_name": "x", "status": "INVALID"})
        assert mod.status == "unknown"

    def test_from_dict_negative_error_count_falls_back_to_zero(self):
        mod = ModuleHealth.from_dict({"module_name": "x", "error_count": -5})
        assert mod.error_count == 0

    def test_from_dict_negative_success_count_falls_back_to_zero(self):
        mod = ModuleHealth.from_dict({"module_name": "x", "success_count": -1})
        assert mod.success_count == 0

    def test_from_dict_non_int_counts_fall_back_to_zero(self):
        mod = ModuleHealth.from_dict({"module_name": "x", "error_count": "bad", "success_count": None})
        assert mod.error_count == 0
        assert mod.success_count == 0

    def test_from_dict_non_dict_metadata_falls_back_to_empty(self):
        mod = ModuleHealth.from_dict({"module_name": "x", "metadata": "not-a-dict"})
        assert mod.metadata == {}

    def test_from_dict_extra_fields_are_ignored(self):
        mod = ModuleHealth.from_dict({"module_name": "x", "surprise_field": 99})
        assert mod.module_name == "x"

    def test_from_dict_empty_module_name_allowed(self):
        # from_dict should not raise — validation is the monitor's job
        mod = ModuleHealth.from_dict({"module_name": ""})
        assert mod.module_name == ""

    def test_from_dict_all_valid_statuses(self):
        for s in _VALID_STATUSES:
            mod = ModuleHealth.from_dict({"module_name": "x", "status": s})
            assert mod.status == s


# ===========================================================================
# _validate_module_name helper
# ===========================================================================


class TestValidateModuleName:
    def test_valid_name(self):
        _validate_module_name("publisher")  # should not raise

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate_module_name("")

    def test_null_byte_raises(self):
        with pytest.raises(ValueError, match="null bytes"):
            _validate_module_name("bad\x00name")

    def test_max_length_exactly_ok(self):
        _validate_module_name("a" * _MAX_MODULE_NAME_LENGTH)

    def test_over_max_length_raises(self):
        with pytest.raises(ValueError):
            _validate_module_name("a" * (_MAX_MODULE_NAME_LENGTH + 1))

    def test_non_string_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            _validate_module_name(None)  # type: ignore[arg-type]


# ===========================================================================
# _validate_metadata helper
# ===========================================================================


class TestValidateMetadata:
    def test_valid_empty_dict(self):
        _validate_metadata({})

    def test_valid_with_keys(self):
        _validate_metadata({"a": 1, "b": "two"})

    def test_too_many_keys_raises(self):
        big = {str(i): i for i in range(_MAX_METADATA_KEYS + 1)}
        with pytest.raises(ValueError, match="exceeds maximum"):
            _validate_metadata(big)

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be a dict"):
            _validate_metadata("not-a-dict")  # type: ignore[arg-type]

    def test_non_serialisable_value_raises(self):
        with pytest.raises(ValueError, match="non-JSON-serialisable"):
            _validate_metadata({"fn": lambda: None})

    def test_exactly_max_keys_ok(self):
        exact = {str(i): i for i in range(_MAX_METADATA_KEYS)}
        _validate_metadata(exact)  # should not raise

    def test_none_values_allowed(self):
        _validate_metadata({"key": None})  # None is JSON-serialisable


# ===========================================================================
# PipelineHealthMonitor.register_module
# ===========================================================================


class TestRegisterModule:
    def test_register_new_module(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("publisher")
        assert "publisher" in m.check_all()

    def test_registered_module_starts_unknown(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("publisher")
        assert m.get_module_health("publisher").status == "unknown"

    def test_duplicate_registration_is_noop(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("publisher")
        m.register_module("publisher")  # second call — no exception
        assert len(m.check_all()) == 1

    def test_register_invalid_empty_name_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        with pytest.raises(ValueError):
            m.register_module("")

    def test_register_null_byte_in_name_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        with pytest.raises(ValueError):
            m.register_module("bad\x00name")

    def test_register_name_at_max_length(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("a" * _MAX_MODULE_NAME_LENGTH)

    def test_register_name_over_max_length_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        with pytest.raises(ValueError):
            m.register_module("a" * (_MAX_MODULE_NAME_LENGTH + 1))

    def test_register_up_to_max_modules(self, tmp_path):
        m = make_monitor(tmp_path)
        for i in range(_MAX_MODULES):
            m.register_module(f"module_{i}")
        assert len(m.check_all()) == _MAX_MODULES

    def test_register_over_max_modules_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        for i in range(_MAX_MODULES):
            m.register_module(f"module_{i}")
        with pytest.raises(ValueError, match="maximum"):
            m.register_module("one_too_many")

    def test_register_modules_with_varied_names(self, tmp_path):
        m = make_monitor(tmp_path)
        names = ["pub", "scraper-v2", "llm_gen", "twitter.bot", "mod 1"]
        for n in names:
            m.register_module(n)
        for n in names:
            assert n in m.check_all()


# ===========================================================================
# PipelineHealthMonitor.report_health
# ===========================================================================


class TestReportHealth:
    def test_report_ok_increments_success_count(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "ok")
        assert m.get_module_health("pub").success_count == 1

    def test_report_ok_twice_increments_twice(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "ok")
        m.report_health("pub", "ok")
        assert m.get_module_health("pub").success_count == 2

    def test_report_error_increments_error_count(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "error", error_msg="boom")
        assert m.get_module_health("pub").error_count == 1

    def test_report_degraded_increments_error_count(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "degraded")
        assert m.get_module_health("pub").error_count == 1

    def test_report_unknown_does_not_change_counts(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "unknown")
        mod = m.get_module_health("pub")
        assert mod.error_count == 0
        assert mod.success_count == 0

    def test_report_error_sets_last_error(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "error", error_msg="Connection timeout")
        assert m.get_module_health("pub").last_error == "Connection timeout"

    def test_report_error_truncates_long_error_msg(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        long_msg = "x" * (_MAX_ERROR_LENGTH + 100)
        m.report_health("pub", "error", error_msg=long_msg)
        assert len(m.get_module_health("pub").last_error) == _MAX_ERROR_LENGTH

    def test_report_degraded_sets_last_error(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "degraded", error_msg="Slow")
        assert m.get_module_health("pub").last_error == "Slow"

    def test_report_ok_does_not_set_last_error(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "error", error_msg="prev error")
        m.report_health("pub", "ok")
        # last_error is not cleared on ok — check it still holds previous value
        assert m.get_module_health("pub").last_error == "prev error"

    def test_report_updates_status(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "error")
        assert m.get_module_health("pub").status == "error"
        m.report_health("pub", "ok")
        assert m.get_module_health("pub").status == "ok"

    def test_report_updates_last_check_timestamp(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        assert m.get_module_health("pub").last_check == ""
        m.report_health("pub", "ok")
        assert m.get_module_health("pub").last_check != ""

    def test_report_last_check_is_iso_utc(self, tmp_path):
        from datetime import datetime, timezone

        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "ok")
        ts = m.get_module_health("pub").last_check
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_report_auto_registers_unknown_module(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("new_module", "ok")  # not registered beforehand
        assert "new_module" in m.check_all()

    def test_report_invalid_status_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        with pytest.raises(ValueError, match="Invalid status"):
            m.report_health("pub", "GOOD")

    def test_report_with_metadata(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "ok", metadata={"retries": 3})
        assert m.get_module_health("pub").metadata == {"retries": 3}

    def test_report_metadata_none_leaves_existing_metadata(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "ok", metadata={"k": "v"})
        m.report_health("pub", "ok", metadata=None)
        # metadata from first call should still be there
        assert m.get_module_health("pub").metadata == {"k": "v"}

    def test_report_metadata_too_many_keys_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        big = {str(i): i for i in range(_MAX_METADATA_KEYS + 1)}
        with pytest.raises(ValueError):
            m.report_health("pub", "ok", metadata=big)

    def test_report_all_valid_statuses(self, tmp_path):
        m = make_monitor(tmp_path)
        for s in _VALID_STATUSES:
            m.report_health(f"mod_{s}", s)
            assert m.get_module_health(f"mod_{s}").status == s

    def test_report_empty_error_msg_on_error(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.report_health("pub", "error")
        assert m.get_module_health("pub").last_error == ""

    def test_report_invalid_name_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        with pytest.raises(ValueError):
            m.report_health("", "ok")

    def test_mixed_ok_and_error_counts(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        for _ in range(3):
            m.report_health("pub", "ok")
        for _ in range(2):
            m.report_health("pub", "error")
        mod = m.get_module_health("pub")
        assert mod.success_count == 3
        assert mod.error_count == 2


# ===========================================================================
# PipelineHealthMonitor.get_module_health
# ===========================================================================


class TestGetModuleHealth:
    def test_get_registered_module(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        mod = m.get_module_health("pub")
        assert isinstance(mod, ModuleHealth)

    def test_get_unregistered_module_raises_key_error(self, tmp_path):
        m = make_monitor(tmp_path)
        with pytest.raises(KeyError):
            m.get_module_health("nonexistent")

    def test_get_returns_live_object(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        mod = m.get_module_health("pub")
        m.report_health("pub", "ok")
        # The returned reference reflects current state
        assert mod.status == "ok"


# ===========================================================================
# PipelineHealthMonitor.check_all
# ===========================================================================


class TestCheckAll:
    def test_check_all_empty_monitor(self, tmp_path):
        m = make_monitor(tmp_path)
        assert m.check_all() == {}

    def test_check_all_returns_all_modules(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("a")
        m.register_module("b")
        m.register_module("c")
        result = m.check_all()
        assert set(result.keys()) == {"a", "b", "c"}

    def test_check_all_returns_copy(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("a")
        snapshot = m.check_all()
        m.register_module("b")
        # snapshot should not contain "b"
        assert "b" not in snapshot

    def test_check_all_values_are_module_health(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("a")
        for v in m.check_all().values():
            assert isinstance(v, ModuleHealth)


# ===========================================================================
# PipelineHealthMonitor.get_summary
# ===========================================================================


class TestGetSummary:
    def test_summary_empty_monitor(self, tmp_path):
        m = make_monitor(tmp_path)
        s = m.get_summary()
        assert s == {"total": 0, "ok": 0, "degraded": 0, "error": 0, "unknown": 0}

    def test_summary_single_unknown(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        s = m.get_summary()
        assert s["total"] == 1
        assert s["unknown"] == 1

    def test_summary_mixed_statuses(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("a", "ok")
        m.report_health("b", "error")
        m.report_health("c", "degraded")
        m.report_health("d", "unknown")
        m.report_health("e", "ok")
        s = m.get_summary()
        assert s["total"] == 5
        assert s["ok"] == 2
        assert s["error"] == 1
        assert s["degraded"] == 1
        assert s["unknown"] == 1

    def test_summary_all_ok(self, tmp_path):
        m = make_monitor(tmp_path)
        for name in ["a", "b", "c"]:
            m.report_health(name, "ok")
        s = m.get_summary()
        assert s["ok"] == 3
        assert s["error"] == 0

    def test_summary_keys_present(self, tmp_path):
        m = make_monitor(tmp_path)
        s = m.get_summary()
        assert set(s.keys()) == {"total", "ok", "degraded", "error", "unknown"}


# ===========================================================================
# PipelineHealthMonitor.reset
# ===========================================================================


class TestReset:
    def test_reset_clears_all_modules(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("a")
        m.register_module("b")
        m.reset()
        assert m.check_all() == {}

    def test_reset_allows_re_registration(self, tmp_path):
        m = make_monitor(tmp_path)
        for i in range(_MAX_MODULES):
            m.register_module(f"m{i}")
        m.reset()
        m.register_module("fresh")  # should not raise
        assert "fresh" in m.check_all()

    def test_reset_on_empty_monitor_is_noop(self, tmp_path):
        m = make_monitor(tmp_path)
        m.reset()  # should not raise
        assert m.check_all() == {}

    def test_reset_summary_returns_zeros(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("a", "ok")
        m.reset()
        assert m.get_summary()["total"] == 0


# ===========================================================================
# PipelineHealthMonitor.save / load — round-trip
# ===========================================================================


class TestSaveLoad:
    def test_save_creates_file(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.save()
        assert os.path.exists(str(tmp_path / "pipeline_health.json"))

    def test_save_load_roundtrip(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok")
        m.report_health("scraper", "error", error_msg="timeout")
        m.save()

        m2 = make_monitor(tmp_path)
        m2.load()
        assert "pub" in m2.check_all()
        assert "scraper" in m2.check_all()
        assert m2.get_module_health("pub").status == "ok"
        assert m2.get_module_health("scraper").status == "error"
        assert m2.get_module_health("scraper").last_error == "timeout"

    def test_save_load_preserves_counts(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        for _ in range(4):
            m.report_health("pub", "ok")
        for _ in range(2):
            m.report_health("pub", "error")
        m.save()

        m2 = make_monitor(tmp_path)
        m2.load()
        mod = m2.get_module_health("pub")
        assert mod.success_count == 4
        assert mod.error_count == 2

    def test_save_load_empty_monitor(self, tmp_path):
        m = make_monitor(tmp_path)
        m.save()

        m2 = make_monitor(tmp_path)
        m2.load()
        assert m2.check_all() == {}

    def test_load_missing_file_is_noop(self, tmp_path):
        m = make_monitor(tmp_path)
        m.load()  # file does not exist — should not raise
        assert m.check_all() == {}

    def test_load_corrupt_file_is_noop(self, tmp_path):
        path = tmp_path / "pipeline_health.json"
        path.write_text("NOT_JSON{{{")
        m = make_monitor(tmp_path)
        m.load()  # should not raise
        assert m.check_all() == {}

    def test_load_non_dict_json_is_noop(self, tmp_path):
        path = tmp_path / "pipeline_health.json"
        path.write_text(json.dumps([1, 2, 3]))
        m = make_monitor(tmp_path)
        m.load()
        assert m.check_all() == {}

    def test_load_partially_corrupt_entry_is_skipped(self, tmp_path):
        path = tmp_path / "pipeline_health.json"
        data = {
            "good": {"module_name": "good", "status": "ok", "error_count": 0,
                     "success_count": 1, "last_check": "", "last_error": "", "metadata": {}},
            "bad": "not_a_dict",
        }
        path.write_text(json.dumps(data))
        m = make_monitor(tmp_path)
        m.load()
        # "good" should be loaded; "bad" should be skipped
        assert "good" in m.check_all()
        assert "bad" not in m.check_all()

    def test_save_is_valid_json(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok", metadata={"k": "v"})
        m.save()
        path = tmp_path / "pipeline_health.json"
        with open(str(path)) as f:
            data = json.load(f)
        assert "pub" in data

    def test_save_overwrites_previous_file(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok")
        m.save()

        m2 = make_monitor(tmp_path)
        m2.report_health("scraper", "error")
        m2.save()

        m3 = make_monitor(tmp_path)
        m3.load()
        # Only scraper should be present; pub was not in m2
        assert "scraper" in m3.check_all()
        assert "pub" not in m3.check_all()


# ===========================================================================
# Atomic write verification
# ===========================================================================


class TestAtomicWrite:
    def test_no_tmp_file_left_after_save(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        m.save()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_creates_file_in_correct_directory(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        persist = str(sub / "health.json")
        m = PipelineHealthMonitor(persist_path=persist)
        m.register_module("pub")
        m.save()
        assert os.path.exists(persist)

    def test_save_creates_parent_dir_if_missing(self, tmp_path):
        persist = str(tmp_path / "new_subdir" / "health.json")
        m = PipelineHealthMonitor(persist_path=persist)
        m.register_module("pub")
        m.save()
        assert os.path.exists(persist)


# ===========================================================================
# Edge cases and boundary conditions
# ===========================================================================


class TestEdgeCases:
    def test_monitor_default_path_is_in_mp_directory(self):
        # Default path should resolve to something ending in pipeline_health.json
        m = PipelineHealthMonitor.__new__(PipelineHealthMonitor)
        # Test via the class constant
        from pipeline_health import _DEFAULT_PERSIST_PATH
        assert _DEFAULT_PERSIST_PATH.endswith("pipeline_health.json")
        assert ".mp" in _DEFAULT_PERSIST_PATH

    def test_error_msg_at_exact_max_length_not_truncated(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("pub")
        exact_msg = "e" * _MAX_ERROR_LENGTH
        m.report_health("pub", "error", error_msg=exact_msg)
        assert len(m.get_module_health("pub").last_error) == _MAX_ERROR_LENGTH

    def test_module_name_with_unicode(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("модуль")
        assert "модуль" in m.check_all()

    def test_module_name_with_spaces(self, tmp_path):
        m = make_monitor(tmp_path)
        m.register_module("my module")
        assert "my module" in m.check_all()

    def test_metadata_with_nested_structure(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok", metadata={"nested": {"a": [1, 2, 3]}})
        assert m.get_module_health("pub").metadata["nested"] == {"a": [1, 2, 3]}

    def test_metadata_with_none_value(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok", metadata={"key": None})
        assert m.get_module_health("pub").metadata["key"] is None

    def test_save_and_load_with_unicode_metadata(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok", metadata={"msg": "héllo wörld"})
        m.save()

        m2 = make_monitor(tmp_path)
        m2.load()
        assert m2.get_module_health("pub").metadata["msg"] == "héllo wörld"

    def test_report_error_with_exact_max_length_error(self, tmp_path):
        m = make_monitor(tmp_path)
        msg = "x" * _MAX_ERROR_LENGTH
        m.report_health("pub", "error", error_msg=msg)
        assert m.get_module_health("pub").last_error == msg

    def test_check_all_after_reset_is_empty(self, tmp_path):
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok")
        m.reset()
        assert len(m.check_all()) == 0

    def test_get_summary_totals_match_check_all(self, tmp_path):
        m = make_monitor(tmp_path)
        for i in range(7):
            m.report_health(f"mod{i}", "ok")
        summary = m.get_summary()
        assert summary["total"] == len(m.check_all())

    def test_concurrent_save_does_not_corrupt(self, tmp_path):
        """Save twice in quick succession; second save should overwrite cleanly."""
        m = make_monitor(tmp_path)
        m.report_health("pub", "ok")
        m.save()
        m.report_health("pub", "error", error_msg="second")
        m.save()

        m2 = make_monitor(tmp_path)
        m2.load()
        assert m2.get_module_health("pub").status == "error"

    def test_metadata_exactly_max_keys(self, tmp_path):
        m = make_monitor(tmp_path)
        meta = {str(i): i for i in range(_MAX_METADATA_KEYS)}
        m.report_health("pub", "ok", metadata=meta)
        assert len(m.get_module_health("pub").metadata) == _MAX_METADATA_KEYS

    def test_metadata_one_over_max_keys_raises(self, tmp_path):
        m = make_monitor(tmp_path)
        meta = {str(i): i for i in range(_MAX_METADATA_KEYS + 1)}
        with pytest.raises(ValueError):
            m.report_health("pub", "ok", metadata=meta)


# ===========================================================================
# Auto-persist (H62)
# ===========================================================================


class TestAutoSaveInterval:
    """Test auto-save triggers after N report_health() calls."""

    def test_auto_save_triggers_after_n_reports(self, tmp_path):
        monitor = PipelineHealthMonitor(
            persist_path=str(tmp_path / "ph.json"),
            auto_save_interval=3,
        )
        persist_file = tmp_path / "ph.json"
        assert not persist_file.exists()

        monitor.report_health("mod1", "ok")
        monitor.report_health("mod1", "ok")
        assert not persist_file.exists()  # not yet

        monitor.report_health("mod1", "ok")
        assert persist_file.exists()  # triggered at 3

    def test_auto_save_resets_counter(self, tmp_path):
        monitor = PipelineHealthMonitor(
            persist_path=str(tmp_path / "ph.json"),
            auto_save_interval=2,
        )
        monitor.report_health("a", "ok")
        monitor.report_health("a", "ok")  # save triggers, counter resets
        assert monitor._report_count == 0

        monitor.report_health("a", "ok")
        assert monitor._report_count == 1  # counting again

    def test_auto_save_interval_default(self, tmp_path):
        monitor = PipelineHealthMonitor(persist_path=str(tmp_path / "ph.json"))
        assert monitor._auto_save_interval == 10

    def test_auto_save_interval_configurable(self, tmp_path):
        monitor = PipelineHealthMonitor(
            persist_path=str(tmp_path / "ph.json"),
            auto_save_interval=5,
        )
        assert monitor._auto_save_interval == 5

    def test_auto_save_persists_correct_data(self, tmp_path):
        persist_file = tmp_path / "ph.json"
        monitor = PipelineHealthMonitor(
            persist_path=str(persist_file),
            auto_save_interval=2,
        )
        monitor.report_health("pub", "ok")
        monitor.report_health("pub", "error", error_msg="timeout")
        # auto-save should have fired
        data = json.loads(persist_file.read_text())
        assert "pub" in data
        assert data["pub"]["status"] == "error"
        assert data["pub"]["error_count"] == 1

    def test_auto_save_failure_does_not_propagate(self, tmp_path):
        monitor = PipelineHealthMonitor(
            persist_path="/nonexistent/dir/health.json",
            auto_save_interval=1,
        )
        # Should not raise even though save will fail
        monitor.report_health("mod", "ok")
        # counter is NOT reset on failure — it stays at its post-increment value
        assert monitor._report_count == 1

    def test_reset_clears_report_count(self, tmp_path):
        monitor = PipelineHealthMonitor(
            persist_path=str(tmp_path / "ph.json"),
            auto_save_interval=100,
        )
        monitor.report_health("a", "ok")
        monitor.report_health("a", "ok")
        assert monitor._report_count == 2
        monitor.reset()
        assert monitor._report_count == 0


class TestAtexitRegistration:
    """Test atexit handler registration on first report_health() call."""

    def test_atexit_registered_on_first_report(self, tmp_path):
        monitor = PipelineHealthMonitor(
            persist_path=str(tmp_path / "ph.json"),
            auto_save_interval=100,
        )
        assert not monitor._atexit_registered
        monitor.report_health("mod", "ok")
        assert monitor._atexit_registered

    def test_atexit_not_re_registered(self, tmp_path):
        import atexit as atexit_mod
        monitor = PipelineHealthMonitor(
            persist_path=str(tmp_path / "ph.json"),
            auto_save_interval=100,
        )
        with patch.object(atexit_mod, "register") as mock_reg:
            monitor.report_health("a", "ok")
            monitor.report_health("a", "ok")
            monitor.report_health("a", "ok")
            assert mock_reg.call_count == 1

    def test_atexit_save_calls_save(self, tmp_path):
        monitor = PipelineHealthMonitor(
            persist_path=str(tmp_path / "ph.json"),
            auto_save_interval=100,
        )
        monitor.report_health("mod", "ok")
        persist_file = tmp_path / "ph.json"
        assert not persist_file.exists()  # interval not reached
        monitor._atexit_save()
        assert persist_file.exists()

    def test_atexit_save_failsoft(self):
        monitor = PipelineHealthMonitor(
            persist_path="/nonexistent/dir/health.json",
            auto_save_interval=100,
        )
        monitor.report_health("mod", "ok")
        # Should not raise
        monitor._atexit_save()

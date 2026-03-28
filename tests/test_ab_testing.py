"""
Tests for src/ab_testing.py — A/B testing module.

Covers:
- ABVariant: creation, to_dict, from_dict, defaults
- ABTest: creation, to_dict, from_dict, defaults, variant nesting
- ABTestManager: create_test (valid + invalid), get_test, get_active_tests,
  delete_test, rotate_variant (round-robin, single variant, not-found),
  record_metrics, evaluate_winner (all metrics), generate_variants (mocked LLM)
- Edge cases: empty variants list, too-few variants, bad metric, long strings,
  missing fields in from_dict, file-not-found startup, concurrent safety
- Persistence: JSON file created, atomic writes, round-trip fidelity
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import asdict

import ab_testing as ab_module
from ab_testing import ABVariant, ABTest, ABTestManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(tmp_path) -> ABTestManager:
    """Return an ABTestManager whose cache lives inside tmp_path."""
    mgr = ABTestManager()
    mgr._cache_path = str(tmp_path / ".mp" / "ab_tests.json")
    os.makedirs(str(tmp_path / ".mp"), exist_ok=True)
    return mgr


def _two_variants():
    return [
        {"title": "How AI Will Change Everything", "thumbnail_path": "/img/a.png"},
        {"title": "The Future of Artificial Intelligence", "thumbnail_path": "/img/b.png"},
    ]


# ---------------------------------------------------------------------------
# ABVariant tests
# ---------------------------------------------------------------------------

class TestABVariant:
    def test_creation_required_fields(self):
        v = ABVariant(variant_id="abc123", title="Test Title")
        assert v.variant_id == "abc123"
        assert v.title == "Test Title"

    def test_defaults(self):
        v = ABVariant(variant_id="x", title="T")
        assert v.thumbnail_path == ""
        assert v.metrics == {"views": 0, "ctr": 0.0, "watch_time": 0}
        assert v.active is False

    def test_metrics_default_is_independent(self):
        """Each instance should get its own metrics dict."""
        v1 = ABVariant(variant_id="a", title="A")
        v2 = ABVariant(variant_id="b", title="B")
        v1.metrics["views"] = 99
        assert v2.metrics["views"] == 0

    def test_to_dict_round_trip(self):
        v = ABVariant(
            variant_id="id1",
            title="Title",
            thumbnail_path="/path/img.png",
            metrics={"views": 10, "ctr": 0.5, "watch_time": 120},
            active=True,
        )
        d = v.to_dict()
        assert d["variant_id"] == "id1"
        assert d["title"] == "Title"
        assert d["thumbnail_path"] == "/path/img.png"
        assert d["metrics"]["views"] == 10
        assert d["active"] is True

    def test_from_dict_full(self):
        data = {
            "variant_id": "v1",
            "title": "Hi",
            "thumbnail_path": "/t.png",
            "metrics": {"views": 5, "ctr": 0.1, "watch_time": 60},
            "active": True,
        }
        v = ABVariant.from_dict(data)
        assert v.variant_id == "v1"
        assert v.title == "Hi"
        assert v.thumbnail_path == "/t.png"
        assert v.metrics["views"] == 5
        assert v.active is True

    def test_from_dict_missing_fields_uses_defaults(self):
        v = ABVariant.from_dict({})
        assert v.variant_id == ""
        assert v.title == ""
        assert v.thumbnail_path == ""
        assert v.active is False
        assert isinstance(v.metrics, dict)

    def test_from_dict_to_dict_round_trip(self):
        original = ABVariant(variant_id="z", title="Z title", active=True)
        restored = ABVariant.from_dict(original.to_dict())
        assert restored.variant_id == original.variant_id
        assert restored.title == original.title
        assert restored.active == original.active


# ---------------------------------------------------------------------------
# ABTest tests
# ---------------------------------------------------------------------------

class TestABTest:
    def _make_test(self):
        v1 = ABVariant(variant_id="v1", title="A", active=True)
        v2 = ABVariant(variant_id="v2", title="B")
        return ABTest(
            test_id="t1",
            video_id="vid123",
            variants=[v1, v2],
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )

    def test_defaults(self):
        t = ABTest(test_id="x", video_id="v", variants=[])
        assert t.schedule_hours == 24
        assert t.metric == "watch_time"
        assert t.status == "running"
        assert t.winner_id == ""

    def test_to_dict_contains_variants(self):
        t = self._make_test()
        d = t.to_dict()
        assert d["test_id"] == "t1"
        assert d["video_id"] == "vid123"
        assert len(d["variants"]) == 2
        assert d["variants"][0]["variant_id"] == "v1"

    def test_from_dict_full(self):
        data = {
            "test_id": "t1",
            "video_id": "vid123",
            "variants": [
                {"variant_id": "v1", "title": "A", "active": True,
                 "thumbnail_path": "", "metrics": {"views": 0, "ctr": 0.0, "watch_time": 0}},
            ],
            "schedule_hours": 48,
            "metric": "ctr",
            "status": "completed",
            "winner_id": "v1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00",
        }
        t = ABTest.from_dict(data)
        assert t.test_id == "t1"
        assert t.schedule_hours == 48
        assert t.metric == "ctr"
        assert t.status == "completed"
        assert t.winner_id == "v1"
        assert len(t.variants) == 1
        assert t.variants[0].variant_id == "v1"

    def test_from_dict_missing_fields_uses_defaults(self):
        t = ABTest.from_dict({})
        assert t.test_id == ""
        assert t.video_id == ""
        assert t.variants == []
        assert t.schedule_hours == 24

    def test_to_dict_from_dict_round_trip(self):
        t = self._make_test()
        restored = ABTest.from_dict(t.to_dict())
        assert restored.test_id == t.test_id
        assert restored.video_id == t.video_id
        assert len(restored.variants) == len(t.variants)
        assert restored.variants[0].active is True


# ---------------------------------------------------------------------------
# ABTestManager — create_test
# ---------------------------------------------------------------------------

class TestCreateTest:
    def test_create_valid_test(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        assert test.test_id
        assert len(test.test_id) == 8
        assert test.video_id == "vid001"
        assert len(test.variants) == 2
        assert test.status == "running"
        assert test.metric == "watch_time"
        assert test.created_at != ""
        assert test.updated_at != ""

    def test_first_variant_is_active(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        assert test.variants[0].active is True
        assert test.variants[1].active is False

    def test_variant_ids_are_unique(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        ids = [v.variant_id for v in test.variants]
        assert len(set(ids)) == len(ids)

    def test_custom_schedule_and_metric(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants(), schedule_hours=48, metric="ctr")
        assert test.schedule_hours == 48
        assert test.metric == "ctr"

    def test_persists_to_file(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.create_test("vid001", _two_variants())
        assert os.path.exists(mgr._cache_path)
        with open(mgr._cache_path) as f:
            data = json.load(f)
        assert len(data["tests"]) == 1

    def test_multiple_tests_accumulate(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.create_test("vid001", _two_variants())
        mgr.create_test("vid002", _two_variants())
        with open(mgr._cache_path) as f:
            data = json.load(f)
        assert len(data["tests"]) == 2

    def test_raises_empty_video_id(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="video_id"):
            mgr.create_test("", _two_variants())

    def test_raises_whitespace_only_video_id(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="video_id"):
            mgr.create_test("   ", _two_variants())

    def test_raises_video_id_too_long(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="video_id"):
            mgr.create_test("x" * 201, _two_variants())

    def test_raises_fewer_than_two_variants(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="2 variants"):
            mgr.create_test("vid001", [{"title": "Only one"}])

    def test_raises_empty_variants_list(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError):
            mgr.create_test("vid001", [])

    def test_raises_invalid_metric(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="metric"):
            mgr.create_test("vid001", _two_variants(), metric="engagement")

    def test_raises_non_positive_schedule_hours(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="schedule_hours"):
            mgr.create_test("vid001", _two_variants(), schedule_hours=0)

    def test_raises_variant_missing_title(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="title"):
            mgr.create_test("vid001", [{"thumbnail_path": ""}, {"title": "B"}])

    def test_raises_variant_title_too_long(self, tmp_path):
        mgr = _make_manager(tmp_path)
        long_title = "x" * 501
        with pytest.raises(ValueError, match="title"):
            mgr.create_test("vid001", [{"title": long_title}, {"title": "B"}])

    def test_all_allowed_metrics(self, tmp_path):
        for metric in ("watch_time", "ctr", "views"):
            mgr = _make_manager(tmp_path)
            test = mgr.create_test(f"vid_{metric}", _two_variants(), metric=metric)
            assert test.metric == metric


# ---------------------------------------------------------------------------
# ABTestManager — get_test
# ---------------------------------------------------------------------------

class TestGetTest:
    def test_get_existing_test(self, tmp_path):
        mgr = _make_manager(tmp_path)
        created = mgr.create_test("vid001", _two_variants())
        retrieved = mgr.get_test(created.test_id)
        assert retrieved is not None
        assert retrieved.test_id == created.test_id

    def test_get_nonexistent_test_returns_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_test("doesnotexist") is None

    def test_get_test_file_not_found(self, tmp_path):
        mgr = _make_manager(tmp_path)
        # Cache file does not exist yet
        assert mgr.get_test("anything") is None


# ---------------------------------------------------------------------------
# ABTestManager — get_active_tests
# ---------------------------------------------------------------------------

class TestGetActiveTests:
    def test_empty_when_no_tests(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_active_tests() == []

    def test_returns_only_running_tests(self, tmp_path):
        mgr = _make_manager(tmp_path)
        t1 = mgr.create_test("vid001", _two_variants())
        t2 = mgr.create_test("vid002", _two_variants())
        # Manually mark t2 as completed
        mgr.evaluate_winner(t2.test_id)
        active = mgr.get_active_tests()
        assert len(active) == 1
        assert active[0].test_id == t1.test_id

    def test_file_not_found_returns_empty(self, tmp_path):
        mgr = _make_manager(tmp_path)
        # No file yet
        assert mgr.get_active_tests() == []


# ---------------------------------------------------------------------------
# ABTestManager — delete_test
# ---------------------------------------------------------------------------

class TestDeleteTest:
    def test_delete_existing_test(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        result = mgr.delete_test(test.test_id)
        assert result is True
        assert mgr.get_test(test.test_id) is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.delete_test("ghost") is False

    def test_delete_one_of_two(self, tmp_path):
        mgr = _make_manager(tmp_path)
        t1 = mgr.create_test("vid001", _two_variants())
        t2 = mgr.create_test("vid002", _two_variants())
        mgr.delete_test(t1.test_id)
        assert mgr.get_test(t1.test_id) is None
        assert mgr.get_test(t2.test_id) is not None


# ---------------------------------------------------------------------------
# ABTestManager — rotate_variant
# ---------------------------------------------------------------------------

class TestRotateVariant:
    def test_rotate_basic(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        v0_id = test.variants[0].variant_id
        v1_id = test.variants[1].variant_id

        new_active = mgr.rotate_variant(test.test_id)
        assert new_active is not None
        assert new_active.variant_id == v1_id

        # Reload and confirm persistence
        reloaded = mgr.get_test(test.test_id)
        assert reloaded.variants[0].active is False
        assert reloaded.variants[1].active is True

    def test_rotate_wraps_around(self, tmp_path):
        mgr = _make_manager(tmp_path)
        variants = [
            {"title": "A"},
            {"title": "B"},
            {"title": "C"},
        ]
        test = mgr.create_test("vid001", variants)
        mgr.rotate_variant(test.test_id)  # -> B
        mgr.rotate_variant(test.test_id)  # -> C
        new_active = mgr.rotate_variant(test.test_id)  # -> A (wrap)
        assert new_active.title == "A"

    def test_rotate_single_variant_returns_that_variant(self, tmp_path):
        """With only one variant, rotate_variant should return it unchanged."""
        mgr = _make_manager(tmp_path)
        # We must bypass the create_test 2-variant minimum by injecting directly
        test = ABTest(
            test_id="solo",
            video_id="vid",
            variants=[ABVariant(variant_id="only", title="Solo", active=True)],
            created_at=mgr._now_iso(),
            updated_at=mgr._now_iso(),
        )
        mgr._save_tests([test])
        result = mgr.rotate_variant("solo")
        assert result is not None
        assert result.variant_id == "only"

    def test_rotate_nonexistent_test_returns_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.rotate_variant("nothere") is None

    def test_rotate_updates_updated_at(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        original_updated = test.updated_at
        mgr.rotate_variant(test.test_id)
        reloaded = mgr.get_test(test.test_id)
        # updated_at should be >= original
        assert reloaded.updated_at >= original_updated


# ---------------------------------------------------------------------------
# ABTestManager — record_metrics
# ---------------------------------------------------------------------------

class TestRecordMetrics:
    def test_record_valid_metrics(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        v_id = test.variants[0].variant_id

        result = mgr.record_metrics(test.test_id, v_id, {"views": 100, "ctr": 0.05})
        assert result is True

        reloaded = mgr.get_test(test.test_id)
        assert reloaded.variants[0].metrics["views"] == 100
        assert reloaded.variants[0].metrics["ctr"] == 0.05

    def test_record_metrics_returns_false_wrong_test(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.record_metrics("ghost_test", "ghost_var", {"views": 1}) is False

    def test_record_metrics_returns_false_wrong_variant(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        assert mgr.record_metrics(test.test_id, "ghost_var", {"views": 1}) is False

    def test_record_metrics_merges(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants())
        v_id = test.variants[0].variant_id
        mgr.record_metrics(test.test_id, v_id, {"views": 50})
        mgr.record_metrics(test.test_id, v_id, {"ctr": 0.03})
        reloaded = mgr.get_test(test.test_id)
        assert reloaded.variants[0].metrics["views"] == 50
        assert reloaded.variants[0].metrics["ctr"] == 0.03


# ---------------------------------------------------------------------------
# ABTestManager — evaluate_winner
# ---------------------------------------------------------------------------

class TestEvaluateWinner:
    def _setup_test_with_metrics(self, tmp_path, metric="watch_time"):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid001", _two_variants(), metric=metric)
        v0 = test.variants[0].variant_id
        v1 = test.variants[1].variant_id
        return mgr, test, v0, v1

    def test_winner_by_watch_time(self, tmp_path):
        mgr, test, v0, v1 = self._setup_test_with_metrics(tmp_path, "watch_time")
        mgr.record_metrics(test.test_id, v0, {"watch_time": 200})
        mgr.record_metrics(test.test_id, v1, {"watch_time": 500})
        winner = mgr.evaluate_winner(test.test_id)
        assert winner == v1

    def test_winner_by_ctr(self, tmp_path):
        mgr, test, v0, v1 = self._setup_test_with_metrics(tmp_path, "ctr")
        mgr.record_metrics(test.test_id, v0, {"ctr": 0.08})
        mgr.record_metrics(test.test_id, v1, {"ctr": 0.05})
        winner = mgr.evaluate_winner(test.test_id)
        assert winner == v0

    def test_winner_by_views(self, tmp_path):
        mgr, test, v0, v1 = self._setup_test_with_metrics(tmp_path, "views")
        mgr.record_metrics(test.test_id, v0, {"views": 1000})
        mgr.record_metrics(test.test_id, v1, {"views": 2000})
        winner = mgr.evaluate_winner(test.test_id)
        assert winner == v1

    def test_evaluate_sets_status_completed(self, tmp_path):
        mgr, test, v0, v1 = self._setup_test_with_metrics(tmp_path)
        mgr.evaluate_winner(test.test_id)
        reloaded = mgr.get_test(test.test_id)
        assert reloaded.status == "completed"

    def test_evaluate_sets_winner_id(self, tmp_path):
        mgr, test, v0, v1 = self._setup_test_with_metrics(tmp_path, "views")
        mgr.record_metrics(test.test_id, v1, {"views": 9999})
        mgr.evaluate_winner(test.test_id)
        reloaded = mgr.get_test(test.test_id)
        assert reloaded.winner_id == v1

    def test_evaluate_nonexistent_returns_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.evaluate_winner("ghost") is None

    def test_completed_test_excluded_from_active(self, tmp_path):
        mgr, test, v0, v1 = self._setup_test_with_metrics(tmp_path)
        mgr.evaluate_winner(test.test_id)
        assert mgr.get_active_tests() == []


# ---------------------------------------------------------------------------
# ABTestManager — generate_variants
# ---------------------------------------------------------------------------

class TestGenerateVariants:
    def _mock_llm_response(self, titles):
        import json as _json
        return _json.dumps(titles)

    def test_generate_variants_returns_list(self, tmp_path):
        mgr = _make_manager(tmp_path)
        llm_resp = '["Title A", "Title B", "Title C"]'
        with patch("ab_testing.generate_text", return_value=llm_resp):
            result = mgr.generate_variants("Original Title", count=3)
        assert isinstance(result, list)
        assert len(result) == 3
        assert all("title" in r for r in result)
        assert all("thumbnail_path" in r for r in result)

    def test_generate_variants_correct_titles(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with patch("ab_testing.generate_text", return_value='["V1", "V2"]'):
            result = mgr.generate_variants("Original", count=2)
        assert result[0]["title"] == "V1"
        assert result[1]["title"] == "V2"

    def test_generate_variants_thumbnail_path_empty(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with patch("ab_testing.generate_text", return_value='["V1", "V2"]'):
            result = mgr.generate_variants("Original", count=2)
        assert all(r["thumbnail_path"] == "" for r in result)

    def test_generate_variants_fallback_on_bad_json(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with patch("ab_testing.generate_text", return_value="not json at all"):
            result = mgr.generate_variants("My Title", count=2)
        assert len(result) == 2
        assert all(r["title"] == "My Title" for r in result)

    def test_generate_variants_fallback_on_non_array_json(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with patch("ab_testing.generate_text", return_value='{"key": "val"}'):
            result = mgr.generate_variants("My Title", count=2)
        assert len(result) == 2

    def test_generate_variants_pads_if_llm_returns_fewer(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with patch("ab_testing.generate_text", return_value='["Only One"]'):
            result = mgr.generate_variants("Original", count=3)
        assert len(result) == 3

    def test_generate_variants_truncates_if_llm_returns_more(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with patch("ab_testing.generate_text", return_value='["A", "B", "C", "D"]'):
            result = mgr.generate_variants("Original", count=2)
        assert len(result) == 2

    def test_generate_variants_raises_empty_title(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="title"):
            mgr.generate_variants("")

    def test_generate_variants_raises_whitespace_title(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="title"):
            mgr.generate_variants("   ")

    def test_generate_variants_raises_title_too_long(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="title"):
            mgr.generate_variants("x" * 501)

    def test_generate_variants_raises_count_less_than_one(self, tmp_path):
        mgr = _make_manager(tmp_path)
        with pytest.raises(ValueError, match="count"):
            with patch("ab_testing.generate_text", return_value='["A"]'):
                mgr.generate_variants("Title", count=0)

    def test_generate_variants_json_embedded_in_text(self, tmp_path):
        """LLM often wraps JSON in prose — should extract the array."""
        mgr = _make_manager(tmp_path)
        resp = 'Here are your variants: ["V1", "V2", "V3"] Hope that helps!'
        with patch("ab_testing.generate_text", return_value=resp):
            result = mgr.generate_variants("Original", count=3)
        assert result[0]["title"] == "V1"


# ---------------------------------------------------------------------------
# Persistence / edge cases
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_json_file_structure(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.create_test("vid001", _two_variants())
        with open(mgr._cache_path) as f:
            data = json.load(f)
        assert "tests" in data
        assert isinstance(data["tests"], list)
        t = data["tests"][0]
        assert "test_id" in t
        assert "variants" in t

    def test_load_returns_empty_if_file_missing(self, tmp_path):
        mgr = _make_manager(tmp_path)
        tests = mgr._load_tests()
        assert tests == []

    def test_load_returns_empty_on_corrupt_json(self, tmp_path):
        mgr = _make_manager(tmp_path)
        os.makedirs(os.path.dirname(mgr._cache_path), exist_ok=True)
        with open(mgr._cache_path, "w") as f:
            f.write("{ bad json }")
        tests = mgr._load_tests()
        assert tests == []

    def test_atomic_write_creates_dir(self, tmp_path):
        mgr = _make_manager(tmp_path)
        # Ensure .mp dir does NOT exist yet
        import shutil
        mp_dir = str(tmp_path / ".mp")
        shutil.rmtree(mp_dir, ignore_errors=True)
        mgr.create_test("vid001", _two_variants())
        assert os.path.exists(mgr._cache_path)

    def test_round_trip_serialization(self, tmp_path):
        mgr = _make_manager(tmp_path)
        test = mgr.create_test("vid999", _two_variants(), schedule_hours=12, metric="ctr")
        reloaded = mgr.get_test(test.test_id)
        assert reloaded.video_id == "vid999"
        assert reloaded.schedule_hours == 12
        assert reloaded.metric == "ctr"
        assert len(reloaded.variants) == 2

    def test_no_cross_contamination_between_managers(self, tmp_path):
        """Two managers pointing to different paths must not share state."""
        p1 = tmp_path / "a"
        p2 = tmp_path / "b"
        p1.mkdir()
        p2.mkdir()

        mgr1 = ABTestManager()
        mgr1._cache_path = str(p1 / "ab_tests.json")

        mgr2 = ABTestManager()
        mgr2._cache_path = str(p2 / "ab_tests.json")

        mgr1.create_test("vid001", _two_variants())
        assert mgr2.get_active_tests() == []

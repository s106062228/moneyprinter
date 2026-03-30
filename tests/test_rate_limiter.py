"""
Tests for src/rate_limiter.py — token-bucket rate limiter.

Covers RateLimiter and RateLimiterRegistry, including init validation,
try_acquire, acquire, wait, token refill, per-key isolation, thread
safety, and registry behaviour.
"""

import os
import sys
import time
import json
import threading
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — mirrors the pattern used throughout the test suite
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config as config_module  # noqa: E402 — must come after sys.path insert
import rate_limiter as rl_module  # noqa: E402
from rate_limiter import (  # noqa: E402
    RateLimiter,
    RateLimiterRegistry,
    registry,
    _MAX_RATE,
    _MAX_BURST,
    _MIN_RATE,
    _DEFAULT_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_config_cache():
    """Reset the config module cache before/after every test."""
    config_module._config_cache = None
    yield
    config_module._config_cache = None


@pytest.fixture
def fresh_registry():
    """Return a brand-new RateLimiterRegistry for each test."""
    return RateLimiterRegistry()


@pytest.fixture
def limiter():
    """A RateLimiter with rate=10/s, burst=5 — plenty of head room."""
    return RateLimiter(rate=10.0, burst=5)


# ---------------------------------------------------------------------------
# Helper: freeze time.monotonic in the rate_limiter module
# ---------------------------------------------------------------------------

class FakeClock:
    """Controllable monotonic clock."""

    def __init__(self, start: float = 0.0):
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


# ---------------------------------------------------------------------------
# TestRateLimiterInit
# ---------------------------------------------------------------------------

class TestRateLimiterInit:
    """RateLimiter construction — valid and invalid arguments."""

    def test_valid_rate_and_burst(self):
        rl = RateLimiter(rate=1.0, burst=5)
        assert rl.rate == 1.0
        assert rl.burst == 5

    def test_default_name_assigned(self):
        rl = RateLimiter(rate=1.0)
        assert rl.name == "rate_limiter"

    def test_custom_name_preserved(self):
        rl = RateLimiter(rate=1.0, name="my_limiter")
        assert rl.name == "my_limiter"

    def test_empty_name_uses_default(self):
        rl = RateLimiter(rate=1.0, name="")
        assert rl.name == "rate_limiter"

    def test_default_burst_is_one(self):
        rl = RateLimiter(rate=5.0)
        assert rl.burst == 1

    def test_min_rate_boundary_accepted(self):
        rl = RateLimiter(rate=_MIN_RATE)
        assert rl.rate == _MIN_RATE

    def test_max_rate_boundary_accepted(self):
        rl = RateLimiter(rate=_MAX_RATE)
        assert rl.rate == _MAX_RATE

    def test_max_burst_boundary_accepted(self):
        rl = RateLimiter(rate=1.0, burst=_MAX_BURST)
        assert rl.burst == _MAX_BURST

    # --- invalid rate ---

    def test_rate_zero_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=0)

    def test_negative_rate_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=-1.0)

    def test_rate_exceeds_max_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=_MAX_RATE + 0.001)

    def test_rate_below_min_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=_MIN_RATE / 2)

    # --- invalid burst ---

    def test_burst_zero_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=1.0, burst=0)

    def test_burst_negative_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=1.0, burst=-1)

    def test_burst_exceeds_max_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=1.0, burst=_MAX_BURST + 1)


# ---------------------------------------------------------------------------
# TestTryAcquire
# ---------------------------------------------------------------------------

class TestTryAcquire:
    """Non-blocking token acquisition."""

    def test_succeeds_when_tokens_available(self, limiter):
        assert limiter.try_acquire() is True

    def test_fails_when_bucket_empty(self):
        rl = RateLimiter(rate=1.0, burst=1)
        assert rl.try_acquire() is True   # consumes the single token
        assert rl.try_acquire() is False  # bucket empty

    def test_returns_bool(self, limiter):
        result = limiter.try_acquire()
        assert isinstance(result, bool)

    def test_burst_all_tokens_immediately(self):
        burst = 5
        rl = RateLimiter(rate=1.0, burst=burst)
        successes = sum(rl.try_acquire() for _ in range(burst))
        assert successes == burst

    def test_next_after_burst_fails(self):
        burst = 3
        rl = RateLimiter(rate=1.0, burst=burst)
        for _ in range(burst):
            rl.try_acquire()
        assert rl.try_acquire() is False

    def test_default_key_used(self, limiter):
        # Calling with and without the key=default should share the same bucket
        limiter.try_acquire()
        limiter.try_acquire()
        # Verify by counting remaining
        remaining = limiter.tokens_available()
        assert remaining < limiter.burst

    def test_custom_key_independent(self, limiter):
        limiter.try_acquire(key="a")
        # Key "b" should still be full
        assert limiter.try_acquire(key="b") is True


# ---------------------------------------------------------------------------
# TestAcquireBlocking
# ---------------------------------------------------------------------------

class TestAcquireBlocking:
    """Blocking acquire() behaviour."""

    def test_timeout_zero_behaves_like_try_acquire_success(self):
        rl = RateLimiter(rate=10.0, burst=2)
        assert rl.acquire(timeout=0) is True

    def test_timeout_zero_behaves_like_try_acquire_failure(self):
        rl = RateLimiter(rate=1.0, burst=1)
        rl.try_acquire()               # drain the bucket
        assert rl.acquire(timeout=0) is False

    def test_acquire_blocks_then_succeeds(self):
        """Token refill during sleep allows acquire to succeed."""
        rl = RateLimiter(rate=50.0, burst=1)  # fast refill
        rl.try_acquire()               # drain
        result = rl.acquire(timeout=1.0)
        assert result is True

    def test_acquire_timeout_exceeded_returns_false(self):
        """With a very slow refill rate, acquire should time out."""
        rl = RateLimiter(rate=_MIN_RATE, burst=1)  # extremely slow
        rl.try_acquire()               # drain
        start = time.monotonic()
        result = rl.acquire(timeout=0.05)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed >= 0.04  # waited at least most of the timeout

    def test_acquire_none_timeout_uses_default(self):
        """None timeout should not immediately time out on a full bucket."""
        rl = RateLimiter(rate=10.0, burst=1)
        assert rl.acquire(timeout=None) is True

    def test_acquire_returns_true_on_success(self, limiter):
        assert limiter.acquire(timeout=1.0) is True

    def test_acquire_returns_false_on_timeout(self):
        rl = RateLimiter(rate=_MIN_RATE, burst=1)
        rl.try_acquire()
        assert rl.acquire(timeout=0.02) is False


# ---------------------------------------------------------------------------
# TestWait
# ---------------------------------------------------------------------------

class TestWait:
    """wait() — like acquire() but raises TimeoutError on failure."""

    def test_wait_succeeds_when_tokens_available(self, limiter):
        limiter.wait()  # should not raise

    def test_wait_succeeds_after_refill(self):
        rl = RateLimiter(rate=50.0, burst=1)
        rl.try_acquire()
        rl.wait(timeout=1.0)  # should not raise

    def test_wait_raises_timeout_error(self):
        rl = RateLimiter(rate=_MIN_RATE, burst=1)
        rl.try_acquire()
        with pytest.raises(TimeoutError):
            rl.wait(timeout=0.02)

    def test_wait_timeout_error_message_contains_name(self):
        rl = RateLimiter(rate=_MIN_RATE, burst=1, name="my_api")
        rl.try_acquire()
        with pytest.raises(TimeoutError, match="my_api"):
            rl.wait(timeout=0.02)

    def test_wait_timeout_error_contains_key(self):
        rl = RateLimiter(rate=_MIN_RATE, burst=1)
        rl.try_acquire(key="special_key")  # drain the specific key
        with pytest.raises(TimeoutError, match="special_key"):
            rl.wait(key="special_key", timeout=0.02)


# ---------------------------------------------------------------------------
# TestTokenRefill
# ---------------------------------------------------------------------------

class TestTokenRefill:
    """Deterministic refill tests using a mocked clock."""

    def test_tokens_refill_over_time(self):
        clock = FakeClock(start=100.0)
        with patch.object(rl_module.time, "monotonic", clock):
            rl = RateLimiter(rate=2.0, burst=4)
            # Drain all tokens
            for _ in range(4):
                rl.try_acquire()
            assert rl.tokens_available() < 1.0

            # Advance 1 second: should gain 2 tokens
            clock.advance(1.0)
            assert rl.tokens_available() == pytest.approx(2.0, abs=0.05)

    def test_tokens_capped_at_burst(self):
        clock = FakeClock(start=0.0)
        with patch.object(rl_module.time, "monotonic", clock):
            rl = RateLimiter(rate=10.0, burst=3)
            # Drain all tokens
            for _ in range(3):
                rl.try_acquire()
            # Advance a very long time
            clock.advance(1000.0)
            assert rl.tokens_available() == pytest.approx(3.0, abs=0.01)

    def test_refill_after_partial_drain(self):
        clock = FakeClock(start=0.0)
        with patch.object(rl_module.time, "monotonic", clock):
            rl = RateLimiter(rate=1.0, burst=5)
            rl.try_acquire()    # consume 1, leaving 4
            clock.advance(0.5)  # gain 0.5
            tokens = rl.tokens_available()
            assert tokens == pytest.approx(4.5, abs=0.05)

    def test_get_wait_time_zero_when_tokens_available(self, limiter):
        assert limiter.get_wait_time() == pytest.approx(0.0)

    def test_get_wait_time_positive_when_empty(self):
        clock = FakeClock(start=0.0)
        with patch.object(rl_module.time, "monotonic", clock):
            rl = RateLimiter(rate=2.0, burst=1)
            rl.try_acquire()  # drain
            wait = rl.get_wait_time()
            assert wait > 0.0
            # With rate=2/s and 1 token deficit, wait should be ~0.5 s
            assert wait == pytest.approx(0.5, abs=0.05)

    def test_get_wait_time_scales_with_rate(self):
        clock = FakeClock(start=0.0)
        with patch.object(rl_module.time, "monotonic", clock):
            rl = RateLimiter(rate=4.0, burst=1)
            rl.try_acquire()
            # deficit=1, rate=4 → wait=0.25 s
            assert rl.get_wait_time() == pytest.approx(0.25, abs=0.01)


# ---------------------------------------------------------------------------
# TestTokensAvailable
# ---------------------------------------------------------------------------

class TestTokensAvailable:
    """tokens_available() returns current post-refill token count."""

    def test_full_bucket_returns_burst(self, limiter):
        assert limiter.tokens_available() == pytest.approx(float(limiter.burst))

    def test_decreases_after_acquire(self, limiter):
        before = limiter.tokens_available()
        limiter.try_acquire()
        after = limiter.tokens_available()
        assert after == pytest.approx(before - 1.0, abs=0.05)

    def test_returns_float(self, limiter):
        result = limiter.tokens_available()
        assert isinstance(result, float)

    def test_creates_bucket_for_new_key(self, limiter):
        tokens = limiter.tokens_available(key="brand_new")
        assert tokens == pytest.approx(float(limiter.burst))


# ---------------------------------------------------------------------------
# TestPerKeyIsolation
# ---------------------------------------------------------------------------

class TestPerKeyIsolation:
    """Different keys have independent token buckets."""

    def test_different_keys_are_independent(self):
        rl = RateLimiter(rate=1.0, burst=1)
        assert rl.try_acquire(key="a") is True
        assert rl.try_acquire(key="b") is True  # "b" is untouched

    def test_draining_one_key_does_not_affect_other(self):
        rl = RateLimiter(rate=1.0, burst=2)
        rl.try_acquire(key="x")
        rl.try_acquire(key="x")
        # key "y" should still be full
        assert rl.try_acquire(key="y") is True

    def test_separate_wait_times_per_key(self):
        clock = FakeClock(start=0.0)
        with patch.object(rl_module.time, "monotonic", clock):
            rl = RateLimiter(rate=1.0, burst=1)
            rl.try_acquire(key="a")  # drain "a"
            assert rl.get_wait_time(key="a") > 0.0
            assert rl.get_wait_time(key="b") == pytest.approx(0.0)

    def test_reset_single_key_does_not_affect_others(self):
        rl = RateLimiter(rate=1.0, burst=1)
        rl.try_acquire(key="a")
        rl.try_acquire(key="b")
        rl.reset(key="a")
        assert rl.tokens_available(key="a") == pytest.approx(1.0)
        # "b" remains empty (less than 1 token)
        assert rl.tokens_available(key="b") < 1.0


# ---------------------------------------------------------------------------
# TestReset
# ---------------------------------------------------------------------------

class TestReset:
    """reset() — single key and all keys."""

    def test_reset_single_key_refills_bucket(self, limiter):
        limiter.try_acquire()
        limiter.try_acquire()
        limiter.reset(key="default")
        assert limiter.tokens_available() == pytest.approx(float(limiter.burst))

    def test_reset_all_keys_clears_all(self, limiter):
        limiter.try_acquire(key="a")
        limiter.try_acquire(key="b")
        limiter.reset()  # key=None → reset all
        assert limiter.tokens_available(key="a") == pytest.approx(float(limiter.burst))
        assert limiter.tokens_available(key="b") == pytest.approx(float(limiter.burst))

    def test_reset_unknown_key_does_not_raise(self, limiter):
        limiter.reset(key="nonexistent_key")  # must not raise

    def test_reset_none_clears_internal_buckets_dict(self, limiter):
        limiter.try_acquire(key="x")
        limiter.reset()
        assert len(limiter._buckets) == 0

    def test_reset_single_key_only_removes_that_bucket(self, limiter):
        limiter.try_acquire(key="keep")
        limiter.try_acquire(key="remove")
        limiter.reset(key="remove")
        # "keep" bucket should still exist
        assert "keep" in limiter._buckets
        # "remove" bucket should be gone (or recreated fresh on next access)
        assert "remove" not in limiter._buckets


# ---------------------------------------------------------------------------
# TestThreadSafety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    """Concurrent access from multiple threads must not corrupt state."""

    def test_concurrent_try_acquire_no_over_consumption(self):
        burst = 10
        rl = RateLimiter(rate=1.0, burst=burst)
        results = []
        lock = threading.Lock()

        def worker():
            ok = rl.try_acquire()
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r)
        # Should not have consumed more tokens than the burst size
        assert successes <= burst

    def test_concurrent_acquire_on_different_keys(self):
        rl = RateLimiter(rate=100.0, burst=5)
        errors = []

        def worker(key):
            try:
                for _ in range(3):
                    rl.try_acquire(key=key)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(f"key_{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_concurrent_reset_and_acquire(self):
        """Reset and acquire racing together must not raise."""
        rl = RateLimiter(rate=100.0, burst=5)
        errors = []

        def acquirer():
            try:
                for _ in range(20):
                    rl.try_acquire()
            except Exception as exc:
                errors.append(exc)

        def resetter():
            try:
                for _ in range(10):
                    rl.reset()
            except Exception as exc:
                errors.append(exc)

        threads = (
            [threading.Thread(target=acquirer) for _ in range(4)]
            + [threading.Thread(target=resetter) for _ in range(2)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# TestRateLimiterRegistry
# ---------------------------------------------------------------------------

class TestRateLimiterRegistry:
    """RateLimiterRegistry — creation, caching, and management."""

    def test_get_limiter_creates_new(self, fresh_registry):
        rl = fresh_registry.get_limiter("llm", rate=5.0, burst=10)
        assert isinstance(rl, RateLimiter)
        assert rl.rate == 5.0
        assert rl.burst == 10

    def test_get_limiter_returns_same_instance(self, fresh_registry):
        first = fresh_registry.get_limiter("api", rate=1.0, burst=2)
        second = fresh_registry.get_limiter("api")  # no rate needed
        assert first is second

    def test_get_limiter_no_rate_raises(self, fresh_registry):
        with pytest.raises(ValueError, match="provide 'rate'"):
            fresh_registry.get_limiter("missing")

    def test_get_limiter_existing_ignores_new_rate(self, fresh_registry):
        rl1 = fresh_registry.get_limiter("x", rate=1.0)
        rl2 = fresh_registry.get_limiter("x", rate=999.0)  # rate ignored
        assert rl1 is rl2
        assert rl2.rate == 1.0

    def test_get_limiter_default_burst_is_one(self, fresh_registry):
        rl = fresh_registry.get_limiter("y", rate=2.0)
        assert rl.burst == 1

    def test_list_limiters_empty(self, fresh_registry):
        assert fresh_registry.list_limiters() == []

    def test_list_limiters_sorted(self, fresh_registry):
        fresh_registry.get_limiter("zebra", rate=1.0)
        fresh_registry.get_limiter("alpha", rate=1.0)
        fresh_registry.get_limiter("middle", rate=1.0)
        assert fresh_registry.list_limiters() == ["alpha", "middle", "zebra"]

    def test_reset_all_resets_all_limiters(self, fresh_registry):
        rl_a = fresh_registry.get_limiter("a", rate=1.0, burst=3)
        rl_b = fresh_registry.get_limiter("b", rate=1.0, burst=2)
        for _ in range(3):
            rl_a.try_acquire()
        for _ in range(2):
            rl_b.try_acquire()
        fresh_registry.reset_all()
        assert rl_a.tokens_available() == pytest.approx(3.0)
        assert rl_b.tokens_available() == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# TestRegistryConfigureFromConfig
# ---------------------------------------------------------------------------

class TestRegistryConfigureFromConfig:
    """configure_from_config() loads limiters from config.json."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Patch config._config_path to a temp file and reset the cache."""
        cfg = {
            "rate_limits": {
                "publisher": {"rate": 1.0, "burst": 3},
                "llm": {"rate": 5.0, "burst": 10},
            }
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))
        original = config_module._config_path
        config_module._config_path = str(p)
        config_module._config_cache = None
        yield cfg
        config_module._config_path = original
        config_module._config_cache = None

    def test_loads_limiters_from_config(self, fresh_registry, mock_config):
        fresh_registry.configure_from_config()
        names = fresh_registry.list_limiters()
        assert "publisher" in names
        assert "llm" in names

    def test_loaded_limiter_has_correct_rate(self, fresh_registry, mock_config):
        fresh_registry.configure_from_config()
        rl = fresh_registry.get_limiter("llm")
        assert rl.rate == pytest.approx(5.0)
        assert rl.burst == 10

    def test_configure_skips_existing_limiter(self, fresh_registry, mock_config):
        existing = fresh_registry.get_limiter("llm", rate=99.0, burst=1)
        fresh_registry.configure_from_config()
        rl = fresh_registry.get_limiter("llm")
        assert rl is existing  # not replaced
        assert rl.rate == pytest.approx(99.0)

    def test_missing_rate_limits_key_handled(self, fresh_registry, tmp_path):
        """config.json with no 'rate_limits' key — no error, no limiters added."""
        cfg = {"verbose": True}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))
        original = config_module._config_path
        config_module._config_path = str(p)
        config_module._config_cache = None
        try:
            fresh_registry.configure_from_config()
        finally:
            config_module._config_path = original
            config_module._config_cache = None
        assert fresh_registry.list_limiters() == []

    def test_malformed_entry_skipped(self, fresh_registry, tmp_path):
        """Entries with no 'rate' key are skipped without raising."""
        cfg = {
            "rate_limits": {
                "bad_entry": {"burst": 5},         # missing 'rate'
                "good_entry": {"rate": 2.0, "burst": 2},
            }
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))
        original = config_module._config_path
        config_module._config_path = str(p)
        config_module._config_cache = None
        try:
            fresh_registry.configure_from_config()
        finally:
            config_module._config_path = original
            config_module._config_cache = None
        names = fresh_registry.list_limiters()
        assert "bad_entry" not in names
        assert "good_entry" in names

    def test_non_dict_rate_limits_skipped(self, fresh_registry, tmp_path):
        """'rate_limits' being a list (not dict) is handled gracefully."""
        cfg = {"rate_limits": ["not", "a", "dict"]}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))
        original = config_module._config_path
        config_module._config_path = str(p)
        config_module._config_cache = None
        try:
            fresh_registry.configure_from_config()
        finally:
            config_module._config_path = original
            config_module._config_cache = None
        assert fresh_registry.list_limiters() == []

    def test_non_dict_spec_skipped(self, fresh_registry, tmp_path):
        """Individual entries that are not dicts are skipped."""
        cfg = {
            "rate_limits": {
                "string_spec": "invalid",
                "valid": {"rate": 1.0, "burst": 1},
            }
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))
        original = config_module._config_path
        config_module._config_path = str(p)
        config_module._config_cache = None
        try:
            fresh_registry.configure_from_config()
        finally:
            config_module._config_path = original
            config_module._config_cache = None
        names = fresh_registry.list_limiters()
        assert "string_spec" not in names
        assert "valid" in names


# ---------------------------------------------------------------------------
# TestModuleLevelRegistry
# ---------------------------------------------------------------------------

class TestModuleLevelRegistry:
    """The module-level singleton 'registry' is importable and functional."""

    def test_registry_is_importable(self):
        assert registry is not None

    def test_registry_is_rate_limiter_registry(self):
        assert isinstance(registry, RateLimiterRegistry)

    def test_registry_can_create_limiter(self):
        """Create a limiter in the module-level registry without errors."""
        # Use a unique name to avoid collisions with other tests
        name = "_test_module_level_registry_limiter_"
        rl = registry.get_limiter(name, rate=1.0, burst=1)
        assert isinstance(rl, RateLimiter)

    def test_registry_get_limiter_cached(self):
        name = "_test_module_level_cache_"
        rl1 = registry.get_limiter(name, rate=2.0, burst=2)
        rl2 = registry.get_limiter(name)
        assert rl1 is rl2

    def test_registry_list_limiters_returns_list(self):
        result = registry.list_limiters()
        assert isinstance(result, list)

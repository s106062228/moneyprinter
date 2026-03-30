"""
Token-bucket rate limiter for MoneyPrinter.

Provides per-key, thread-safe rate limiting using the token-bucket algorithm.
Limiters can be configured programmatically or loaded from config.json under
the "rate_limits" key:

    "rate_limits": {
        "publisher": {"rate": 1.0, "burst": 3},
        "webhook":   {"rate": 1.0, "burst": 1},
        "llm":       {"rate": 5.0, "burst": 10},
        "api":       {"rate": 10.0, "burst": 20}
    }

Usage:
    from rate_limiter import registry

    registry.configure_from_config()

    # Block until a token is available (up to 30 s by default)
    registry.get_limiter("llm").wait()

    # Non-blocking check
    if registry.get_limiter("api").try_acquire():
        call_api()
"""

import time
import threading
from typing import Optional

from config import _get
from mp_logger import get_logger

logger = get_logger("rate_limiter")

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MAX_RATE: float = 1000.0   # tokens per second (upper bound)
_MIN_RATE: float = 0.001    # tokens per second (lower bound — 1 per 1000 s)
_MAX_BURST: int = 100       # maximum bucket size
_DEFAULT_TIMEOUT: float = 30.0


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Thread-safe, token-bucket rate limiter with per-key support.

    Each unique key gets its own independent bucket so that, for example,
    different accounts or endpoints can be throttled separately while sharing
    a single RateLimiter instance.

    Args:
        rate:  Tokens added to the bucket per second.
        burst: Maximum number of tokens the bucket can hold (== max burst).
        name:  Optional human-readable label used in log messages.

    Raises:
        ValueError: If rate or burst are outside the allowed ranges.
    """

    def __init__(self, rate: float, burst: int = 1, name: str = "") -> None:
        if not (_MIN_RATE <= rate <= _MAX_RATE):
            raise ValueError(
                f"rate must be between {_MIN_RATE} and {_MAX_RATE}, got {rate}"
            )
        if not (1 <= burst <= _MAX_BURST):
            raise ValueError(
                f"burst must be between 1 and {_MAX_BURST}, got {burst}"
            )

        self.rate = rate
        self.burst = burst
        self.name = name or "rate_limiter"

        # Per-key state: {key: {"tokens": float, "last_refill": float}}
        self._buckets: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_bucket(self, key: str) -> dict:
        """Return the bucket for *key*, creating it if it does not exist."""
        if key not in self._buckets:
            self._buckets[key] = {
                "tokens": float(self.burst),
                "last_refill": time.monotonic(),
            }
        return self._buckets[key]

    def _refill(self, bucket: dict) -> None:
        """Add tokens earned since the last refill, capped at burst."""
        now = time.monotonic()
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(
            float(self.burst),
            bucket["tokens"] + elapsed * self.rate,
        )
        bucket["last_refill"] = now

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def try_acquire(self, key: str = "default") -> bool:
        """
        Non-blocking acquire.

        Returns:
            True if a token was consumed, False if the bucket is empty.
        """
        with self._lock:
            bucket = self._get_bucket(key)
            self._refill(bucket)
            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                logger.debug("[%s] token acquired (key=%s)", self.name, key)
                return True
            logger.debug(
                "[%s] no token available (key=%s, tokens=%.3f)",
                self.name, key, bucket["tokens"],
            )
            return False

    def get_wait_time(self, key: str = "default") -> float:
        """
        Seconds until at least one token will be available.

        Returns:
            0.0 if a token is available right now, otherwise the wait in seconds.
        """
        with self._lock:
            bucket = self._get_bucket(key)
            self._refill(bucket)
            if bucket["tokens"] >= 1.0:
                return 0.0
            deficit = 1.0 - bucket["tokens"]
            return deficit / self.rate

    def tokens_available(self, key: str = "default") -> float:
        """Current (post-refill) token count for *key*."""
        with self._lock:
            bucket = self._get_bucket(key)
            self._refill(bucket)
            return bucket["tokens"]

    def acquire(self, key: str = "default", timeout: Optional[float] = None) -> bool:
        """
        Blocking acquire.

        Sleeps in a tight loop until a token is available or *timeout* expires.
        Passing timeout=0 is equivalent to try_acquire().

        Args:
            key:     Per-key bucket identifier.
            timeout: Maximum seconds to wait. None uses _DEFAULT_TIMEOUT.

        Returns:
            True if a token was acquired, False if the timeout was reached.
        """
        if timeout is None:
            timeout = _DEFAULT_TIMEOUT

        # Non-blocking fast path
        if timeout == 0:
            return self.try_acquire(key)

        deadline = time.monotonic() + timeout

        while True:
            if self.try_acquire(key):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "[%s] acquire timed out after %.1f s (key=%s)",
                    self.name, timeout, key,
                )
                return False
            # Sleep for at most the wait time, but no longer than what remains
            sleep_for = min(self.get_wait_time(key), remaining, 0.05)
            time.sleep(max(sleep_for, 0.001))

    def wait(self, key: str = "default", timeout: Optional[float] = None) -> None:
        """
        Blocking wait — identical to acquire() but raises TimeoutError on failure.

        Args:
            key:     Per-key bucket identifier.
            timeout: Maximum seconds to wait. None uses _DEFAULT_TIMEOUT.

        Raises:
            TimeoutError: If the token could not be acquired within *timeout*.
        """
        if not self.acquire(key=key, timeout=timeout):
            effective = timeout if timeout is not None else _DEFAULT_TIMEOUT
            raise TimeoutError(
                f"[{self.name}] Rate limit wait exceeded {effective:.1f} s for key '{key}'"
            )

    def reset(self, key: Optional[str] = None) -> None:
        """
        Reset token buckets.

        Args:
            key: Key to reset. If None, all keys are reset.
        """
        with self._lock:
            if key is None:
                self._buckets.clear()
                logger.debug("[%s] all buckets reset", self.name)
            elif key in self._buckets:
                del self._buckets[key]
                logger.debug("[%s] bucket reset (key=%s)", self.name, key)


# ---------------------------------------------------------------------------
# RateLimiterRegistry
# ---------------------------------------------------------------------------

class RateLimiterRegistry:
    """
    Global registry for named RateLimiter instances.

    Limiters are created on first access and optionally seeded from
    config.json.  Thread-safe.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    def get_limiter(
        self,
        name: str,
        rate: Optional[float] = None,
        burst: Optional[int] = None,
    ) -> RateLimiter:
        """
        Return an existing limiter by name, or create one with the supplied
        rate / burst if it does not exist yet.

        If the limiter already exists, *rate* and *burst* are ignored so that
        callers cannot accidentally reconfigure a shared limiter.

        Args:
            name:  Unique identifier for the limiter.
            rate:  Tokens per second (required when creating a new limiter).
            burst: Maximum bucket size (defaults to 1 when creating).

        Returns:
            The named RateLimiter.

        Raises:
            ValueError: If the limiter is new and *rate* is not supplied.
        """
        with self._lock:
            if name in self._limiters:
                return self._limiters[name]

            if rate is None:
                raise ValueError(
                    f"Limiter '{name}' does not exist; provide 'rate' to create it."
                )
            effective_burst = burst if burst is not None else 1
            limiter = RateLimiter(rate=rate, burst=effective_burst, name=name)
            self._limiters[name] = limiter
            logger.info(
                "[registry] created limiter '%s' (rate=%.3f/s, burst=%d)",
                name, rate, effective_burst,
            )
            return limiter

    def configure_from_config(self) -> None:
        """
        Load limiter definitions from config.json "rate_limits" key.

        Existing limiters with the same name are left untouched (to avoid
        disrupting in-flight requests).

        Expected config shape::

            "rate_limits": {
                "publisher": {"rate": 1.0, "burst": 3},
                "llm":       {"rate": 5.0, "burst": 10}
            }
        """
        rate_limits: dict = _get("rate_limits", {})
        if not isinstance(rate_limits, dict):
            logger.warning("[registry] 'rate_limits' in config is not a dict, skipping")
            return

        for name, spec in rate_limits.items():
            if not isinstance(spec, dict):
                logger.warning("[registry] skipping invalid rate_limits entry: %s", name)
                continue
            try:
                rate = float(spec["rate"])
                burst = int(spec.get("burst", 1))
                with self._lock:
                    if name not in self._limiters:
                        limiter = RateLimiter(rate=rate, burst=burst, name=name)
                        self._limiters[name] = limiter
                        logger.info(
                            "[registry] configured limiter '%s' from config "
                            "(rate=%.3f/s, burst=%d)",
                            name, rate, burst,
                        )
                    else:
                        logger.debug(
                            "[registry] limiter '%s' already exists, skipping config", name
                        )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "[registry] invalid rate_limits config for '%s': %s", name, exc
                )

    def reset_all(self) -> None:
        """Reset all token buckets across every registered limiter."""
        with self._lock:
            for limiter in self._limiters.values():
                limiter.reset()
        logger.debug("[registry] all limiters reset")

    def list_limiters(self) -> list[str]:
        """Return a sorted list of registered limiter names."""
        with self._lock:
            return sorted(self._limiters.keys())


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

registry = RateLimiterRegistry()

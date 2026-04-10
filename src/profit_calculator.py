"""
Profit calculator — closes the money-printing feedback loop.

MoneyPrinter's :mod:`revenue_tracker` estimates gross/net earnings from
view counts, but for a truly profitable automation pipeline users need to
know the *real* profit after subtracting production costs (LLM tokens,
text-to-speech, compute, storage). This module tracks those costs and
computes per-video, per-platform, and per-niche profit margins.

Typical usage:

    from profit_calculator import ProfitCalculator
    from revenue_tracker import RevenueTracker

    revenue = RevenueTracker()
    calc = ProfitCalculator(revenue_tracker=revenue)

    # Record production cost after generating a video.
    calc.record_cost(
        "vid_abc",
        platform="youtube",
        niche="finance",
        llm_tokens=4_500,
        tts_chars=2_200,
        compute_seconds=55,
        storage_mb=35.0,
    )

    # Later, after the revenue tracker has recorded views/earnings:
    report = calc.get_profit_for_video("vid_abc")
    print(report["net_profit"], report["margin_percent"])

Configuration (``config.json``):

.. code-block:: json

    {
        "profit": {
            "llm_rate_per_1k_tokens": 0.01,
            "tts_rate_per_1k_chars": 0.015,
            "compute_rate_per_hour": 0.02,
            "storage_rate_per_gb_month": 0.023,
            "currency": "USD"
        }
    }

All rates default to the most commonly quoted 2026 open-source/commodity
values. Users running self-hosted LLM/TTS can set them to ``0``.

The module is thread-safe, persists to an atomic JSON file with rotation,
and all timestamps are timezone-aware (UTC).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import ROOT_DIR, _get
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MAX_ENTRIES = 50_000
_MAX_VIDEO_ID_LENGTH = 256
_MAX_NICHE_LENGTH = 100
_MAX_PLATFORM_LENGTH = 50
_SUPPORTED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})
_COST_FILE = os.path.join(ROOT_DIR, ".mp", "profit_calculator.json")

# 2026 commodity-rate defaults (USD).
_DEFAULT_LLM_RATE_PER_1K_TOKENS = 0.01
_DEFAULT_TTS_RATE_PER_1K_CHARS = 0.015
_DEFAULT_COMPUTE_RATE_PER_HOUR = 0.02
_DEFAULT_STORAGE_RATE_PER_GB_MONTH = 0.023
_DEFAULT_CURRENCY = "USD"

# Safety caps to prevent integer-overflow style abuse via config.
_MAX_RATE = 1_000.0
_MAX_TOKENS = 10_000_000
_MAX_CHARS = 10_000_000
_MAX_COMPUTE_SECONDS = 10 * 24 * 3600  # 10 days
_MAX_STORAGE_MB = 10 * 1024 * 1024      # 10 TB


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _read_float(key: str, default: float) -> float:
    try:
        value = float(_get(key, default))
    except (TypeError, ValueError):
        return float(default)
    if value < 0 or value > _MAX_RATE:
        return float(default)
    return value


def get_llm_rate() -> float:
    """Return configured LLM cost per 1k tokens (USD)."""
    return _read_float("profit.llm_rate_per_1k_tokens", _DEFAULT_LLM_RATE_PER_1K_TOKENS)


def get_tts_rate() -> float:
    """Return configured TTS cost per 1k characters (USD)."""
    return _read_float("profit.tts_rate_per_1k_chars", _DEFAULT_TTS_RATE_PER_1K_CHARS)


def get_compute_rate() -> float:
    """Return configured compute cost per hour (USD)."""
    return _read_float("profit.compute_rate_per_hour", _DEFAULT_COMPUTE_RATE_PER_HOUR)


def get_storage_rate() -> float:
    """Return configured storage cost per GB-month (USD)."""
    return _read_float("profit.storage_rate_per_gb_month", _DEFAULT_STORAGE_RATE_PER_GB_MONTH)


def get_currency() -> str:
    """Return configured currency code (3-letter, uppercase)."""
    raw = _get("profit.currency", _DEFAULT_CURRENCY)
    if not isinstance(raw, str):
        return _DEFAULT_CURRENCY
    cleaned = raw.strip().upper()
    if len(cleaned) != 3 or not cleaned.isalpha():
        return _DEFAULT_CURRENCY
    return cleaned


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CostEntry:
    """Single cost record for one produced video."""

    video_id: str
    platform: str = ""
    niche: str = "general"
    llm_tokens: int = 0
    tts_chars: int = 0
    compute_seconds: float = 0.0
    storage_mb: float = 0.0
    total_cost: float = 0.0
    currency: str = _DEFAULT_CURRENCY
    recorded_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict) -> "CostEntry":
        if not isinstance(raw, dict):
            raise TypeError("CostEntry.from_dict expects a dict")
        video_id = str(raw.get("video_id", "")).strip()[:_MAX_VIDEO_ID_LENGTH]
        if not video_id:
            raise ValueError("video_id is required")
        platform = str(raw.get("platform", "")).strip()[:_MAX_PLATFORM_LENGTH]
        niche = str(raw.get("niche", "general")).strip()[:_MAX_NICHE_LENGTH] or "general"
        try:
            llm_tokens = max(0, int(raw.get("llm_tokens", 0)))
            tts_chars = max(0, int(raw.get("tts_chars", 0)))
            compute_seconds = max(0.0, float(raw.get("compute_seconds", 0.0)))
            storage_mb = max(0.0, float(raw.get("storage_mb", 0.0)))
            total_cost = max(0.0, float(raw.get("total_cost", 0.0)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid numeric field: {exc}") from exc
        llm_tokens = min(llm_tokens, _MAX_TOKENS)
        tts_chars = min(tts_chars, _MAX_CHARS)
        compute_seconds = min(compute_seconds, _MAX_COMPUTE_SECONDS)
        storage_mb = min(storage_mb, _MAX_STORAGE_MB)
        currency_raw = raw.get("currency", _DEFAULT_CURRENCY)
        if not isinstance(currency_raw, str) or len(currency_raw.strip()) != 3:
            currency = _DEFAULT_CURRENCY
        else:
            currency = currency_raw.strip().upper()
        recorded_at = str(raw.get("recorded_at", ""))[:64]
        return CostEntry(
            video_id=video_id,
            platform=platform,
            niche=niche,
            llm_tokens=llm_tokens,
            tts_chars=tts_chars,
            compute_seconds=compute_seconds,
            storage_mb=storage_mb,
            total_cost=total_cost,
            currency=currency,
            recorded_at=recorded_at,
        )


@dataclass
class ProfitSummary:
    """Aggregated profit metrics for a window of activity."""

    period_days: int = 30
    total_cost: float = 0.0
    total_gross: float = 0.0
    total_net: float = 0.0
    total_profit: float = 0.0
    margin_percent: float = 0.0
    entry_count: int = 0
    currency: str = _DEFAULT_CURRENCY
    by_platform: dict = field(default_factory=dict)
    by_niche: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# ProfitCalculator
# ---------------------------------------------------------------------------


class ProfitCalculator:
    """Track production costs and compute profit vs. revenue tracker data."""

    def __init__(
        self,
        revenue_tracker=None,
        cost_path: Optional[str] = None,
    ) -> None:
        self._revenue_tracker = revenue_tracker
        self._cost_path = cost_path or _COST_FILE
        self._entries: list[dict] = []
        self._loaded = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(self._cost_path):
            self._entries = []
            return
        try:
            with open(self._cost_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            logger.warning("profit_calculator: could not read cost file — starting empty")
            self._entries = []
            return
        if isinstance(data, list):
            self._entries = [item for item in data if isinstance(item, dict)]
        else:
            self._entries = []

    def _persist(self) -> None:
        directory = os.path.dirname(self._cost_path)
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=directory or None,
                prefix=".profit_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._entries, fh)
                os.replace(tmp_path, self._cost_path)
            except Exception:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                raise
        except OSError:
            logger.warning("profit_calculator: persist failed")

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def estimate_cost(
        self,
        llm_tokens: int = 0,
        tts_chars: int = 0,
        compute_seconds: float = 0.0,
        storage_mb: float = 0.0,
    ) -> float:
        """Compute total production cost in USD for one video.

        All inputs are clamped to safe bounds; negatives are treated as 0.
        """
        try:
            tokens = max(0, int(llm_tokens))
            chars = max(0, int(tts_chars))
            seconds = max(0.0, float(compute_seconds))
            mb = max(0.0, float(storage_mb))
        except (TypeError, ValueError):
            return 0.0
        tokens = min(tokens, _MAX_TOKENS)
        chars = min(chars, _MAX_CHARS)
        seconds = min(seconds, _MAX_COMPUTE_SECONDS)
        mb = min(mb, _MAX_STORAGE_MB)
        llm_cost = (tokens / 1000.0) * get_llm_rate()
        tts_cost = (chars / 1000.0) * get_tts_rate()
        compute_cost = (seconds / 3600.0) * get_compute_rate()
        storage_cost = (mb / 1024.0) * get_storage_rate()
        total = llm_cost + tts_cost + compute_cost + storage_cost
        return round(max(0.0, total), 6)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_cost(
        self,
        video_id: str,
        platform: str = "",
        niche: str = "general",
        llm_tokens: int = 0,
        tts_chars: int = 0,
        compute_seconds: float = 0.0,
        storage_mb: float = 0.0,
    ) -> CostEntry:
        """Record production cost for a video and persist to disk."""
        if not isinstance(video_id, str):
            raise TypeError("video_id must be a string")
        video_id = video_id.strip()
        if not video_id or "\x00" in video_id:
            raise ValueError("video_id must be non-empty and contain no null bytes")
        video_id = video_id[:_MAX_VIDEO_ID_LENGTH]

        if platform and not isinstance(platform, str):
            raise TypeError("platform must be a string")
        platform_clean = (platform or "").strip()[:_MAX_PLATFORM_LENGTH]
        if platform_clean and platform_clean not in _SUPPORTED_PLATFORMS:
            # Allow it but log — some users have custom platforms.
            logger.debug("profit_calculator: unknown platform '%s'", platform_clean)

        if not isinstance(niche, str):
            niche_clean = "general"
        else:
            niche_clean = niche.strip()[:_MAX_NICHE_LENGTH] or "general"

        total_cost = self.estimate_cost(
            llm_tokens=llm_tokens,
            tts_chars=tts_chars,
            compute_seconds=compute_seconds,
            storage_mb=storage_mb,
        )

        entry = CostEntry(
            video_id=video_id,
            platform=platform_clean,
            niche=niche_clean,
            llm_tokens=min(max(0, int(llm_tokens or 0)), _MAX_TOKENS),
            tts_chars=min(max(0, int(tts_chars or 0)), _MAX_CHARS),
            compute_seconds=min(max(0.0, float(compute_seconds or 0.0)), _MAX_COMPUTE_SECONDS),
            storage_mb=min(max(0.0, float(storage_mb or 0.0)), _MAX_STORAGE_MB),
            total_cost=total_cost,
            currency=get_currency(),
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )

        with self._lock:
            self._ensure_loaded()
            self._entries.append(entry.to_dict())
            # Keep only the most recent _MAX_ENTRIES records.
            if len(self._entries) > _MAX_ENTRIES:
                self._entries = self._entries[-_MAX_ENTRIES:]
            self._persist()
        logger.info(
            "profit_calculator: recorded cost %.4f %s for %s",
            total_cost,
            entry.currency,
            video_id[:32],
        )
        return entry

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_cost_entries(
        self,
        days: Optional[int] = None,
        video_id: Optional[str] = None,
        platform: Optional[str] = None,
        niche: Optional[str] = None,
    ) -> list[CostEntry]:
        """Return cost entries filtered by window and/or metadata."""
        with self._lock:
            self._ensure_loaded()
            cutoff: Optional[str] = None
            if days is not None:
                if not isinstance(days, int) or days < 1:
                    days = 1
                if days > 3650:
                    days = 3650
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            results: list[CostEntry] = []
            for raw in self._entries:
                if not isinstance(raw, dict):
                    continue
                if video_id and raw.get("video_id") != video_id:
                    continue
                if platform and raw.get("platform") != platform:
                    continue
                if niche and raw.get("niche") != niche:
                    continue
                if cutoff and raw.get("recorded_at", "") < cutoff:
                    continue
                try:
                    results.append(CostEntry.from_dict(raw))
                except (TypeError, ValueError):
                    continue
            return results

    def get_total_cost(
        self,
        days: Optional[int] = None,
        platform: Optional[str] = None,
        niche: Optional[str] = None,
    ) -> float:
        """Return the sum of ``total_cost`` across filtered entries."""
        return round(
            sum(e.total_cost for e in self.get_cost_entries(days=days, platform=platform, niche=niche)),
            6,
        )

    # ------------------------------------------------------------------
    # Profit analysis
    # ------------------------------------------------------------------

    def _revenue_for_video(self, video_id: str) -> tuple[float, float]:
        """Return ``(gross, net)`` revenue for *video_id* from the tracker."""
        if self._revenue_tracker is None:
            return 0.0, 0.0
        try:
            entries = self._revenue_tracker.get_entries()
        except Exception:
            return 0.0, 0.0
        gross = 0.0
        net = 0.0
        for entry in entries:
            vid = getattr(entry, "video_id", None)
            if vid != video_id:
                continue
            gross += float(getattr(entry, "estimated_gross", 0.0) or 0.0)
            net += float(getattr(entry, "estimated_net", 0.0) or 0.0)
        return gross, net

    def get_profit_for_video(self, video_id: str) -> dict:
        """Return per-video profit breakdown.

        The returned dict contains ``video_id``, ``total_cost``,
        ``gross_revenue``, ``net_revenue``, ``net_profit`` (net − cost),
        ``margin_percent`` and ``currency``.
        """
        if not isinstance(video_id, str) or not video_id.strip():
            raise ValueError("video_id must be a non-empty string")
        video_id = video_id.strip()[:_MAX_VIDEO_ID_LENGTH]

        cost_entries = self.get_cost_entries(video_id=video_id)
        total_cost = round(sum(e.total_cost for e in cost_entries), 6)
        gross, net = self._revenue_for_video(video_id)
        net_profit = round(net - total_cost, 6)
        margin = 0.0
        if gross > 0:
            margin = round(((net - total_cost) / gross) * 100.0, 4)
        return {
            "video_id": video_id,
            "total_cost": total_cost,
            "gross_revenue": round(gross, 6),
            "net_revenue": round(net, 6),
            "net_profit": net_profit,
            "margin_percent": margin,
            "currency": get_currency(),
            "is_profitable": net_profit > 0,
        }

    def get_profit_summary(
        self,
        days: int = 30,
        platform: Optional[str] = None,
        niche: Optional[str] = None,
    ) -> ProfitSummary:
        """Aggregate profit metrics across the last *days* of activity."""
        if not isinstance(days, int) or days < 1:
            days = 1
        if days > 3650:
            days = 3650

        cost_entries = self.get_cost_entries(days=days, platform=platform, niche=niche)
        total_cost = sum(e.total_cost for e in cost_entries)
        by_platform: dict[str, dict[str, float]] = {}
        by_niche: dict[str, dict[str, float]] = {}

        for e in cost_entries:
            p_slot = by_platform.setdefault(
                e.platform or "unknown",
                {"cost": 0.0, "gross": 0.0, "net": 0.0, "profit": 0.0, "count": 0},
            )
            p_slot["cost"] += e.total_cost
            p_slot["count"] += 1
            n_slot = by_niche.setdefault(
                e.niche or "general",
                {"cost": 0.0, "gross": 0.0, "net": 0.0, "profit": 0.0, "count": 0},
            )
            n_slot["cost"] += e.total_cost
            n_slot["count"] += 1

        total_gross = 0.0
        total_net = 0.0
        if self._revenue_tracker is not None:
            try:
                revenue_entries = self._revenue_tracker.get_entries(
                    days=days, platform=platform, niche=niche
                )
            except Exception:
                revenue_entries = []
            for entry in revenue_entries:
                gross_val = float(getattr(entry, "estimated_gross", 0.0) or 0.0)
                net_val = float(getattr(entry, "estimated_net", 0.0) or 0.0)
                total_gross += gross_val
                total_net += net_val
                plat_key = getattr(entry, "platform", "") or "unknown"
                niche_key = getattr(entry, "niche", "") or "general"
                if plat_key in by_platform:
                    by_platform[plat_key]["gross"] += gross_val
                    by_platform[plat_key]["net"] += net_val
                if niche_key in by_niche:
                    by_niche[niche_key]["gross"] += gross_val
                    by_niche[niche_key]["net"] += net_val

        for slot in by_platform.values():
            slot["profit"] = round(slot["net"] - slot["cost"], 6)
            slot["cost"] = round(slot["cost"], 6)
            slot["gross"] = round(slot["gross"], 6)
            slot["net"] = round(slot["net"], 6)
        for slot in by_niche.values():
            slot["profit"] = round(slot["net"] - slot["cost"], 6)
            slot["cost"] = round(slot["cost"], 6)
            slot["gross"] = round(slot["gross"], 6)
            slot["net"] = round(slot["net"], 6)

        total_profit = round(total_net - total_cost, 6)
        margin = 0.0
        if total_gross > 0:
            margin = round(((total_net - total_cost) / total_gross) * 100.0, 4)

        return ProfitSummary(
            period_days=days,
            total_cost=round(total_cost, 6),
            total_gross=round(total_gross, 6),
            total_net=round(total_net, 6),
            total_profit=total_profit,
            margin_percent=margin,
            entry_count=len(cost_entries),
            currency=get_currency(),
            by_platform=by_platform,
            by_niche=by_niche,
        )

    def get_top_profitable_niches(self, days: int = 30, limit: int = 5) -> list[dict]:
        """Rank niches by absolute profit across the window."""
        if not isinstance(limit, int) or limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
        summary = self.get_profit_summary(days=days)
        rows = [
            {"niche": niche, **slot}
            for niche, slot in summary.by_niche.items()
        ]
        rows.sort(key=lambda r: r.get("profit", 0.0), reverse=True)
        return rows[:limit]

    def forecast_monthly_profit(self, lookback_days: int = 7) -> dict:
        """Project 30-day profit from recent activity."""
        if not isinstance(lookback_days, int) or lookback_days < 1:
            lookback_days = 1
        if lookback_days > 365:
            lookback_days = 365
        summary = self.get_profit_summary(days=lookback_days)
        if lookback_days <= 0:
            scale = 0.0
        else:
            scale = 30.0 / float(lookback_days)
        return {
            "projected_cost": round(summary.total_cost * scale, 6),
            "projected_gross": round(summary.total_gross * scale, 6),
            "projected_net": round(summary.total_net * scale, 6),
            "projected_profit": round(summary.total_profit * scale, 6),
            "lookback_days": lookback_days,
            "currency": summary.currency,
        }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all in-memory and persisted cost entries."""
        with self._lock:
            self._entries = []
            self._loaded = True
            self._persist()


# ---------------------------------------------------------------------------
# Module-level convenience helpers
# ---------------------------------------------------------------------------

_DEFAULT_CALCULATOR: Optional[ProfitCalculator] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_calculator() -> ProfitCalculator:
    """Return a process-wide singleton :class:`ProfitCalculator`."""
    global _DEFAULT_CALCULATOR
    with _DEFAULT_LOCK:
        if _DEFAULT_CALCULATOR is None:
            _DEFAULT_CALCULATOR = ProfitCalculator()
        return _DEFAULT_CALCULATOR


def estimate_cost(**kwargs) -> float:
    """Estimate production cost using the default calculator's rates."""
    return get_default_calculator().estimate_cost(**kwargs)

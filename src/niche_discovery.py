"""
Niche Discovery Engine for MoneyPrinter.

Combines trend detection data with revenue/profit analytics to automatically
discover and rank the most profitable content niches. The engine scores
niches across multiple dimensions — trending momentum, historical
profitability, CPM rates, and platform suitability — then generates
actionable content topic suggestions for top-performing niches.

This is the "brain" that tells the money printer *what* to print.

Usage:
    from niche_discovery import NicheDiscoveryEngine, NicheOpportunity

    engine = NicheDiscoveryEngine()
    opportunities = engine.discover(days=30, limit=10)
    for opp in opportunities:
        print(opp.niche, opp.overall_score, opp.recommended_platform)
        print(opp.topic_suggestions)

Configuration (config.json):
    "niche_discovery": {
        "enabled": true,
        "lookback_days": 30,
        "min_data_points": 3,
        "trend_weight": 0.30,
        "profit_weight": 0.35,
        "cpm_weight": 0.20,
        "volume_weight": 0.15,
        "max_results": 20
    }

All weights default to balanced values that prioritise profitability
over raw trend momentum — because the goal is money, not virality.

Thread-safe, all timestamps UTC-aware, no exception messages disclosed.
"""

from __future__ import annotations

import json
import math
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

_DISCOVERY_FILE = os.path.join(ROOT_DIR, ".mp", "niche_discovery.json")
_MAX_ENTRIES = 10_000
_MAX_NICHE_LENGTH = 100
_MAX_PLATFORM_LENGTH = 50
_MAX_TOPIC_LENGTH = 500
_MAX_SUGGESTIONS = 50
_MAX_RESULTS = 100
_MAX_LOOKBACK_DAYS = 365
_MIN_LOOKBACK_DAYS = 1
_MAX_DATA_POINTS = 1_000_000
_MIN_DATA_POINTS = 1

# Weight bounds
_MIN_WEIGHT = 0.0
_MAX_WEIGHT = 1.0

# Default scoring weights
_DEFAULT_TREND_WEIGHT = 0.30
_DEFAULT_PROFIT_WEIGHT = 0.35
_DEFAULT_CPM_WEIGHT = 0.20
_DEFAULT_VOLUME_WEIGHT = 0.15

# Known niches and platforms (mirrors revenue_tracker)
_KNOWN_NICHES = frozenset({
    "finance", "technology", "health", "education", "gaming",
    "entertainment", "lifestyle", "cooking", "travel", "business",
    "general",
})
_SUPPORTED_PLATFORMS = frozenset({"youtube", "tiktok", "twitter", "instagram"})

# CPM lookup (mirrors revenue_tracker._CPM_BY_NICHE for scoring)
_CPM_BY_NICHE: dict[str, dict[str, float]] = {
    "finance": {"youtube": 12.0, "tiktok": 1.5, "twitter": 2.0, "instagram": 3.0},
    "technology": {"youtube": 9.5, "tiktok": 1.2, "twitter": 1.8, "instagram": 2.5},
    "health": {"youtube": 8.0, "tiktok": 1.0, "twitter": 1.5, "instagram": 2.2},
    "education": {"youtube": 7.5, "tiktok": 0.9, "twitter": 1.3, "instagram": 2.0},
    "gaming": {"youtube": 5.0, "tiktok": 0.8, "twitter": 1.0, "instagram": 1.5},
    "entertainment": {"youtube": 4.0, "tiktok": 0.7, "twitter": 0.8, "instagram": 1.2},
    "lifestyle": {"youtube": 5.5, "tiktok": 0.9, "twitter": 1.2, "instagram": 2.0},
    "cooking": {"youtube": 6.0, "tiktok": 0.8, "twitter": 1.0, "instagram": 1.8},
    "travel": {"youtube": 7.0, "tiktok": 1.0, "twitter": 1.4, "instagram": 2.5},
    "business": {"youtube": 11.0, "tiktok": 1.4, "twitter": 2.0, "instagram": 2.8},
    "general": {"youtube": 5.0, "tiktok": 0.8, "twitter": 1.0, "instagram": 1.5},
}

# Niche topic seed bank — used for generating suggestions when no
# trend data is available. Each niche has evergreen sub-topics.
_TOPIC_SEEDS: dict[str, list[str]] = {
    "finance": [
        "passive income strategies",
        "stock market analysis",
        "cryptocurrency trends",
        "budgeting tips",
        "side hustle ideas",
        "investing for beginners",
        "tax saving strategies",
        "real estate investing",
    ],
    "technology": [
        "AI tool reviews",
        "latest gadget unboxing",
        "coding tutorials",
        "tech industry news",
        "software comparisons",
        "productivity apps",
        "cybersecurity tips",
        "open source projects",
    ],
    "health": [
        "workout routines",
        "nutrition tips",
        "mental health awareness",
        "sleep optimization",
        "supplement reviews",
        "healthy recipes",
        "fitness challenges",
        "stress management",
    ],
    "education": [
        "study techniques",
        "online course reviews",
        "learning hacks",
        "exam preparation",
        "skill development",
        "language learning",
        "career guidance",
        "educational tools",
    ],
    "gaming": [
        "game reviews",
        "gameplay tips",
        "esports highlights",
        "indie game discoveries",
        "gaming setup tours",
        "speedrun strategies",
        "game development",
        "retro gaming",
    ],
    "entertainment": [
        "movie reviews",
        "TV show recaps",
        "celebrity news analysis",
        "music discoveries",
        "pop culture commentary",
        "streaming recommendations",
        "award show predictions",
        "viral trend analysis",
    ],
    "lifestyle": [
        "morning routine",
        "home organization",
        "minimalism tips",
        "self improvement",
        "relationship advice",
        "fashion lookbooks",
        "daily vlogs",
        "life hacks",
    ],
    "cooking": [
        "quick meal recipes",
        "meal prep guides",
        "kitchen gadget reviews",
        "international cuisines",
        "baking tutorials",
        "healthy cooking",
        "budget meals",
        "food challenges",
    ],
    "travel": [
        "hidden gem destinations",
        "budget travel tips",
        "travel gear reviews",
        "cultural experiences",
        "road trip guides",
        "solo travel advice",
        "luxury vs budget",
        "travel photography",
    ],
    "business": [
        "startup advice",
        "marketing strategies",
        "productivity systems",
        "leadership lessons",
        "business case studies",
        "entrepreneur interviews",
        "automation tools",
        "scaling strategies",
    ],
    "general": [
        "interesting facts",
        "how-to guides",
        "life tips",
        "trending topics",
        "educational content",
        "motivational content",
        "comparison videos",
        "reaction videos",
    ],
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NicheOpportunity:
    """A scored niche opportunity with actionable recommendations."""

    niche: str
    overall_score: float            # 0.0 – 10.0
    trend_score: float              # 0.0 – 10.0
    profit_score: float             # 0.0 – 10.0
    cpm_score: float                # 0.0 – 10.0
    volume_score: float             # 0.0 – 10.0
    recommended_platform: str       # best platform for this niche
    estimated_cpm: float            # best CPM across platforms
    estimated_monthly_profit: float # projected 30-day profit (USD)
    video_count: int                # videos produced in lookback window
    topic_suggestions: list[str] = field(default_factory=list)
    reasoning: str = ""
    discovered_at: str = ""

    def __post_init__(self):
        # Validate niche
        if not isinstance(self.niche, str) or not self.niche.strip():
            raise ValueError("niche must be a non-empty string")
        self.niche = self.niche.strip()[:_MAX_NICHE_LENGTH]

        # Clamp scores to [0, 10]
        for attr in ("overall_score", "trend_score", "profit_score",
                      "cpm_score", "volume_score"):
            val = getattr(self, attr)
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = 0.0
            setattr(self, attr, max(0.0, min(10.0, val)))

        # Clamp numeric fields
        try:
            self.estimated_cpm = max(0.0, float(self.estimated_cpm))
        except (TypeError, ValueError):
            self.estimated_cpm = 0.0

        try:
            self.estimated_monthly_profit = float(self.estimated_monthly_profit)
        except (TypeError, ValueError):
            self.estimated_monthly_profit = 0.0

        try:
            self.video_count = max(0, int(self.video_count))
        except (TypeError, ValueError):
            self.video_count = 0

        # Validate platform
        if self.recommended_platform not in _SUPPORTED_PLATFORMS:
            self.recommended_platform = "youtube"

        # Clamp suggestions
        if not isinstance(self.topic_suggestions, list):
            self.topic_suggestions = []
        self.topic_suggestions = [
            str(s)[:_MAX_TOPIC_LENGTH]
            for s in self.topic_suggestions[:_MAX_SUGGESTIONS]
            if isinstance(s, str) and s.strip()
        ]

        # Truncate reasoning
        if not isinstance(self.reasoning, str):
            self.reasoning = ""
        self.reasoning = self.reasoning[:2000]

        # Timestamp
        if not self.discovered_at:
            self.discovered_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Serialize to plain dictionary."""
        return {
            "niche": self.niche,
            "overall_score": round(self.overall_score, 2),
            "trend_score": round(self.trend_score, 2),
            "profit_score": round(self.profit_score, 2),
            "cpm_score": round(self.cpm_score, 2),
            "volume_score": round(self.volume_score, 2),
            "recommended_platform": self.recommended_platform,
            "estimated_cpm": round(self.estimated_cpm, 4),
            "estimated_monthly_profit": round(self.estimated_monthly_profit, 2),
            "video_count": self.video_count,
            "topic_suggestions": self.topic_suggestions,
            "reasoning": self.reasoning,
            "discovered_at": self.discovered_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NicheOpportunity":
        """Deserialize from a dictionary with defensive validation."""
        if not isinstance(data, dict):
            raise ValueError("data must be a dict")
        return cls(
            niche=str(data.get("niche", "general"))[:_MAX_NICHE_LENGTH],
            overall_score=_safe_float(data.get("overall_score")),
            trend_score=_safe_float(data.get("trend_score")),
            profit_score=_safe_float(data.get("profit_score")),
            cpm_score=_safe_float(data.get("cpm_score")),
            volume_score=_safe_float(data.get("volume_score")),
            recommended_platform=str(
                data.get("recommended_platform", "youtube")
            )[:_MAX_PLATFORM_LENGTH],
            estimated_cpm=_safe_float(data.get("estimated_cpm")),
            estimated_monthly_profit=_safe_float(
                data.get("estimated_monthly_profit")
            ),
            video_count=_safe_int(data.get("video_count")),
            topic_suggestions=data.get("topic_suggestions", []),
            reasoning=str(data.get("reasoning", ""))[:2000],
            discovered_at=str(data.get("discovered_at", "")),
        )


@dataclass
class DiscoveryReport:
    """Summary of a niche discovery run."""

    opportunities: list[NicheOpportunity] = field(default_factory=list)
    top_niche: str = ""
    top_platform: str = ""
    total_niches_analyzed: int = 0
    lookback_days: int = 30
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()
        try:
            self.total_niches_analyzed = max(0, int(self.total_niches_analyzed))
        except (TypeError, ValueError):
            self.total_niches_analyzed = 0
        try:
            self.lookback_days = max(1, min(_MAX_LOOKBACK_DAYS, int(self.lookback_days)))
        except (TypeError, ValueError):
            self.lookback_days = 30

    def to_dict(self) -> dict:
        """Serialize to plain dictionary."""
        return {
            "opportunities": [o.to_dict() for o in self.opportunities],
            "top_niche": self.top_niche,
            "top_platform": self.top_platform,
            "total_niches_analyzed": self.total_niches_analyzed,
            "lookback_days": self.lookback_days,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _safe_float(val, default: float = 0.0) -> float:
    """Convert *val* to float, returning *default* on failure."""
    if val is None:
        return default
    try:
        f = float(val)
        if f != f:  # NaN check
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    """Convert *val* to int, returning *default* on failure."""
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _read_config_float(key: str, default: float) -> float:
    """Read a float from the niche_discovery config section."""
    cfg = _get("niche_discovery", {})
    if not isinstance(cfg, dict):
        return default
    val = cfg.get(key, default)
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    if f < 0 or f > 1000:
        return default
    return f


def get_trend_weight() -> float:
    return _read_config_float("trend_weight", _DEFAULT_TREND_WEIGHT)


def get_profit_weight() -> float:
    return _read_config_float("profit_weight", _DEFAULT_PROFIT_WEIGHT)


def get_cpm_weight() -> float:
    return _read_config_float("cpm_weight", _DEFAULT_CPM_WEIGHT)


def get_volume_weight() -> float:
    return _read_config_float("volume_weight", _DEFAULT_VOLUME_WEIGHT)


def get_lookback_days() -> int:
    cfg = _get("niche_discovery", {})
    if not isinstance(cfg, dict):
        return 30
    val = cfg.get("lookback_days", 30)
    try:
        d = int(val)
    except (TypeError, ValueError):
        return 30
    return max(_MIN_LOOKBACK_DAYS, min(_MAX_LOOKBACK_DAYS, d))


def get_min_data_points() -> int:
    cfg = _get("niche_discovery", {})
    if not isinstance(cfg, dict):
        return 3
    val = cfg.get("min_data_points", 3)
    try:
        d = int(val)
    except (TypeError, ValueError):
        return 3
    return max(_MIN_DATA_POINTS, min(_MAX_DATA_POINTS, d))


def get_max_results() -> int:
    cfg = _get("niche_discovery", {})
    if not isinstance(cfg, dict):
        return 20
    val = cfg.get("max_results", 20)
    try:
        d = int(val)
    except (TypeError, ValueError):
        return 20
    return max(1, min(_MAX_RESULTS, d))


# ---------------------------------------------------------------------------
# NicheDiscoveryEngine
# ---------------------------------------------------------------------------


class NicheDiscoveryEngine:
    """
    Discovers and ranks the most profitable content niches by combining
    trend data, revenue analytics, and profit margins.

    Parameters
    ----------
    revenue_tracker : optional
        An instance of :class:`revenue_tracker.RevenueTracker`. If not
        provided, the engine operates in CPM-only mode (no historical
        revenue data).
    profit_calculator : optional
        An instance of :class:`profit_calculator.ProfitCalculator`. If not
        provided, profit scoring uses CPM estimates only.
    trend_detector : optional
        An instance of :class:`trend_detector.TrendDetector`. If not
        provided, trend scoring falls back to static niche weights.
    data_dir : str, optional
        Directory for persisting discovery results. Defaults to
        ``<ROOT_DIR>/.mp/``.
    """

    def __init__(
        self,
        revenue_tracker=None,
        profit_calculator=None,
        trend_detector=None,
        data_dir: Optional[str] = None,
    ):
        self._revenue = revenue_tracker
        self._profit = profit_calculator
        self._trend = trend_detector
        self._lock = threading.RLock()

        if data_dir is not None:
            if not isinstance(data_dir, str):
                data_dir = None
            elif "\x00" in data_dir:
                data_dir = None

        if data_dir:
            self._file = os.path.join(data_dir, "niche_discovery.json")
        else:
            self._file = _DISCOVERY_FILE

        self._history: list[dict] = []
        self._loaded = False

    # -------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------

    def _ensure_loaded(self):
        """Load discovery history from disk (once)."""
        if self._loaded:
            return
        try:
            if os.path.exists(self._file):
                with open(self._file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    self._history = data[:_MAX_ENTRIES]
                else:
                    self._history = []
            else:
                self._history = []
        except Exception:
            logger.warning("Failed to load discovery history — starting empty")
            self._history = []
        self._loaded = True

    def _persist(self):
        """Atomically persist discovery history to disk."""
        parent = os.path.dirname(self._file) or "."
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError:
            return
        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".niche_disc_", suffix=".tmp", dir=parent
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fd = None  # os.fdopen takes ownership
                json.dump(self._history[-_MAX_ENTRIES:], fh)
            os.replace(tmp_path, self._file)
            tmp_path = None
        except Exception:
            logger.warning("Failed to persist discovery history")
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # -------------------------------------------------------------------
    # Scoring helpers
    # -------------------------------------------------------------------

    def _score_trend(self, niche: str, days: int) -> float:
        """
        Score a niche 0-10 based on trending momentum.

        If a TrendDetector is available, looks for recent topic candidates
        matching this niche. Otherwise returns a static baseline.
        """
        if self._trend is None:
            # Static fallback: high-CPM niches get a slight trend bonus
            cpm = self._best_cpm_for_niche(niche)
            return min(10.0, cpm / 2.0)

        try:
            # Try to get cached topics from the trend detector
            topics = []
            if hasattr(self._trend, "get_cached_topics"):
                topics = self._trend.get_cached_topics() or []
            elif hasattr(self._trend, "detect"):
                topics = self._trend.detect() or []

            if not isinstance(topics, list):
                topics = []

            # Filter topics relevant to this niche
            niche_lower = niche.lower()
            relevant = []
            for t in topics:
                topic_text = ""
                score = 0.0
                if hasattr(t, "topic"):
                    topic_text = str(t.topic).lower()
                    score = float(getattr(t, "score", 0.0))
                elif isinstance(t, dict):
                    topic_text = str(t.get("topic", "")).lower()
                    score = _safe_float(t.get("score", 0.0))
                else:
                    continue

                # Check if topic relates to niche
                if niche_lower in topic_text or any(
                    seed.split()[0].lower() in topic_text
                    for seed in _TOPIC_SEEDS.get(niche, [])
                ):
                    relevant.append(score)

            if relevant:
                avg_score = sum(relevant) / len(relevant)
                # Boost by volume of relevant trends
                volume_bonus = min(2.0, len(relevant) * 0.5)
                return min(10.0, avg_score + volume_bonus)

        except Exception:
            logger.warning("Trend scoring failed for niche %s", niche)

        # Fallback
        cpm = self._best_cpm_for_niche(niche)
        return min(10.0, cpm / 2.0)

    def _score_profit(self, niche: str, days: int) -> float:
        """
        Score a niche 0-10 based on historical profit margins.
        """
        if self._profit is None:
            # No profit data: use CPM as proxy
            cpm = self._best_cpm_for_niche(niche)
            return min(10.0, cpm / 1.5)

        try:
            summary = None
            if hasattr(self._profit, "get_profit_summary"):
                summary = self._profit.get_profit_summary(
                    days=days, niche=niche
                )

            if summary is None:
                cpm = self._best_cpm_for_niche(niche)
                return min(10.0, cpm / 1.5)

            margin = 0.0
            if isinstance(summary, dict):
                margin = _safe_float(summary.get("margin_percent", 0.0))
            elif hasattr(summary, "margin_percent"):
                margin = _safe_float(getattr(summary, "margin_percent", 0.0))

            # Map margin percentage (0-100%) to 0-10 score
            # 50%+ margin = 10, 0% margin = 0
            return min(10.0, max(0.0, margin / 5.0))

        except Exception:
            logger.warning("Profit scoring failed for niche %s", niche)

        cpm = self._best_cpm_for_niche(niche)
        return min(10.0, cpm / 1.5)

    def _score_cpm(self, niche: str) -> float:
        """Score a niche 0-10 based on CPM rates."""
        best_cpm = self._best_cpm_for_niche(niche)
        # Finance has ~12.0 YouTube CPM, normalize so 12+ = 10
        return min(10.0, best_cpm * 10.0 / 12.0)

    def _score_volume(self, niche: str, days: int) -> float:
        """
        Score a niche 0-10 based on content production volume.

        Higher volume = more data = more confidence, but also more
        competition from ourselves. We want a balanced signal.
        """
        count = self._video_count_for_niche(niche, days)
        if count == 0:
            # Untapped niche gets moderate score (opportunity)
            return 5.0
        # Logarithmic scale: 1 video = 3, 10 = 6, 100 = 9
        try:
            count = max(1, int(count))
        except (TypeError, ValueError):
            count = 1
        return min(10.0, 3.0 + 3.0 * math.log10(count))

    def _best_cpm_for_niche(self, niche: str) -> float:
        """Return the highest CPM across platforms for a given niche."""
        rates = _CPM_BY_NICHE.get(niche, _CPM_BY_NICHE["general"])
        return max(rates.values()) if rates else 1.0

    def _best_platform_for_niche(self, niche: str) -> str:
        """Return the platform with the highest CPM for this niche."""
        rates = _CPM_BY_NICHE.get(niche, _CPM_BY_NICHE["general"])
        if not rates:
            return "youtube"
        return max(rates, key=rates.get)

    def _video_count_for_niche(self, niche: str, days: int) -> int:
        """Get the number of videos produced for this niche in the window."""
        if self._profit is not None:
            try:
                if hasattr(self._profit, "get_cost_entries"):
                    entries = self._profit.get_cost_entries(
                        days=days, niche=niche
                    )
                    if isinstance(entries, list):
                        return len(entries)
            except Exception:
                logger.warning("Cost entry lookup failed for niche %s", niche)

        if self._revenue is not None:
            try:
                if hasattr(self._revenue, "get_entries"):
                    entries = self._revenue.get_entries(
                        days=days, niche=niche
                    )
                    if isinstance(entries, list):
                        return len(entries)
            except Exception:
                logger.warning("Revenue entry lookup failed for niche %s", niche)

        return 0

    def _estimated_monthly_profit(self, niche: str, days: int) -> float:
        """Estimate monthly profit for a niche based on historical data."""
        if self._profit is not None:
            try:
                if hasattr(self._profit, "get_profit_summary"):
                    summary = self._profit.get_profit_summary(
                        days=days, niche=niche
                    )
                    if summary is not None:
                        total_profit = 0.0
                        if isinstance(summary, dict):
                            total_profit = _safe_float(
                                summary.get("total_profit", 0.0)
                            )
                        elif hasattr(summary, "total_profit"):
                            total_profit = _safe_float(
                                getattr(summary, "total_profit", 0.0)
                            )

                        if days > 0 and total_profit != 0.0:
                            return total_profit * 30.0 / days

            except Exception:
                logger.warning("Profit estimation failed for niche %s", niche)

        # Fallback: estimate from CPM * assumed view volume
        best_cpm = self._best_cpm_for_niche(niche)
        # Assume 10 videos/month, 10k views each
        estimated_views = 100_000
        gross = (estimated_views / 1000.0) * best_cpm
        # Apply average platform revenue share (45-55%)
        net = gross * 0.50
        # Subtract estimated production cost (~$0.50/video * 10)
        return net - 5.0

    def _generate_topics(self, niche: str, count: int = 5) -> list[str]:
        """Generate topic suggestions for a niche."""
        count = max(1, min(20, count))
        seeds = _TOPIC_SEEDS.get(niche, _TOPIC_SEEDS["general"])

        # If trend detector has relevant topics, prefer those
        if self._trend is not None:
            try:
                topics = []
                if hasattr(self._trend, "get_cached_topics"):
                    topics = self._trend.get_cached_topics() or []
                elif hasattr(self._trend, "detect"):
                    topics = self._trend.detect() or []

                if isinstance(topics, list):
                    niche_lower = niche.lower()
                    trending = []
                    for t in topics:
                        topic_text = ""
                        if hasattr(t, "topic"):
                            topic_text = str(t.topic)
                        elif isinstance(t, dict):
                            topic_text = str(t.get("topic", ""))

                        if topic_text and (
                            niche_lower in topic_text.lower()
                            or any(
                                seed.split()[0].lower()
                                in topic_text.lower()
                                for seed in seeds
                            )
                        ):
                            trending.append(topic_text[:_MAX_TOPIC_LENGTH])

                    if trending:
                        result = trending[:count]
                        # Fill remaining with seeds
                        remaining = count - len(result)
                        if remaining > 0:
                            result.extend(seeds[:remaining])
                        return result[:count]

            except Exception:
                logger.warning("Topic generation from trends failed for niche %s", niche)

        # Fall back to seed topics
        return seeds[:count]

    def _build_reasoning(self, niche: str, scores: dict) -> str:
        """Generate a human-readable reasoning string."""
        parts = []
        if scores.get("trend_score", 0) >= 7.0:
            parts.append("strong trending momentum")
        elif scores.get("trend_score", 0) >= 4.0:
            parts.append("moderate trend activity")
        else:
            parts.append("low current trend activity")

        if scores.get("profit_score", 0) >= 7.0:
            parts.append("highly profitable historically")
        elif scores.get("profit_score", 0) >= 4.0:
            parts.append("moderate profit margins")
        else:
            parts.append("limited profit data")

        cpm = self._best_cpm_for_niche(niche)
        parts.append(f"best CPM ${cpm:.2f}")

        platform = self._best_platform_for_niche(niche)
        parts.append(f"strongest on {platform}")

        return "; ".join(parts)

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def discover(
        self,
        days: Optional[int] = None,
        limit: Optional[int] = None,
        niches: Optional[list[str]] = None,
    ) -> list[NicheOpportunity]:
        """
        Discover and rank the most profitable content niches.

        Parameters
        ----------
        days : int, optional
            Lookback window in days. Defaults to config value or 30.
        limit : int, optional
            Maximum number of results. Defaults to config value or 20.
        niches : list[str], optional
            Niches to analyse. Defaults to all known niches.

        Returns
        -------
        list[NicheOpportunity]
            Opportunities sorted by overall_score descending.
        """
        with self._lock:
            if days is None:
                days = get_lookback_days()
            else:
                try:
                    days = int(days)
                except (TypeError, ValueError):
                    days = 30
                days = max(_MIN_LOOKBACK_DAYS, min(_MAX_LOOKBACK_DAYS, days))

            if limit is None:
                limit = get_max_results()
            else:
                try:
                    limit = int(limit)
                except (TypeError, ValueError):
                    limit = 20
                limit = max(1, min(_MAX_RESULTS, limit))

            # Determine niches to analyse
            if niches is not None:
                if not isinstance(niches, list):
                    niches = list(_KNOWN_NICHES)
                else:
                    niches = [
                        str(n).strip()[:_MAX_NICHE_LENGTH]
                        for n in niches
                        if isinstance(n, str) and n.strip()
                        and "\x00" not in n
                    ]
                    if not niches:
                        niches = list(_KNOWN_NICHES)
            else:
                niches = list(_KNOWN_NICHES)

            # Load weights
            w_trend = get_trend_weight()
            w_profit = get_profit_weight()
            w_cpm = get_cpm_weight()
            w_volume = get_volume_weight()

            # Normalize weights to sum to 1.0
            total_w = w_trend + w_profit + w_cpm + w_volume
            if total_w <= 0:
                w_trend = _DEFAULT_TREND_WEIGHT
                w_profit = _DEFAULT_PROFIT_WEIGHT
                w_cpm = _DEFAULT_CPM_WEIGHT
                w_volume = _DEFAULT_VOLUME_WEIGHT
                total_w = 1.0
            else:
                w_trend /= total_w
                w_profit /= total_w
                w_cpm /= total_w
                w_volume /= total_w

            opportunities = []
            for niche in niches:
                try:
                    trend_s = self._score_trend(niche, days)
                    profit_s = self._score_profit(niche, days)
                    cpm_s = self._score_cpm(niche)
                    volume_s = self._score_volume(niche, days)

                    overall = (
                        w_trend * trend_s
                        + w_profit * profit_s
                        + w_cpm * cpm_s
                        + w_volume * volume_s
                    )

                    scores = {
                        "trend_score": trend_s,
                        "profit_score": profit_s,
                        "cpm_score": cpm_s,
                        "volume_score": volume_s,
                    }

                    opp = NicheOpportunity(
                        niche=niche,
                        overall_score=overall,
                        trend_score=trend_s,
                        profit_score=profit_s,
                        cpm_score=cpm_s,
                        volume_score=volume_s,
                        recommended_platform=self._best_platform_for_niche(
                            niche
                        ),
                        estimated_cpm=self._best_cpm_for_niche(niche),
                        estimated_monthly_profit=self._estimated_monthly_profit(
                            niche, days
                        ),
                        video_count=self._video_count_for_niche(niche, days),
                        topic_suggestions=self._generate_topics(niche, 5),
                        reasoning=self._build_reasoning(niche, scores),
                    )
                    opportunities.append(opp)
                except Exception:
                    logger.warning("Failed to score niche %s", niche)
                    continue

            # Sort by overall_score descending
            opportunities.sort(key=lambda o: o.overall_score, reverse=True)
            opportunities = opportunities[:limit]

            # Build and persist report
            report = DiscoveryReport(
                opportunities=opportunities,
                top_niche=opportunities[0].niche if opportunities else "",
                top_platform=(
                    opportunities[0].recommended_platform
                    if opportunities
                    else ""
                ),
                total_niches_analyzed=len(niches),
                lookback_days=days,
            )

            self._ensure_loaded()
            self._history.append(report.to_dict())
            if len(self._history) > _MAX_ENTRIES:
                self._history = self._history[-_MAX_ENTRIES:]
            self._persist()

            return opportunities

    def get_top_niche(
        self, days: Optional[int] = None
    ) -> Optional[NicheOpportunity]:
        """
        Convenience: return the single best niche opportunity.

        Returns None if no niches could be scored.
        """
        results = self.discover(days=days, limit=1)
        return results[0] if results else None

    def get_discovery_history(
        self, limit: int = 10
    ) -> list[dict]:
        """Return recent discovery reports from disk."""
        with self._lock:
            self._ensure_loaded()
            try:
                limit = max(1, min(100, int(limit)))
            except (TypeError, ValueError):
                limit = 10
            return list(self._history[-limit:])

    def compare_niches(
        self,
        niche_a: str,
        niche_b: str,
        days: Optional[int] = None,
    ) -> dict:
        """
        Head-to-head comparison of two niches.

        Returns a dict with both opportunities and a recommendation.
        """
        if not isinstance(niche_a, str) or not niche_a.strip():
            raise ValueError("niche_a must be a non-empty string")
        if not isinstance(niche_b, str) or not niche_b.strip():
            raise ValueError("niche_b must be a non-empty string")

        niche_a = niche_a.strip()[:_MAX_NICHE_LENGTH]
        niche_b = niche_b.strip()[:_MAX_NICHE_LENGTH]

        results = self.discover(
            days=days, limit=100, niches=[niche_a, niche_b]
        )

        opp_a = None
        opp_b = None
        for r in results:
            if r.niche == niche_a:
                opp_a = r
            elif r.niche == niche_b:
                opp_b = r

        winner = ""
        if opp_a and opp_b:
            winner = (
                niche_a
                if opp_a.overall_score >= opp_b.overall_score
                else niche_b
            )
        elif opp_a:
            winner = niche_a
        elif opp_b:
            winner = niche_b

        return {
            "niche_a": opp_a.to_dict() if opp_a else None,
            "niche_b": opp_b.to_dict() if opp_b else None,
            "winner": winner,
            "margin": (
                abs(opp_a.overall_score - opp_b.overall_score)
                if opp_a and opp_b
                else 0.0
            ),
        }

    def clear(self):
        """Clear in-memory and on-disk discovery history."""
        with self._lock:
            self._history = []
            self._loaded = True
            self._persist()


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_engine: Optional[NicheDiscoveryEngine] = None
_default_lock = threading.Lock()


def get_default_engine() -> NicheDiscoveryEngine:
    """Return a module-level singleton engine."""
    global _default_engine
    with _default_lock:
        if _default_engine is None:
            # Try to wire up available trackers
            revenue = None
            profit = None
            trend = None
            try:
                from revenue_tracker import RevenueTracker
                revenue = RevenueTracker()
            except Exception:
                logger.debug("RevenueTracker not available")
            try:
                from profit_calculator import ProfitCalculator
                profit = ProfitCalculator(revenue_tracker=revenue)
            except Exception:
                logger.debug("ProfitCalculator not available")
            try:
                from trend_detector import TrendDetector
                trend = TrendDetector()
            except Exception:
                logger.debug("TrendDetector not available")
            _default_engine = NicheDiscoveryEngine(
                revenue_tracker=revenue,
                profit_calculator=profit,
                trend_detector=trend,
            )
        return _default_engine


def discover_niches(
    days: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[NicheOpportunity]:
    """Module-level convenience: discover top niches."""
    return get_default_engine().discover(days=days, limit=limit)

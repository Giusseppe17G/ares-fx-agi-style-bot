"""Measured decision evidence for live forward-shadow paper candidates.

The paper lifecycle requires dated broker-quality evidence before a candidate
reaches the decision pipeline, and a measured correlation once the paper book
holds positions (``lifecycle.validate_evidence``). This provider derives both
from what the current cycle actually read: the live quote and instrument
metadata, the account permission, the tick and rates read latencies and the
closed M5 bars. Nothing is filled with a default. A symbol not observed in this
cycle gets no evidence (``BROKER_EVIDENCE_MISSING``); an exposure whose
correlation cannot be measured gets ``correlation=None``, which the lifecycle
rejects as ``CORRELATION_UNVERIFIED``. Paper only: nothing here builds, checks
or sends an order.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..broker_quality.readiness_score import score_symbol_readiness
from ..contracts import MarketSnapshot
from ..core.clock import Clock, resolve_clock

EVIDENCE_VERSION = "live_decision_evidence_v1"
CORRELATION_BARS = 300
MIN_CORRELATION_RETURNS = 100
TIMEFRAMES = ("M5", "M15", "H1")


@dataclass(frozen=True)
class SymbolObservation:
    rates_available: frozenset[str]
    closed_m5_closes: pd.Series
    tick_latency_ms: int
    rates_latency_ms: int


class LiveDecisionEvidence:
    """Per-cycle evidence; call ``begin_cycle`` and ``observe_symbol`` before use."""

    def __init__(self, *, max_spread_points: float, clock: Clock | None = None) -> None:
        if not (isinstance(max_spread_points, (int, float)) and math.isfinite(max_spread_points) and max_spread_points > 0):
            raise ValueError("max_spread_points must be positive and finite")
        self.max_spread_points = float(max_spread_points)
        self.clock = resolve_clock(clock)
        self._account_trade_allowed: bool | None = None
        self._symbols: dict[str, SymbolObservation] = {}

    def begin_cycle(self, *, account_trade_allowed: Any) -> None:
        """Forget the previous cycle; evidence never carries over between cycles."""
        self._account_trade_allowed = account_trade_allowed is True
        self._symbols = {}

    def observe_symbol(self, symbol: str, bars_by_timeframe: Mapping[str, pd.DataFrame], *,
                       tick_latency_ms: int, rates_latency_ms: int) -> None:
        available = frozenset(tf for tf in TIMEFRAMES if _has_rows(bars_by_timeframe.get(tf)))
        self._symbols[symbol] = SymbolObservation(available, _closed_closes(bars_by_timeframe.get("M5")),
                                                  int(tick_latency_ms), int(rates_latency_ms))

    def __call__(self, snapshot: MarketSnapshot, features: Mapping[str, Any],
                 open_trades: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        observation = self._symbols.get(snapshot.symbol)
        if observation is None or self._account_trade_allowed is None:
            return None
        now = self.clock.now_utc()
        readiness = {
            "symbol_visible": True,
            "trade_allowed": self._account_trade_allowed,
            "spread_points": snapshot.spread_points,
            "tick_age_seconds": (now - snapshot.timestamp_utc).total_seconds(),
            "rates_available_m5": "M5" in observation.rates_available,
            "rates_available_m15": "M15" in observation.rates_available,
            "rates_available_h1": "H1" in observation.rates_available,
            "stops_level_points": snapshot.stops_level_points,
            "freeze_level_points": snapshot.freeze_level_points,
            "volume_min": snapshot.volume_min,
            "volume_step": snapshot.volume_step,
            "read_latency_ms_tick": observation.tick_latency_ms,
            "read_latency_ms_rates": observation.rates_latency_ms,
        }
        score, status, reasons = score_symbol_readiness(readiness, max_spread_points=self.max_spread_points)
        return {"observed_at_utc": now, "broker_readiness_score": score,
                "correlation": self._exposure_correlation(snapshot.symbol, open_trades),
                "evidence_version": EVIDENCE_VERSION, "readiness_status": status,
                "readiness_reasons": list(reasons)}

    def _exposure_correlation(self, symbol: str, open_trades: Sequence[Mapping[str, Any]]) -> float | None:
        """Largest absolute correlation with any open symbol, or None if any is unmeasured."""
        exposed = sorted({str(trade.get("symbol", "")) for trade in open_trades})
        if not exposed:
            return None
        values = []
        for other in exposed:
            value = 1.0 if other == symbol else self._correlation(symbol, other)
            if value is None:
                return None
            values.append(value)
        return max(values, key=abs)

    def _correlation(self, first: str, second: str) -> float | None:
        a, b = self._symbols.get(first), self._symbols.get(second)
        if a is None or b is None:
            return None
        joined = pd.concat([a.closed_m5_closes, b.closed_m5_closes], axis=1, join="inner").dropna()
        if len(joined) <= MIN_CORRELATION_RETURNS or (joined <= 0).any().any():
            return None
        returns = np.diff(np.log(joined.to_numpy(dtype=float)), axis=0)
        if not np.isfinite(returns).all() or np.std(returns[:, 0]) == 0 or np.std(returns[:, 1]) == 0:
            return None
        value = float(np.corrcoef(returns[:, 0], returns[:, 1])[0, 1])
        return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def _has_rows(frame: Any) -> bool:
    return isinstance(frame, pd.DataFrame) and not frame.empty


def _closed_closes(frame: Any) -> pd.Series:
    """Closes of closed M5 bars indexed by bar time; the last (forming) bar is dropped."""
    if not _has_rows(frame) or not {"timestamp_utc", "close"} <= set(frame.columns):
        return pd.Series(dtype=float)
    ordered = frame.sort_values("timestamp_utc").iloc[:-1]
    closes = pd.Series(pd.to_numeric(ordered["close"], errors="coerce").to_numpy(dtype=float),
                       index=pd.to_datetime(ordered["timestamp_utc"], utc=True))
    closes = closes[~closes.index.duplicated(keep="last")]
    return closes.tail(CORRELATION_BARS + 1)

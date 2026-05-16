"""Regime-aware strategy weighting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RegimeSelection:
    regime: str
    weights: Mapping[str, float]
    reasons: tuple[str, ...]


def select_for_regime(regime: str, *, spread_normal: bool = True) -> RegimeSelection:
    """Return strategy weights for a market regime."""

    normalized = regime.strip().upper()
    if normalized in {"TREND_UP", "TREND_DOWN"}:
        return RegimeSelection(
            normalized,
            {"trend_pullback": 1.4, "session_momentum": 1.1, "breakout_compression": 0.9},
            ("trend regime prioritizes pullback, momentum and breakout",),
        )
    if normalized == "RANGE":
        return RegimeSelection(
            normalized,
            {"mean_reversion": 1.3, "liquidity_sweep": 1.1, "breakout_compression": 0.5},
            ("range regime prioritizes reversion and liquidity sweeps",),
        )
    if normalized == "HIGH_VOLATILITY":
        if not spread_normal:
            return RegimeSelection(normalized, {}, ("high volatility with abnormal spread blocks strategies",))
        return RegimeSelection(
            normalized,
            {"volatility_expansion": 0.8},
            ("high volatility permits only reduced volatility expansion",),
        )
    if normalized == "LOW_VOLATILITY":
        return RegimeSelection(
            normalized,
            {"breakout_compression": 0.7},
            ("low volatility waits for compression breakout confirmation",),
        )
    if normalized in {"MARKET_CLOSED_OR_NO_TICKS", "SPREAD_DANGER", "LIQUIDITY_THIN"}:
        return RegimeSelection(normalized, {}, (f"{normalized} blocks strategy selection",))
    return RegimeSelection(normalized, {"mean_reversion": 0.5}, ("unknown regime falls back conservatively",))

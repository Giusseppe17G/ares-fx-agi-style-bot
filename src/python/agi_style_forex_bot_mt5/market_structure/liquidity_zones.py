"""Liquidity zones and sweep detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LiquidityContext:
    swept_recent_high: bool
    swept_recent_low: bool
    reclaimed_high: bool
    reclaimed_low: bool
    equal_highs: bool
    equal_lows: bool
    sweep_direction: str
    reasons: tuple[str, ...]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_liquidity_zones(frame: pd.DataFrame, *, lookback: int = 20, tolerance_points: float = 5.0, point: float = 0.00001) -> LiquidityContext:
    if frame.empty or len(frame) < 3 or not {"high", "low", "close"}.issubset(frame.columns):
        return LiquidityContext(False, False, False, False, False, False, "NONE", ("insufficient data",), False)
    recent = frame.iloc[-lookback - 1 : -1] if len(frame) > lookback else frame.iloc[:-1]
    last = frame.iloc[-1]
    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    swept_high = high > recent_high
    swept_low = low < recent_low
    reclaimed_high = swept_high and close < recent_high
    reclaimed_low = swept_low and close > recent_low
    tolerance = tolerance_points * point
    equal_highs = bool((recent["high"].astype(float).sub(recent_high).abs() <= tolerance).sum() >= 2)
    equal_lows = bool((recent["low"].astype(float).sub(recent_low).abs() <= tolerance).sum() >= 2)
    reasons: list[str] = []
    if reclaimed_high:
        reasons.append("swept recent high and reclaimed below")
    if reclaimed_low:
        reasons.append("swept recent low and reclaimed above")
    direction = "SELL_SWEEP" if reclaimed_high else "BUY_SWEEP" if reclaimed_low else "NONE"
    return LiquidityContext(swept_high, swept_low, reclaimed_high, reclaimed_low, equal_highs, equal_lows, direction, tuple(reasons), False)


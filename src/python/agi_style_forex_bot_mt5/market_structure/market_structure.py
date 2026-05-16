"""Market structure labels: HH/HL, BOS and CHOCH."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .swing_points import SwingPoint, detect_swing_points, latest_swings


@dataclass(frozen=True)
class MarketStructureContext:
    trend_structure: str
    latest_swing_high: float | None
    latest_swing_low: float | None
    higher_high: bool
    higher_low: bool
    lower_high: bool
    lower_low: bool
    break_of_structure: str
    change_of_character: str
    swings: tuple[dict[str, Any], ...]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_market_structure(frame: pd.DataFrame, *, lookback: int = 2) -> MarketStructureContext:
    if frame.empty or not {"high", "low", "close"}.issubset(frame.columns):
        return MarketStructureContext("UNKNOWN", None, None, False, False, False, False, "NONE", "NONE", (), False)
    swings = detect_swing_points(frame, lookback=lookback)
    high_swings = latest_swings(swings, kind="HIGH", limit=2)
    low_swings = latest_swings(swings, kind="LOW", limit=2)
    higher_high = len(high_swings) == 2 and high_swings[-1].price > high_swings[-2].price
    lower_high = len(high_swings) == 2 and high_swings[-1].price < high_swings[-2].price
    higher_low = len(low_swings) == 2 and low_swings[-1].price > low_swings[-2].price
    lower_low = len(low_swings) == 2 and low_swings[-1].price < low_swings[-2].price
    close = float(frame["close"].iloc[-1])
    latest_high = high_swings[-1].price if high_swings else None
    latest_low = low_swings[-1].price if low_swings else None
    bos = "BULLISH" if latest_high is not None and close > latest_high else "BEARISH" if latest_low is not None and close < latest_low else "NONE"
    trend = "UP" if higher_high and higher_low else "DOWN" if lower_high and lower_low else "RANGE"
    choch = "BEARISH" if trend == "UP" and latest_low is not None and close < latest_low else "BULLISH" if trend == "DOWN" and latest_high is not None and close > latest_high else "NONE"
    return MarketStructureContext(
        trend,
        latest_high,
        latest_low,
        higher_high,
        higher_low,
        lower_high,
        lower_low,
        bos,
        choch,
        tuple(swing.to_dict() for swing in swings[-20:]),
        False,
    )


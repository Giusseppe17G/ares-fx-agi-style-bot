"""Swing high/low detection for market structure context."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SwingPoint:
    index: int
    kind: str
    price: float
    timestamp_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_swing_points(frame: pd.DataFrame, *, lookback: int = 2) -> tuple[SwingPoint, ...]:
    """Detect local swing highs/lows from OHLC candles."""

    required = {"high", "low"}
    if frame.empty or not required.issubset(frame.columns):
        return ()
    swings: list[SwingPoint] = []
    highs = frame["high"].astype(float).to_list()
    lows = frame["low"].astype(float).to_list()
    times = frame["time"].astype(str).to_list() if "time" in frame.columns else [str(i) for i in range(len(frame))]
    for idx in range(lookback, len(frame) - lookback):
        left = slice(idx - lookback, idx)
        right = slice(idx + 1, idx + lookback + 1)
        if highs[idx] > max(highs[left]) and highs[idx] >= max(highs[right]):
            swings.append(SwingPoint(idx, "HIGH", highs[idx], times[idx]))
        if lows[idx] < min(lows[left]) and lows[idx] <= min(lows[right]):
            swings.append(SwingPoint(idx, "LOW", lows[idx], times[idx]))
    return tuple(swings)


def latest_swings(swings: tuple[SwingPoint, ...], *, kind: str, limit: int = 2) -> tuple[SwingPoint, ...]:
    selected = [swing for swing in swings if swing.kind == kind.upper()]
    return tuple(selected[-limit:])


"""Volatility and compression context."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class VolatilityContext:
    atr_percentile: float
    range_compression: bool
    expansion_candle: bool
    volatility_regime: str
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_volatility_context(frame: pd.DataFrame, *, window: int = 50) -> VolatilityContext:
    if frame.empty or not {"high", "low", "close"}.issubset(frame.columns):
        return VolatilityContext(0.0, False, False, "UNKNOWN", False)
    ranges = (frame["high"].astype(float) - frame["low"].astype(float)).abs()
    latest = float(ranges.iloc[-1])
    sample = ranges.tail(window)
    percentile = float((sample <= latest).sum() / len(sample) * 100.0) if len(sample) else 0.0
    median = float(sample.median()) if len(sample) else latest
    compression = latest < median * 0.65 if median > 0 else False
    body = abs(float(frame["close"].iloc[-1]) - float(frame["open"].iloc[-1])) if "open" in frame.columns else latest
    expansion = latest > median * 1.4 and body >= latest * 0.5 if median > 0 and latest > 0 else False
    regime = "HIGH_VOLATILITY" if percentile >= 80 else "LOW_VOLATILITY" if percentile <= 25 else "NORMAL"
    return VolatilityContext(percentile, compression, expansion, regime, False)


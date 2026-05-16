"""Price action quality features."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class PriceActionFeatures:
    wick_rejection: str
    candle_body_quality: float
    upper_wick_ratio: float
    lower_wick_ratio: float
    distance_to_ema20: float | None
    distance_to_vwap: float | None
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_price_action_features(frame: pd.DataFrame, *, ema20: float | None = None, vwap: float | None = None) -> PriceActionFeatures:
    if frame.empty or not {"open", "high", "low", "close"}.issubset(frame.columns):
        return PriceActionFeatures("NONE", 0.0, 0.0, 0.0, None, None, False)
    last = frame.iloc[-1]
    open_price = float(last["open"])
    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    candle_range = max(high - low, 1e-12)
    body = abs(close - open_price)
    upper = high - max(open_price, close)
    lower = min(open_price, close) - low
    upper_ratio = upper / candle_range
    lower_ratio = lower / candle_range
    rejection = "LOWER_WICK" if lower_ratio >= 0.45 else "UPPER_WICK" if upper_ratio >= 0.45 else "NONE"
    return PriceActionFeatures(
        rejection,
        body / candle_range,
        upper_ratio,
        lower_ratio,
        None if ema20 is None else close - ema20,
        None if vwap is None else close - vwap,
        False,
    )


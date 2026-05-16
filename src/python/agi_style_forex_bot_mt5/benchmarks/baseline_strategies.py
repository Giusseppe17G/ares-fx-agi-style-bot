"""Simple baseline strategies for competitive benchmarking."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from ..backtesting import TradeCandidate


BASELINES = (
    "BUY_AND_HOLD_PROXY",
    "RANDOM_ENTRY_WITH_SAME_FREQUENCY",
    "EMA20_EMA50_CROSS",
    "RSI_MEAN_REVERSION_SIMPLE",
    "SESSION_BREAKOUT_SIMPLE",
    "NO_TRADE_BASELINE",
)


def generate_baseline_candidates(
    name: str,
    candles: pd.DataFrame,
    *,
    symbol: str,
    frequency: int = 24,
    seed: int = 0,
) -> tuple[TradeCandidate, ...]:
    """Generate deterministic baseline trade candidates."""

    baseline = name.upper()
    bars = candles.copy()
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    if baseline == "NO_TRADE_BASELINE":
        return ()
    if baseline == "BUY_AND_HOLD_PROXY":
        return (_candidate(bars.iloc[0], symbol=symbol, direction="BUY", suffix="buy_hold"),)
    if baseline == "RANDOM_ENTRY_WITH_SAME_FREQUENCY":
        rng = np.random.default_rng(seed)
        indexes = list(range(20, max(20, len(bars) - 20), max(1, frequency)))
        return tuple(
            _candidate(bars.iloc[index], symbol=symbol, direction="BUY" if rng.random() >= 0.5 else "SELL", suffix=f"rnd_{index}")
            for index in indexes
        )
    if baseline == "EMA20_EMA50_CROSS":
        ema20 = bars["close"].ewm(span=20, adjust=False, min_periods=20).mean()
        ema50 = bars["close"].ewm(span=50, adjust=False, min_periods=50).mean()
        signals = []
        for index in range(51, len(bars)):
            if ema20.iloc[index - 1] <= ema50.iloc[index - 1] and ema20.iloc[index] > ema50.iloc[index]:
                signals.append(_candidate(bars.iloc[index], symbol=symbol, direction="BUY", suffix=f"ema_{index}"))
            elif ema20.iloc[index - 1] >= ema50.iloc[index - 1] and ema20.iloc[index] < ema50.iloc[index]:
                signals.append(_candidate(bars.iloc[index], symbol=symbol, direction="SELL", suffix=f"ema_{index}"))
        return tuple(signals)
    if baseline == "RSI_MEAN_REVERSION_SIMPLE":
        rsi = _rsi(bars["close"])
        signals = []
        for index in range(20, len(bars), max(1, frequency // 2)):
            if rsi.iloc[index] < 30:
                signals.append(_candidate(bars.iloc[index], symbol=symbol, direction="BUY", suffix=f"rsi_{index}"))
            elif rsi.iloc[index] > 70:
                signals.append(_candidate(bars.iloc[index], symbol=symbol, direction="SELL", suffix=f"rsi_{index}"))
        return tuple(signals)
    if baseline == "SESSION_BREAKOUT_SIMPLE":
        signals = []
        for index in range(24, len(bars)):
            ts = pd.Timestamp(bars.iloc[index]["timestamp"])
            if ts.hour == 7 and ts.minute == 0:
                previous = bars.iloc[index - 12 : index]
                direction = "BUY" if bars.iloc[index]["close"] > previous["high"].max() else "SELL"
                signals.append(_candidate(bars.iloc[index], symbol=symbol, direction=direction, suffix=f"session_{index}"))
        return tuple(signals)
    raise ValueError(f"unsupported baseline: {name}")


def _candidate(row: pd.Series, *, symbol: str, direction: str, suffix: str) -> TradeCandidate:
    close = float(row["close"])
    point = 0.01 if "JPY" in symbol else 0.0001
    stop = 20 * point
    target = 36 * point
    if direction == "BUY":
        sl = close - stop
        tp = close + target
    else:
        sl = close + stop
        tp = close - target
    return TradeCandidate(
        timestamp=pd.Timestamp(row["timestamp"]),
        symbol=symbol,
        direction=direction,
        sl_price=sl,
        tp_price=tp,
        signal_id=f"baseline_{suffix}",
        lot=1.0,
        metadata={"baseline": True},
    )


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.astype(float).diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)

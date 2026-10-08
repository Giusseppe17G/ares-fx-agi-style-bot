"""Causal, shared feature preparation for offline and closed-bar shadow research.

All rolling statistics are trailing. A pivot at bar t is first visible at t+2;
unconfirmed pivots are never exposed. See quant-signal-diagnostics.md for the
fixed feature definitions, which are research hypotheses, not fitted values.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..contracts import MarketSnapshot
from .indicators import add_indicators
from .market_data import MarketDataError, validate_ohlcv_frame
from .regime_detector import add_regime_labels


FEATURE_VERSION = "closed_bar_features_v1"


def prepare_strategy_features(
    bars: pd.DataFrame, *, point: float, max_spread_points: float = 25.0,
) -> pd.DataFrame:
    """Prepare a normalized history once; each row uses only its closed prefix.

Input has canonical timestamp_utc/OHLC/volume/spread_points. The caller retains
responsibility for dataset provenance and for passing closed candles only.
"""
    validate_ohlcv_frame(bars, require_spread=True)
    if not isinstance(bars["timestamp_utc"].dtype, pd.DatetimeTZDtype):
        raise MarketDataError("strategy history requires timezone-aware timestamps")
    if not math.isfinite(point) or point <= 0:
        raise MarketDataError("feature point must be finite and positive")
    if not math.isfinite(max_spread_points) or max_spread_points <= 0:
        raise MarketDataError("feature spread limit must be finite and positive")
    if bars["timestamp_utc"].duplicated().any() or not bars["timestamp_utc"].is_monotonic_increasing:
        raise MarketDataError("feature timestamps must be unique and chronological")
    frame = add_regime_labels(add_indicators(bars), max_spread_points=max_spread_points)
    high, low, close = (frame[key].astype(float) for key in ("high", "low", "close"))
    candle_range = high - low
    prior_range = candle_range.shift(1)
    prior_high = high.shift(1).rolling(20, min_periods=20).max()
    prior_low = low.shift(1).rolling(20, min_periods=20).min()
    frame["support"] = prior_low
    frame["resistance"] = prior_high
    frame["prior_high"] = prior_high
    frame["prior_low"] = prior_low
    frame["previous_close"] = close.shift(1)
    deviation = (frame["bb_upper"] - frame["bb_lower"]) / 4.0
    frame["zscore"] = (close - frame["bb_middle"]) / deviation.replace(0.0, np.nan)
    frame.loc[deviation == 0.0, "zscore"] = 0.0
    frame["compression_ratio"] = (
        prior_range.rolling(5, min_periods=5).mean()
        / prior_range.rolling(20, min_periods=20).mean().replace(0.0, np.nan)
    )
    frame["range_compression"] = frame["compression_ratio"] <= 0.65
    frame["volume_ratio"] = frame["volume"] / frame["volume"].shift(1).rolling(20, min_periods=20).mean().replace(0.0, np.nan)
    frame["atr_mean_points"] = frame["atr14"].shift(1).rolling(50, min_periods=50).mean() / point
    frame["atr_expansion_ratio"] = (frame["atr14"] / point) / frame["atr_mean_points"].replace(0.0, np.nan)
    frame["atr_percentile"] = frame["atr14"].rolling(50, min_periods=50).rank(pct=True) * 100.0
    safe_range = candle_range.replace(0.0, np.nan)
    frame["body_ratio"] = (frame["candle_body"].abs() / safe_range).fillna(0.0)
    frame["upper_wick_ratio"] = (frame["upper_wick"] / safe_range).fillna(0.0)
    frame["lower_wick_ratio"] = (frame["lower_wick"] / safe_range).fillna(0.0)
    frame["expansion_candle"] = (
        (candle_range > prior_range.rolling(50, min_periods=50).median() * 1.4)
        & (frame["body_ratio"] >= 0.5)
    )
    frame["range_points"] = (high.rolling(20, min_periods=20).max() - low.rolling(20, min_periods=20).min()) / point
    frame["swept_prev_high"] = high > prior_high
    frame["swept_prev_low"] = low < prior_low
    frame["reclaimed_high"] = frame["swept_prev_high"] & (close < prior_high)
    frame["reclaimed_low"] = frame["swept_prev_low"] & (close > prior_low)
    for kind, values, greater in (("high", high, True), ("low", low, False)):
        pivot = values.shift(2)
        if greater:
            confirmed = (pivot > values.shift(3)) & (pivot > values.shift(4)) & (pivot >= values.shift(1)) & (pivot >= values)
        else:
            confirmed = (pivot < values.shift(3)) & (pivot < values.shift(4)) & (pivot <= values.shift(1)) & (pivot <= values)
        events = pivot.where(confirmed)
        latest = events.ffill()
        previous = latest.shift(1).where(events.notna()).ffill()
        frame[f"latest_swing_{kind}"] = latest
        frame[f"previous_swing_{kind}"] = previous
    highs_up = frame["latest_swing_high"] > frame["previous_swing_high"]
    lows_up = frame["latest_swing_low"] > frame["previous_swing_low"]
    highs_down = frame["latest_swing_high"] < frame["previous_swing_high"]
    lows_down = frame["latest_swing_low"] < frame["previous_swing_low"]
    known_structure = frame[["latest_swing_high", "previous_swing_high", "latest_swing_low", "previous_swing_low"]].notna().all(axis=1)
    frame["trend_structure"] = np.select(
        [highs_up & lows_up, highs_down & lows_down, known_structure], ["UP", "DOWN", "RANGE"], default="UNKNOWN")
    frame["break_of_structure"] = np.select(
        [close > frame["latest_swing_high"], close < frame["latest_swing_low"]], ["BULLISH", "BEARISH"], default="NONE")
    frame["change_of_character"] = np.select(
        [(frame["trend_structure"] == "UP") & (close < frame["latest_swing_low"]),
         (frame["trend_structure"] == "DOWN") & (close > frame["latest_swing_high"])],
        ["BEARISH", "BULLISH"], default="NONE")
    utc = frame["timestamp_utc"].dt.tz_convert("UTC")
    days = utc.dt.floor("D")
    frame["day_high"] = high.groupby(days).cummax()
    frame["day_low"] = low.groupby(days).cummin()
    frame["previous_day_high"] = days.map(high.groupby(days).max().shift(1))
    frame["previous_day_low"] = days.map(low.groupby(days).min().shift(1))
    for name, start, end in (("asian", 0, 6), ("london", 7, 11), ("ny", 13, 20)):
        active = utc.dt.hour.between(start, end)
        frame[f"{name}_high"] = high.where(active).groupby(days).cummax().groupby(days).ffill()
        frame[f"{name}_low"] = low.where(active).groupby(days).cummin().groupby(days).ffill()
    frame["feature_point"] = point
    frame["feature_version"] = FEATURE_VERSION
    return frame


def strategy_features_at(
    frame: pd.DataFrame, idx: int, snapshot: MarketSnapshot, *, max_spread_points: float = 25.0,
) -> dict[str, Any]:
    """Extract one prepared closed candle; never examine later rows."""
    _validate_snapshot(snapshot)
    if idx < 0 or idx >= len(frame):
        raise MarketDataError("feature index is outside history")
    row = frame.iloc[idx]
    if row.get("feature_version") != FEATURE_VERSION or row.get("feature_point") != snapshot.point:
        raise MarketDataError("feature preparation version or instrument point mismatch")
    if ("symbol" in row and str(row["symbol"]) != snapshot.symbol) or ("timeframe" in row and str(row["timeframe"]) != snapshot.timeframe):
        raise MarketDataError("feature symbol or timeframe mismatch")
    if not math.isfinite(max_spread_points) or max_spread_points <= 0:
        raise MarketDataError("feature spread limit must be finite and positive")
    source_time = pd.Timestamp(row["timestamp_utc"])
    available_at = source_time + _bar_duration(snapshot.timeframe)
    decision_time = pd.Timestamp(snapshot.timestamp_utc)
    if source_time.tzinfo is None or decision_time.tzinfo is None or decision_time < available_at:
        raise MarketDataError("strategy features require a closed candle at decision time")
    numeric_names = (
        "open", "high", "low", "close", "previous_close", "ema20", "ema50", "ema200",
        "rsi14", "atr14", "atr_percent", "ema_slope", "trend_strength", "momentum", "volatility",
        "support", "resistance", "prior_high", "prior_low", "zscore", "compression_ratio",
        "volume_ratio", "atr_mean_points", "atr_expansion_ratio", "atr_percentile", "body_ratio",
        "upper_wick", "lower_wick", "upper_wick_ratio", "lower_wick_ratio", "range_points",
    )
    missing = [name for name in numeric_names if name not in row or not math.isfinite(float(row[name]))]
    if missing:
        raise MarketDataError("critical strategy features missing or non-finite: " + ", ".join(missing))
    features: dict[str, Any] = {name: float(row[name]) for name in numeric_names}
    for name in ("range_compression", "expansion_candle", "swept_prev_high", "swept_prev_low", "reclaimed_high", "reclaimed_low"):
        features[name] = bool(row[name])
    history = frame.iloc[max(0, idx - 49):idx + 1]["spread_points"].to_numpy(dtype=float)
    spread = float(snapshot.spread_points)
    percentile = 100 * (np.count_nonzero(history < spread) + 0.5 * np.count_nonzero(history == spread)) / len(history)
    features.update({
        "regime": str(row["regime"]), "trend_structure": str(row["trend_structure"]),
        "break_of_structure": str(row["break_of_structure"]),
        "change_of_character": str(row["change_of_character"]),
        "ema_fast": features["ema20"], "ema_slow": features["ema50"], "rsi": features["rsi14"],
        "atr": features["atr14"], "atr_points": features["atr14"] / snapshot.point,
        "trend_slope": features["ema_slope"], "momentum_points": features["momentum"] / snapshot.point,
        "prev_high": features["prior_high"], "prev_low": features["prior_low"],
        "follow_through_points": (features["close"] - features["previous_close"]) / snapshot.point,
        "spread_points": spread, "spread_percentile": float(percentile),
        "max_strategy_spread_points": max_spread_points, "session": _session_at(decision_time),
        "feature_version": FEATURE_VERSION, "source_bar_timestamp_utc": source_time.isoformat(),
        "available_at_utc": available_at.isoformat(),
    })
    features["wick_rejection"] = "LOWER_WICK" if features["lower_wick_ratio"] >= 0.45 else "UPPER_WICK" if features["upper_wick_ratio"] >= 0.45 else "NONE"
    features["market_structure"] = {name: features[name] for name in ("trend_structure", "break_of_structure", "change_of_character")}
    features["market_structure"].update({name: _optional_number(row[name]) for name in ("latest_swing_high", "latest_swing_low")})
    features["liquidity"] = {name: features[name] for name in ("swept_prev_high", "swept_prev_low", "reclaimed_high", "reclaimed_low")}
    features["volatility_context"] = {name: features[name] for name in ("atr_percentile", "range_compression", "expansion_candle")}
    features["price_action"] = {name: features[name] for name in ("body_ratio", "upper_wick_ratio", "lower_wick_ratio")}
    levels = {name: _optional_number(row[name]) for name in (
        "previous_day_high", "previous_day_low", "asian_high", "asian_low", "london_high", "london_low", "ny_high", "ny_low")}
    if decision_time.tz_convert("UTC").date() != source_time.tz_convert("UTC").date():
        levels = {name: None for name in levels}
        levels.update(previous_day_high=float(row["day_high"]), previous_day_low=float(row["day_low"]))
    levels.update(current_session=features["session"], execution_attempted=False)
    features["session_levels"] = levels
    return features


def build_strategy_features(
    bars: pd.DataFrame, snapshot: MarketSnapshot, *, max_spread_points: float = 25.0,
) -> dict[str, Any]:
    """Convenience wrapper for closed-bar shadow history."""
    closed = closed_strategy_bars(bars, snapshot)
    frame = prepare_strategy_features(closed, point=snapshot.point, max_spread_points=max_spread_points)
    return strategy_features_at(frame, len(frame) - 1, snapshot, max_spread_points=max_spread_points)


def closed_strategy_bars(bars: pd.DataFrame, snapshot: MarketSnapshot) -> pd.DataFrame:
    """Exclude MT5's forming candle and any future rows before calculating features."""
    _validate_snapshot(snapshot)
    if "timestamp_utc" not in bars:
        raise MarketDataError("strategy history requires timestamp_utc")
    timestamps = bars["timestamp_utc"]
    if not isinstance(timestamps.dtype, pd.DatetimeTZDtype) or timestamps.isna().any():
        raise MarketDataError("strategy history requires valid timezone-aware timestamps")
    decision_time = pd.Timestamp(snapshot.timestamp_utc)
    if decision_time.tzinfo is None:
        raise MarketDataError("strategy decision time requires timezone")
    duration = _bar_duration(snapshot.timeframe)
    closed = bars.loc[timestamps + duration <= decision_time].copy()
    validate_ohlcv_frame(closed, require_spread=True)
    if closed["timestamp_utc"].duplicated().any() or not closed["timestamp_utc"].is_monotonic_increasing:
        raise MarketDataError("closed feature timestamps must be unique and chronological")
    return closed


def _validate_snapshot(snapshot: MarketSnapshot) -> None:
    snapshot.validate()
    numeric = (snapshot.bid, snapshot.ask, snapshot.spread_points, snapshot.point,
               snapshot.tick_value, snapshot.tick_size, snapshot.volume_min,
               snapshot.volume_max, snapshot.volume_step)
    if not all(math.isfinite(value) for value in numeric):
        raise MarketDataError("strategy snapshot contains non-finite values")


def _optional_number(value: Any) -> float | None:
    return None if pd.isna(value) else float(value)


def _bar_duration(timeframe: str) -> pd.Timedelta:
    text = str(timeframe).strip().upper()
    units = {"M": 60, "H": 3600, "D": 86400, "W": 604800}
    if len(text) < 2 or text[0] not in units or not text[1:].isdigit() or int(text[1:]) <= 0:
        raise MarketDataError("unknown strategy feature timeframe duration")
    return pd.Timedelta(seconds=int(text[1:]) * units[text[0]])


def _session_at(timestamp: pd.Timestamp) -> str:
    hour = timestamp.tz_convert("UTC").hour
    if hour < 7:
        return "ASIA"
    if hour < 12:
        return "LONDON"
    if hour < 17:
        return "LONDON_NY_OVERLAP"
    if hour < 21:
        return "NEW_YORK"
    return "ROLLOVER"

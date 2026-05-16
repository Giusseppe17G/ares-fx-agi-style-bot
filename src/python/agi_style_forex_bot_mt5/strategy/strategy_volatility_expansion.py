"""Volatility expansion continuation strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import MarketSnapshot
from .scoring_engine import choose_direction, feature_float, none_signal, score_conditions, spread_is_unsafe, strategy_metadata


STRATEGY_NAME = "volatility_expansion"
STRATEGY_VERSION = "0.2.0"


def evaluate(snapshot: MarketSnapshot, features: Mapping[str, Any]) -> Any:
    """Return a StrategySignal when range expansion confirms direction."""

    try:
        snapshot.validate()
    except ValueError as exc:
        return none_signal(STRATEGY_NAME, f"invalid snapshot: {exc}")
    if spread_is_unsafe(snapshot, features):
        return none_signal(STRATEGY_NAME, "spread unsafe for strategy")

    close = feature_float(features, "close", (snapshot.bid + snapshot.ask) / 2)
    ema_fast = feature_float(features, "ema_fast", close)
    prior_high = feature_float(features, "prior_high", close)
    prior_low = feature_float(features, "prior_low", close)
    atr_points = feature_float(features, "atr_points", 0)
    atr_mean_points = feature_float(features, "atr_mean_points", 0)
    trend_slope = feature_float(features, "trend_slope", 0)
    expansion_ratio = atr_points / atr_mean_points if atr_mean_points > 0 else 0
    if expansion_ratio < 1.15 and not bool(features.get("expansion_candle", False)):
        return none_signal(STRATEGY_NAME, "volatility expansion not confirmed", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))
    if feature_float(features, "spread_percentile", 50) >= 90:
        return none_signal(STRATEGY_NAME, "spread expanded too much for volatility setup", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))

    buy_score, buy_reasons = score_conditions(
        base=8,
        conditions=(
            (expansion_ratio >= 1.20, 22, "ATR expanding above baseline"),
            (close > prior_high, 20, "new bullish range extension"),
            (close >= ema_fast, 12, "price above fast EMA"),
            (trend_slope > 0, 14, "positive trend slope"),
            (feature_float(features, "momentum_points", 0) > 0, 10, "positive expansion momentum"),
        ),
    )
    sell_score, sell_reasons = score_conditions(
        base=8,
        conditions=(
            (expansion_ratio >= 1.20, 22, "ATR expanding above baseline"),
            (close < prior_low, 20, "new bearish range extension"),
            (close <= ema_fast, 12, "price below fast EMA"),
            (trend_slope < 0, 14, "negative trend slope"),
            (feature_float(features, "momentum_points", 0) < 0, 10, "negative expansion momentum"),
        ),
    )
    return choose_direction(
        buy_score=buy_score,
        sell_score=sell_score,
        buy_reasons=buy_reasons,
        sell_reasons=sell_reasons,
        threshold=64,
        min_margin=8,
        strategy_name=STRATEGY_NAME,
        metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME, extra={"expansion_ratio": expansion_ratio}),
    )

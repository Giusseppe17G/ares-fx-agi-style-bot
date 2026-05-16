"""Compression breakout strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import MarketSnapshot
from .scoring_engine import choose_direction, feature_float, none_signal, score_conditions, spread_is_unsafe, strategy_metadata


STRATEGY_NAME = "breakout_compression"
STRATEGY_VERSION = "0.2.0"


def evaluate(snapshot: MarketSnapshot, features: Mapping[str, Any]) -> Any:
    """Return a StrategySignal when volatility compression breaks cleanly."""

    try:
        snapshot.validate()
    except ValueError as exc:
        return none_signal(STRATEGY_NAME, f"invalid snapshot: {exc}")
    if spread_is_unsafe(snapshot, features):
        return none_signal(STRATEGY_NAME, "spread unsafe for strategy")

    close = feature_float(features, "close", (snapshot.bid + snapshot.ask) / 2)
    resistance = feature_float(features, "resistance", close)
    support = feature_float(features, "support", close)
    compression_ratio = feature_float(features, "compression_ratio", 1.0)
    volume_ratio = feature_float(features, "volume_ratio", 1.0)
    momentum_points = feature_float(features, "momentum_points", 0.0)
    atr_expansion_ratio = feature_float(features, "atr_expansion_ratio", 1.0)
    body_ratio = feature_float(features, "body_ratio", 0.0)
    if compression_ratio > 0.75 and not bool(features.get("range_compression", False)):
        return none_signal(STRATEGY_NAME, "breakout requires prior compression", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))
    if body_ratio < 0.45:
        return none_signal(STRATEGY_NAME, "breakout body quality too weak", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))
    if str(features.get("session", "")).upper() == "ROLLOVER":
        return none_signal(STRATEGY_NAME, "rollover blocks breakout", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))

    buy_score, buy_reasons = score_conditions(
        base=8,
        conditions=(
            (compression_ratio <= 0.65, 22, "prior volatility compression"),
            (close > resistance, 24, "bullish resistance break"),
            (volume_ratio >= 1.10, 14, "participation above baseline"),
            (momentum_points > 0, 14, "positive breakout momentum"),
            (atr_expansion_ratio >= 1.05, 10, "volatility expanding after break"),
        ),
    )
    sell_score, sell_reasons = score_conditions(
        base=8,
        conditions=(
            (compression_ratio <= 0.65, 22, "prior volatility compression"),
            (close < support, 24, "bearish support break"),
            (volume_ratio >= 1.10, 14, "participation above baseline"),
            (momentum_points < 0, 14, "negative breakout momentum"),
            (atr_expansion_ratio >= 1.05, 10, "volatility expanding after break"),
        ),
    )
    return choose_direction(
        buy_score=buy_score,
        sell_score=sell_score,
        buy_reasons=buy_reasons,
        sell_reasons=sell_reasons,
        threshold=66,
        min_margin=10,
        strategy_name=STRATEGY_NAME,
        metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME, extra={"compression_ratio": compression_ratio}),
    )

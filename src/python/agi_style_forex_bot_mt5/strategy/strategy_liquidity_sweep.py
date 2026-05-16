"""Liquidity sweep and rejection strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import MarketSnapshot
from .scoring_engine import (
    choose_direction,
    feature_bool,
    feature_float,
    none_signal,
    score_conditions,
    spread_is_unsafe,
    strategy_metadata,
)


STRATEGY_NAME = "liquidity_sweep"
STRATEGY_VERSION = "0.2.0"


def evaluate(snapshot: MarketSnapshot, features: Mapping[str, Any]) -> Any:
    """Return a StrategySignal after failed stop-run moves."""

    try:
        snapshot.validate()
    except ValueError as exc:
        return none_signal(STRATEGY_NAME, f"invalid snapshot: {exc}")
    if spread_is_unsafe(snapshot, features):
        return none_signal(STRATEGY_NAME, "spread unsafe for strategy")

    close = feature_float(features, "close", (snapshot.bid + snapshot.ask) / 2)
    high = feature_float(features, "high", close)
    low = feature_float(features, "low", close)
    prev_high = feature_float(features, "prev_high", high)
    prev_low = feature_float(features, "prev_low", low)
    lower_wick_ratio = feature_float(features, "lower_wick_ratio", 0)
    upper_wick_ratio = feature_float(features, "upper_wick_ratio", 0)
    rsi = feature_float(features, "rsi", 50)
    if not (
        feature_bool(features, "swept_prev_low")
        or feature_bool(features, "swept_prev_high")
        or feature_bool(features, "reclaimed_low")
        or feature_bool(features, "reclaimed_high")
        or low < prev_low
        or high > prev_high
    ):
        return none_signal(STRATEGY_NAME, "liquidity sweep missing", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))
    if max(lower_wick_ratio, upper_wick_ratio) < 0.35:
        return none_signal(STRATEGY_NAME, "wick rejection missing", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))

    buy_score, buy_reasons = score_conditions(
        base=8,
        conditions=(
            (feature_bool(features, "swept_prev_low") or low < prev_low, 24, "previous low swept"),
            (close > prev_low, 20, "closed back above swept low"),
            (lower_wick_ratio >= 0.45, 16, "bullish rejection wick"),
            (rsi >= 35, 10, "momentum recovered from weak low"),
            (feature_float(features, "follow_through_points", 0) > 0, 10, "positive follow-through"),
        ),
    )
    sell_score, sell_reasons = score_conditions(
        base=8,
        conditions=(
            (feature_bool(features, "swept_prev_high") or high > prev_high, 24, "previous high swept"),
            (close < prev_high, 20, "closed back below swept high"),
            (upper_wick_ratio >= 0.45, 16, "bearish rejection wick"),
            (rsi <= 65, 10, "momentum faded from strong high"),
            (feature_float(features, "follow_through_points", 0) < 0, 10, "negative follow-through"),
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
        metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME, extra={"prev_high": prev_high, "prev_low": prev_low}),
    )

"""Range-bound mean reversion strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import MarketSnapshot, Regime
from .scoring_engine import (
    choose_direction,
    detected_regime,
    feature_float,
    none_signal,
    score_conditions,
    spread_is_unsafe,
    strategy_metadata,
)


STRATEGY_NAME = "mean_reversion"
STRATEGY_VERSION = "0.2.0"


def evaluate(snapshot: MarketSnapshot, features: Mapping[str, Any]) -> Any:
    """Return a StrategySignal when price stretches inside a range regime."""

    try:
        snapshot.validate()
    except ValueError as exc:
        return none_signal(STRATEGY_NAME, f"invalid snapshot: {exc}")
    if spread_is_unsafe(snapshot, features):
        return none_signal(STRATEGY_NAME, "spread unsafe for strategy")

    close = feature_float(features, "close", (snapshot.bid + snapshot.ask) / 2)
    support = feature_float(features, "support", close)
    resistance = feature_float(features, "resistance", close)
    rsi = feature_float(features, "rsi", 50)
    zscore = feature_float(features, "zscore", 0)
    trend_strength = abs(feature_float(features, "trend_strength", 0))
    regime = detected_regime(features)
    range_width = max(resistance - support, snapshot.point)
    if regime != Regime.RANGE:
        return none_signal(STRATEGY_NAME, "mean reversion requires RANGE regime", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))
    if feature_float(features, "atr_percentile", 50) >= 90:
        return none_signal(STRATEGY_NAME, "high volatility blocks mean reversion", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))
    if feature_text := str(features.get("break_of_structure", "NONE")).upper():
        if feature_text in {"BULLISH", "BEARISH"}:
            return none_signal(STRATEGY_NAME, "fresh breakout blocks mean reversion", metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME))

    buy_score, buy_reasons = score_conditions(
        base=8,
        conditions=(
            (regime in {Regime.RANGE, Regime.LOW_VOLATILITY}, 22, "range or low-volatility regime"),
            (rsi <= 32, 22, "oversold RSI"),
            (zscore <= -1.25, 18, "negative price stretch"),
            ((close - support) / range_width <= 0.35, 16, "price near support"),
            (trend_strength <= 0.55, 12, "trend strength not dominant"),
        ),
    )
    sell_score, sell_reasons = score_conditions(
        base=8,
        conditions=(
            (regime in {Regime.RANGE, Regime.LOW_VOLATILITY}, 22, "range or low-volatility regime"),
            (rsi >= 68, 22, "overbought RSI"),
            (zscore >= 1.25, 18, "positive price stretch"),
            ((resistance - close) / range_width <= 0.35, 16, "price near resistance"),
            (trend_strength <= 0.55, 12, "trend strength not dominant"),
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
        metadata=strategy_metadata(strategy_version=STRATEGY_VERSION, features=features, snapshot=snapshot, strategy_name=STRATEGY_NAME, extra={"regime": regime.value, "rsi": rsi, "zscore": zscore}),
    )

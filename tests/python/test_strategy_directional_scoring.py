"""Regression: score setup components against the chosen trade direction."""

from datetime import datetime, timezone

import pytest

from agi_style_forex_bot_mt5.contracts import MarketSnapshot, SignalAction, StrategySignal
from agi_style_forex_bot_mt5.strategy import (
    strategy_breakout_compression,
    strategy_liquidity_sweep,
    strategy_mean_reversion,
    strategy_session_momentum,
    strategy_trend_pullback,
    strategy_volatility_expansion,
)
from agi_style_forex_bot_mt5.strategy.strategy_ensemble import evaluate


EVALUATORS = (
    strategy_trend_pullback.evaluate,
    strategy_mean_reversion.evaluate,
    strategy_breakout_compression.evaluate,
    strategy_liquidity_sweep.evaluate,
    strategy_session_momentum.evaluate,
    strategy_volatility_expansion.evaluate,
)


def _snapshot():
    return MarketSnapshot(
        "EURUSD", "M5", datetime(2026, 1, 5, 10, tzinfo=timezone.utc),
        1.1000, 1.10005, 5, 5, 0.00001, 1.0, 0.00001,
        0.01, 100, 0.01, 10, 5,
    )


def _features(evaluator, direction):
    features = {
        "regime": "TREND_UP", "session": "LONDON", "trend_structure": "UP",
        "close": 1.1000, "previous_close": 1.0998,
        "ema_fast": 1.0999, "ema_slow": 1.0990, "trend_slope": 0.0001,
        "trend_strength": 1.0, "atr_points": 30, "atr_mean_points": 20,
        "rsi": 48, "momentum_points": 20, "range_points": 40, "body_ratio": 0.6,
        "prior_high": 1.0998, "prior_low": 1.0990,
        "spread_points": 5, "max_strategy_spread_points": 25,
    }
    if evaluator is strategy_mean_reversion.evaluate:
        features.update(regime="RANGE", support=1.099, resistance=1.11,
                        rsi=25, zscore=-2, trend_strength=0.1)
    if evaluator is strategy_breakout_compression.evaluate:
        features.update(regime="LOW_VOLATILITY", resistance=1.0999, support=1.098,
                        compression_ratio=0.6, volume_ratio=1.2, atr_expansion_ratio=1.1)
    if evaluator is strategy_liquidity_sweep.evaluate:
        features.update(regime="RANGE", high=1.101, low=1.098,
                        prev_high=1.103, prev_low=1.099, lower_wick_ratio=0.6,
                        upper_wick_ratio=0.1, follow_through_points=20)
    if direction == "SELL":
        for key in ("close", "previous_close", "ema_fast", "ema_slow"):
            features[key] = 2.2 - features[key]
        for low, high in (("prior_low", "prior_high"), ("support", "resistance"),
                          ("low", "high"), ("prev_low", "prev_high")):
            if low in features:
                features[low], features[high] = 2.2 - features[high], 2.2 - features[low]
        for key in ("trend_slope", "momentum_points", "follow_through_points", "zscore"):
            if key in features:
                features[key] *= -1
        if "lower_wick_ratio" in features:
            features["lower_wick_ratio"], features["upper_wick_ratio"] = (
                features["upper_wick_ratio"], features["lower_wick_ratio"])
        features["rsi"] = 100 - features["rsi"]
        features["trend_structure"] = "DOWN"
        if features["regime"] == "TREND_UP":
            features["regime"] = "TREND_DOWN"
    return features


@pytest.mark.parametrize("evaluator", EVALUATORS, ids=lambda item: item.__module__.split(".")[-1])
@pytest.mark.parametrize("direction", ("BUY", "SELL"))
def test_all_strategies_score_momentum_and_structure_for_selected_direction(evaluator, direction):
    signal = evaluator(_snapshot(), _features(evaluator, direction))

    assert signal.action.value == direction
    assert signal.metadata["component_scores"]["momentum_fit"] == 85.0
    assert signal.metadata["component_scores"]["structure_fit"] == 90.0


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
def test_adverse_momentum_keeps_low_component_score(direction):
    features = _features(strategy_trend_pullback.evaluate, direction)
    features["momentum_points"] *= -1
    signal = strategy_trend_pullback.evaluate(_snapshot(), features)

    assert signal.action.value == direction
    assert signal.metadata["component_scores"]["momentum_fit"] == 40.0


def test_ensemble_preserves_directional_component_and_promotion_gate():
    features = _features(strategy_session_momentum.evaluate, "BUY")
    signal = evaluate(_snapshot(), features, evaluators=(strategy_session_momentum.evaluate,))
    assert signal.action == SignalAction.BUY
    assert signal.metadata["component_scores"]["momentum_fit"] == 85.0
    assert signal.metadata["setup_quality_score"] == pytest.approx(
        sum(signal.metadata["component_scores"].values()) / len(signal.metadata["component_scores"]))

    blocked = evaluate(_snapshot(), features, mode="demo")
    assert blocked.action == SignalAction.NONE
    assert blocked.metadata["promotion_gate"]["approved"] is False


def test_ensemble_setup_quality_averages_only_winning_direction_voters():
    def child(action, score, quality):
        return lambda *_: StrategySignal(action, score, ("test",), "test", {"setup_quality_score": quality})

    signal = evaluate(_snapshot(), {"regime": "RANGE"}, evaluators=(
        child(SignalAction.BUY, 90, 60), child(SignalAction.BUY, 80, 80), child(SignalAction.SELL, 60, 10)))
    assert signal.action == SignalAction.BUY
    assert signal.metadata["setup_quality_score"] == 70
    assert signal.metadata["required_data_missing"] is False


@pytest.mark.parametrize("quality", (None, float("nan"), float("inf"), -1, 101, True))
def test_ensemble_does_not_fabricate_missing_or_invalid_setup_quality(quality):
    def child(*_):
        return StrategySignal(SignalAction.BUY, 90, ("test",), "test", {"setup_quality_score": quality})

    signal = evaluate(_snapshot(), {"regime": "RANGE"}, evaluators=(child,))
    assert "setup_quality_score" not in signal.metadata
    assert signal.metadata["required_data_missing"] is True

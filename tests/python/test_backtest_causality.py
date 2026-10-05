"""Temporal causality and spread regressions; synthetic evidence, no broker."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import backtester as bt
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import MarketSnapshot, SignalAction
from agi_style_forex_bot_mt5.core.execution import SharedFillModel
from agi_style_forex_bot_mt5.core.operational_state.errors import ExecutionSimulationError
from agi_style_forex_bot_mt5.core.parity import build_fixture, compare_pipelines
from agi_style_forex_bot_mt5.execution_simulation import SpreadModel


def bars(rows=230):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-05", periods=rows, freq="5min", tz="UTC"),
        "open": [1.1] * rows, "high": [1.1003] * rows,
        "low": [1.0997] * rows, "close": [1.1001] * rows,
        "volume": [100] * rows, "spread_points": [10.0] * rows,
    })


def snapshot(spread=0.0):
    return MarketSnapshot(
        symbol="EURUSD", timeframe="M5",
        timestamp_utc=datetime(2026, 1, 5, tzinfo=timezone.utc),
        bid=1.1, ask=1.1 + max(spread, 0) * 0.00001,
        spread_points=spread, digits=5, point=0.00001,
        tick_value=1.0, tick_size=0.00001,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=0, freeze_level_points=0,
    )


@pytest.fixture
def forced_buy(monkeypatch):
    def evaluate(snapshot, features, **kwargs):
        return SimpleNamespace(
            action=SignalAction.BUY, score=100.0, strategy_name="test_only",
            reasons=("synthetic fixture",), metadata={"setup_quality_score": 100.0,
                "component_scores": {name: 100.0 for name in ("regime_fit", "momentum_fit", "structure_fit", "volatility_fit", "session_fit", "cost_fit", "liquidity_fit", "risk_reward_fit", "broker_fit", "portfolio_fit")}},
        )
    monkeypatch.setattr(bt, "evaluate_ensemble", evaluate)


def candidates(frame):
    return bt.generate_strategy_candidates(
        frame, symbol="EURUSD", timeframe="M5",
        config=BotConfig(), point=0.00001,
    )


def test_generated_signals_cannot_fill_before_source_candle_closes(forced_buy):
    frame = bars()
    signals = candidates(frame)
    outcome = bt.Backtester().run(frame, signals)
    assert outcome.trades, "fixture must exercise entries, not pass vacuously"
    by_id = {signal.signal_id: signal for signal in signals}
    for trade in outcome.trades:
        signal = by_id[trade.signal_id]
        assert pd.Timestamp(trade.entry_time) >= pd.Timestamp(signal.timestamp) + pd.Timedelta(minutes=5)
        assert trade.metadata["available_at_utc"] == signal.available_at_utc.isoformat()


@pytest.mark.parametrize("next_bar", [False, True])
def test_explicit_availability_prevents_same_bar_profit_and_double_delay(next_bar):
    frame = bars(3)
    frame.loc[0, "high"] = 1.2  # TP before signal became available is unusable.
    frame.loc[1, "low"] = 1.08
    signal = bt.TradeCandidate(
        timestamp=frame.timestamp[0], available_at_utc=frame.timestamp[1],
        symbol="EURUSD", direction="BUY", sl_price=1.09, tp_price=1.11,
    )
    outcome = bt.Backtester(bt.BacktestSettings(use_next_bar_open=next_bar)).run(frame, [signal])
    assert len(outcome.trades) == 1
    assert outcome.trades[0].entry_time == frame.timestamp[1].isoformat()
    assert outcome.trades[0].exit_reason == "SL"
    assert outcome.trades[0].profit < 0


def test_availability_inside_bar_waits_for_next_open():
    frame = bars(3)
    signal = bt.TradeCandidate(
        timestamp=frame.timestamp[0],
        available_at_utc=frame.timestamp[0] + pd.Timedelta(minutes=2),
        symbol="EURUSD", direction="BUY", sl_price=1.09, tp_price=1.11,
    )
    outcome = bt.Backtester().run(frame, [signal])
    assert outcome.trades[0].entry_time == frame.timestamp[1].isoformat()


@pytest.mark.parametrize("available", ["NaT", "2026-01-04T00:00:00Z", "not-a-time"])
def test_invalid_availability_is_audited_rejection(available):
    frame = bars(3)
    signal = bt.TradeCandidate(
        timestamp=frame.timestamp[0], available_at_utc=available,
        symbol="EURUSD", direction="BUY", sl_price=1.09, tp_price=1.11,
    )
    outcome = bt.Backtester().run(frame, [signal])
    assert not outcome.trades
    assert outcome.rejected_candidates[0]["reason"]


def test_no_future_bar_and_future_price_override_are_rejected():
    frame = bars(2)
    signal = bt.TradeCandidate(
        timestamp=frame.timestamp[-1:].iloc[0],
        available_at_utc=frame.timestamp.iloc[-1] + pd.Timedelta(minutes=5),
        symbol="EURUSD", direction="BUY", sl_price=1.09, tp_price=1.11,
    )
    assert not bt.Backtester().run(frame, [signal]).trades
    override = replace(signal, timestamp=frame.timestamp[0],
                       available_at_utc=frame.timestamp[1], entry_price=1.1)
    outcome = bt.Backtester().run(frame, [override])
    assert not outcome.trades
    assert "entry_price" in outcome.rejected_candidates[0]["reason"]


def test_generated_candidates_are_prefix_invariant_and_reproducible(forced_buy):
    frame = bars(245)
    prefix = frame.iloc[:230].copy()
    expected = [asdict(signal) for signal in candidates(prefix)]
    full = [asdict(signal) for signal in candidates(frame)
            if signal.timestamp <= prefix.timestamp.iloc[-1]]
    assert expected and full == expected
    frame.loc[230:, ["open", "high", "low", "close"]] *= 2
    poisoned = [asdict(signal) for signal in candidates(frame)
                if signal.timestamp <= prefix.timestamp.iloc[-1]]
    assert poisoned == expected
    assert [asdict(signal) for signal in candidates(prefix)] == expected


def test_real_features_regimes_and_ensemble_ignore_future_bars():
    frame = bars(260).rename(columns={"timestamp": "timestamp_utc"})
    prefix = frame.iloc[:235]
    first = bt.prepare_strategy_features(prefix, point=0.00001)
    full = bt.prepare_strategy_features(frame, point=0.00001)
    pd.testing.assert_frame_equal(first, full.iloc[:235])
    cfg = BotConfig()
    # No mocked strategy: exercise the actual ensemble on equal past data.
    for idx in (220, 225, 234):
        snap = bt._snapshot_from_row(first.iloc[idx], symbol="EURUSD", timeframe="M5", point=0.00001, config=cfg)
        snap = replace(snap, timestamp_utc=(pd.Timestamp(snap.timestamp_utc) + pd.Timedelta(minutes=5)).to_pydatetime())
        left = bt._features_from_row(first, idx, snap, cfg)
        right = bt._features_from_row(full, idx, snap, cfg)
        assert left == right
        assert bt.evaluate_ensemble(snap, left, mode="shadow") == bt.evaluate_ensemble(snap, right, mode="shadow")


@pytest.mark.parametrize("timeframe", ["M0", "H-1", "MN1", "unknown"])
def test_unknown_or_invalid_bar_duration_fails_closed(timeframe):
    with pytest.raises(ValueError):
        bt.generate_strategy_candidates(
            bars(), symbol="EURUSD", timeframe=timeframe,
            config=BotConfig(), point=0.00001,
        )


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_zero_spread_is_real_data_and_fills_in_shared_model(direction):
    estimate = SpreadModel().estimate(symbol="EURUSD", snapshot=snapshot())
    assert estimate.spread_regime == "NORMAL"
    assert estimate.expected_spread == estimate.p95_spread == estimate.p99_spread == 0.0
    model = SharedFillModel(slippage_points=0.0)
    result = model.entry(direction=direction, snapshot=snapshot(), lot=0.1, replay=True)
    assert result.accepted
    assert result.fill_price == 1.1
    assert result.metadata["spread_model_used"]["expected_spread"] == 0.0


@pytest.mark.parametrize("profile", [
    {"symbols": {"EURUSD": {"spread_median": 0, "spread_p95": 0, "spread_p99": 0}}},
    {"by_symbol": {"EURUSD": {"spread_median": 0, "spread_p95": 0, "spread_p99": 0}}},
    {"symbol": "EURUSD", "spread_median": 0, "spread_p95": 0, "spread_p99": 0},
])
def test_zero_profile_values_and_all_supported_shapes_are_preserved(profile):
    estimate = SpreadModel(broker_cost_profile=profile).estimate(symbol="EURUSD")
    assert estimate.source == "profile"
    assert estimate.expected_spread == estimate.p95_spread == estimate.p99_spread == 0
    assert estimate.trade_allowed_by_spread


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), -float("inf"), "bad"])
@pytest.mark.parametrize("source", ["current", "observed", "profile"])
def test_invalid_spread_evidence_never_approves(value, source):
    kwargs = {}
    profile = None
    if source == "current":
        kwargs["snapshot"] = replace(snapshot(), spread_points=value)
    elif source == "observed":
        kwargs["forward_spreads"] = [0.0, value]
    else:
        profile = {"symbols": {"EURUSD": {"spread_p95": value}}}
    estimate = SpreadModel(broker_cost_profile=profile).estimate(symbol="EURUSD", **kwargs)
    assert not estimate.trade_allowed_by_spread
    assert estimate.reject_reason


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_spread_limit_is_rejected(value):
    with pytest.raises(ValueError):
        SpreadModel(max_spread_points=value)


def test_absent_spread_is_not_equivalent_to_zero():
    estimate = SpreadModel().estimate(symbol="EURUSD")
    assert not estimate.trade_allowed_by_spread
    assert estimate.reject_reason == "SPREAD_DATA_MISSING"
    observed = SpreadModel().estimate(symbol="EURUSD", forward_spreads=[0.0])
    assert observed.trade_allowed_by_spread
    assert observed.source == "observed"


@pytest.mark.parametrize("stats", [
    {"spread_median": 0}, {"spread_median": 100}, {"spread_p99": 100},
])
def test_incomplete_profile_cannot_manufacture_p95_at_the_limit(stats):
    estimate = SpreadModel(broker_cost_profile={"symbol": "EURUSD", **stats}).estimate(symbol="EURUSD")
    assert not estimate.trade_allowed_by_spread
    assert estimate.reject_reason == "SPREAD_DATA_MISSING"


def test_spread_exactly_at_limit_and_above_limit():
    model = SharedFillModel(max_spread_points=25, slippage_points=0)
    assert model.entry(direction="BUY", snapshot=snapshot(25), replay=True).accepted
    result = model.entry(direction="BUY", snapshot=snapshot(25.01), replay=True)
    assert not result.accepted


def test_csv_spread_validation_and_zero(tmp_path):
    path = tmp_path / "spreads.csv"
    path.write_text("spread\n0\n0\n", encoding="utf-8")
    model = SpreadModel()
    estimate = model.estimate(symbol="EURUSD", historical_csv=path)
    assert estimate.trade_allowed_by_spread and estimate.p95_spread == 0
    path.write_text("spread\n0\nnan\n", encoding="utf-8")
    assert not model.estimate(symbol="EURUSD", historical_csv=path).trade_allowed_by_spread
    assert not model.estimate(symbol="EURUSD", historical_csv=tmp_path / "missing.csv").trade_allowed_by_spread


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_bar_spread_is_audited_instead_of_using_fallback(value):
    frame = bars(3)
    frame.loc[0, "spread_points"] = value
    signal = bt.TradeCandidate(
        timestamp=frame.timestamp[0], symbol="EURUSD", direction="BUY",
        sl_price=1.09, tp_price=1.11,
    )
    outcome = bt.Backtester().run(frame, [signal])
    assert not outcome.trades
    assert "spread" in outcome.rejected_candidates[0]["reason"]


@pytest.mark.parametrize("field", ["lot", "sl_price", "tp_price"])
def test_nonfinite_trade_geometry_is_rejected(field):
    frame = bars(3)
    signal = bt.TradeCandidate(
        timestamp=frame.timestamp[0], symbol="EURUSD", direction="BUY",
        sl_price=1.09, tp_price=1.11,
    )
    outcome = bt.Backtester().run(frame, [replace(signal, **{field: float("nan")})])
    assert not outcome.trades and outcome.rejected_candidates


@pytest.mark.parametrize("price_function", [bt._apply_entry_cost, bt._apply_exit_cost])
def test_shared_fill_preserves_limit_and_rounds_both_sides(price_function):
    with pytest.raises(ExecutionSimulationError):
        price_function(1.1, direction="BUY", spread_points=26,
                       slippage_points=0, point=0.00001)
    # The half-point rounding must match the shared model on exits too.
    price = price_function(1.1, direction="BUY", spread_points=9,
                           slippage_points=0, point=0.00001)
    snap = bt._replay_snapshot(1.1, spread_points=9, point=0.00001)
    model = SharedFillModel(slippage_points=0)
    method = model.entry if price_function == bt._apply_entry_cost else model.exit
    assert price == method(direction="BUY", snapshot=snap, replay=True).fill_price


def test_cost_model_rejects_nonfinite_assumptions():
    with pytest.raises(ValueError, match="finite"):
        bt.Backtester(bt.BacktestSettings(cost_model=bt.CostModel(tick_value=float("nan"))))


def test_parity_rejects_truncated_fixtures_and_empty_never_passes():
    fixture = build_fixture(bars=2)
    with pytest.raises(ValueError, match="one feature"):
        compare_pipelines(replace(fixture, features=fixture.features[:1]))
    result = compare_pipelines(replace(fixture, snapshots=(), features=()))
    assert result["parity_status"] == "PARITY_BELOW_THRESHOLD"
    assert result["full_pipeline_verified"] is False


def test_adapter_stages_are_not_counted_as_shared_implementations():
    result = compare_pipelines(build_fixture(bars=2))
    stages = {stage["stage_id"]: stage for stage in result["stages"]}
    for name in ("market_data", "persistence", "metrics"):
        assert stages[name]["scope"] == "ADAPTER_REQUIRED"
        assert stages[name]["same"] is False
    assert result["stage_parity_pct"] == 43.75
    assert result["parity_status"] == "PARITY_INCOMPLETE"

"""Actual indicator/strategy/fill integration on explicitly synthetic candles."""
from dataclasses import replace
import json
import math

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting.backtester import CostModel
from agi_style_forex_bot_mt5.core.instruments import InstrumentSpec
from agi_style_forex_bot_mt5.research.experiment_plan import (
    ExperimentPlan, ResearchManagement, build_experiment_plan, dataframe_sha256,
)
from agi_style_forex_bot_mt5.research.trend_pullback_evaluator import (
    evaluate_trend_pullback, generate_trend_pullback_candidates,
)
from agi_style_forex_bot_mt5.strategy.strategy_trend_pullback import TrendPullbackResearchParams


def research_bars(count=1200):
    x = np.arange(count)
    close = 1.1 + x * .00001 + .00015 * np.sin(x / 3)
    opening = close - .00001 * np.cos(x)
    return pd.DataFrame({"timestamp_utc": pd.date_range("2026-01-05", periods=count, freq="5min", tz="UTC"),
        "open": opening, "high": np.maximum(opening, close)+.0001,
        "low": np.minimum(opening, close)-.0001, "close": close,
        "volume": 100+x%30, "spread_points": np.full(count, 5.)})


def research_inputs(bars=None, **changes):
    bars = research_bars() if bars is None else bars
    spec = InstrumentSpec("EURUSD", "EURUSD", "EURUSD", 5, .00001, .00001, 1., 100000., .01, 100., .01, 10, 5, "EUR", "USD", "SYNTHETIC_FIXTURE")
    values = dict(datasets={"EURUSD": bars}, instruments={"EURUSD": spec},
        cost_models={"EURUSD": CostModel(spread_points=5, slippage_points=1, commission_per_lot_round_turn=4)},
        data_provenance={"EURUSD": {"source_sha256": "1"*64, "provider": "SYNTHETIC_FIXTURE", "quality_report": {"synthetic": True}, "tick_value_currency": "USD", "tick_value_status": "ASSUMED"}},
        cost_provenance={"EURUSD": {"source": "SYNTHETIC_FIXTURE", "assumptions": ["synthetic constant costs"], "commission_currency": "USD", "swap_mode": "NOT_MODELED", "status": "ASSUMED"}},
        code_commit="2"*40, source_sha256="3"*64, data_role="SYNTHETIC_FIXTURE", lot=.1,
        denomination_currency="USD", management=ResearchManagement(max_holding_bars=12))
    return {**values, **changes}


def generation(bars, **changes):
    values = research_inputs(bars)
    arguments = dict(symbol="EURUSD", params=TrendPullbackResearchParams(),
        instrument=values["instruments"]["EURUSD"], cost_model=values["cost_models"]["EURUSD"],
        management=values["management"], lot=.1, window_start=bars.iloc[300].timestamp_utc,
        window_end=bars.iloc[-1].timestamp_utc+pd.Timedelta(minutes=5))
    return generate_trend_pullback_candidates(bars, **{**arguments, **changes})


def evaluate_cell(plan, bars, split="validation", hypothesis=0):
    return evaluate_trend_pullback(plan, bars, symbol="EURUSD", hypothesis_id=plan.hypotheses[hypothesis].hypothesis_id, split=split)


def test_actual_strategy_trades_and_independent_partition_metrics():
    bars = research_bars()
    plan = build_experiment_plan(**research_inputs(bars))
    results = [evaluate_cell(plan, bars, split=name) for name in ("train", "validation", "development_test")]
    assert all(result.outcome.trades for result in results)
    assert len({result.outcome.metrics.net_profit for result in results}) > 1
    for result, window in zip(results, plan.splits):
        assert result.to_dict()["promotion_eligible"] is False
        assert result.to_dict()["denomination_currency"] == "USD"
        assert result.outcome.settings.parameters["strategy_params"]["min_score"] == 62
        assert all(pd.Timestamp(t.entry_time) >= pd.Timestamp(window.start_utc) for t in result.outcome.trades)
        assert all(pd.Timestamp(t.exit_time)+pd.Timedelta(minutes=5) <= pd.Timestamp(window.end_utc) for t in result.outcome.trades)
        assert result.outcome.metrics.net_profit == pytest.approx(sum(t.profit for t in result.outcome.trades))
        json.dumps(result.to_dict(), allow_nan=False)


def test_all_three_thresholds_are_consumed_and_identity_is_repeatable():
    bars = research_bars()
    plan = build_experiment_plan(**research_inputs(bars))
    results = [evaluate_cell(plan, bars, hypothesis=i) for i in range(3)]
    assert len({x.evaluation_id for x in results}) == 3
    assert [x.outcome.settings.parameters["strategy_params"]["min_score"] for x in results] == [62,70,78]
    assert len(results[2].outcome.trades) < len(results[0].outcome.trades)
    assert evaluate_cell(plan, bars).to_dict() == results[0].to_dict()


def test_future_prices_and_prefix_cannot_change_prior_signals():
    bars = research_bars(900)
    cutoff = bars.iloc[600].timestamp_utc
    full = generation(bars)
    mutated = bars.copy(deep=True)
    mutated.loc[601:, ["open", "high", "low", "close"]] *= 2
    mutated.loc[601:, "volume"] *= 10
    changed = generation(mutated)
    prefix = generation(bars.iloc[:650])
    def prior_candidates(result):
        return [x for x in result.candidates if pd.Timestamp(x.timestamp) <= cutoff]
    def prior_decisions(result):
        return [x for x in result.decisions if pd.Timestamp(x["source_bar_timestamp_utc"]) <= cutoff]
    assert prior_candidates(full) and prior_candidates(full) == prior_candidates(changed) == prior_candidates(prefix)
    assert prior_decisions(full) == prior_decisions(changed) == prior_decisions(prefix)


def test_horizon_is_excluded_before_strategy_or_exit_is_known():
    bars = research_bars(500)
    result = generation(bars)
    rejected = [x for x in result.decisions if x["reason"] == "INCOMPLETE_EXIT_HORIZON"]
    assert len(rejected) == 11  # Last source is separately outside decision interval.
    assert all("action" not in x and "score" not in x for x in rejected)
    altered = bars.copy(deep=True)
    altered.loc[488:, ["open", "high", "low", "close"]] *= 4
    changed = generation(altered)
    assert [(x["source_bar_timestamp_utc"], x["reason"]) for x in rejected] == [(x["source_bar_timestamp_utc"], x["reason"]) for x in changed.decisions if x["reason"] == "INCOMPLETE_EXIT_HORIZON"]
    assert all(pd.Timestamp(x["horizon_end_utc"]) <= bars.iloc[-1].timestamp_utc+pd.Timedelta(minutes=5) for x in result.decisions if x["status"] == "CANDIDATE")


def test_warmup_never_generates_a_trade_and_uses_only_previous_250_rows():
    bars = research_bars(600)
    result = generation(bars)
    start = bars.iloc[300].timestamp_utc
    assert result.candidates and all(pd.Timestamp(x.timestamp) >= start for x in result.candidates)
    assert all(pd.Timestamp(x["source_bar_timestamp_utc"]) >= start for x in result.decisions)
    changed = bars.copy(deep=True)
    changed.loc[:49, ["open", "high", "low", "close"]] *= 3
    assert generation(changed) == result


def test_plan_binding_rejects_changed_future_even_when_past_signals_would_match():
    bars = research_bars()
    plan = build_experiment_plan(**research_inputs(bars))
    changed = bars.copy(deep=True)
    changed.loc[1100:, "volume"] += 1
    with pytest.raises(ValueError, match="differ from plan"):
        evaluate_cell(plan, changed, split="train")


def test_insufficient_history_is_recorded_without_inventing_trades():
    bars = research_bars(20)
    plan = build_experiment_plan(**research_inputs(bars))
    result = evaluate_cell(plan, bars, split="train")
    assert result.status == "INSUFFICIENT_DATA"
    assert not result.outcome.trades
    assert result.decisions and all(x["status"] == "REJECTED" for x in result.decisions)


@pytest.mark.parametrize("name,value", [("net_profit", math.inf), ("max_drawdown_pct", math.nan), ("profit_factor", math.inf)])
def test_unexpected_nonfinite_economics_cannot_be_a_successful_json_result(name, value):
    bars = research_bars()
    result = evaluate_cell(build_experiment_plan(**research_inputs(bars)), bars)
    # The fixture includes both outcomes, so an infinite PF here is also invalid.
    assert any(t.profit < 0 for t in result.outcome.trades)
    poisoned = replace(result, outcome=replace(result.outcome, metrics=replace(result.outcome.metrics, **{name:value})))
    with pytest.raises(ValueError, match="nonfinite"):
        poisoned.to_dict()


def test_invalid_trade_profit_cannot_be_hidden_as_null():
    bars = research_bars()
    result = evaluate_cell(build_experiment_plan(**research_inputs(bars)), bars)
    poisoned_trade = replace(result.outcome.trades[0], profit=math.nan)
    poisoned = replace(result, outcome=replace(result.outcome, trades=(poisoned_trade,)))
    with pytest.raises(ValueError, match="nonfinite"):
        poisoned.to_dict()


def test_roundtrip_is_strict_and_does_not_expose_mutable_configuration():
    plan = build_experiment_plan(**research_inputs())
    payload = plan.to_dict()
    payload["management"]["max_holding_bars"] = 1
    assert plan.to_dict()["management"]["max_holding_bars"] == 12
    assert ExperimentPlan.from_json(plan.canonical_json) == plan
    with pytest.raises(ValueError):
        ExperimentPlan.from_json(plan.canonical_json.replace('"lot":0.1', '"lot":NaN'))


def test_overflow_from_finite_but_impossible_monetary_scale_fails():
    bars = research_bars()
    values = research_inputs(bars)
    values["instruments"]["EURUSD"] = replace(values["instruments"]["EURUSD"], tick_value=1e308)
    values["cost_models"]["EURUSD"] = replace(values["cost_models"]["EURUSD"], tick_value=1e308)
    plan = build_experiment_plan(**values)
    with pytest.raises((ValueError, OverflowError)):
        evaluate_cell(plan, bars)


@pytest.mark.parametrize("mode", ["MODELED", "NONE", "", True])
def test_swap_cannot_be_reported_as_a_modeled_cost(mode):
    values = research_inputs()
    values["cost_provenance"]["EURUSD"]["swap_mode"] = mode
    with pytest.raises(ValueError):
        build_experiment_plan(**values)


def test_empty_partition_is_insufficient_without_fake_market_dates():
    bars = research_bars(1)
    plan = build_experiment_plan(**research_inputs(bars))
    for split in plan.splits:
        result = evaluate_cell(plan, bars, split=split.name)
        assert result.status == "INSUFFICIENT_DATA" and not result.outcome.trades

"""Independent research review with synthetic inputs and real evaluations."""

from dataclasses import replace
import json

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting.backtester import CostModel
from agi_style_forex_bot_mt5.contracts import SignalAction
from agi_style_forex_bot_mt5.core.instruments import InstrumentSpec
from agi_style_forex_bot_mt5.research.experiment_plan import (
    ExperimentPlan, ResearchManagement, build_experiment_plan, validate_plan_datasets,
)
from agi_style_forex_bot_mt5.strategy import strategy_trend_pullback as strategy
from agi_style_forex_bot_mt5.strategy.strategy_trend_pullback import TrendPullbackResearchParams

from test_strategy_directional_scoring import _features, _snapshot
from test_shared_strategy_features import _bars


def study_inputs(datasets=None, **changes):
    datasets = datasets or {"EURUSD": _bars(800)}
    instruments = {symbol: InstrumentSpec(symbol, symbol, symbol+".fixture", 5, .00001,
        .00001, 1., 100000., .01, 100., .01, 10, 5, symbol[:3], symbol[3:], "SYNTHETIC_FIXTURE")
        for symbol in datasets}
    kwargs = dict(datasets=datasets, instruments=instruments,
        cost_models={symbol: CostModel(spread_points=5, slippage_points=1, commission_per_lot_round_turn=4) for symbol in datasets},
        data_provenance={symbol: {"source_sha256": "1"*64, "provider": "SYNTHETIC_FIXTURE", "quality_report": {"scope": "SYNTHETIC"}, "tick_value_currency": "USD", "tick_value_status": "ASSUMED"} for symbol in datasets},
        cost_provenance={symbol: {"source": "SYNTHETIC_FIXTURE", "assumptions": ["fixed fixture costs"], "commission_currency": "USD", "swap_mode": "NOT_MODELED", "status": "ASSUMED"} for symbol in datasets},
        code_commit="2"*40, source_sha256="3"*64, data_role="SYNTHETIC_FIXTURE", lot=.1,
        denomination_currency="USD",
        management=ResearchManagement(max_holding_bars=12))
    return {**kwargs, **changes}


def study_plan(**kwargs):
    return build_experiment_plan(**study_inputs(**kwargs))


@pytest.mark.parametrize("direction,rsi,parameter,value", [
    ("BUY", 39, "rsi_buy_min", 40), ("BUY", 57, "rsi_buy_max", 56),
    ("SELL", 43, "rsi_sell_min", 44), ("SELL", 61, "rsi_sell_max", 60),
])
def test_each_rsi_parameter_changes_an_actual_strategy_decision(direction, rsi, parameter, value):
    features = {**_features(strategy.evaluate, direction), "rsi": rsi}
    original = TrendPullbackResearchParams(min_score=78)
    baseline = strategy.evaluate(_snapshot(), features, params=original)
    changed = strategy.evaluate(_snapshot(), features, params=replace(original, **{parameter: value}))
    assert baseline.action.value == direction and baseline.score == 92
    assert changed.action is SignalAction.NONE


def test_min_score_changes_actual_acceptance_without_other_parameter_changes():
    features = _features(strategy.evaluate, "BUY")
    original = TrendPullbackResearchParams()
    assert strategy.evaluate(_snapshot(), features, params=original).action is SignalAction.BUY
    assert strategy.evaluate(_snapshot(), features, params=replace(original, min_score=93)).action is SignalAction.NONE


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
def test_optional_defaults_preserve_existing_evaluator_behavior(direction):
    features = _features(strategy.evaluate, direction)
    assert strategy.evaluate(_snapshot(), features) == strategy.evaluate(_snapshot(), features,
        params=TrendPullbackResearchParams())


@pytest.mark.parametrize("values", [
    {"ema_fast": 20}, {"risk_pct": .01}, {"sl_atr": 2}, {"min_score": float("nan")},
    {"rsi_buy_min": True}, {"rsi_sell_max": float("inf")},
    {"rsi_buy_min": 60, "rsi_buy_max": 58}, {"rsi_sell_min": -1},
])
def test_unsupported_or_invalid_research_parameters_fail_closed(values):
    with pytest.raises(ValueError):
        TrendPullbackResearchParams.from_dict(values)


def test_common_partition_is_elapsed_time_not_symbol_row_percentiles():
    eurusd = _bars(800)
    gbpusd = _bars(760).iloc[20:].drop(index=list(range(30, 400, 3))).reset_index(drop=True)
    plan = study_plan(datasets={"EURUSD": eurusd, "GBPUSD": gbpusd})
    cuts = plan.splits
    start = gbpusd.iloc[0].timestamp_utc
    end = gbpusd.iloc[-1].timestamp_utc + pd.Timedelta(minutes=5)
    duration = end - start
    assert pd.Timestamp(cuts[0].start_utc) == start
    assert pd.Timestamp(cuts[0].end_utc) == start + duration * .6
    assert pd.Timestamp(cuts[1].start_utc) == pd.Timestamp(cuts[0].end_utc)
    assert pd.Timestamp(cuts[1].end_utc) == start + duration * .8
    assert pd.Timestamp(cuts[2].start_utc) == pd.Timestamp(cuts[1].end_utc)
    assert pd.Timestamp(cuts[2].end_utc) == end
    assert plan.to_dict()["datasets"]["EURUSD"]["split_bindings"]["train"]["rows"] != plan.to_dict()["datasets"]["GBPUSD"]["split_bindings"]["train"]["rows"]


@pytest.mark.parametrize("fault", ("reversed", "duplicate", "naive", "overlap", "inconsistent_symbol"))
def test_plan_rejects_ambiguous_or_reordered_time_without_repair(fault):
    bars = _bars(800)
    if fault == "reversed":
        bars = bars.iloc[::-1]
    elif fault == "duplicate":
        bars.loc[400, "timestamp_utc"] = bars.loc[399, "timestamp_utc"]
    elif fault == "naive":
        bars["timestamp_utc"] = bars["timestamp_utc"].dt.tz_localize(None)
    elif fault == "overlap":
        bars.loc[400, "timestamp_utc"] -= pd.Timedelta(minutes=1)
    else:
        bars["symbol"] = "GBPUSD"
    before = bars.copy(deep=True)
    with pytest.raises(ValueError):
        study_plan(datasets={"EURUSD": bars})
    pd.testing.assert_frame_equal(bars, before)


def test_plan_canonical_payload_cannot_be_mutated_through_exposed_copies():
    inputs = study_inputs()
    plan = build_experiment_plan(**inputs)
    original = plan.canonical_json
    exposed = plan.to_dict()
    exposed["datasets"]["EURUSD"]["cost_model"]["commission_per_lot_round_turn"] = 0
    inputs["data_provenance"]["EURUSD"]["provider"] = "changed"
    assert plan.canonical_json == original
    assert ExperimentPlan.from_json(original).plan_id == plan.plan_id


@pytest.mark.parametrize("field", ("open", "volume", "spread_points", "timestamp_utc"))
def test_post_plan_data_changes_reject_instead_of_rebinding(field):
    inputs = study_inputs()
    plan = build_experiment_plan(**inputs)
    bars = inputs["datasets"]["EURUSD"].copy(deep=True)
    if field == "timestamp_utc":
        bars["timestamp_utc"] += pd.Timedelta(days=1)
    elif field == "volume":
        bars.loc[400, field] += 1
    else:
        bars.loc[400, field] += .000001
    with pytest.raises(ValueError, match="differ from plan"):
        validate_plan_datasets(plan, {"EURUSD": bars})


@pytest.mark.parametrize("lot", (.005, .015, 101, True, float("nan")))
def test_fixed_lot_must_be_executable_under_frozen_instrument(lot):
    with pytest.raises(ValueError):
        study_plan(lot=lot)


@pytest.mark.parametrize("field,value", [("point", .001), ("tick_size", .001), ("tick_value", 2)])
def test_cost_geometry_cannot_silently_replace_instrument_geometry(field, value):
    costs = {"EURUSD": replace(CostModel(), **{field: value})}
    with pytest.raises(ValueError, match="differs from instrument"):
        study_plan(cost_models=costs)


@pytest.mark.parametrize("change", ("holdout", "selection", "split", "warmup", "extra_parameter"))
def test_serialized_plan_cannot_change_predeclared_protocol(change):
    payload = study_plan().to_dict()
    if change == "holdout":
        payload["data_role"] = "FINAL_HOLDOUT"
    elif change == "selection":
        payload["selection_policy"] = "BEST_TEST_RESULT"
    elif change == "split":
        payload["splits"][1]["start_utc"] = payload["splits"][0]["start_utc"]
    elif change == "warmup":
        payload["warmup_bars"] = 200
    else:
        payload["hypotheses"][0]["params"]["ema_fast"] = 10
    with pytest.raises(ValueError):
        ExperimentPlan.from_json(json.dumps(payload))


@pytest.mark.parametrize("text", ('[]', '{"x":1,"x":2}', '{"initial_balance":NaN}', '{"initial_balance":1e999}'))
def test_noncanonical_json_cannot_become_an_executable_plan(text):
    with pytest.raises(ValueError):
        ExperimentPlan.from_json(text)


@pytest.mark.parametrize("location,field,value", [
    (None, "denomination_currency", "usd"), (None, "denomination_currency", "USＤ"),
    ("data_provenance", "tick_value_currency", "EUR"),
    ("cost_provenance", "commission_currency", "EUR"),
    ("data_provenance", "tick_value_currency", None),
    ("cost_provenance", "commission_currency", None),
])
def test_monetary_units_cannot_be_missing_or_implicitly_converted(location, field, value):
    inputs = study_inputs()
    if location is None:
        inputs[field] = value
    elif value is None:
        inputs[location]["EURUSD"].pop(field)
    else:
        inputs[location]["EURUSD"][field] = value
    with pytest.raises(ValueError):
        build_experiment_plan(**inputs)


@pytest.mark.parametrize("field,value", [("point", .00002), ("tick_size", .000015)])
def test_incoherent_broker_price_geometry_cannot_be_predeclared(field, value):
    inputs = study_inputs()
    inputs["instruments"]["EURUSD"] = replace(inputs["instruments"]["EURUSD"], **{field: value})
    inputs["cost_models"]["EURUSD"] = replace(inputs["cost_models"]["EURUSD"], **{field: value})
    with pytest.raises(ValueError):
        build_experiment_plan(**inputs)


def actual_source_plan(inputs=None):
    from agi_style_forex_bot_mt5.research.predeclared_runner import current_source_manifest
    inputs = inputs or study_inputs()
    manifest = current_source_manifest()
    inputs.update(code_commit=manifest.git_commit_sha, source_sha256=manifest.source_tree_hash)
    return build_experiment_plan(**inputs), inputs["datasets"]


def test_runner_persists_plan_before_every_real_evaluation(tmp_path, monkeypatch):
    from agi_style_forex_bot_mt5.research import predeclared_runner as runner
    plan, datasets = actual_source_plan()
    output = tmp_path / "research"
    original = runner.evaluate_trend_pullback
    observed = []

    def observe(plan_arg, bars, **kwargs):
        assert (output / "plan.json").read_text() == plan.canonical_json
        assert (output / "inputs.json").is_file() and (output / "manifest.json").is_file()
        journal = [json.loads(line) for line in (output / "journal.jsonl").read_text().splitlines()]
        assert journal[0]["event_type"] == "PLAN_PERSISTED"
        assert journal[-1]["event_type"] == "EVALUATION_STARTED"
        observed.append((kwargs["hypothesis_id"], kwargs["symbol"], kwargs["split"]))
        return original(plan_arg, bars, **kwargs)

    monkeypatch.setattr(runner, "evaluate_trend_pullback", observe)
    result = runner.run_predeclared_research(plan, datasets, output_dir=output).to_dict()
    assert result["status"] == "COMPLETED", result
    assert len(set(observed)) == 9 and result["cell_count"] == 9
    assert result["selected_hypothesis_id"] is None
    assert result["full_pipeline_verified"] is False and result["execution_authorized"] is False
    assert result["promotion_eligible"] is False
    assert result["final_holdout"] == "NOT_AVAILABLE"
    assert result["raw_source_hash_verified"] is False


def test_changed_source_hash_blocks_before_any_result_directory(tmp_path):
    from agi_style_forex_bot_mt5.research.predeclared_runner import run_predeclared_research
    plan, datasets = actual_source_plan()
    payload = plan.to_dict()
    payload["source_sha256"] = "4"*64
    changed = ExperimentPlan.from_json(json.dumps(payload))
    output = tmp_path / "blocked"
    with pytest.raises(ValueError, match="SOURCE_BINDING_MISMATCH"):
        run_predeclared_research(changed, datasets, output_dir=output)
    assert not output.exists()


def test_last_evaluation_cannot_complete_after_persisted_plan_changes(tmp_path, monkeypatch):
    from agi_style_forex_bot_mt5.research import predeclared_runner as runner
    plan, datasets = actual_source_plan()
    output = tmp_path / "research"
    original = runner.evaluate_trend_pullback
    calls = []

    def change_last(plan_arg, bars, **kwargs):
        result = original(plan_arg, bars, **kwargs)
        calls.append(True)
        if len(calls) == 9:
            (output / "plan.json").write_text("{}", encoding="utf-8")
        return result

    monkeypatch.setattr(runner, "evaluate_trend_pullback", change_last)
    result = runner.run_predeclared_research(plan, datasets, output_dir=output).to_dict()
    assert len(calls) == 9
    assert result["status"] == "INCOMPLETE"
    assert result["cells"][-1]["status"] == "FAILED"


def candidate_generation(bars, *, start=None, end=None):
    from agi_style_forex_bot_mt5.research.trend_pullback_evaluator import generate_trend_pullback_candidates
    inputs = study_inputs({"EURUSD": bars})
    return generate_trend_pullback_candidates(bars, symbol="EURUSD",
        params=TrendPullbackResearchParams(), instrument=inputs["instruments"]["EURUSD"],
        cost_model=inputs["cost_models"]["EURUSD"], management=inputs["management"], lot=inputs["lot"],
        window_start=start if start is not None else bars.iloc[0].timestamp_utc,
        window_end=end if end is not None else bars.iloc[-1].timestamp_utc + pd.Timedelta(minutes=5))


def test_warmup_requires_250_closed_predecessors_without_future_substitution():
    bars = _bars(400)
    result = candidate_generation(bars)
    assert all(x["reason"] == "INSUFFICIENT_WARMUP" for x in result.decisions[:250])
    assert result.decisions[250]["available_at_utc"] == bars.iloc[251].timestamp_utc.isoformat()
    assert result.decisions[250].get("action") is not None


def test_later_window_uses_only_last_250_fully_closed_predecessors(monkeypatch):
    from agi_style_forex_bot_mt5.research import trend_pullback_evaluator as evaluator
    bars = _bars(500)
    seen = []
    original = evaluator.prepare_strategy_features

    def observe(frame, **kwargs):
        seen.append(frame.copy(deep=True))
        return original(frame, **kwargs)

    monkeypatch.setattr(evaluator, "prepare_strategy_features", observe)
    start = bars.iloc[400].timestamp_utc + pd.Timedelta(minutes=2)
    end = bars.iloc[460].timestamp_utc
    result = candidate_generation(bars, start=start, end=end)
    assert len(seen) == 1
    assert seen[0].iloc[0].timestamp_utc == bars.iloc[150].timestamp_utc
    assert seen[0].iloc[249].timestamp_utc == bars.iloc[399].timestamp_utc
    assert seen[0].iloc[250].timestamp_utc == bars.iloc[401].timestamp_utc
    assert bars.iloc[400].timestamp_utc not in set(seen[0].timestamp_utc)
    assert result.decisions[0]["source_bar_timestamp_utc"] == bars.iloc[401].timestamp_utc.isoformat()
    assert result.decisions[0].get("action") is not None


def test_future_prices_cannot_change_prior_real_decisions_or_candidates():
    bars = _bars(500)
    before = candidate_generation(bars)
    altered = bars.copy(deep=True)
    altered.loc[351:, ["open", "high", "low", "close"]] *= 3
    altered.loc[351:, "volume"] *= 17
    altered.loc[351:, "spread_points"] = 20
    after = candidate_generation(altered)
    cutoff = bars.iloc[350].timestamp_utc
    prior = lambda result: tuple(x for x in result.decisions if pd.Timestamp(x["source_bar_timestamp_utc"]) <= cutoff)
    assert prior(before) == prior(after)
    candidates = lambda result: tuple(x for x in result.candidates if x.timestamp <= cutoff)
    assert candidates(before), "fixture must exercise actual strategy candidates"
    assert candidates(before) == candidates(after)


def test_horizon_eligibility_is_decided_before_prices_and_includes_exact_final_close():
    bars = _bars(500)
    start = bars.iloc[400].timestamp_utc
    end = bars.iloc[431].timestamp_utc
    before = candidate_generation(bars, start=start, end=end)
    by_time = {x["source_bar_timestamp_utc"]: x for x in before.decisions}
    exact = by_time[bars.iloc[418].timestamp_utc.isoformat()]
    assert exact["horizon_end_utc"] == end.isoformat()
    assert exact.get("action") is not None
    excluded = by_time[bars.iloc[419].timestamp_utc.isoformat()]
    assert excluded["reason"] == "INCOMPLETE_EXIT_HORIZON" and "action" not in excluded
    assert by_time[bars.iloc[430].timestamp_utc.isoformat()]["reason"] == "DECISION_OUTSIDE_WINDOW"
    altered = bars.copy(deep=True)
    altered.loc[420:430, "high"] = 99
    altered.loc[420:430, "low"] = .01
    after = candidate_generation(altered, start=start, end=end)
    assert [(x["source_bar_timestamp_utc"], x["reason"]) for x in before.decisions if "action" not in x] == [
        (x["source_bar_timestamp_utc"], x["reason"]) for x in after.decisions if "action" not in x]


def test_development_evaluation_has_no_holdout_or_operational_claim():
    from agi_style_forex_bot_mt5.research.trend_pullback_evaluator import evaluate_trend_pullback
    inputs = study_inputs(data_role="DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED")
    plan = build_experiment_plan(**inputs)
    result = evaluate_trend_pullback(plan, inputs["datasets"]["EURUSD"], symbol="EURUSD",
        hypothesis_id=plan.hypotheses[0].hypothesis_id, split="development_test")
    payload = result.to_dict()
    assert payload["scope"] == "INDEPENDENT_FIXED_LOT_CANDIDATES"
    assert payload["full_risk_pipeline_applied"] is False and payload["full_pipeline_verified"] is False
    assert payload["promotion_eligible"] is False and payload["final_holdout"] == "NOT_AVAILABLE"
    assert payload["walk_forward_status"] == "NOT_EVALUATED" and payload["baselines_status"] == "NOT_EVALUATED"
    assert result.outcome.settings.parameters["data_role"] == "DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED"
    boundary = pd.Timestamp(plan.splits[2].end_utc)
    assert result.outcome.trades, "fixture must exercise actual closed trades"
    assert all(pd.Timestamp(x.exit_time) <= boundary for x in result.outcome.trades)

"""Matched baselines on explicitly synthetic candles; never a market or promotion test."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from agi_style_forex_bot_mt5.research import predeclared_baselines as baselines
from agi_style_forex_bot_mt5.research.experiment_plan import build_experiment_plan
from agi_style_forex_bot_mt5.research.trend_pullback_evaluator import evaluate_trend_pullback

from test_trend_pullback_research_evaluator import research_bars, research_inputs

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_predeclared_baselines.py"


@pytest.fixture(scope="module")
def study():
    bars = research_bars()
    plan = build_experiment_plan(**research_inputs(bars))
    cells = {split.name: baselines.simulate_cell(plan, bars, symbol="EURUSD", split=split.name) for split in plan.splits}
    return plan, bars, cells


def test_every_eligible_bar_has_both_directions_resolved(study):
    plan, bars, cells = study
    for cell in cells.values():
        assert cell.bars
        keys = {(position, direction) for position in range(len(cell.bars)) for direction in baselines.DIRECTIONS}
        assert set(cell.trades) | set(cell.unavailable) == keys and not set(cell.trades) & set(cell.unavailable)
        for (position, direction), trade in cell.trades.items():
            assert str(getattr(trade.direction, "value", trade.direction)) == direction


@pytest.mark.parametrize("hypothesis", (0, 1, 2))
@pytest.mark.parametrize("split", ("train", "validation", "development_test"))
def test_strategy_subset_reproduces_the_actual_evaluator(study, hypothesis, split):
    plan, bars, cells = study
    hypothesis_id = plan.hypotheses[hypothesis].hypothesis_id
    actual = evaluate_trend_pullback(plan, bars, symbol="EURUSD", hypothesis_id=hypothesis_id, split=split)
    result = baselines.evaluate_baselines(plan, bars, cells[split], hypothesis_id=hypothesis_id, replications=20)
    assert result["strategy"]["trades"] == len(actual.outcome.trades)
    assert result["strategy"]["net_profit"] == pytest.approx(actual.outcome.metrics.net_profit, abs=1e-9)
    assert result["strategy"]["win_rate_pct"] == pytest.approx(actual.outcome.metrics.win_rate_pct)
    assert result["strategy"]["max_drawdown_pct"] == pytest.approx(actual.outcome.metrics.max_drawdown_pct)


def test_baselines_are_deterministic_matched_and_never_authorize(study):
    plan, bars, cells = study
    hypothesis_id = plan.hypotheses[0].hypothesis_id
    first = baselines.evaluate_baselines(plan, bars, cells["validation"], hypothesis_id=hypothesis_id, replications=50)
    second = baselines.evaluate_baselines(plan, bars, cells["validation"], hypothesis_id=hypothesis_id, replications=50)
    assert first == second
    strategy_trades = first["strategy"]["trades"]
    assert first["no_trade"]["trades"] == 0 and first["no_trade"]["net_profit"] == 0.0
    random_entries = first["replicated"]["random_entries"]
    assert random_entries["sample_size"]["p05"] == random_entries["sample_size"]["p95"] == strategy_trades
    for name in baselines.REPLICATED_BASELINES:
        item = first["replicated"][name]
        assert item["replications"] == 50 and item["net_profit"]["count"] == 50
        assert 1 / 51 <= item["baseline_at_least_strategy_share"] <= 1
    assert set(first["replicated"]) == set(baselines.REPLICATED_BASELINES)


def test_direction_flip_is_the_exact_opposite_choice(study):
    plan, bars, cells = study
    cell = cells["validation"]
    hypothesis_id = plan.hypotheses[0].hypothesis_id
    strategy = baselines.strategy_selection(plan, bars, cell, hypothesis_id=hypothesis_id)
    flipped = [(position, "SELL" if direction == "BUY" else "BUY") for position, direction in strategy]
    expected = baselines.summarize_profits(baselines._profits(cell, flipped))
    result = baselines.evaluate_baselines(plan, bars, cell, hypothesis_id=hypothesis_id, replications=5)
    assert result["direction_flip"] == expected


def test_random_draws_use_only_bars_with_both_outcomes_without_replacement(study):
    plan, bars, cells = study
    cell = cells["train"]
    strategy = baselines.strategy_selection(plan, bars, cell, hypothesis_id=plan.hypotheses[0].hypothesis_id)
    pools = baselines._Pools(cell, strategy)
    rng = np.random.Generator(np.random.PCG64(7))
    profits = pools.draw("random_entries", rng)
    assert len(profits) == min(pools.traded_count, len(pools.both)) and not np.isnan(profits).any()
    trend = pools.draw("trend_direction_random_bars", np.random.Generator(np.random.PCG64(7)))
    assert not np.isnan(trend).any()
    with pytest.raises(ValueError, match="unknown baseline"):
        pools.draw("best_of_both", rng)


def test_summary_uses_backtester_definitions():
    summary = baselines.summarize_profits(np.array([3.0, -1.0, -1.0, 0.0]))
    assert summary["net_profit"] == 1.0 and summary["profit_factor"] == 1.5
    assert summary["win_rate_pct"] == 25.0 and summary["expectancy"] == 0.25
    assert baselines.summarize_profits(np.array([2.0]))["profit_factor_status"] == "UNBOUNDED_NO_LOSSES"
    assert baselines.summarize_profits(np.array([], dtype=float))["profit_factor"] == 0.0


def test_rejects_unbound_data_and_invalid_replications(study):
    plan, bars, cells = study
    changed = bars.copy()
    changed.loc[500, "close"] += 0.00001
    changed.loc[500, "high"] = max(changed.loc[500, "high"], changed.loc[500, "close"])
    with pytest.raises(ValueError, match="differ from plan"):
        baselines.simulate_cell(plan, changed, symbol="EURUSD", split="train")
    with pytest.raises(ValueError, match="replications"):
        baselines.evaluate_baselines(plan, bars, cells["train"], hypothesis_id=plan.hypotheses[0].hypothesis_id, replications=0)


def test_matrix_covers_every_cell_and_declares_limits(study):
    plan, bars, _ = study
    report = baselines.run_baseline_matrix(plan, {"EURUSD": bars}, replications=5)
    assert len(report["cells"]) == len(plan.symbols) * len(plan.splits) * len(plan.hypotheses)
    assert {cell["min_score"] for cell in report["cells"]} == {62, 70, 78}
    for flag in ("full_risk_pipeline_applied", "full_pipeline_verified", "promotion_eligible", "execution_authorized"):
        assert report[flag] is False
    assert report["selection_policy"] == "NONE_COMPARE_ALL" and report["final_holdout"] == "NOT_AVAILABLE"
    assert any("not out-of-sample" in item for item in report["limitations"])
    json.dumps(report, allow_nan=False)


def test_cli_runs_from_study_inputs_and_never_overwrites(tmp_path):
    bars = research_bars()
    values = research_inputs(bars)
    plan = build_experiment_plan(**values)
    bars.to_csv(tmp_path / "EURUSD_M5.csv", index=False)
    spec, costs = values["instruments"]["EURUSD"], values["cost_models"]["EURUSD"]
    study = {"data_role": values["data_role"], "denomination_currency": "USD", "lot": values["lot"],
             "initial_balance": 10000.0, "random_seed": plan.to_dict()["random_seed"],
             "management": asdict(values["management"]),
             "datasets": {"EURUSD": {"path": "EURUSD_M5.csv", **{key: values["data_provenance"]["EURUSD"][key]
                 for key in ("provider", "quality_report", "tick_value_currency", "tick_value_status")},
                 "instrument": asdict(spec), "cost_model": asdict(costs),
                 "cost_provenance": values["cost_provenance"]["EURUSD"]}}}
    (tmp_path / "inputs.json").write_text(json.dumps(study), encoding="utf-8")
    (tmp_path / "plan.json").write_text(plan.canonical_json, encoding="utf-8")
    command = [sys.executable, "-B", str(SCRIPT), "--source-root", str(ROOT), "--inputs", str(tmp_path / "inputs.json"),
               "--plan", str(tmp_path / "plan.json"), "--output", str(tmp_path / "out"), "--replications", "5"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "out/baselines.json").read_text(encoding="utf-8"))
    assert report["plan_id"] == plan.plan_id and len(report["cells"]) == 9
    assert (tmp_path / "out/baselines.csv").read_text(encoding="utf-8").count("\n") == 10
    again = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=600)
    assert again.returncode == 2 and json.loads(again.stdout)["status"] == "REJECTED"

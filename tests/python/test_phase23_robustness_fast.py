from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.real_data_research import load_latest_run_summary
from agi_style_forex_bot_mt5.robustness_validation import (
    analyze_cost_sensitivity,
    decide_robustness,
    run_monte_carlo_fast,
    run_robustness_fast,
    run_stress_fast,
    run_walk_forward_fast,
)


def test_robustness_fast_loads_profile_runs_balanced_trades(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile_runs" / "balanced"
    profile_dir.mkdir(parents=True)
    _robust_trades(120).to_csv(profile_dir / "trades.csv", index=False)

    summary = run_robustness_fast(runs_root=tmp_path / "runs", profile_runs_dir=tmp_path / "profile_runs", output_dir=tmp_path / "robustness", simulations=100, seed=7)

    assert summary["mode"] == "robustness-fast"
    assert summary["total_trades"] == 120
    assert summary["trades_source"].endswith("trades.csv")
    assert summary["execution_attempted"] is False


def test_monte_carlo_fast_produces_probability_profit_positive() -> None:
    summary, simulations = run_monte_carlo_fast(_robust_trades(120), simulations=100, seed=42)

    assert 0.0 <= summary["probability_profit_positive"] <= 1.0
    assert not simulations.empty
    assert summary["execution_attempted"] is False


def test_stress_fast_detects_remove_best_10pct() -> None:
    summary, scenarios = run_stress_fast(_fragile_top_heavy_trades())

    row = scenarios.loc[scenarios["scenario"] == "remove_best_10pct"].iloc[0]
    assert bool(row["failed"]) is True
    assert "remove_best_10pct" in summary["scenarios_failed"]


def test_cost_sensitivity_detects_spread_fragility() -> None:
    summary, frame = analyze_cost_sensitivity(_fragile_cost_trades())

    assert summary["classification"] in {"NEEDS_COST_RECALIBRATION", "COST_FRAGILE"}
    assert not frame.empty


def test_walk_forward_fast_handles_insufficient_data() -> None:
    summary, folds = run_walk_forward_fast(_robust_trades(20))

    assert summary["classification"] == "NEEDS_MORE_WALK_FORWARD_DATA"
    assert folds.empty


def test_robustness_decision_candidate_with_robust_metrics() -> None:
    decision = decide_robustness(
        profile="BALANCED",
        base_metrics={"total_trades": 150, "profit_factor": 1.6, "expectancy_r": 0.2},
        monte_carlo={"classification": "MONTE_CARLO_OK", "probability_profit_positive": 0.75},
        stress={"classification": "STRESS_OK", "worst_case_profit_factor": 1.1},
        walk_forward={"classification": "WALK_FORWARD_OK", "overfit_warning": False},
        cost_sensitivity={"classification": "COST_SENSITIVITY_OK", "cost_fragility_score": 20},
        profile_allowed_for_shadow=True,
        not_for_demo_live=False,
    )

    assert decision["robustness_decision"] == "PAPER_FORWARD_SHADOW_CANDIDATE"
    assert decision["execution_attempted"] is False


def test_robustness_decision_needs_cost_recalibration_when_spread_destroys_edge() -> None:
    decision = decide_robustness(
        profile="BALANCED",
        base_metrics={"total_trades": 150, "profit_factor": 1.6, "expectancy_r": 0.2},
        monte_carlo={"classification": "MONTE_CARLO_OK", "probability_profit_positive": 0.75},
        stress={"classification": "STRESS_WARNING", "worst_case_profit_factor": 0.9, "most_sensitive_cost": "spread_x2"},
        walk_forward={"classification": "WALK_FORWARD_OK", "overfit_warning": False},
        cost_sensitivity={"classification": "COST_SENSITIVITY_OK", "cost_fragility_score": 20},
        profile_allowed_for_shadow=True,
        not_for_demo_live=False,
    )

    assert decision["robustness_decision"] == "NEEDS_COST_RECALIBRATION"


def test_robustness_decision_needs_more_data_without_trades() -> None:
    decision = decide_robustness(
        profile="BALANCED",
        base_metrics={"total_trades": 0, "profit_factor": None, "expectancy_r": None},
        monte_carlo={"classification": "NEEDS_MORE_ROBUSTNESS_DATA"},
        stress={"classification": "NEEDS_MORE_ROBUSTNESS_DATA"},
        walk_forward={"classification": "NEEDS_MORE_WALK_FORWARD_DATA"},
        cost_sensitivity={"classification": "NEEDS_MORE_ROBUSTNESS_DATA"},
        profile_allowed_for_shadow=True,
        not_for_demo_live=False,
    )

    assert decision["robustness_decision"] == "NEEDS_MORE_ROBUSTNESS_DATA"


def test_cli_accepts_robustness_fast(tmp_path: Path, capsys) -> None:
    run = tmp_path / "runs" / "20260101-000000-real-data-research" / "reports" / "backtests"
    run.mkdir(parents=True)
    _robust_trades(120).to_csv(run / "trades.csv", index=False)
    (run.parents[1] / "final_summary_compact.json").write_text(json.dumps({"run_id": run.parents[1].name, "execution_attempted": False}), encoding="utf-8")

    assert cli.main(["--mode", "robustness-fast", "--runs-root", str(tmp_path / "runs"), "--profile-runs-dir", str(tmp_path / "profile_runs"), "--output-dir", str(tmp_path / "robustness"), "--simulations", "100", "--seed", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "robustness-fast"
    assert payload["execution_attempted"] is False
    assert payload["order_send_called"] is False
    assert payload["order_check_called"] is False


def test_latest_run_summary_includes_robustness_status(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "20260101-000000-real-data-research"
    report_dir = run / "reports" / "robustness"
    report_dir.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    (report_dir / "robustness_summary.json").write_text(
        json.dumps(
            {
                "robustness_decision": "PAPER_FORWARD_SHADOW_CANDIDATE",
                "monte_carlo_classification": "MONTE_CARLO_OK",
                "stress_classification": "STRESS_OK",
                "walk_forward_classification": "WALK_FORWARD_OK",
                "cost_sensitivity_classification": "COST_SENSITIVITY_OK",
                "paper_forward_shadow_candidate": True,
            }
        ),
        encoding="utf-8",
    )

    summary = load_latest_run_summary(tmp_path / "runs")

    assert summary["robustness_decision"] == "PAPER_FORWARD_SHADOW_CANDIDATE"
    assert summary["paper_forward_shadow_candidate"] is True


def _robust_trades(count: int) -> pd.DataFrame:
    rows = []
    for index in range(count):
        r = 0.75 if index % 2 == 0 else -0.25
        rows.append(_trade_row(index, r))
    return pd.DataFrame(rows)


def _fragile_cost_trades() -> pd.DataFrame:
    rows = [_trade_row(index, 0.06 if index % 2 == 0 else -0.03) for index in range(120)]
    return pd.DataFrame(rows)


def _fragile_top_heavy_trades() -> pd.DataFrame:
    rows = [_trade_row(index, -0.05) for index in range(100)]
    for index in range(10):
        rows.append(_trade_row(100 + index, 2.0))
    return pd.DataFrame(rows)


def _trade_row(index: int, r_multiple: float) -> dict[str, object]:
    return {
        "signal_id": f"s{index}",
        "symbol": "EURUSD",
        "strategy_name": "strategy_ensemble",
        "session": "LONDON" if index % 10 else "ROLLOVER",
        "regime": "TREND_UP",
        "entry_time": f"2024-01-{(index % 28) + 1:02d}T00:00:00Z",
        "exit_time": f"2024-01-{(index % 28) + 1:02d}T01:00:00Z",
        "profit": r_multiple * 100.0,
        "r_multiple": r_multiple,
    }

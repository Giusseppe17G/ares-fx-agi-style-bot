from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.research import (
    CandidateRegistry,
    StrategyCandidate,
    assess_overfit,
    build_symbol_strategy_mix,
    composite_score,
    generate_research_parameter_sets,
    run_research,
    select_for_regime,
)
from agi_style_forex_bot_mt5.backtesting.stress_tester import StressResult, UNMODELED_SCOPE
from agi_style_forex_bot_mt5.research.research_runner import _stress_evidence_summary


def _history(path: Path, rows: int = 260) -> None:
    times = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    price = 1.1
    data = []
    for index, ts in enumerate(times):
        price += 0.00005
        data.append(
            {
                "time": ts.isoformat(),
                "open": price,
                "high": price + 0.0003,
                "low": price - 0.0003,
                "close": price + (0.0001 if index % 3 else -0.00005),
                "tick_volume": 1000 + index,
                "spread": 10,
            }
        )
    pd.DataFrame(data).to_csv(path, index=False)


def test_strategy_candidate_serializes_to_json() -> None:
    candidate = StrategyCandidate.build(strategy_name="trend_pullback", symbol="EURUSD", params={"ema_fast": 20})
    payload = json.loads(candidate.to_json())
    assert payload["strategy_name"] == "trend_pullback"
    assert payload["candidate_id"].startswith("cand_")


def test_parameter_space_reproducible() -> None:
    first = generate_research_parameter_sets(max_candidates=10)
    second = generate_research_parameter_sets(max_candidates=10)
    assert first == second
    assert len(first) == 10


def test_candidate_registry_avoids_duplicates() -> None:
    candidate = StrategyCandidate.build(strategy_name="trend_pullback", symbol="EURUSD", params={"x": 1})
    registry = CandidateRegistry()
    assert registry.add(candidate) is True
    assert registry.add(candidate) is False
    assert len(registry.list()) == 1


def test_composite_objective_penalizes_few_trades_and_drawdown() -> None:
    good = composite_score({"total_trades": 300, "profit_factor": 1.5, "expectancy_r": 0.2, "max_drawdown_pct": -5})
    few = composite_score({"total_trades": 10, "profit_factor": 1.5, "expectancy_r": 0.2, "max_drawdown_pct": -5})
    drawdown = composite_score({"total_trades": 300, "profit_factor": 1.5, "expectancy_r": 0.2, "max_drawdown_pct": -25})
    assert few < good
    assert drawdown < good


def test_overfit_guard_detects_train_positive_test_negative_and_top5() -> None:
    result = assess_overfit(
        train_metrics={"expectancy_r": 0.2, "total_trades": 100},
        test_metrics={"expectancy_r": -0.1, "total_trades": 20},
        trades_summary={"top_5_profit_concentration_pct": 60, "profitable_days": 2, "profitable_sessions": 1},
    )
    assert result.overfit_risk in {"HIGH", "CRITICAL"}
    assert result.recommended_status == "REJECTED"


def test_regime_selector_returns_weights() -> None:
    trend = select_for_regime("TREND_UP")
    closed = select_for_regime("MARKET_CLOSED_OR_NO_TICKS")
    assert trend.weights["trend_pullback"] > 1
    assert closed.weights == {}


def test_symbol_strategy_selector_generates_mix() -> None:
    approved = StrategyCandidate.build(strategy_name="trend_pullback", symbol="EURUSD", params={"x": 1}).with_status(
        "APPROVED_FOR_SHADOW_OBSERVATION",
        metrics_summary={"max_allowed_spread_points": 12},
    )
    rejected = StrategyCandidate.build(strategy_name="mean_reversion", symbol="EURUSD", params={"x": 2}).with_status("REJECTED")
    mix = build_symbol_strategy_mix([approved, rejected])
    assert mix[0]["symbol"] == "EURUSD"
    assert "trend_pullback" in mix[0]["approved_strategies"]


def test_research_runner_produces_reports(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    reports_root = tmp_path / "reports"
    output_dir = reports_root / "research"
    data_dir.mkdir()
    (reports_root / "data_quality").mkdir(parents=True)
    (reports_root / "broker_costs").mkdir()
    _history(data_dir / "EURUSD_M5.csv")
    (reports_root / "data_quality" / "dataset_manifest.json").write_text('{"dataset_fingerprint":"abc"}', encoding="utf-8")
    (reports_root / "broker_costs" / "broker_cost_profile.json").write_text('{"symbols":{"EURUSD":{"spread_p95":10}}}', encoding="utf-8")

    summary = run_research(symbols=("EURUSD",), data_dir=data_dir, reports_root=reports_root, output_dir=output_dir, max_candidates=4)

    assert summary["mode"] == "research"
    assert summary["execution_attempted"] is False
    assert (output_dir / "candidate_registry.json").exists()
    assert (output_dir / "recommended_strategy_mix.json").exists()
    assert summary["stress_evidence_status"] == "INCOMPLETE"
    assert summary["stress_scenario_counts"]["not_modeled_scenario_count"] == 16
    assert summary["approved_for_shadow_observation"] == 0
    assert summary["promotion_eligible"] is False
    assert summary["oos_status"] == "OOS_NOT_EVALUATED"
    assert summary["candidate_parameter_application"] is False


def test_research_cli_accepts_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "run_research",
        lambda **kwargs: {
            "mode": "research",
            "candidates_tested": 1,
            "approved_for_shadow_observation": 0,
            "watchlist": 1,
            "rejected": 0,
            "best_candidates": [],
            "execution_attempted": False,
        },
    )
    code = cli.main(["--mode", "research", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--reports-root", str(tmp_path), "--output-dir", str(tmp_path)])
    assert code == 0
    assert '"execution_attempted": false' in capsys.readouterr().out


def test_research_stress_summary_keeps_unsupported_scenarios_incomplete():
    rows = [StressResult("cost", {}, SimpleNamespace(net_profit=100)),
        StressResult("entry_delay_one_bar", {}, None, status="NOT_MODELED", evidence_scope=UNMODELED_SCOPE)]
    result = _stress_evidence_summary(rows)
    assert result["classification"] == "WATCHLIST"
    assert result["evidence_status"] == "INCOMPLETE"
    assert result["completed_scenario_count"] == result["not_modeled_scenario_count"] == 1
    assert result["scenarios"][1]["net_profit"] is None
    assert result["promotion_eligible"] is False


@pytest.mark.parametrize("status", ["NOT_MODELED", "NO_INPUT", "INSUFFICIENT_INPUT"])
def test_research_stress_summary_cannot_approve_without_completed_evidence(status):
    result = _stress_evidence_summary([StressResult("unavailable", {}, None, status=status)])
    assert result["classification"] == "REJECTED"
    assert result["evidence_status"] == "NO_COMPLETED_EVIDENCE"
    assert result["completed_scenario_count"] == 0


@pytest.mark.parametrize("row", [
    StressResult("missing", {}, None),
    StressResult("nan", {}, SimpleNamespace(net_profit=float("nan"))),
    StressResult("inf", {}, SimpleNamespace(net_profit=float("inf"))),
    StressResult("boolean", {}, SimpleNamespace(net_profit=True)),
    StressResult("unknown", {}, SimpleNamespace(net_profit=1), status="UNKNOWN"),
    StressResult("unsupported_with_metrics", {}, SimpleNamespace(net_profit=1), status="NOT_MODELED"),
    StressResult("unknown_scope", {}, SimpleNamespace(net_profit=1), evidence_scope="UNKNOWN"),
    SimpleNamespace(status="COMPLETED", metrics=SimpleNamespace(net_profit=1)),
])
def test_research_stress_summary_rejects_invalid_typed_results(row):
    result = _stress_evidence_summary([row])
    assert result["classification"] == "REJECTED"
    assert result["evidence_status"] == "INVALID"
    assert result["invalid_scenario_count"] == 1
    assert result["completed_scenario_count"] == 0


def test_research_stress_negative_completed_result_preserves_rejection():
    result = _stress_evidence_summary([StressResult("cost", {}, SimpleNamespace(net_profit=-1))])
    assert result["classification"] == "REJECTED"
    assert result["negative_completed_scenario_count"] == 1


def test_profitable_research_fixture_does_not_claim_parameter_or_oos_validation(tmp_path, monkeypatch):
    from test_backtesting import _trade
    from agi_style_forex_bot_mt5.backtesting import BacktestOutcome, BacktestSettings, calculate_metrics
    import agi_style_forex_bot_mt5.research.research_runner as runner

    data = tmp_path / "historical"
    data.mkdir()
    _history(data / "EURUSD_M5.csv")
    # A deterministic, deliberately favorable supplied outcome tests only the
    # consumer contract. It is not evidence of any strategy's performance.
    trades = tuple(replace(_trade(1000 if i % 4 else -100, signal_id=str(i)),
        entry_time=f"2026-01-{i % 10 + 1:02d}T00:00:00Z",
        exit_time=f"2026-01-{i % 10 + 1:02d}T01:00:00Z",
        metadata={"session": "LONDON" if i % 2 else "NEW_YORK"}) for i in range(300))
    outcome = BacktestOutcome(BacktestSettings(), calculate_metrics(trades), trades, (), pd.DataFrame())
    monkeypatch.setattr(runner, "run_strategy_backtest", lambda *args, **kwargs: outcome)
    summary = run_research(symbols=("EURUSD",), data_dir=data, reports_root=tmp_path / "reports",
        output_dir=tmp_path / "output", max_candidates=1)
    assert summary["approved_for_shadow_observation"] == 0
    assert summary["classification"] == "WATCHLIST"
    candidate, = summary["best_candidates"]
    artifacts = candidate["validation_artifacts"]
    assert artifacts["stress_summary"]["completed_scenario_count"] == 20
    assert artifacts["stress_summary"]["not_modeled_scenario_count"] == 4
    assert artifacts["stress_summary"]["evidence_status"] == "INCOMPLETE"
    assert artifacts["candidate_parameter_application"] is False
    assert artifacts["oos_status"] == "OOS_NOT_EVALUATED"
    assert artifacts["promotion_eligible"] is False
    registry = json.loads((tmp_path / "output" / "candidate_registry.json").read_text())
    assert registry[0]["validation_artifacts"]["stress_summary"] == artifacts["stress_summary"]
    mix = json.loads((tmp_path / "output" / "recommended_strategy_mix.json").read_text())
    assert mix[0]["approved_strategies"] == []

"""Expected validation artifact paths."""

from __future__ import annotations

from pathlib import Path


def artifact_paths(reports_root: str | Path, output_dir: str | Path) -> dict[str, Path]:
    root = Path(reports_root)
    output = Path(output_dir)
    return {
        "data_quality": root / "data_quality" / "summary.json",
        "broker_cost_profile": root / "broker_costs" / "broker_cost_profile.json",
        "backtest": root / "backtests" / "summary.json",
        "walk_forward": root / "walk_forward" / "summary.json",
        "monte_carlo": root / "monte_carlo" / "summary.json",
        "stress": root / "stress" / "summary.json",
        "research": root / "research" / "research_summary.json",
        "benchmark": root / "benchmarks" / "summary.json",
        "competitive_scorecard": root / "competitive_scorecard" / "competitive_scorecard.json",
        "broker_quality": root / "broker_quality" / "summary.json",
        "simulation_calibration": root / "execution_simulation" / "simulation_calibration.json",
        "paper_vs_backtest": root / "paper_vs_backtest" / "summary.json",
        "validation_report": root / "validation" / "master_validation_report.json",
        "pipeline_summary": output / "pipeline_summary.json",
        "stage_results": output / "stage_results.csv",
        "master_decision": output / "master_decision.json",
        "master_decision_csv": output / "master_decision.csv",
        "html": output / "report.html",
    }


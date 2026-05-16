"""Execution simulation report convenience wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .paper_vs_backtest import compare_paper_vs_backtest
from .simulation_calibrator import run_simulation_calibration


def build_execution_sim_report(*, database: TelemetryDatabase, reports_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    simulation = run_simulation_calibration(database=database, reports_root=reports_root, output_dir=Path(output_dir) / "execution_simulation")
    paper = compare_paper_vs_backtest(database=database, reports_root=reports_root, output_dir=Path(output_dir) / "paper_vs_backtest")
    classification = "CALIBRATED_OK" if simulation["classification"] == "CALIBRATED_OK" and paper["classification"] == "CALIBRATED_OK" else "WATCHLIST"
    return {"mode": "execution-sim-report", "classification": classification, "simulation": simulation, "paper_vs_backtest": paper, "execution_attempted": False}


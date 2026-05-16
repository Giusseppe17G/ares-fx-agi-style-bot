"""Full validation pipeline configuration."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PipelineConfig:
    """Serializable configuration for reproducible full validation runs."""

    symbols: tuple[str, ...]
    timeframes: tuple[str, ...] = ("M5", "M15", "H1")
    data_dir: str = "data/historical"
    reports_root: str = "data/reports"
    sqlite_path: str = "data/sqlite/forward-shadow.sqlite3"
    log_dir: str = "data/logs/full-validation"
    output_dir: str = "data/reports/full_validation"
    bars: int = 50_000
    run_export_history: bool = False
    run_data_quality: bool = True
    run_cost_profile: bool = True
    run_backtest: bool = True
    run_walk_forward: bool = True
    run_monte_carlo: bool = True
    run_stress_test: bool = True
    run_research: bool = True
    run_benchmark: bool = True
    run_competitive_scorecard: bool = True
    run_broker_quality: bool = False
    run_simulation_calibration: bool = True
    run_paper_vs_backtest: bool = True
    run_validation_report: bool = True
    fail_fast: bool = False
    seed: int = 0
    git_commit: str = ""

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("PipelineConfig requires at least one symbol")
        object.__setattr__(self, "symbols", tuple(symbol.upper() for symbol in self.symbols))
        object.__setattr__(self, "timeframes", tuple(tf.upper() for tf in self.timeframes))
        if not self.git_commit:
            object.__setattr__(self, "git_commit", _git_commit())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_paths(
        *,
        symbols: tuple[str, ...],
        timeframes: tuple[str, ...],
        data_dir: str | Path,
        reports_root: str | Path,
        sqlite_path: str | Path,
        log_dir: str | Path,
        output_dir: str | Path,
        bars: int,
        run_export_history: bool,
        fail_fast: bool,
        seed: int,
    ) -> "PipelineConfig":
        return PipelineConfig(
            symbols=symbols,
            timeframes=timeframes,
            data_dir=str(data_dir),
            reports_root=str(reports_root),
            sqlite_path=str(sqlite_path),
            log_dir=str(log_dir),
            output_dir=str(output_dir),
            bars=bars,
            run_export_history=run_export_history,
            fail_fast=fail_fast,
            seed=seed,
        )


def _git_commit() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except OSError:
        return ""


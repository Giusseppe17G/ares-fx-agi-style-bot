"""CLI report writers for stability repair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..robustness_validation.robustness_runner import jsonable, write_json
from .stability_filter_builder import build_balanced_stable_profile
from .walk_forward_failure_analyzer import analyze_walk_forward_failures


def run_walk_forward_failure_analysis(
    *,
    runs_root: str | Path,
    robustness_dir: str | Path,
    profile_runs_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Analyze walk-forward failure and write diagnostics."""

    analysis = analyze_walk_forward_failures(runs_root=runs_root, robustness_dir=robustness_dir, profile_runs_dir=profile_runs_dir)
    return _write_report(analysis, output_dir=output_dir, mode="walk-forward-failure-analysis", build_profile=False)


def run_stability_repair(
    *,
    runs_root: str | Path,
    robustness_dir: str | Path,
    profile_runs_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Analyze failures and create BALANCED_STABLE profile artifacts."""

    analysis = analyze_walk_forward_failures(runs_root=runs_root, robustness_dir=robustness_dir, profile_runs_dir=profile_runs_dir)
    return _write_report(analysis, output_dir=output_dir, mode="stability-repair", build_profile=True)


def run_build_stable_profile(*, runs_root: str | Path, stability_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Build BALANCED_STABLE from existing stability report files."""

    source = Path(stability_dir)
    symbols = _read_csv(source / "by_symbol_stability.csv")
    strategies = _read_csv(source / "by_strategy_stability.csv")
    sessions = _read_csv(source / "by_session_stability.csv")
    regimes = _read_csv(source / "by_regime_stability.csv")
    disabled_symbols = _names(symbols, "symbol", "DISABLE_FOR_NOW")
    disabled_strategies = _names(strategies, "strategy_name", "DISABLE_IN_BALANCED")
    blocked_sessions = _names(sessions, "session", "DISABLE_FOR_NOW")
    blocked_regimes = _names(regimes, "regime", "DISABLE_FOR_NOW")
    profile = build_balanced_stable_profile(
        output_dir=output_dir,
        disabled_symbols=disabled_symbols,
        disabled_strategies=disabled_strategies,
        blocked_sessions=blocked_sessions,
        blocked_regimes=blocked_regimes,
        stability_summary={"source": str(source), "runs_root": str(runs_root)},
    )
    return {
        "mode": "build-stable-profile",
        "stability_repair_decision": "BALANCED_STABLE_PROFILE_CREATED",
        **profile,
        "execution_attempted": False,
    }


def _write_report(analysis: dict[str, Any], *, output_dir: str | Path, mode: str, build_profile: bool) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    folds: pd.DataFrame = analysis["fold_diagnostics"]
    symbols: pd.DataFrame = analysis["symbols"]
    strategies: pd.DataFrame = analysis["strategies"]
    session_regime = analysis["session_regime"]
    sessions = pd.DataFrame(session_regime["sessions"])
    regimes = pd.DataFrame(session_regime["regimes"])
    edge_decay = analysis["edge_decay"]
    disabled_symbols = _names(symbols, "symbol", "DISABLE_FOR_NOW")
    disabled_strategies = _names(strategies, "strategy_name", "DISABLE_IN_BALANCED")
    blocked_sessions = session_regime["blocked_sessions_stable"]
    blocked_regimes = session_regime["blocked_regimes_stable"]
    profile_reports: list[str] = []
    if build_profile:
        profile = build_balanced_stable_profile(
            output_dir=output,
            disabled_symbols=disabled_symbols,
            disabled_strategies=disabled_strategies,
            blocked_sessions=blocked_sessions,
            blocked_regimes=blocked_regimes,
            stability_summary=edge_decay,
        )
        profile_reports = list(profile.get("reports_created", []))
    summary = {
        "mode": mode,
        "stability_repair_decision": analysis["decision"],
        "walk_forward_classification": analysis["walk_forward_classification"],
        "folds_negative": analysis["folds_negative"],
        "fold_stability_score": edge_decay["fold_stability_score"],
        "overfit_risk_score": edge_decay["overfit_risk_score"],
        "edge_decay_score": edge_decay["edge_decay_score"],
        "disabled_symbols_stable": disabled_symbols,
        "disabled_strategies_stable": disabled_strategies,
        "blocked_sessions_stable": blocked_sessions,
        "blocked_regimes_stable": blocked_regimes,
        "balanced_stable_profile_path": str(output / "balanced_stable.ini") if build_profile else "",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "reports_created": [],
    }
    paths = {
        "summary": output / "walk_forward_failure_summary.json",
        "folds": output / "fold_diagnostics.csv",
        "symbols": output / "by_symbol_stability.csv",
        "strategies": output / "by_strategy_stability.csv",
        "sessions": output / "by_session_stability.csv",
        "regimes": output / "by_regime_stability.csv",
        "edge_decay": output / "edge_decay.json",
        "html": output / "report.html",
    }
    write_json(paths["summary"], summary)
    folds.to_csv(paths["folds"], index=False)
    symbols.to_csv(paths["symbols"], index=False)
    strategies.to_csv(paths["strategies"], index=False)
    sessions.to_csv(paths["sessions"], index=False)
    regimes.to_csv(paths["regimes"], index=False)
    write_json(paths["edge_decay"], edge_decay)
    _write_html(paths["html"], summary)
    summary["reports_created"] = [str(path) for path in paths.values()] + profile_reports
    write_json(paths["summary"], summary)
    return jsonable(summary)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _names(frame: pd.DataFrame, column: str, decision: str) -> list[str]:
    if frame.empty or column not in frame.columns or "decision" not in frame.columns:
        return []
    return [str(value) for value in frame.loc[frame["decision"] == decision, column].dropna().tolist()]


def _write_html(path: Path, summary: dict[str, Any]) -> None:
    rows = "\n".join(f"<tr><th>{key}</th><td>{jsonable(value)}</td></tr>" for key, value in summary.items() if key != "reports_created")
    path.write_text(f"<html><body><h1>Walk-Forward Stability Repair</h1><p>Research/backtest only. No demo/live execution.</p><table>{rows}</table></body></html>", encoding="utf-8")

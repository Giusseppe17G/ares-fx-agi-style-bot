"""Report writer and CLI helpers for fast edge evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .blocker_analyzer import analyze_blockers, blocker_summary
from .edge_metrics import EdgeMetricsBundle, load_edge_metrics
from .fast_decision_engine import decide_fast
from .session_regime_analyzer import analyze_sessions_regimes
from .strategy_selector import select_strategies
from .symbol_selector import select_symbols


def run_edge_evaluation(*, runs_root: str | Path = "data/runs", output_dir: str | Path = "data/reports/edge", run_id: str | None = None) -> dict[str, Any]:
    """Run full fast edge evaluation and persist reports."""

    bundle = load_edge_metrics(runs_root=runs_root, run_id=run_id)
    return write_edge_report(bundle, output_dir)


def run_symbol_selection(*, runs_root: str | Path = "data/runs", output_dir: str | Path = "data/reports/edge", run_id: str | None = None) -> dict[str, Any]:
    bundle = load_edge_metrics(runs_root=runs_root, run_id=run_id)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    symbols = select_symbols(bundle.by_symbol)
    path = output / "by_symbol.csv"
    symbols.to_csv(path, index=False)
    return {"mode": "symbol-selection", "symbols_keep": _names(symbols, "symbol", "KEEP"), "symbols_reject": _names(symbols, "symbol", "REJECT"), "reports_created": [str(path)], "execution_attempted": False}


def run_strategy_selection(*, runs_root: str | Path = "data/runs", output_dir: str | Path = "data/reports/edge", run_id: str | None = None) -> dict[str, Any]:
    bundle = load_edge_metrics(runs_root=runs_root, run_id=run_id)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    strategies = select_strategies(bundle.by_strategy)
    path = output / "by_strategy.csv"
    strategies.to_csv(path, index=False)
    return {"mode": "strategy-selection", "strategies_keep": _names(strategies, "strategy_name", "KEEP"), "strategies_disable": _names(strategies, "strategy_name", "DISABLE_IN_BALANCED"), "reports_created": [str(path)], "execution_attempted": False}


def write_edge_report(bundle: EdgeMetricsBundle, output_dir: str | Path) -> dict[str, Any]:
    """Write edge JSON/CSV/HTML reports from preloaded metrics."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    symbols = select_symbols(bundle.by_symbol)
    strategies = select_strategies(bundle.by_strategy)
    session_regime = analyze_sessions_regimes(bundle.by_session, bundle.by_regime)
    blockers = analyze_blockers(bundle.blockers)
    blocker_info = blocker_summary(bundle.blockers)
    decision = decide_fast(global_metrics=bundle.global_metrics, symbol_selection=symbols, strategy_selection=strategies, blocker_summary=blocker_info)
    summary = {
        "mode": "edge-evaluation",
        "run_id": bundle.run_id,
        "classification": bundle.classification,
        "metrics_source": bundle.global_metrics.get("metrics_source", ""),
        "metrics_status": bundle.global_metrics.get("metrics_status", ""),
        "missing_metrics": bundle.global_metrics.get("missing_metrics", []),
        "total_trades": int(bundle.global_metrics.get("total_trades", 0) or 0),
        "sample_status": bundle.global_metrics.get("sample_status", "LOW_SAMPLE"),
        "trade_frequency_status": bundle.global_metrics.get("trade_frequency_status", bundle.global_metrics.get("sample_status", "LOW_SAMPLE")),
        "trades_by_symbol": _counts_dict(bundle.by_symbol, "symbol"),
        "trades_by_strategy": _counts_dict(bundle.by_strategy, "strategy_name"),
        "global_profit_factor": bundle.global_metrics.get("profit_factor", 0.0),
        "global_expectancy_r": bundle.global_metrics.get("expectancy_r", 0.0),
        "global_winrate": bundle.global_metrics.get("winrate", 0.0),
        "decision": decision["decision"],
        "decision_reason": decision["reason"],
        "symbols_keep": _names(symbols, "symbol", "KEEP"),
        "symbols_reject": _names(symbols, "symbol", "REJECT"),
        "strategies_keep": _names(strategies, "strategy_name", "KEEP"),
        "strategies_disable": _names(strategies, "strategy_name", "DISABLE_IN_BALANCED"),
        "allowed_sessions": session_regime["allowed_sessions"],
        "blocked_sessions": session_regime["blocked_sessions"],
        "allowed_regimes": session_regime["allowed_regimes"],
        "blocked_regimes": session_regime["blocked_regimes"],
        "reduce_risk_regimes": session_regime["reduce_risk_regimes"],
        "top_blockers": blocker_info["top_blockers"],
        "execution_attempted": False,
        "reports_created": [],
    }
    paths = _write_reports(output, summary, bundle, symbols, strategies, session_regime, blockers)
    summary["reports_created"] = paths
    (output / "edge_summary.json").write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    _write_config_suggestions(output / "config_suggestions", summary)
    summary["reports_created"].extend([str(output / "config_suggestions" / "balanced_filtered.ini"), str(output / "config_suggestions" / "research_active.ini")])
    (output / "edge_summary.json").write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return _jsonable(summary)


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    bundle: EdgeMetricsBundle,
    symbols: pd.DataFrame,
    strategies: pd.DataFrame,
    session_regime: Mapping[str, Any],
    blockers: pd.DataFrame,
) -> list[str]:
    paths = {
        "summary_json": output / "edge_summary.json",
        "summary_csv": output / "edge_summary.csv",
        "by_symbol": output / "by_symbol.csv",
        "by_strategy": output / "by_strategy.csv",
        "by_session": output / "by_session.csv",
        "by_regime": output / "by_regime.csv",
        "blockers": output / "blockers.csv",
        "recommendations": output / "recommendations.json",
        "html": output / "report.html",
    }
    pd.DataFrame([summary]).to_csv(paths["summary_csv"], index=False)
    symbols.to_csv(paths["by_symbol"], index=False)
    strategies.to_csv(paths["by_strategy"], index=False)
    pd.DataFrame(session_regime["sessions"]).to_csv(paths["by_session"], index=False)
    pd.DataFrame(session_regime["regimes"]).to_csv(paths["by_regime"], index=False)
    blockers.to_csv(paths["blockers"], index=False)
    recommendations = {
        "symbols_keep": summary["symbols_keep"],
        "symbols_reject": summary["symbols_reject"],
        "strategies_keep": summary["strategies_keep"],
        "strategies_disable": summary["strategies_disable"],
        "allowed_sessions": summary["allowed_sessions"],
        "blocked_sessions": summary["blocked_sessions"],
        "allowed_regimes": summary["allowed_regimes"],
        "blocked_regimes": summary["blocked_regimes"],
        "decision": summary["decision"],
        "execution_attempted": False,
    }
    paths["recommendations"].write_text(json.dumps(_jsonable(recommendations), indent=2, sort_keys=True), encoding="utf-8")
    _write_html(paths["html"], summary)
    return [str(path) for path in paths.values()]


def _write_html(path: Path, summary: Mapping[str, Any]) -> None:
    rows = "\n".join(f"<tr><th>{key}</th><td>{_jsonable(value)}</td></tr>" for key, value in summary.items() if key != "reports_created")
    path.write_text(f"<html><body><h1>Fast Edge Evaluation</h1><p>Research-only. No demo/live execution.</p><table>{rows}</table></body></html>", encoding="utf-8")


def _write_config_suggestions(output: Path, summary: Mapping[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    keep_symbols = ",".join(summary.get("symbols_keep", []))
    keep_strategies = ",".join(summary.get("strategies_keep", []))
    sessions = ",".join(summary.get("allowed_sessions", []))
    (output / "balanced_filtered.ini").write_text(
        "\n".join(
            [
                "DEMO_ONLY=True",
                "LIVE_TRADING_APPROVED=False",
                "SIGNAL_PROFILE=BALANCED",
                f"ALLOWED_SYMBOLS={keep_symbols}",
                f"ENABLED_STRATEGIES={keep_strategies}",
                f"ALLOWED_SESSIONS={sessions}",
                "EXECUTION_ATTEMPTED=False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "research_active.ini").write_text(
        "; NOT FOR DEMO/LIVE EXECUTION\nDEMO_ONLY=True\nLIVE_TRADING_APPROVED=False\nSIGNAL_PROFILE=ACTIVE\nEXECUTION_ATTEMPTED=False\n",
        encoding="utf-8",
    )


def _names(frame: pd.DataFrame, column: str, decision: str) -> list[str]:
    if frame.empty or column not in frame.columns or "decision" not in frame.columns:
        return []
    return [str(value) for value in frame.loc[frame["decision"] == decision, column].dropna().tolist()]


def _counts_dict(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    result: dict[str, int] = {}
    for _, row in frame.iterrows():
        result[str(row.get(column, "UNKNOWN"))] = int(row.get("total_trades", 0) or 0)
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and value in {float("inf"), float("-inf")}:
        return "Infinity" if value > 0 else "-Infinity"
    return value

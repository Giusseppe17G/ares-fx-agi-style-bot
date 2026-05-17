"""Build BALANCED_FILTERED profile artifacts from edge reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .regime_filter import filter_regimes
from .session_filter import filter_sessions
from .setup_quality_filter import analyze_setup_quality
from .strategy_filter import filter_strategies
from .symbol_filter import filter_symbols


def build_filtered_profile(
    *,
    runs_root: str | Path = "data/runs",
    edge_dir: str | Path = "data/reports/edge",
    output_dir: str | Path = "data/reports/edge_filtering",
    base_profile: str = "BALANCED",
) -> dict[str, Any]:
    """Read edge artifacts and create BALANCED_FILTERED profile files."""

    edge = Path(edge_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    edge_summary = _read_json(edge / "edge_summary.json")
    latest_summary = _latest_summary(Path(runs_root))
    by_symbol = filter_symbols(_read_csv(edge / "by_symbol.csv"))
    by_strategy = filter_strategies(_read_csv(edge / "by_strategy.csv"))
    blockers = _read_csv(edge / "blockers.csv")
    by_session = filter_sessions(_read_csv(edge / "by_session.csv"), blockers)
    by_regime = filter_regimes(_read_csv(edge / "by_regime.csv"), blockers)
    setup_quality = analyze_setup_quality(edge_summary, blockers)

    symbols_keep = _names(by_symbol, "symbol", "KEEP")
    symbols_disable = _names(by_symbol, "symbol", "DISABLE")
    strategies_keep = _names(by_strategy, "strategy_name", "KEEP")
    strategies_disable = _names(by_strategy, "strategy_name", "DISABLE_IN_BALANCED")
    allowed_sessions = _names(by_session, "session", "ALLOW")
    blocked_sessions = _names(by_session, "session", "BLOCK")
    watchlist_sessions = _names(by_session, "session", "WATCHLIST")
    allowed_regimes = _names(by_regime, "regime", "ALLOW")
    blocked_regimes = _names(by_regime, "regime", "BLOCK")
    watchlist_regimes = _names(by_regime, "regime", "WATCHLIST")
    summary = {
        "mode": "edge-filtering",
        "filtered_profile": "BALANCED_FILTERED",
        "base_profile": base_profile.upper(),
        "run_id": edge_summary.get("run_id") or latest_summary.get("run_id", ""),
        "edge_decision": edge_summary.get("decision", ""),
        "metrics_status": edge_summary.get("metrics_status", ""),
        "symbols_keep": symbols_keep,
        "symbols_disable": symbols_disable,
        "strategies_keep": strategies_keep,
        "strategies_disable": strategies_disable,
        "allowed_sessions": allowed_sessions,
        "blocked_sessions": blocked_sessions,
        "watchlist_sessions": watchlist_sessions,
        "allowed_regimes": allowed_regimes,
        "blocked_regimes": blocked_regimes,
        "watchlist_regimes": watchlist_regimes,
        "setup_quality_filter": setup_quality,
        "profile_allowed_for_demo_live": False,
        "execution_attempted": False,
        "reports_created": [],
    }
    paths = _write_outputs(output, summary, by_symbol, by_strategy, by_session, by_regime, edge_summary, latest_summary)
    summary["reports_created"] = paths
    (output / "filter_summary.json").write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return _jsonable(summary)


def _write_outputs(
    output: Path,
    summary: Mapping[str, Any],
    by_symbol: pd.DataFrame,
    by_strategy: pd.DataFrame,
    by_session: pd.DataFrame,
    by_regime: pd.DataFrame,
    edge_summary: Mapping[str, Any],
    latest_summary: Mapping[str, Any],
) -> list[str]:
    paths = [
        output / "filter_summary.json",
        output / "by_symbol_filter.csv",
        output / "by_strategy_filter.csv",
        output / "by_session_filter.csv",
        output / "by_regime_filter.csv",
        output / "balanced_filtered.ini",
        output / "balanced_filtered.json",
        output / "filter_diff.json",
        output / "report.html",
    ]
    by_symbol.to_csv(output / "by_symbol_filter.csv", index=False)
    by_strategy.to_csv(output / "by_strategy_filter.csv", index=False)
    by_session.to_csv(output / "by_session_filter.csv", index=False)
    by_regime.to_csv(output / "by_regime_filter.csv", index=False)
    profile_json = {
        "profile": "BALANCED_FILTERED",
        "base_profile": summary.get("base_profile", "BALANCED"),
        "symbols_keep": summary.get("symbols_keep", []),
        "symbols_disable": summary.get("symbols_disable", []),
        "strategies_keep": summary.get("strategies_keep", []),
        "strategies_disable": summary.get("strategies_disable", []),
        "allowed_sessions": summary.get("allowed_sessions", []),
        "blocked_sessions": summary.get("blocked_sessions", []),
        "allowed_regimes": summary.get("allowed_regimes", []),
        "blocked_regimes": summary.get("blocked_regimes", []),
        "setup_quality_filter": summary.get("setup_quality_filter", {}),
        "not_for_demo_live": True,
        "execution_attempted": False,
    }
    (output / "balanced_filtered.json").write_text(json.dumps(_jsonable(profile_json), indent=2, sort_keys=True), encoding="utf-8")
    (output / "balanced_filtered.ini").write_text(_ini_text(profile_json), encoding="utf-8")
    diff = {
        "from_profile": summary.get("base_profile", "BALANCED"),
        "to_profile": "BALANCED_FILTERED",
        "edge_decision": edge_summary.get("decision", ""),
        "latest_total_trades": latest_summary.get("total_trades", edge_summary.get("total_trades", 0)),
        "disabled_symbols": summary.get("symbols_disable", []),
        "disabled_strategies": summary.get("strategies_disable", []),
        "blocked_sessions": summary.get("blocked_sessions", []),
        "blocked_regimes": summary.get("blocked_regimes", []),
        "execution_attempted": False,
    }
    (output / "filter_diff.json").write_text(json.dumps(_jsonable(diff), indent=2, sort_keys=True), encoding="utf-8")
    (output / "report.html").write_text(_html(summary), encoding="utf-8")
    return [str(path) for path in paths]


def _ini_text(profile: Mapping[str, Any]) -> str:
    lines = [
        "; BALANCED_FILTERED is for research/backtest/forward-shadow paper only",
        "; NOT FOR DEMO/LIVE EXECUTION",
        "DEMO_ONLY=True",
        "LIVE_TRADING_APPROVED=False",
        "SIGNAL_PROFILE=BALANCED_FILTERED",
        f"ALLOWED_SYMBOLS={','.join(profile.get('symbols_keep', []))}",
        f"DISABLED_SYMBOLS={','.join(profile.get('symbols_disable', []))}",
        f"ENABLED_STRATEGIES={','.join(profile.get('strategies_keep', []))}",
        f"DISABLED_STRATEGIES={','.join(profile.get('strategies_disable', []))}",
        f"ALLOWED_SESSIONS={','.join(profile.get('allowed_sessions', []))}",
        f"BLOCKED_SESSIONS={','.join(profile.get('blocked_sessions', []))}",
        f"ALLOWED_REGIMES={','.join(profile.get('allowed_regimes', []))}",
        f"BLOCKED_REGIMES={','.join(profile.get('blocked_regimes', []))}",
        f"MIN_SETUP_SCORE_FILTERED={profile.get('setup_quality_filter', {}).get('minimum_setup_score_filtered', 62)}",
        f"MIN_COMPONENT_SCORE_FILTERED={profile.get('setup_quality_filter', {}).get('minimum_component_score_filtered', 50)}",
        "EXECUTION_ATTEMPTED=False",
    ]
    return "\n".join(lines) + "\n"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _latest_summary(runs_root: Path) -> dict[str, Any]:
    if not runs_root.exists():
        return {}
    candidates = [path for path in runs_root.iterdir() if path.is_dir() and (path / "final_summary_compact.json").exists()]
    if not candidates:
        return {}
    latest = sorted(candidates, key=lambda path: (path.stat().st_mtime, path.name))[-1]
    return _read_json(latest / "final_summary_compact.json")


def _names(frame: pd.DataFrame, column: str, decision: str) -> list[str]:
    if frame.empty or column not in frame.columns or "filter_decision" not in frame.columns:
        return []
    return [str(value) for value in frame.loc[frame["filter_decision"] == decision, column].dropna().tolist()]


def _html(summary: Mapping[str, Any]) -> str:
    rows = "\n".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in summary.items() if key != "reports_created")
    return f"<html><body><h1>BALANCED_FILTERED Edge Filter</h1><p>Research only. No demo/live execution.</p><table>{rows}</table></body></html>"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value

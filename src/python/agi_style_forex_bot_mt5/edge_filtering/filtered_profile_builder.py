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
    require_actionable_filter: bool = False,
) -> dict[str, Any]:
    """Read edge artifacts and create BALANCED_FILTERED profile files."""

    edge = Path(edge_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    edge_summary = _read_json(edge / "edge_summary.json")
    latest_summary = _latest_summary(Path(runs_root))
    symbol_source = _fallback_symbol_frame(_read_csv(edge / "by_symbol.csv"), edge_summary, latest_summary)
    strategy_source = _fallback_strategy_frame(_read_csv(edge / "by_strategy.csv"), edge_summary, latest_summary)
    by_symbol = filter_symbols(symbol_source)
    by_strategy = filter_strategies(strategy_source)
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
    filtering_decision, filter_reason, apply_filters = _filtering_decision(
        edge_summary=edge_summary,
        by_symbol=by_symbol,
        by_strategy=by_strategy,
        blocked_sessions=blocked_sessions,
        blocked_regimes=blocked_regimes,
        setup_quality=setup_quality,
    )
    if require_actionable_filter and filtering_decision != "ACTIONABLE_FILTER_CREATED":
        apply_filters = False
        filter_reason = f"{filter_reason}; require_actionable_filter=true"
    summary = {
        "mode": "edge-filtering",
        "classification": filtering_decision,
        "filtering_decision": filtering_decision,
        "filter_reason": filter_reason,
        "actionable_filter_created": filtering_decision == "ACTIONABLE_FILTER_CREATED",
        "apply_filters": apply_filters,
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


def _filtering_decision(
    *,
    edge_summary: Mapping[str, Any],
    by_symbol: pd.DataFrame,
    by_strategy: pd.DataFrame,
    blocked_sessions: list[str],
    blocked_regimes: list[str],
    setup_quality: Mapping[str, Any],
) -> tuple[str, str, bool]:
    metrics_status = str(edge_summary.get("metrics_status", ""))
    edge_decision = str(edge_summary.get("decision", ""))
    if metrics_status and metrics_status != "FULL_EDGE_METRICS":
        return "NEEDS_MORE_EDGE_METRICS", "edge metrics are incomplete; cannot build actionable filter", False
    symbols_disable = _names(by_symbol, "symbol", "DISABLE")
    strategies_disable = _names(by_strategy, "strategy_name", "DISABLE_IN_BALANCED")
    setup_changed = bool(setup_quality.get("active", False))
    actionable = bool(symbols_disable or strategies_disable or blocked_sessions or blocked_regimes or setup_changed)
    if actionable:
        return "ACTIONABLE_FILTER_CREATED", "one or more symbols, strategies, sessions, regimes, or setup-quality filters changed", True
    if edge_decision == "TEST_ACTIVE_RESEARCH_ONLY":
        return "ACTIVE_RESEARCH_EXPERIMENT_RECOMMENDED", "edge is weak or mixed and no BALANCED subset was actionable; test ACTIVE only in research", False
    global_pf = _maybe_float(edge_summary.get("global_profit_factor"))
    global_expectancy = _maybe_float(edge_summary.get("global_expectancy_r"))
    has_positive_subset = _has_decision(by_symbol, "KEEP") or _has_decision(by_strategy, "KEEP")
    if global_pf is not None and global_expectancy is not None and global_pf < 0.95 and global_expectancy < 0 and not has_positive_subset:
        return "REJECT_BALANCED_PROFILE", "global edge is negative and no positive subset was found", False
    if _all_watchlist(by_symbol) and _all_watchlist(by_strategy):
        return "NO_ACTIONABLE_FILTER", "all symbols and strategies are watchlist; no safe filter can be applied", False
    return "NO_ACTIONABLE_FILTER", "no actionable filter was created", False


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
        "filtering_decision": summary.get("filtering_decision", ""),
        "apply_filters": bool(summary.get("apply_filters", False)),
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
    active = {
        "profile": "ACTIVE",
        "source_decision": summary.get("filtering_decision", ""),
        "not_for_demo_live": True,
        "research_only": True,
        "allow_forward_shadow_promotion": False,
        "suggested_command": "py -m agi_style_forex_bot_mt5.cli --mode profile-comparison-run --compare-profiles BALANCED,ACTIVE",
        "execution_attempted": False,
    }
    (output / "research_active_experiment.ini").write_text(_research_active_ini(active), encoding="utf-8")
    (output / "report.html").write_text(_html(summary), encoding="utf-8")
    return [str(path) for path in [*paths, output / "research_active_experiment.ini"]]


def _ini_text(profile: Mapping[str, Any]) -> str:
    lines = [
        "; BALANCED_FILTERED is for research/backtest/forward-shadow paper only",
        "; NOT FOR DEMO/LIVE EXECUTION",
        f"FILTERING_DECISION={profile.get('filtering_decision', '')}",
        f"APPLY_FILTERS={str(bool(profile.get('apply_filters', False))).lower()}",
        "NOT_FOR_DEMO_LIVE=true",
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


def _research_active_ini(payload: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "; ACTIVE research experiment only",
            "; NOT FOR DEMO/LIVE EXECUTION",
            "SIGNAL_PROFILE=ACTIVE",
            "NOT_FOR_DEMO_LIVE=true",
            "RESEARCH_ONLY=true",
            "ALLOW_FORWARD_SHADOW_PROMOTION=false",
            f"FILTERING_DECISION={payload.get('source_decision', '')}",
            "EXECUTION_ATTEMPTED=False",
        ]
    ) + "\n"


def _fallback_symbol_frame(frame: pd.DataFrame, edge_summary: Mapping[str, Any], latest_summary: Mapping[str, Any]) -> pd.DataFrame:
    if not frame.empty:
        return frame
    raw = edge_summary.get("trades_by_symbol") or latest_summary.get("trades_by_symbol")
    return _counts_frame(raw, "symbol")


def _fallback_strategy_frame(frame: pd.DataFrame, edge_summary: Mapping[str, Any], latest_summary: Mapping[str, Any]) -> pd.DataFrame:
    if not frame.empty:
        return frame
    raw = edge_summary.get("trades_by_strategy") or latest_summary.get("trades_by_strategy")
    return _counts_frame(raw, "strategy_name")


def _counts_frame(raw: Any, column: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if isinstance(raw, Mapping):
        for name, count in raw.items():
            rows.append({column: str(name), "total_trades": _count_value(count)})
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                name = item.get(column) or item.get("symbol") or item.get("strategy_name") or item.get("name", "UNKNOWN")
                rows.append({column: str(name), "total_trades": _count_value(item)})
    return pd.DataFrame(rows)


def _count_value(value: Any) -> int:
    if isinstance(value, Mapping):
        value = value.get("total_trades", value.get("trades", value.get("count", 0)))
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


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


def _has_decision(frame: pd.DataFrame, decision: str) -> bool:
    return not frame.empty and "filter_decision" in frame.columns and bool((frame["filter_decision"] == decision).any())


def _all_watchlist(frame: pd.DataFrame) -> bool:
    if frame.empty or "filter_decision" not in frame.columns:
        return False
    return bool(frame["filter_decision"].astype(str).str.contains("WATCHLIST|RESEARCH_ONLY|INSUFFICIENT_METRICS").all())


def _maybe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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

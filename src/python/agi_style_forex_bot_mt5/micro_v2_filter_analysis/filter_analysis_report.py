"""Report orchestration for Micro V2 live-market filter analysis."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.base_vs_v2_comparator import compare_base_vs_v2
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.heartbeat_audit import audit_heartbeat
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.v2_activity_audit import audit_activity

from .cooldown_filter_audit import audit_cooldown_filter
from .fresh_tick_filter_scope import build_fresh_tick_scope
from .liquidity_filter_audit import audit_liquidity_filter
from .rejection_taxonomy_breakdown import build_rejection_breakdown
from .regime_filter_audit import audit_regime_filter
from .score_filter_audit import audit_score_filter
from .spread_filter_audit import audit_spread_filter
from .symbol_filter_breakdown import build_symbol_rows
from .v2_filter_event_loader import load_filter_analysis_inputs


STATUS_BY_FILTER = {
    "REGIME_BLOCK": "MICRO_V2_FILTER_ANALYSIS_REGIME_BLOCK_DOMINATES",
    "LIQUIDITY_BLOCK": "MICRO_V2_FILTER_ANALYSIS_LIQUIDITY_BLOCK_DOMINATES",
    "SPREAD_BLOCK": "MICRO_V2_FILTER_ANALYSIS_SPREAD_BLOCK_DOMINATES",
    "SCORE_THRESHOLD_BLOCK": "MICRO_V2_FILTER_ANALYSIS_SCORE_THRESHOLD_DOMINATES",
    "COOLDOWN_BLOCK": "MICRO_V2_FILTER_ANALYSIS_COOLDOWN_DOMINATES",
    "SESSION_BLOCK": "MICRO_V2_FILTER_ANALYSIS_SESSION_BLOCK_DOMINATES",
}


def run_micro_v2_filter_analysis(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    checkpoint_dir: str | Path = "data/reports/micro_v2_observation_checkpoint",
    monitor_dir: str | Path = "data/reports/micro_v2_dry_run_monitor",
    readiness_dir: str | Path = "data/reports/micro_v2_market_open_readiness",
    output_dir: str | Path = "data/reports/micro_v2_filter_analysis",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_filter_analysis_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        checkpoint_dir=checkpoint_dir,
        monitor_dir=monitor_dir,
        readiness_dir=readiness_dir,
    )
    v2 = inputs["v2_dataset"]
    base = inputs["base_dataset"]
    breakdown = build_rejection_breakdown(v2)
    fresh_scope = build_fresh_tick_scope(v2, inputs["readiness"], inputs["checkpoint"])
    base_activity = audit_activity(base)
    v2_activity = audit_activity(v2)
    comparison = compare_base_vs_v2(
        base_activity=base_activity,
        base_window=audit_heartbeat(base),
        v2_activity=v2_activity,
        v2_window=audit_heartbeat(v2),
    )
    filter_audits = {
        "regime": audit_regime_filter(breakdown),
        "liquidity": audit_liquidity_filter(breakdown),
        "spread": audit_spread_filter(breakdown),
        "score": audit_score_filter(breakdown),
        "cooldown": audit_cooldown_filter(breakdown),
    }
    dominant = breakdown.get("dominant_real_filter", {})
    status, action = _classify(breakdown, fresh_scope, dominant)
    candidate = _candidate(status, dominant)
    summary = {
        "mode": "micro-v2-filter-analysis",
        "micro_v2_filter_analysis_status": status,
        "dominant_v2_filter": dominant.get("filter_category", ""),
        "dominant_v2_filter_count": dominant.get("count", 0),
        "dominant_v2_filter_real_share": dominant.get("real_filter_share", 0.0),
        "total_v2_signals": v2_activity.get("signals_detected", 0),
        "total_v2_rejections": breakdown.get("total_rejections", 0),
        "rejection_rate": v2_activity.get("rejection_rate", 0.0),
        "market_closed_rejection_count": breakdown.get("market_closed_count", 0),
        "stale_tick_rejection_count": breakdown.get("stale_tick_count", 0),
        "invalid_market_snapshot_rejection_count": breakdown.get("invalid_snapshot_count", 0),
        "fresh_tick_symbols": fresh_scope.get("fresh_tick_symbols", []),
        "stale_tick_symbols": fresh_scope.get("stale_tick_symbols", []),
        "top_rejection_reasons": breakdown.get("by_reason", [])[:10],
        "base_closed_trade_rate_per_24h": comparison.get("base_metrics", {}).get("closed_trade_rate_per_24h", 0.0),
        "v2_closed_trade_rate_per_24h": comparison.get("v2_metrics", {}).get("closed_trade_rate_per_24h", 0.0),
        "v2_improves_frequency": comparison.get("v2_improves_frequency", False),
        "filter_tuning_candidate_available": bool(candidate),
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, breakdown, fresh_scope, comparison, filter_audits, candidate)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _classify(breakdown: Mapping[str, Any], fresh_scope: Mapping[str, Any], dominant: Mapping[str, Any]) -> tuple[str, str]:
    if breakdown.get("execution_attempted_detected") or breakdown.get("order_send_detected") or breakdown.get("order_check_detected"):
        return "MICRO_V2_FILTER_ANALYSIS_SAFETY_BLOCKED", "STOP_AND_REVIEW_EXECUTION_SAFETY_EVIDENCE"
    total = int(breakdown.get("total_rejections", 0) or 0)
    if total:
        if float(breakdown.get("market_closed_count", 0) or 0) / total > 0.7:
            return "MICRO_V2_FILTER_ANALYSIS_MARKET_CLOSED_DOMINATES", "KEEP_COLLECTING_WHEN_MARKET_OPEN_TICKS_ARE_STABLE"
        if float(breakdown.get("stale_tick_count", 0) or 0) / total > 0.7:
            return "MICRO_V2_FILTER_ANALYSIS_STALE_TICKS_DOMINATE", "RECHECK_TICK_FRESHNESS_AND_MARKET_DATA_FEED"
    if not fresh_scope.get("fresh_tick_symbols"):
        return "MICRO_V2_FILTER_ANALYSIS_NOT_ENOUGH_FRESH_TICK_DATA", "WAIT_FOR_MORE_FRESH_TICK_EVIDENCE"
    dominant_name = str(dominant.get("filter_category", ""))
    dominant_share = float(dominant.get("real_filter_share", 0.0) or 0.0)
    if dominant_name in STATUS_BY_FILTER and dominant_share > 0.4:
        return STATUS_BY_FILTER[dominant_name], f"REVIEW_{dominant_name}_OFFLINE_WITH_NON_ACTIVE_TUNING_CANDIDATE"
    if int(breakdown.get("real_filter_rejections", 0) or 0) > 0:
        return "MICRO_V2_FILTER_ANALYSIS_READY", "REVIEW_MIXED_REAL_FILTERS_OFFLINE_BEFORE_ANY_TUNING_PHASE"
    return "MICRO_V2_FILTER_ANALYSIS_REQUIRES_MANUAL_REVIEW", "REVIEW_V2_FILTER_EVENTS_AND_MARKET_DATA_SCOPE"


def _candidate(status: str, dominant: Mapping[str, Any]) -> dict[str, Any]:
    if status not in set(STATUS_BY_FILTER.values()):
        return {}
    return {
        "NOT_ACTIVE_RESEARCH_ONLY": True,
        "REQUIRES_REVIEW_PHASE": True,
        "APPROVED_FOR_RUNTIME": False,
        "dominant_filter": dominant.get("filter_category", ""),
        "dominant_filter_count": dominant.get("count", 0),
        "dominant_filter_real_share": dominant.get("real_filter_share", 0.0),
        "proposal": "Create a later explicit review phase before any profile or runtime change.",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    breakdown: Mapping[str, Any],
    fresh_scope: Mapping[str, Any],
    comparison: Mapping[str, Any],
    filter_audits: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_filter_analysis_summary.json",
        output / "rejection_breakdown.csv",
        output / "rejection_by_symbol.csv",
        output / "rejection_by_session.csv",
        output / "fresh_tick_filter_scope.json",
        output / "dominant_filter_audit.json",
        output / "base_vs_v2_filter_comparison.json",
        output / "filter_tuning_recommendations.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], breakdown.get("by_reason", []))
    _write_csv(paths[2], breakdown.get("by_symbol", []))
    _write_csv(paths[3], breakdown.get("by_session", []))
    _write_json(paths[4], fresh_scope)
    _write_json(paths[5], {"dominant_real_filter": breakdown.get("dominant_real_filter", {}), "filter_audits": filter_audits, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(paths[6], comparison)
    paths[7].write_text(_tuning_recommendations(summary, candidate), encoding="utf-8")
    if candidate:
        candidate_path = output / "filter_tuning_candidate.json"
        _write_json(candidate_path, candidate)
        paths.append(candidate_path)
    paths[8].write_text(_recommendations(summary), encoding="utf-8")
    paths[9].write_text(_html(summary), encoding="utf-8")
    return paths


def _tuning_recommendations(summary: Mapping[str, Any], candidate: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Filter Tuning Recommendations

Status: `{summary.get('micro_v2_filter_analysis_status')}`

Dominant filter: `{summary.get('dominant_v2_filter')}`

Candidate created: `{bool(candidate)}`

Any tuning must happen in a later explicit review phase. This analysis does not modify profiles, stable gate, ledgers, SQLite, logs, or runtime.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Filter Analysis

Status: `{summary.get('micro_v2_filter_analysis_status')}`

Dominant V2 filter: `{summary.get('dominant_v2_filter')}`

Rejection rate: `{summary.get('rejection_rate')}`

Fresh tick symbols: `{', '.join(summary.get('fresh_tick_symbols', []))}`

Recommended next action: `{summary.get('recommended_next_action')}`

This phase is offline/read-only and does not authorize demo/live execution.
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Filter Analysis</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

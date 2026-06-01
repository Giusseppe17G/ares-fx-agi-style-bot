"""Report orchestration for Micro V2 risk block root-cause audit."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .cooldown_risk_audit import audit_cooldown_risk
from .drawdown_risk_audit import audit_daily_ledger, audit_drawdown_risk
from .exposure_risk_audit import audit_exposure_risk
from .invalid_trade_state_audit import audit_invalid_trade_state
from .paper_risk_state_audit import audit_paper_risk_state
from .risk_block_loader import load_risk_block_inputs
from .risk_reason_classifier import extract_risk_rejections
from .trade_limit_audit import audit_max_open_trades, audit_trade_limit


STATUS_BY_DOMINANT = {
    "COOLDOWN": "MICRO_V2_RISK_BLOCK_COOLDOWN_DOMINATES",
    "MAX_PAPER_TRADES_PER_DAY": "MICRO_V2_RISK_BLOCK_TRADE_LIMIT_DOMINATES",
    "MAX_OPEN_TRADES": "MICRO_V2_RISK_BLOCK_MAX_OPEN_TRADES_DOMINATES",
    "DRAWDOWN_HALT": "MICRO_V2_RISK_BLOCK_DRAWDOWN_HALT_DOMINATES",
    "DAILY_LEDGER_BLOCK": "MICRO_V2_RISK_BLOCK_DAILY_LEDGER_BLOCK",
    "PROFILE_LIMIT_BLOCK": "MICRO_V2_RISK_BLOCK_PROFILE_LIMIT_BLOCK",
}


def run_micro_v2_risk_block_audit(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    filter_analysis_dir: str | Path = "data/reports/micro_v2_filter_analysis",
    checkpoint_dir: str | Path = "data/reports/micro_v2_observation_checkpoint",
    output_dir: str | Path = "data/reports/micro_v2_risk_block_audit",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_risk_block_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        filter_analysis_dir=filter_analysis_dir,
        checkpoint_dir=checkpoint_dir,
    )
    extracted = extract_risk_rejections(inputs["v2_dataset"])
    audits = {
        "paper_risk_state": audit_paper_risk_state(inputs["filter_analysis"], inputs["checkpoint"]),
        "cooldown": audit_cooldown_risk(extracted),
        "trade_limit": audit_trade_limit(extracted),
        "max_open_trades": audit_max_open_trades(extracted),
        "exposure": audit_exposure_risk(extracted),
        "drawdown": audit_drawdown_risk(extracted),
        "daily_ledger": audit_daily_ledger(extracted),
        "invalid_trade_state": audit_invalid_trade_state(extracted),
    }
    status, action = _classify(extracted)
    dominant = extracted.get("dominant_risk_block_reason", {})
    candidate = _candidate(status, dominant)
    summary = {
        "mode": "micro-v2-risk-block-audit",
        "micro_v2_risk_block_status": status,
        "dominant_risk_block_reason": dominant.get("risk_block_reason", ""),
        "dominant_risk_block_count": dominant.get("count", 0),
        "dominant_risk_block_share": dominant.get("share", 0.0),
        "risk_rejected_count": extracted.get("risk_rejected_count", 0),
        "affected_symbols": extracted.get("affected_symbols", []),
        "filter_analysis_status": inputs["filter_analysis"].get("micro_v2_filter_analysis_status", ""),
        "checkpoint_status": inputs["checkpoint"].get("micro_v2_checkpoint_status", ""),
        "risk_block_candidate_available": bool(candidate),
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, extracted, audits, candidate)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _classify(extracted: Mapping[str, Any]) -> tuple[str, str]:
    if extracted.get("execution_attempted_detected") or extracted.get("order_send_detected") or extracted.get("order_check_detected"):
        return "MICRO_V2_RISK_BLOCK_SAFETY_BLOCKED", "STOP_AND_REVIEW_EXECUTION_SAFETY_EVIDENCE"
    total = int(extracted.get("risk_rejected_count", 0) or 0)
    if total < 10:
        return "MICRO_V2_RISK_BLOCK_NOT_ENOUGH_DATA", "KEEP_COLLECTING_RISK_REJECTION_EVIDENCE"
    counts = {str(row.get("risk_block_reason")): int(row.get("count", 0) or 0) for row in extracted.get("reason_breakdown", [])}
    if counts.get("INVALID_RISK_DISTANCE", 0) > 0:
        return "MICRO_V2_RISK_BLOCK_INVALID_RISK_DISTANCE", "REVIEW_INVALID_RISK_DISTANCE_EVIDENCE_OFFLINE"
    if counts.get("ZERO_POSITION_SIZE", 0) > 0:
        return "MICRO_V2_RISK_BLOCK_ZERO_POSITION_SIZE", "REVIEW_POSITION_SIZING_INPUTS_OFFLINE"
    dominant = extracted.get("dominant_risk_block_reason", {})
    reason = str(dominant.get("risk_block_reason", ""))
    share = float(dominant.get("share", 0.0) or 0.0)
    if reason in STATUS_BY_DOMINANT and share > 0.4:
        return STATUS_BY_DOMINANT[reason], f"REVIEW_{reason}_OFFLINE_WITH_NO_RUNTIME_CHANGE"
    if reason in {"EXPECTED_SAFETY_GUARD", "EXPOSURE_BLOCK", "INVALID_SL_TP", "INVALID_TRADE_STATE"}:
        return "MICRO_V2_RISK_BLOCK_EXPECTED_SAFETY_GUARD", "KEEP_COLLECTING_MARKET_OPEN_DATA_AND_DO_NOT_TUNE_WHILE_MARKET_CLOSED_DOMINATES"
    return "MICRO_V2_RISK_BLOCK_REQUIRES_MANUAL_REVIEW", "REVIEW_RISK_REJECTION_PAYLOADS_BEFORE_ANY_CHANGE"


def _candidate(status: str, dominant: Mapping[str, Any]) -> dict[str, Any]:
    if status in {"MICRO_V2_RISK_BLOCK_NOT_ENOUGH_DATA", "MICRO_V2_RISK_BLOCK_SAFETY_BLOCKED", "MICRO_V2_RISK_BLOCK_EXPECTED_SAFETY_GUARD"}:
        return {}
    return {
        "NOT_ACTIVE_RESEARCH_ONLY": True,
        "REQUIRES_REVIEW_PHASE": True,
        "APPROVED_FOR_RUNTIME": False,
        "dominant_risk_block_reason": dominant.get("risk_block_reason", ""),
        "dominant_risk_block_count": dominant.get("count", 0),
        "dominant_risk_block_share": dominant.get("share", 0.0),
        "proposal": "Create a later explicit risk-block review phase before any profile or runtime change.",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    extracted: Mapping[str, Any],
    audits: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_risk_block_summary.json",
        output / "risk_rejections.csv",
        output / "risk_reason_breakdown.csv",
        output / "risk_by_symbol.csv",
        output / "risk_by_session.csv",
        output / "cooldown_risk_audit.json",
        output / "trade_limit_audit.json",
        output / "exposure_risk_audit.json",
        output / "drawdown_risk_audit.json",
        output / "invalid_trade_state_audit.json",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], extracted.get("rows", []))
    _write_csv(paths[2], extracted.get("reason_breakdown", []))
    _write_csv(paths[3], extracted.get("by_symbol", []))
    _write_csv(paths[4], extracted.get("by_session", []))
    _write_json(paths[5], audits["cooldown"])
    _write_json(paths[6], {"trade_limit": audits["trade_limit"], "max_open_trades": audits["max_open_trades"], "paper_risk_state": audits["paper_risk_state"], "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(paths[7], audits["exposure"])
    _write_json(paths[8], {"drawdown": audits["drawdown"], "daily_ledger": audits["daily_ledger"], "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(paths[9], audits["invalid_trade_state"])
    paths[10].write_text(_recommendations(summary), encoding="utf-8")
    if candidate:
        rec_path = output / "risk_block_fix_recommendations.md"
        cand_path = output / "risk_block_candidate.json"
        rec_path.write_text(_candidate_recommendations(summary, candidate), encoding="utf-8")
        _write_json(cand_path, candidate)
        paths.extend([rec_path, cand_path])
    paths[11].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Risk Block Audit

Status: `{summary.get('micro_v2_risk_block_status')}`

Dominant risk block: `{summary.get('dominant_risk_block_reason')}`

Risk rejected count: `{summary.get('risk_rejected_count')}`

Affected symbols: `{', '.join(summary.get('affected_symbols', []))}`

Recommended next action: `{summary.get('recommended_next_action')}`

This audit is offline/read-only. It does not tune profiles or authorize demo/live execution.
"""


def _candidate_recommendations(summary: Mapping[str, Any], candidate: Mapping[str, Any]) -> str:
    return f"""# Risk Block Fix Recommendations

Status: `{summary.get('micro_v2_risk_block_status')}`

Candidate is research-only: `{candidate.get('NOT_ACTIVE_RESEARCH_ONLY')}`

Runtime approved: `{candidate.get('APPROVED_FOR_RUNTIME')}`

Any adjustment requires a later explicit review phase, especially while market-closed rejections still dominate V2 telemetry.
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Risk Block Audit</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


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

"""Report orchestration for paper PnL root-cause audit."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import extract_paper_risk_multiplier

from .drawdown_trigger_auditor import audit_drawdown_trigger
from .micro_risk_application_auditor import audit_micro_risk_application
from .paper_trade_loader import load_paper_trade_evidence
from .pnl_formula_auditor import audit_pnl_formulas
from .symbol_contract_auditor import audit_symbol_contracts


def run_paper_pnl_audit(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    daily_risk_dir: str | Path = "data/reports/paper_daily_risk",
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_pnl_audit",
    mt5_client: Any | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence = load_paper_trade_evidence(database=database, log_dir=log_dir, reports_root=reports_root, paper_risk_dir=paper_risk_dir, daily_risk_dir=daily_risk_dir, profile_config=profile_config)
    trades = list(evidence.get("trades", []))
    contracts = audit_symbol_contracts(trades, mt5_client=mt5_client)
    formulas = audit_pnl_formulas(trades, contracts)
    micro = audit_micro_risk_application(trades, formulas)
    drawdown = audit_drawdown_trigger(evidence, trades, formulas)
    scaling = _scaling_summary(trades, profile_config)
    status, root_cause = _status(formulas, micro, drawdown, scaling)
    affected_symbols = sorted({str(row.get("symbol")) for row in formulas if row.get("audit_flags")})
    affected_strategies = sorted({str(row.get("strategy_name")) for row in formulas if row.get("audit_flags")})
    summary = {
        "mode": "paper-pnl-audit",
        "paper_pnl_audit_status": status,
        "root_cause": root_cause,
        "pnl_scaling_issue_detected": status in {"PAPER_PNL_SCALING_BUG", "MICRO_RISK_NOT_APPLIED"},
        "micro_multiplier_applied": micro.get("micro_multiplier_applied", False),
        "risk_multiplier_applied": micro.get("risk_multiplier_applied", False),
        "legacy_unscaled_events": scaling.get("legacy_unscaled_trade_count", 0) > 0,
        "legacy_unscaled_trade_count": scaling.get("legacy_unscaled_trade_count", 0),
        "scaled_trade_count": scaling.get("scaled_trade_count", 0),
        "profile_multiplier": scaling.get("profile_multiplier"),
        "current_engine_multiplier_ready": scaling.get("multiplier_application_ready", False),
        "micro_risk_application_status": micro.get("micro_risk_application_status", ""),
        "drawdown_trigger_status": drawdown.get("drawdown_trigger_status", ""),
        "affected_symbols": affected_symbols,
        "affected_strategies": affected_strategies,
        "recommended_action": _recommended_action(status, root_cause),
        "trade_count": len(trades),
        "halt_count": len(evidence.get("halts", [])),
        "profile_config": str(profile_config) if profile_config else "",
        "profile_defaults": evidence.get("profile_defaults", {}),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, formulas, contracts, drawdown)
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def run_paper_risk_recommendation(
    *,
    reports_root: str | Path = "data/reports",
    pnl_audit_dir: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_pnl_audit",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    audit_dir = Path(pnl_audit_dir) if pnl_audit_dir else Path(reports_root) / "paper_pnl_audit"
    audit = _load_json(audit_dir / "paper_pnl_audit_summary.json")
    status = str(audit.get("paper_pnl_audit_status") or "PAPER_PNL_AUDIT_INCONCLUSIVE")
    recommendation = _recommendation(status)
    summary = {
        "mode": "paper-risk-recommendation",
        "recommendation": recommendation,
        "safe_to_clear_again": recommendation == "READY_FOR_NEW_MICRO_CLEARANCE",
        "required_fix": _required_fix(status),
        "suggested_micro_multiplier": 0.05 if status in {"VALID_MICRO_DRAWDOWN_HALT", "DRAWDOWN_THRESHOLD_TOO_TIGHT"} else None,
        "symbols_to_disable": audit.get("affected_symbols", []) if recommendation == "DISABLE_SYMBOL_FOR_MICRO" else [],
        "strategies_to_disable": audit.get("affected_strategies", []) if recommendation == "DISABLE_STRATEGY_FOR_MICRO" else [],
        "whether_new_clearance_allowed": recommendation == "READY_FOR_NEW_MICRO_CLEARANCE",
        "paper_pnl_audit_status": status,
        "root_cause": audit.get("root_cause", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_risk_recommendation.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def run_paper_pnl_scaling_check(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_pnl_audit",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trades = [_trade_payload(row) for row in database.fetch_paper_trades()]
    scaling = _scaling_summary(trades, profile_config)
    profile_multiplier = scaling.get("profile_multiplier")
    if profile_multiplier is None:
        status = "PAPER_PNL_SCALING_CONFIG_MISSING"
    elif scaling.get("legacy_unscaled_trade_count", 0) > 0:
        status = "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"
    elif scaling.get("scaled_trade_count", 0) > 0 or not trades:
        status = "PAPER_PNL_SCALING_FIXED"
    else:
        status = "PAPER_PNL_SCALING_NOT_FIXED"
    summary = {
        "mode": "paper-pnl-scaling-check",
        "paper_pnl_scaling_status": status,
        "profile_multiplier": profile_multiplier,
        "legacy_unscaled_trade_count": scaling.get("legacy_unscaled_trade_count", 0),
        "scaled_trade_count": scaling.get("scaled_trade_count", 0),
        "multiplier_application_ready": status in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"},
        "can_run_micro_shadow_after_new_clearance": status in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"},
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_pnl_scaling_check.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def run_paper_risk_post_fix_gate(
    *,
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/paper_pnl_audit",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = Path(reports_root)
    scaling = _load_json(reports / "paper_pnl_audit" / "paper_pnl_scaling_check.json")
    audit = _load_json(reports / "paper_pnl_audit" / "paper_pnl_audit_summary.json")
    risk_status = _load_json(reports / "paper_risk" / "paper_risk_status.json")
    execution = _load_json(reports / "execution_evidence" / "execution_evidence_summary.json")
    telemetry = _load_json(reports / "telemetry_repair" / "telemetry_timestamp_summary.json")
    scaling_status = str(scaling.get("paper_pnl_scaling_status", "PAPER_PNL_SCALING_NOT_FIXED"))
    if scaling_status not in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"}:
        decision = "NEEDS_PNL_SCALING_FIX"
    elif int(scaling.get("legacy_unscaled_trade_count", 0) or 0) > 0 and str(risk_status.get("daily_risk_ledger_status", "")).upper() not in {"DAILY_RISK_LEDGER_ACCEPTED", "DAILY_RISK_LEDGER_MISSING", ""}:
        decision = "NEEDS_LEGACY_EVENT_QUARANTINE"
    elif execution.get("blocking_findings_count", 0) or telemetry.get("active_blocking_count", 0):
        decision = "KEEP_BLOCKED"
    else:
        decision = "READY_FOR_NEW_MICRO_CLEARANCE"
    summary = {
        "mode": "paper-risk-post-fix-gate",
        "decision": decision,
        "classification": decision,
        "paper_pnl_scaling_status": scaling_status,
        "paper_pnl_audit_status": audit.get("paper_pnl_audit_status", ""),
        "legacy_unscaled_trade_count": scaling.get("legacy_unscaled_trade_count", 0),
        "scaled_trade_count": scaling.get("scaled_trade_count", 0),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_risk_post_fix_gate.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def _status(formulas: list[Mapping[str, Any]], micro: Mapping[str, Any], drawdown: Mapping[str, Any], scaling: Mapping[str, Any]) -> tuple[str, str]:
    drawdown_flags = set(drawdown.get("trigger_flags", []))
    if "DRAWDOWN_HISTORY_LEAK" in drawdown_flags:
        return "DRAWDOWN_HISTORY_LEAK", "DRAWDOWN_HISTORY_LEAK"
    if scaling.get("multiplier_application_ready") and scaling.get("legacy_unscaled_trade_count", 0):
        return "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS", "LEGACY_UNSCALED_PNL"
    if scaling.get("multiplier_application_ready"):
        return "PAPER_PNL_SCALING_FIXED", "PAPER_RISK_MULTIPLIER_APPLIED"
    flags = ";".join(str(row.get("audit_flags", "")) for row in formulas)
    if "MICRO_MULTIPLIER_NOT_APPLIED" in flags or micro.get("micro_risk_application_status") == "MICRO_MULTIPLIER_NOT_APPLIED":
        return "MICRO_RISK_NOT_APPLIED", "MICRO_MULTIPLIER_NOT_APPLIED"
    if any(flag in flags for flag in ("PNL_SIGN_ERROR", "PNL_SCALE_TOO_LARGE", "POINT_PIP_MISMATCH", "RISK_MULTIPLIER_NOT_APPLIED")):
        return "PAPER_PNL_SCALING_BUG", _first_flag(flags)
    if "DRAWDOWN_HISTORY_LEAK" in drawdown_flags:
        return "DRAWDOWN_HISTORY_LEAK", "DRAWDOWN_HISTORY_LEAK"
    if "DRAWDOWN_UNIT_MISMATCH" in drawdown_flags:
        return "DRAWDOWN_THRESHOLD_TOO_TIGHT", "DRAWDOWN_UNIT_MISMATCH"
    if "DRAWDOWN_TRIGGER_VALID" in drawdown_flags:
        return "VALID_MICRO_DRAWDOWN_HALT", "DRAWDOWN_TRIGGER_VALID"
    return "PAPER_PNL_AUDIT_INCONCLUSIVE", "DRAWDOWN_TRIGGER_UNKNOWN"


def _first_flag(flags: str) -> str:
    for item in ("PNL_SIGN_ERROR", "PNL_SCALE_TOO_LARGE", "RISK_MULTIPLIER_NOT_APPLIED", "POINT_PIP_MISMATCH"):
        if item in flags:
            return item
    return "UNKNOWN_PNL_FORMULA"


def _recommended_action(status: str, root_cause: str) -> str:
    if status in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"}:
        return "READY_FOR_NEW_MICRO_CLEARANCE"
    if status in {"PAPER_PNL_SCALING_BUG", "MICRO_RISK_NOT_APPLIED"}:
        return "FIX_PAPER_PNL_SCALING"
    if status == "DRAWDOWN_HISTORY_LEAK":
        return "READY_FOR_NEW_MICRO_CLEARANCE"
    if status == "VALID_MICRO_DRAWDOWN_HALT":
        return "REDUCE_MICRO_RISK_FURTHER"
    if status == "DRAWDOWN_THRESHOLD_TOO_TIGHT":
        return "REDUCE_MICRO_RISK_FURTHER"
    return "KEEP_BLOCKED"


def _recommendation(status: str) -> str:
    if status in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"}:
        return "READY_FOR_NEW_MICRO_CLEARANCE"
    if status in {"PAPER_PNL_SCALING_BUG", "MICRO_RISK_NOT_APPLIED"}:
        return "FIX_PAPER_PNL_SCALING"
    if status == "VALID_MICRO_DRAWDOWN_HALT":
        return "REDUCE_MICRO_RISK_FURTHER"
    if status == "DRAWDOWN_HISTORY_LEAK":
        return "READY_FOR_NEW_MICRO_CLEARANCE"
    if status == "DRAWDOWN_THRESHOLD_TOO_TIGHT":
        return "REDUCE_MICRO_RISK_FURTHER"
    return "KEEP_BLOCKED"


def _required_fix(status: str) -> str:
    if status in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"}:
        return "No PnL scaling fix required for the current engine; review legacy events and daily risk ledger before clearance."
    if status == "MICRO_RISK_NOT_APPLIED":
        return "Apply PAPER_RISK_MULTIPLIER to paper lot/risk or normalize reported paper PnL before new clearance."
    if status == "PAPER_PNL_SCALING_BUG":
        return "Repair paper PnL formula/sign/point scaling before new clearance."
    if status == "DRAWDOWN_HISTORY_LEAK":
        return "Repair daily drawdown window so pre-clearance PnL does not trigger active-day halt."
    if status == "VALID_MICRO_DRAWDOWN_HALT":
        return "Keep blocked until risk is reduced further or symbol/strategy is disabled in research."
    return "Keep blocked and collect more paper PnL evidence."


def _write_reports(output: Path, summary: Mapping[str, Any], formulas: list[Mapping[str, Any]], contracts: list[Mapping[str, Any]], drawdown: Mapping[str, Any]) -> list[Path]:
    summary_path = output / "paper_pnl_audit_summary.json"
    trade_path = output / "trade_pnl_audit.csv"
    contract_path = output / "symbol_contract_audit.csv"
    drawdown_path = output / "drawdown_trigger_audit.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(trade_path, formulas)
    _write_csv(contract_path, contracts)
    _write_csv(drawdown_path, [drawdown])
    html_path.write_text(f"<html><body><h1>Paper PnL Audit</h1><pre>{html.escape(json.dumps(summary, indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return [summary_path, trade_path, contract_path, drawdown_path, html_path]


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    keys = sorted({key for row in rows for key in row.keys()} | {"execution_attempted"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _jsonable(row.get(key, False if key == "execution_attempted" else "")) for key in keys})


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return value


def _scaling_summary(trades: list[Mapping[str, Any]], profile_config: str | Path | None) -> dict[str, Any]:
    profile_multiplier = extract_paper_risk_multiplier(profile_config)
    scaled = sum(1 for trade in trades if bool(trade.get("multiplier_applied")) or trade.get("scaled_paper_pnl") is not None)
    legacy = max(0, len(trades) - scaled)
    return {
        "profile_multiplier": profile_multiplier,
        "scaled_trade_count": scaled,
        "legacy_unscaled_trade_count": legacy,
        "multiplier_application_ready": profile_multiplier is not None,
    }


def _trade_payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}

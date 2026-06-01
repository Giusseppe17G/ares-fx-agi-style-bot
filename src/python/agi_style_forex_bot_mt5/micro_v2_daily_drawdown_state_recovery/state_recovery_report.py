"""Report orchestration for Micro V2 daily drawdown state recovery."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .closed_trade_integrity_audit import audit_closed_trade_integrity
from .daily_risk_ledger_audit import audit_daily_risk_ledger
from .drawdown_halt_loader import load_drawdown_recovery_inputs, safety_flags
from .drawdown_recovery_plan import build_drawdown_recovery_plan
from .open_trade_integrity_audit import audit_open_trade_integrity
from .paper_state_error_audit import audit_paper_state_error
from .sqlite_backup_manager import create_v2_backup


def run_micro_v2_daily_drawdown_state_recovery(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path | None = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    resume_guard_dir: str | Path = "data/reports/micro_v2_post_repair_resume_guard",
    schema_repair_dir: str | Path = "data/reports/micro_v2_papertrade_schema_repair",
    repair_dir: str | Path = "data/reports/micro_v2_guarded_paper_state_repair",
    output_dir: str | Path = "data/reports/micro_v2_daily_drawdown_state_recovery",
    apply_repair: bool = False,
    backup_root: str | Path = "data/backups/micro_v2_daily_drawdown_state_recovery",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_drawdown_recovery_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        daily_risk_ledger=daily_risk_ledger,
        resume_guard_dir=resume_guard_dir,
        schema_repair_dir=schema_repair_dir,
        repair_dir=repair_dir,
    )
    dataset = inputs["dataset"]
    trades = list(dataset.get("paper_trades", []))
    closed = audit_closed_trade_integrity(trades)
    open_audit = audit_open_trade_integrity(trades)
    ledger = audit_daily_risk_ledger(inputs.get("daily_risk_ledger_payload", {}))
    paper_state = audit_paper_state_error(dataset, closed, open_audit, ledger)
    quarantined_count = sum(1 for trade in trades if str(trade.get("status", "")).upper() == "QUARANTINED_INVALID_PAPER_TRADE")
    plan = build_drawdown_recovery_plan(
        safety_blocked=safety_flags(dataset),
        closed_audit=closed,
        open_audit=open_audit,
        ledger_audit=ledger,
        paper_state_audit=paper_state,
        quarantined_trade_count=quarantined_count,
    )
    backup_manifest: dict[str, Any] = {}
    repair_validation = {"repair_applied": False, "reason": "dry-run or no deterministic repair allowed"}
    if apply_repair and plan.get("repair_allowed"):
        backup_manifest = create_v2_backup(v2_sqlite, backup_root=backup_root)
        repair_validation = {
            "repair_applied": False,
            "reason": "No automated mutation implemented for this dry-run-safe diagnosis.",
            "backup_created": backup_manifest.get("backup_created", False),
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    status = "MICRO_V2_DRAWDOWN_STATE_REPAIR_APPLIED" if repair_validation.get("repair_applied") else str(plan.get("micro_v2_daily_drawdown_state_recovery_status"))
    summary = {
        "mode": "micro-v2-daily-drawdown-state-recovery",
        "micro_v2_daily_drawdown_state_recovery_status": status,
        "drawdown_halt_root_cause": paper_state.get("drawdown_halt_root_cause", ""),
        "repair_applied": bool(repair_validation.get("repair_applied", False)),
        "open_trade_count": open_audit.get("open_trade_count", 0),
        "closed_trade_count": closed.get("closed_trade_count", 0),
        "quarantined_trade_count": quarantined_count,
        "closed_scaled_pnl_total": closed.get("closed_scaled_pnl_total", 0.0),
        "daily_risk_status_after": ledger.get("daily_risk_ledger_status", ""),
        "paper_state_status_after": paper_state.get("paper_state_error_status", ""),
        "recommended_next_action": _next_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, ledger, paper_state, closed, open_audit, plan, repair_validation, backup_manifest)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _next_action(status: str) -> str:
    if status == "MICRO_V2_DRAWDOWN_HALT_LEGITIMATE":
        return "KEEP_V2_BLOCKED_REVIEW_CLOSED_PAPER_LOSSES"
    if "INTEGRITY_ISSUE" in status:
        return "MANUAL_REVIEW_REQUIRED_BEFORE_RELAUNCH"
    if status in {"MICRO_V2_DRAWDOWN_HALT_LEDGER_SCOPE_MISMATCH", "MICRO_V2_DRAWDOWN_HALT_QUARANTINE_CONTAMINATION"}:
        return "PREPARE_DETERMINISTIC_V2_ONLY_REPAIR_PHASE"
    if status == "MICRO_V2_DRAWDOWN_STATE_NO_REPAIR_NEEDED":
        return "RELAUNCH_V2_MANAGE_ONLY_IF_OTHER_GATES_CLEAR"
    return "REVIEW_DRAWDOWN_STATE_RECOVERY_REPORT"


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    ledger: Mapping[str, Any],
    paper_state: Mapping[str, Any],
    closed: Mapping[str, Any],
    open_audit: Mapping[str, Any],
    plan: Mapping[str, Any],
    repair_validation: Mapping[str, Any],
    backup_manifest: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_daily_drawdown_state_recovery_summary.json",
        output / "daily_risk_ledger_audit.json",
        output / "paper_state_error_audit.json",
        output / "closed_trade_integrity_audit.json",
        output / "open_trade_integrity_audit.json",
        output / "drawdown_recovery_plan.json",
        output / "repair_validation.json",
        output / "sqlite_backup_manifest.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], ledger)
    _write_json(paths[2], paper_state)
    _write_json(paths[3], closed)
    _write_json(paths[4], open_audit)
    _write_json(paths[5], plan)
    _write_json(paths[6], repair_validation)
    _write_json(paths[7], backup_manifest or {"backup_created": False, "reason": "dry-run or no repair applied"})
    paths[8].write_text(_commands(summary), encoding="utf-8")
    paths[9].write_text(_recommendations(summary), encoding="utf-8")
    paths[10].write_text(f"<html><body><h1>Micro V2 Daily Drawdown State Recovery</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _commands(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Daily Drawdown State Recovery

Status: `{summary.get('micro_v2_daily_drawdown_state_recovery_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Recommendations

Root cause: `{summary.get('drawdown_halt_root_cause')}`

Closed scaled PnL total: `{summary.get('closed_scaled_pnl_total')}`
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

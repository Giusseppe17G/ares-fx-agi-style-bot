"""Report orchestration for Micro V2 daily risk ledger scope repair."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .ledger_backup_manager import create_ledger_backup, sha256_file
from .ledger_scope_audit import audit_ledger_scope
from .ledger_scope_loader import load_scope_repair_inputs, safety_flags
from .scope_repair_apply import apply_scope_repair
from .scope_repair_plan import build_scope_repair_plan
from .scope_repair_validator import validate_scope_repair


def run_micro_v2_daily_risk_scope_repair(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    closed_loss_scope_dir: str | Path = "data/reports/micro_v2_closed_loss_scope_decision",
    drawdown_recovery_dir: str | Path = "data/reports/micro_v2_daily_drawdown_state_recovery_after_open_trade_repair",
    output_dir: str | Path = "data/reports/micro_v2_daily_risk_scope_repair",
    backup_root: str | Path = "data/backups/micro_v2_daily_risk_scope_repair",
    apply_repair: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_scope_repair_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        daily_risk_ledger=daily_risk_ledger,
        closed_loss_scope_dir=closed_loss_scope_dir,
        drawdown_recovery_dir=drawdown_recovery_dir,
    )
    audit = audit_ledger_scope(inputs)
    plan = build_scope_repair_plan(inputs, audit, safety_blocked=safety_flags(inputs["dataset"]))
    backup = {"backup_created": False, "backup_path": "", "backup_error": "NOT_REQUESTED_DRY_RUN"}
    apply_result = {"repair_applied": False, "apply_status": "SCOPE_REPAIR_NOT_APPLIED", "apply_reason": "DRY_RUN"}
    validation = _validation_not_run(audit)
    before_hash = sha256_file(daily_risk_ledger)
    status = _status_from_plan(plan, apply_repair=False)
    if apply_repair:
        status = _status_from_plan(plan, apply_repair=True)
        if plan.get("scope_repair_plan_status") == "MICRO_V2_DAILY_RISK_SCOPE_DRY_RUN_READY":
            backup = create_ledger_backup(daily_risk_ledger, backup_root=backup_root)
            if not backup.get("backup_created"):
                status = "MICRO_V2_DAILY_RISK_SCOPE_BLOCKED_BACKUP_FAILED"
            else:
                apply_result = apply_scope_repair(daily_risk_ledger, plan)
                validation = validate_scope_repair(daily_risk_ledger, before_audit=audit, before_sha256=before_hash)
                status = "MICRO_V2_DAILY_RISK_SCOPE_REPAIR_APPLIED" if validation.get("validation_passed") else "MICRO_V2_DAILY_RISK_SCOPE_VALIDATION_FAILED"
                backup["after_sha256"] = validation.get("after_sha256", "")
    summary = _summary(status, audit, plan, backup, apply_result, validation, apply_repair)
    paths = _write_reports(output, summary, audit, plan, backup, validation)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status_from_plan(plan: Mapping[str, Any], *, apply_repair: bool) -> str:
    plan_status = str(plan.get("scope_repair_plan_status") or "")
    if plan_status == "MICRO_V2_DAILY_RISK_SCOPE_NO_REPAIR_NEEDED":
        return plan_status
    if plan_status != "MICRO_V2_DAILY_RISK_SCOPE_DRY_RUN_READY":
        return plan_status
    return "MICRO_V2_DAILY_RISK_SCOPE_DRY_RUN_READY" if not apply_repair else "MICRO_V2_DAILY_RISK_SCOPE_REPAIR_APPLY_PENDING"


def _validation_not_run(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scope_repair_validation_status": "NOT_RUN",
        "validation_passed": False,
        "daily_risk_scope_status_after": audit.get("daily_risk_scope_status_before", ""),
        "daily_halt_active": bool(audit.get("daily_halt_active", False)),
        "closed_scaled_pnl_total_after": audit.get("closed_scaled_pnl_total", 0.0),
        "closed_trade_count_after": audit.get("closed_trade_count", 0),
        "pnl_changed": False,
        "daily_halt_cleared": False,
        "stable_scope_untouched": True,
        "v2_scope_present": bool(audit.get("ledger_contains_v2_scope", False)),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _summary(status: str, audit: Mapping[str, Any], plan: Mapping[str, Any], backup: Mapping[str, Any], apply_result: Mapping[str, Any], validation: Mapping[str, Any], apply_repair: bool) -> dict[str, Any]:
    after_status = validation.get("daily_risk_scope_status_after") or audit.get("daily_risk_scope_status_before")
    next_action = _next_action(status, bool(validation.get("daily_halt_active", audit.get("daily_halt_active", False))))
    return {
        "mode": "micro-v2-daily-risk-scope-repair",
        "micro_v2_daily_risk_scope_repair_status": status,
        "dry_run": not apply_repair,
        "repair_applied": bool(apply_result.get("repair_applied", False)),
        "daily_risk_scope_status_before": audit.get("daily_risk_scope_status_before", ""),
        "daily_risk_scope_status_after": after_status,
        "daily_halt_active": bool(validation.get("daily_halt_active", audit.get("daily_halt_active", False))),
        "closed_scaled_pnl_total": audit.get("closed_scaled_pnl_total", 0.0),
        "closed_trade_count": audit.get("closed_trade_count", 0),
        "quarantined_trade_count": audit.get("quarantined_trade_count", 0),
        "backup_created": bool(backup.get("backup_created", False)),
        "backup_path": backup.get("backup_path", ""),
        "stable_scope_untouched": bool(validation.get("stable_scope_untouched", True)),
        "v2_scope_present": bool(validation.get("v2_scope_present", audit.get("ledger_contains_v2_scope", False))),
        "daily_halt_cleared": bool(validation.get("daily_halt_cleared", False)),
        "pnl_changed": bool(validation.get("pnl_changed", False)),
        "next_allowed_action": next_action,
        "recommended_next_action": next_action,
        "plan_status": plan.get("scope_repair_plan_status", ""),
        "apply_status": apply_result.get("apply_status", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _next_action(status: str, daily_halt_active: bool) -> str:
    if status == "MICRO_V2_DAILY_RISK_SCOPE_REPAIR_APPLIED" and daily_halt_active:
        return "WAIT_FOR_DAILY_RESET_BEFORE_RELAUNCHING_V2"
    if status == "MICRO_V2_DAILY_RISK_SCOPE_DRY_RUN_READY":
        return "APPLY_SCOPE_REPAIR_WITH_BACKUP_THEN_WAIT_FOR_DAILY_RESET"
    if status == "MICRO_V2_DAILY_RISK_SCOPE_NO_REPAIR_NEEDED":
        return "WAIT_FOR_DAILY_RESET_BEFORE_RELAUNCHING_V2"
    if status == "MICRO_V2_DAILY_RISK_SCOPE_VALIDATION_FAILED":
        return "RESTORE_LEDGER_BACKUP_AND_REVIEW_MANUALLY"
    return "MANUAL_REVIEW_REQUIRED"


def _write_reports(output: Path, summary: Mapping[str, Any], audit: Mapping[str, Any], plan: Mapping[str, Any], backup: Mapping[str, Any], validation: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "micro_v2_daily_risk_scope_repair_summary.json",
        output / "ledger_scope_audit.json",
        output / "scope_repair_plan.json",
        output / "ledger_backup_manifest.json",
        output / "scope_repair_validation.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], audit)
    _write_json(paths[2], plan)
    _write_json(paths[3], backup)
    _write_json(paths[4], validation)
    paths[5].write_text(_commands(summary), encoding="utf-8")
    paths[6].write_text(_recommendations(summary), encoding="utf-8")
    paths[7].write_text(f"<html><body><h1>Micro V2 Daily Risk Scope Repair</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _commands(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Daily Risk Scope Repair

Status: `{summary.get('micro_v2_daily_risk_scope_repair_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

If the repair was applied and `daily_halt_active=true`, wait for the daily reset before relaunching V2. If validation failed, restore the ledger backup at `{summary.get('backup_path')}`.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Recommendations

This phase repairs only Micro V2 ledger scope metadata. It does not clear the daily halt and does not change PnL.

Daily halt active: `{summary.get('daily_halt_active')}`

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

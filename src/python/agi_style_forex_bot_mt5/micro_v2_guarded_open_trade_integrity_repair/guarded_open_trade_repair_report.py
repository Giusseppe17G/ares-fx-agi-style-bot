"""Report orchestration for guarded Micro V2 open-trade integrity repair."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .before_after_snapshot import snapshot_sqlite
from .invalid_open_trade_loader import load_invalid_open_trades
from .open_trade_quarantine import quarantine_invalid_open_trades
from .repair_plan_loader import load_open_trade_repair_plan
from .repair_validator import validate_open_trade_repair
from .runtime_stop_guard import audit_runtime_stopped
from .sqlite_backup_manager import create_sqlite_backup, sha256_file


def run_micro_v2_guarded_open_trade_integrity_repair(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    drawdown_recovery_dir: str | Path = "data/reports/micro_v2_daily_drawdown_state_recovery",
    schema_repair_dir: str | Path = "data/reports/micro_v2_papertrade_schema_repair",
    previous_repair_dir: str | Path = "data/reports/micro_v2_guarded_paper_state_repair",
    output_dir: str | Path = "data/reports/micro_v2_guarded_open_trade_integrity_repair",
    backup_root: str | Path = "data/backups/micro_v2_guarded_open_trade_integrity_repair",
    apply_repair: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    plan = load_open_trade_repair_plan(drawdown_recovery_dir)
    trade_ids = list(plan.get("target_trade_ids", []))
    before = snapshot_sqlite(v2_sqlite, trade_ids)
    targets = load_invalid_open_trades(v2_sqlite, trade_ids)
    runtime = audit_runtime_stopped(v2_sqlite, v2_log_dir)
    backup: dict[str, Any] = {"backup_created": False, "backup_path": "", "backup_error": "NOT_REQUESTED_DRY_RUN"}
    quarantine: dict[str, Any] = {"quarantine_applied": False, "quarantined_trade_ids": [], "quarantined_trade_count": 0, "quarantine_events": []}
    after = before
    validation = _validation_not_run()
    status = _preflight_status(plan, targets, runtime)
    if not status and not apply_repair:
        status = "MICRO_V2_OPEN_TRADE_REPAIR_DRY_RUN_READY"
    elif not status and apply_repair:
        if runtime.get("runtime_active"):
            status = "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_RUNTIME_ACTIVE"
        else:
            backup = create_sqlite_backup(v2_sqlite, backup_root=backup_root)
            if not backup.get("backup_created"):
                status = "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_BACKUP_FAILED"
            else:
                quarantine = quarantine_invalid_open_trades(v2_sqlite, list(targets.get("target_trades", [])))
                status = str(quarantine.get("blocked_status") or "")
                if not status:
                    after = snapshot_sqlite(v2_sqlite, trade_ids)
                    validation = validate_open_trade_repair(before, after, quarantine)
                    status = "MICRO_V2_OPEN_TRADE_REPAIR_APPLIED_SUCCESSFULLY" if validation.get("validation_passed") else "MICRO_V2_OPEN_TRADE_REPAIR_VALIDATION_FAILED"
                    backup["after_sha256"] = sha256_file(v2_sqlite)
    summary = {
        "mode": "micro-v2-guarded-open-trade-integrity-repair",
        "micro_v2_guarded_open_trade_integrity_repair_status": status,
        "dry_run": not apply_repair,
        "repair_applied": status == "MICRO_V2_OPEN_TRADE_REPAIR_APPLIED_SUCCESSFULLY",
        "repaired_trade_ids": quarantine.get("quarantined_trade_ids", []),
        "target_trade_ids": trade_ids,
        "quarantined_trade_count_before": before.get("quarantined_trade_count", 0),
        "quarantined_trade_count_after": after.get("quarantined_trade_count", before.get("quarantined_trade_count", 0)),
        "open_trade_count_before": before.get("open_trade_count", 0),
        "open_trade_count_after": after.get("open_trade_count", before.get("open_trade_count", 0)),
        "invalid_open_trade_count_before": before.get("invalid_open_trade_count", 0),
        "invalid_open_trade_count_after": after.get("invalid_open_trade_count", before.get("invalid_open_trade_count", 0)),
        "closed_trade_count_changed": bool(validation.get("closed_trade_count_changed", False)),
        "pnl_changed": bool(validation.get("pnl_changed", False)),
        "backup_created": bool(backup.get("backup_created", False)),
        "runtime_active": bool(runtime.get("runtime_active", False)),
        "runtime_guard_status": runtime.get("runtime_guard_status", ""),
        "recommended_next_action": _next_action(status),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "schema_repair_dir": str(schema_repair_dir),
        "previous_repair_dir": str(previous_repair_dir),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, before, after, targets, backup, quarantine, validation, runtime, plan)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _preflight_status(plan: Mapping[str, Any], targets: Mapping[str, Any], runtime: Mapping[str, Any]) -> str:
    if runtime.get("safety_flags_detected"):
        return "MICRO_V2_OPEN_TRADE_REPAIR_SAFETY_BLOCKED"
    if not plan.get("plan_valid"):
        if "UNSAFE_REPAIR_ACTION" in plan.get("plan_errors", []):
            return "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_UNSAFE_ACTION"
        return "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_PLAN_MISMATCH"
    if not targets.get("target_validation_passed"):
        return str(targets.get("blocked_status") or "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_PLAN_MISMATCH")
    return ""


def _validation_not_run() -> dict[str, Any]:
    return {
        "repair_validation_status": "OPEN_TRADE_REPAIR_VALIDATION_NOT_RUN",
        "validation_passed": False,
        "closed_trade_count_changed": False,
        "pnl_changed": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _next_action(status: str) -> str:
    if status == "MICRO_V2_OPEN_TRADE_REPAIR_DRY_RUN_READY":
        return "APPLY_ONLY_AFTER_V2_RUNTIME_IS_STOPPED"
    if status == "MICRO_V2_OPEN_TRADE_REPAIR_APPLIED_SUCCESSFULLY":
        return "RERUN_MICRO_V2_DAILY_DRAWDOWN_STATE_RECOVERY"
    if status == "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_RUNTIME_ACTIVE":
        return "STOP_V2_RUNTIME_AND_REPEAT_DRY_RUN"
    if status == "MICRO_V2_OPEN_TRADE_REPAIR_VALIDATION_FAILED":
        return "RESTORE_BACKUP_AND_REVIEW_MANUALLY"
    return "DO_NOT_TOUCH_SQLITE_MANUALLY_REVIEW_REPAIR_REPORT"


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    targets: Mapping[str, Any],
    backup: Mapping[str, Any],
    quarantine: Mapping[str, Any],
    validation: Mapping[str, Any],
    runtime: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_guarded_open_trade_integrity_repair_summary.json",
        output / "repair_before_snapshot.json",
        output / "repair_after_snapshot.json",
        output / "invalid_open_trades_targeted.csv",
        output / "sqlite_backup_manifest.json",
        output / "quarantine_events.json",
        output / "repair_validation.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], before)
    _write_json(paths[2], after)
    _write_target_csv(paths[3], targets.get("target_trades", []))
    _write_json(paths[4], backup)
    _write_json(paths[5], {"quarantine_events": quarantine.get("quarantine_events", []), **dict(quarantine)})
    _write_json(paths[6], validation)
    paths[7].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[8].write_text(_recommendations(summary, runtime, plan), encoding="utf-8")
    paths[9].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Guarded Open Trade Integrity Repair

Status: `{summary.get('micro_v2_guarded_open_trade_integrity_repair_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

If dry-run is ready, apply only with V2 runtime stopped. If apply succeeds, rerun `micro-v2-daily-drawdown-state-recovery`.
"""


def _recommendations(summary: Mapping[str, Any], runtime: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    return f"""# Guarded Open Trade Repair Recommendations

Repair applied: `{summary.get('repair_applied')}`

Runtime guard: `{runtime.get('runtime_guard_status')}`

Repair action: `{plan.get('repair_action')}`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Guarded Open Trade Integrity Repair</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_target_csv(path: Path, rows: Any) -> None:
    fields = ["paper_trade_id", "symbol", "entry_price", "sl_price", "tp_price", "issue"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows or []:
            writer.writerow({field: row.get(field, "") for field in fields})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

"""Report orchestration for guarded Micro V2 paper-state repair."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .before_after_snapshot import snapshot_sqlite
from .paper_trade_quarantine import quarantine_invalid_paper_trade
from .repair_plan_loader import load_repair_plan
from .repair_validator import validate_repair
from .runtime_stop_guard import audit_runtime_stopped
from .sqlite_backup_manager import create_sqlite_backup, sha256_file


def run_micro_v2_guarded_paper_state_repair(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    repair_plan: str | Path = "data/reports/micro_v2_invalid_trade_forensics/repair_plan.json",
    forensics_dir: str | Path = "data/reports/micro_v2_invalid_trade_forensics",
    lifecycle_dir: str | Path = "data/reports/micro_v2_lifecycle_risk_comparison",
    output_dir: str | Path = "data/reports/micro_v2_guarded_paper_state_repair",
    backup_root: str | Path = "data/backups/micro_v2_guarded_paper_state_repair",
    apply_repair: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    plan = load_repair_plan(repair_plan)
    forensics = _load_json(Path(forensics_dir) / "micro_v2_invalid_trade_forensics_summary.json")
    lifecycle = _load_json(Path(lifecycle_dir) / "micro_v2_lifecycle_risk_comparison_summary.json")
    trade_ids = [str(item) for item in plan.get("target_trade_ids", []) if str(item)]
    before = snapshot_sqlite(v2_sqlite, trade_ids)
    runtime = audit_runtime_stopped(v2_sqlite, v2_log_dir)
    backup: dict[str, Any] = {"backup_created": False, "backup_path": "", "backup_error": "NOT_REQUESTED_DRY_RUN"}
    quarantine: dict[str, Any] = {"quarantine_applied": False, "quarantined_trade_ids": [], "quarantined_trade_count": 0}
    after = before
    validation = {
        "repair_validation_status": "REPAIR_VALIDATION_NOT_RUN",
        "validation_passed": False,
        "closed_trade_count_changed": False,
        "pnl_changed": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    status = "MICRO_V2_REPAIR_SAFETY_BLOCKED" if runtime.get("safety_flags_detected") else _preflight_status(plan, forensics, before)
    if status == "" and not apply_repair:
        status = "MICRO_V2_REPAIR_DRY_RUN_READY"
    elif status == "" and apply_repair:
        if runtime.get("runtime_active"):
            status = "MICRO_V2_REPAIR_BLOCKED_RUNTIME_ACTIVE"
        else:
            backup = create_sqlite_backup(v2_sqlite, backup_root=backup_root)
            if not backup.get("backup_created"):
                status = "MICRO_V2_REPAIR_BLOCKED_BACKUP_FAILED"
            else:
                target_trade_id = trade_ids[0]
                quarantine = quarantine_invalid_paper_trade(
                    v2_sqlite,
                    trade_id=target_trade_id,
                    expected_symbol=(forensics.get("affected_symbols") or ["EURUSD"])[0],
                    root_cause=str(plan.get("root_cause") or ""),
                )
                status = str(quarantine.get("blocked_status") or "")
                if not status:
                    after = snapshot_sqlite(v2_sqlite, trade_ids)
                    validation = validate_repair(before, after, quarantine)
                    status = "MICRO_V2_REPAIR_APPLIED_SUCCESSFULLY" if validation.get("validation_passed") else "MICRO_V2_REPAIR_VALIDATION_FAILED"
                    backup["after_sha256"] = sha256_file(v2_sqlite)
    if after is before and apply_repair and status.startswith("MICRO_V2_REPAIR_BLOCKED"):
        after = snapshot_sqlite(v2_sqlite, trade_ids)
    summary = {
        "mode": "micro-v2-guarded-paper-state-repair",
        "micro_v2_guarded_repair_status": status,
        "repair_applied": status == "MICRO_V2_REPAIR_APPLIED_SUCCESSFULLY",
        "dry_run": not apply_repair,
        "repaired_trade_ids": quarantine.get("quarantined_trade_ids", []),
        "quarantined_trade_count": quarantine.get("quarantined_trade_count", 0),
        "backup_created": bool(backup.get("backup_created", False)),
        "backup_path": backup.get("backup_path", ""),
        "runtime_active": bool(runtime.get("runtime_active", False)),
        "runtime_guard_status": runtime.get("runtime_guard_status", ""),
        "closed_trade_count_changed": bool(validation.get("closed_trade_count_changed", False)),
        "pnl_changed": bool(validation.get("pnl_changed", False)),
        "recommended_next_action": _next_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, before, after, backup, quarantine, validation, runtime, plan, lifecycle)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _preflight_status(plan: Mapping[str, Any], forensics: Mapping[str, Any], before: Mapping[str, Any]) -> str:
    if not plan.get("plan_valid"):
        if "UNSAFE_REPAIR_ACTION" in plan.get("plan_errors", []):
            return "MICRO_V2_REPAIR_BLOCKED_UNSAFE_ACTION"
        return "MICRO_V2_REPAIR_BLOCKED_PLAN_MISMATCH"
    if forensics and forensics.get("repair_action_recommended") != plan.get("repair_action_recommended"):
        return "MICRO_V2_REPAIR_BLOCKED_PLAN_MISMATCH"
    if not before.get("target_trades"):
        return "MICRO_V2_REPAIR_BLOCKED_TRADE_NOT_FOUND"
    target = before.get("target_trades", [{}])[0]
    if str(target.get("status", "")).upper() not in {"OPEN", "ACTIVE"}:
        return "MICRO_V2_REPAIR_BLOCKED_TRADE_ALREADY_CLOSED"
    if target.get("symbol") != "EURUSD" or plan.get("root_cause") != "SL_EQUALS_ENTRY":
        return "MICRO_V2_REPAIR_BLOCKED_PLAN_MISMATCH"
    return ""


def _next_action(status: str) -> str:
    if status == "MICRO_V2_REPAIR_DRY_RUN_READY":
        return "APPLY_ONLY_AFTER_V2_RUNTIME_IS_STOPPED"
    if status == "MICRO_V2_REPAIR_APPLIED_SUCCESSFULLY":
        return "RERUN_MICRO_V2_LIFECYCLE_RISK_COMPARISON"
    if status == "MICRO_V2_REPAIR_BLOCKED_RUNTIME_ACTIVE":
        return "STOP_V2_RUNTIME_AND_REPEAT_DRY_RUN"
    if status == "MICRO_V2_REPAIR_VALIDATION_FAILED":
        return "RESTORE_BACKUP_AND_REVIEW_MANUALLY"
    return "DO_NOT_TOUCH_SQLITE_MANUALLY_REVIEW_REPAIR_REPORT"


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    backup: Mapping[str, Any],
    quarantine: Mapping[str, Any],
    validation: Mapping[str, Any],
    runtime: Mapping[str, Any],
    plan: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_guarded_paper_state_repair_summary.json",
        output / "repair_before_snapshot.json",
        output / "repair_after_snapshot.json",
        output / "sqlite_backup_manifest.json",
        output / "quarantine_event.json",
        output / "repair_validation.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], before)
    _write_json(paths[2], after)
    _write_json(paths[3], backup)
    _write_json(paths[4], quarantine.get("quarantine_event", quarantine))
    _write_json(paths[5], validation)
    paths[6].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[7].write_text(_recommendations(summary, runtime, plan, lifecycle), encoding="utf-8")
    paths[8].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Guarded Paper-State Repair

Status: `{summary.get('micro_v2_guarded_repair_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

If dry-run is ready, apply only with V2 runtime stopped. If apply succeeds, rerun `micro-v2-lifecycle-risk-comparison`.
"""


def _recommendations(summary: Mapping[str, Any], runtime: Mapping[str, Any], plan: Mapping[str, Any], lifecycle: Mapping[str, Any]) -> str:
    return f"""# Guarded Repair Recommendations

Repair applied: `{summary.get('repair_applied')}`

Runtime guard: `{runtime.get('runtime_guard_status')}`

Repair action: `{plan.get('repair_action_recommended')}`

Lifecycle status before repair: `{lifecycle.get('micro_v2_lifecycle_risk_comparison_status')}`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Guarded Paper-State Repair</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

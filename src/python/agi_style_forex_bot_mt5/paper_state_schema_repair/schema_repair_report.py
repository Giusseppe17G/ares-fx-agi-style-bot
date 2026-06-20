"""Report orchestration for paper state schema repair."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .sqlite_schema_sanitizer import scan_and_repair_sqlite


def run_paper_state_schema_repair(
    *,
    sqlite_path: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    output_dir: str | Path = "data/reports/paper_state_schema_repair",
    backup_dir: str | Path = "data/backups/paper_state_schema_repair",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result = scan_and_repair_sqlite(sqlite_path, backup_dir=backup_dir)
    resolution = result.get("config_error_resolution") if isinstance(result.get("config_error_resolution"), Mapping) else {}
    status = _status(result, resolution)
    summary = {
        "mode": "paper-state-schema-repair",
        "paper_state_schema_repair_status": status,
        "sqlite": str(sqlite_path),
        "incompatible_record_count": int(result.get("incompatible_record_count", 0) or 0),
        "repaired_record_count": int(result.get("repaired_record_count", 0) or 0),
        "quarantine_record_count": int(result.get("quarantine_record_count", 0) or 0),
        "active_corrupt_record_count": int(result.get("active_corrupt_record_count", 0) or 0),
        "open_trade_count": int(result.get("open_trade_count", 0) or 0),
        "mt5_connected": bool(result.get("mt5_connected", False)),
        "config_error_resolved": bool(resolution.get("config_error_resolved", False)),
        "paper_state_transition": resolution.get("paper_state_transition", ""),
        "recommended_next_action": _next_action(status),
        "backup": result.get("backup", {}),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, result, resolution)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(result: Mapping[str, Any], resolution: Mapping[str, Any]) -> str:
    if int(result.get("active_corrupt_record_count", 0) or 0) > 0:
        return "PAPER_STATE_SCHEMA_REPAIR_ACTIVE_CORRUPT_RECORDS_REMAIN"
    if int(result.get("quarantine_record_count", 0) or 0) > 0:
        return "PAPER_STATE_SCHEMA_REPAIR_QUARANTINE_REVIEW_REQUIRED"
    if resolution.get("config_error_resolved"):
        return "PAPER_STATE_SCHEMA_REPAIR_CONFIG_ERROR_CLEARED"
    if int(result.get("repaired_record_count", 0) or 0) > 0:
        return "PAPER_STATE_SCHEMA_REPAIR_COMPATIBILITY_REPAIRED"
    return "PAPER_STATE_SCHEMA_REPAIR_NO_ACTION_NEEDED"


def _next_action(status: str) -> str:
    if status == "PAPER_STATE_SCHEMA_REPAIR_CONFIG_ERROR_CLEARED":
        return "WAIT_FOR_NEXT_DAILY_RESET_THEN_RERUN_PHASE76_ORCHESTRATOR"
    if status == "PAPER_STATE_SCHEMA_REPAIR_COMPATIBILITY_REPAIRED":
        return "RERUN_STATUS_AND_PHASE76_ORCHESTRATOR"
    if status == "PAPER_STATE_SCHEMA_REPAIR_ACTIVE_CORRUPT_RECORDS_REMAIN":
        return "MANUAL_REVIEW_ACTIVE_CORRUPT_PAPER_RECORDS"
    if status == "PAPER_STATE_SCHEMA_REPAIR_QUARANTINE_REVIEW_REQUIRED":
        return "REVIEW_QUARANTINE_RECORDS_BEFORE_RELAUNCH"
    return "RERUN_PHASE76_ORCHESTRATOR_IF_RESET_IS_READY"


def _write_reports(output: Path, summary: Mapping[str, Any], result: Mapping[str, Any], resolution: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "schema_repair_summary.json",
        output / "incompatible_records.csv",
        output / "repaired_records.csv",
        output / "quarantine_records.csv",
        output / "config_error_resolution.json",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], result.get("incompatible_records", []))
    _write_csv(paths[2], result.get("repaired_records", []))
    _write_csv(paths[3], result.get("quarantine_records", []))
    _write_json(paths[4], resolution)
    paths[5].write_text(f"<html><body><h1>Paper State Schema Repair</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Any) -> None:
    fieldnames = ["row_id", "paper_trade_id", "status", "symbol", "reason", "fields", "legacy_fields", "execution_attempted", "order_send_called", "order_check_called"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows or []:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

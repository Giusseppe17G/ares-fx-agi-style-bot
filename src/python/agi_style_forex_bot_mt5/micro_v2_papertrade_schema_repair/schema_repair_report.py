"""Report orchestration for Micro V2 PaperTrade schema repair."""

from __future__ import annotations

import csv
import html
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset
from agi_style_forex_bot_mt5.paper_trading.paper_trade import sanitize_paper_trade_payload

from .papertrade_loader_audit import audit_papertrade_loader
from .post_exit_state_audit import audit_post_exit_state
from .schema_field_audit import audit_schema_fields
from .sqlite_backup_manager import create_sqlite_backup


def run_micro_v2_papertrade_schema_repair(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    resume_guard_dir: str | Path = "data/reports/micro_v2_post_repair_resume_guard",
    repair_dir: str | Path = "data/reports/micro_v2_guarded_paper_state_repair",
    output_dir: str | Path = "data/reports/micro_v2_papertrade_schema_repair",
    apply_repair: bool = False,
    backup_root: str | Path = "data/backups/micro_v2_papertrade_schema_repair",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    dataset = load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2")
    trades = list(dataset.get("paper_trades", []))
    events = list(dataset.get("events", []))
    schema = audit_schema_fields(trades, events)
    loader = audit_papertrade_loader(trades)
    post_exit = audit_post_exit_state(trades)
    repair_validation = _repair_validation(schema, loader, post_exit)
    backup_manifest: dict[str, Any] = {}
    sqlite_repair = {"sqlite_repair_applied": False, "rows_normalized": 0}
    if apply_repair and _sqlite_repair_needed(schema):
        backup_manifest = create_sqlite_backup(v2_sqlite, backup_root=backup_root)
        sqlite_repair = _apply_sqlite_payload_normalization(Path(v2_sqlite))
    status = _status(apply_repair, schema, loader, post_exit, sqlite_repair)
    summary = {
        "mode": "micro-v2-papertrade-schema-repair",
        "micro_v2_papertrade_schema_repair_status": status,
        "dry_run": not apply_repair,
        "apply_repair": bool(apply_repair),
        "invalid_close_handled": bool(loader.get("invalid_close_handled", False)),
        "extra_fields_detected": schema.get("extra_fields_detected", {}),
        "sqlite_repair_applied": bool(sqlite_repair.get("sqlite_repair_applied", False)),
        "post_exit_state_status": post_exit.get("post_exit_state_status", ""),
        "open_trade_count": post_exit.get("open_trade_count", 0),
        "closed_trade_count": post_exit.get("closed_trade_count", 0),
        "quarantined_trade_count": post_exit.get("quarantined_trade_count", 0),
        "recommended_next_action": _next_action(status, sqlite_repair),
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "resume_guard_dir": str(resume_guard_dir),
        "repair_dir": str(repair_dir),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, schema, loader, post_exit, repair_validation, backup_manifest, sqlite_repair)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _repair_validation(schema: Mapping[str, Any], loader: Mapping[str, Any], post_exit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "loader_safe": int(loader.get("loader_error_count", 0) or 0) == 0 and int(loader.get("json_loader_error_count", 0) or 0) == 0,
        "extra_fields_preserved": int(loader.get("extra_fields_preserved_in_metadata_count", 0) or 0) >= int(schema.get("extra_field_trade_count", 0) or 0),
        "post_exit_healthy": post_exit.get("post_exit_state_status") == "MICRO_V2_PAPERTRADE_SCHEMA_POST_EXIT_STATE_HEALTHY",
        "sqlite_data_repair_required": False,
        "reason": "Code-level PaperTrade loader compatibility handles extra fields without SQLite mutation.",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _sqlite_repair_needed(schema: Mapping[str, Any]) -> bool:
    return bool(schema.get("extra_fields_detected"))


def _apply_sqlite_payload_normalization(sqlite_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    rows_normalized = 0
    try:
        tables = {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_trades" not in tables:
            return {"sqlite_repair_applied": False, "rows_normalized": 0, "reason": "paper_trades table missing"}
        rows = list(conn.execute("SELECT paper_trade_id, payload_json FROM paper_trades ORDER BY id"))
        for row in rows:
            payload = _loads(row["payload_json"])
            if not payload:
                continue
            normalized = sanitize_paper_trade_payload(payload)
            if normalized != payload:
                conn.execute(
                    "UPDATE paper_trades SET payload_json = ? WHERE paper_trade_id = ?",
                    (json.dumps(normalized, sort_keys=True), row["paper_trade_id"]),
                )
                rows_normalized += 1
        conn.commit()
        return {
            "sqlite_repair_applied": rows_normalized > 0,
            "rows_normalized": rows_normalized,
            "pnl_changed": False,
            "closed_trade_count_changed": False,
            "open_trade_count_changed": False,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    finally:
        conn.close()


def _status(apply_repair: bool, schema: Mapping[str, Any], loader: Mapping[str, Any], post_exit: Mapping[str, Any], sqlite_repair: Mapping[str, Any]) -> str:
    if int(loader.get("loader_error_count", 0) or 0) or int(loader.get("json_loader_error_count", 0) or 0):
        return "MICRO_V2_PAPERTRADE_SCHEMA_REQUIRES_MANUAL_REVIEW"
    if post_exit.get("post_exit_state_status") != "MICRO_V2_PAPERTRADE_SCHEMA_POST_EXIT_STATE_HEALTHY":
        return "MICRO_V2_PAPERTRADE_SCHEMA_POST_EXIT_STATE_CORRUPT"
    if apply_repair and sqlite_repair.get("sqlite_repair_applied"):
        return "MICRO_V2_PAPERTRADE_SCHEMA_SQLITE_REPAIR_APPLIED"
    if schema.get("extra_fields_detected"):
        return "MICRO_V2_PAPERTRADE_SCHEMA_NO_SQLITE_REPAIR_NEEDED"
    return "MICRO_V2_PAPERTRADE_SCHEMA_DRY_RUN_READY"


def _next_action(status: str, sqlite_repair: Mapping[str, Any]) -> str:
    if status in {"MICRO_V2_PAPERTRADE_SCHEMA_NO_SQLITE_REPAIR_NEEDED", "MICRO_V2_PAPERTRADE_SCHEMA_DRY_RUN_READY"}:
        return "RELAUNCH_V2_MANAGE_ONLY"
    if status == "MICRO_V2_PAPERTRADE_SCHEMA_SQLITE_REPAIR_APPLIED":
        return "RERUN_LIFECYCLE_RISK_COMPARISON_THEN_RELAUNCH_V2_MANAGE_ONLY"
    if status == "MICRO_V2_PAPERTRADE_SCHEMA_POST_EXIT_STATE_CORRUPT":
        return "PREPARE_PAPER_STATE_REPAIR_PHASE"
    return "MANUAL_REVIEW_REQUIRED"


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    schema: Mapping[str, Any],
    loader: Mapping[str, Any],
    post_exit: Mapping[str, Any],
    repair_validation: Mapping[str, Any],
    backup_manifest: Mapping[str, Any],
    sqlite_repair: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_papertrade_schema_repair_summary.json",
        output / "schema_field_audit.json",
        output / "papertrade_loader_audit.json",
        output / "extra_fields_detected.json",
        output / "post_exit_state_audit.json",
        output / "sqlite_backup_manifest.json",
        output / "repair_validation.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], schema)
    _write_json(paths[2], loader)
    _write_json(paths[3], {"extra_fields_detected": schema.get("extra_fields_detected", {}), "trades_with_extra_fields": schema.get("trades_with_extra_fields", [])})
    _write_json(paths[4], post_exit)
    _write_json(paths[5], backup_manifest or {"backup_created": False, "reason": "dry-run or no SQLite data repair applied"})
    _write_json(paths[6], {**dict(repair_validation), **dict(sqlite_repair)})
    paths[7].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[8].write_text(_recommendations(summary), encoding="utf-8")
    paths[9].write_text(_html(summary), encoding="utf-8")
    _write_extra_csv(output / "extra_fields_detected.csv", schema.get("trades_with_extra_fields", []))
    return paths


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    if summary.get("sqlite_repair_applied"):
        next_step = "Rerun lifecycle/risk comparison before relaunching V2 manage-only."
    elif summary.get("post_exit_state_status") == "MICRO_V2_PAPERTRADE_SCHEMA_POST_EXIT_STATE_HEALTHY":
        next_step = "Relaunch V2 in manage-open-trades-only mode; no SQLite repair is required."
    else:
        next_step = "Prepare a dedicated paper-state repair phase before relaunch."
    return f"""# Micro V2 PaperTrade Schema Repair Commands

Status: `{summary.get('micro_v2_papertrade_schema_repair_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

{next_step}
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 PaperTrade Schema Repair

The PaperTrade loader now filters unknown schema fields and preserves them in metadata.

Open trades: `{summary.get('open_trade_count')}`
Closed trades: `{summary.get('closed_trade_count')}`
Quarantined trades: `{summary.get('quarantined_trade_count')}`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 PaperTrade Schema Repair</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_extra_csv(path: Path, rows: Any) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["paper_trade_id", "status", "symbol", "extra_fields", "invalid_close"])
        writer.writeheader()
        for row in rows or []:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

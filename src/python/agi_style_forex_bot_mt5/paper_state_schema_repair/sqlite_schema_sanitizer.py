"""SQLite scanner and sanitizer for paper trade schema compatibility."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema_adapter import incompatible_fields, legacy_fields, normalize_paper_trade_payload, unknown_field_quarantine_metadata


def scan_and_repair_sqlite(sqlite_path: str | Path, *, backup_dir: str | Path = "data/backups/paper_state_schema_repair") -> dict[str, Any]:
    path = Path(sqlite_path)
    if not path.exists():
        return _empty_result("SQLITE_MISSING")
    backup = _backup(path, Path(backup_dir))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    incompatible: list[dict[str, Any]] = []
    repaired: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    try:
        tables = {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_trades" not in tables:
            return {**_empty_result("PAPER_TRADES_TABLE_MISSING"), "backup": backup}
        rows = list(conn.execute("SELECT id, paper_trade_id, status, symbol, payload_json FROM paper_trades ORDER BY id"))
        for row in rows:
            payload = _loads(row["payload_json"])
            row_id = int(row["id"])
            trade_id = str(row["paper_trade_id"] or payload.get("paper_trade_id") or row_id)
            status = str(row["status"] or payload.get("status") or "")
            symbol = str(row["symbol"] or payload.get("symbol") or "")
            if not payload:
                quarantine.append(_record(row_id, trade_id, status, symbol, "INVALID_JSON_OR_EMPTY_PAYLOAD", [], []))
                continue
            extras = incompatible_fields(payload)
            legacy = legacy_fields(payload)
            if extras:
                incompatible.append(_record(row_id, trade_id, status, symbol, "INCOMPATIBLE_EXTRA_FIELDS", sorted(extras), sorted(legacy)))
                normalized = normalize_paper_trade_payload(payload)
                if normalized != payload:
                    conn.execute("UPDATE paper_trades SET payload_json = ? WHERE id = ?", (json.dumps(normalized, sort_keys=True), row_id))
                    repaired.append(_record(row_id, trade_id, status, symbol, "NORMALIZED_EXTRA_FIELDS_TO_METADATA", sorted(extras), sorted(legacy)))
                    _insert_quarantine_event(conn, trade_id, unknown_field_quarantine_metadata(payload))
            elif _active_corrupt(payload, status):
                quarantine.append(_record(row_id, trade_id, status, symbol, "ACTIVE_CORRUPT_OPEN_TRADE", [], []))
        conn.commit()
        open_count = _open_count(conn)
        active_corrupt_count = sum(1 for row in quarantine if str(row.get("status", "")).upper() == "OPEN" or row.get("reason") == "ACTIVE_CORRUPT_OPEN_TRADE")
        mt5_connected = _mt5_connected(conn)
        state_before = _runtime_state(conn)
        config_resolution = _resolve_config_error(conn, open_count=open_count, active_corrupt_count=active_corrupt_count, mt5_connected=mt5_connected)
        state_after = _runtime_state(conn)
        return {
            "schema_scan_status": "PAPER_STATE_SCHEMA_SCAN_COMPLETE",
            "incompatible_records": incompatible,
            "repaired_records": repaired,
            "quarantine_records": quarantine,
            "incompatible_record_count": len(incompatible),
            "repaired_record_count": len(repaired),
            "quarantine_record_count": len(quarantine),
            "active_corrupt_record_count": active_corrupt_count,
            "open_trade_count": open_count,
            "mt5_connected": mt5_connected,
            "backup": backup,
            "state_before": state_before,
            "state_after": state_after,
            "config_error_resolution": config_resolution,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    finally:
        conn.close()


def _resolve_config_error(conn: sqlite3.Connection, *, open_count: int, active_corrupt_count: int, mt5_connected: bool) -> dict[str, Any]:
    state = _runtime_state(conn)
    detected = state.get("latest_exit_reason") == "CONFIG_ERROR" or state.get("halt_reason") == "PAPER_STATE_ERROR"
    can_clear = detected and open_count == 0 and active_corrupt_count == 0 and mt5_connected
    if can_clear:
        now = datetime.now(timezone.utc).isoformat()
        state.update(
            {
                "latest_exit_reason": "",
                "halt_reason": "PAPER_STATE_READY_FOR_NEXT_RESET",
                "latest_forward_shadow_error": "",
                "paper_state_schema_compatible": True,
                "config_error_resolved": True,
                "paper_state_schema_repair_status": "PAPER_STATE_READY_FOR_NEXT_RESET",
                "paper_state_schema_repaired_at_utc": now,
                "execution_attempted": False,
            }
        )
        conn.execute(
            """
            INSERT INTO operational_state (state_key, payload_json, updated_at_utc)
            VALUES ('runtime', ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET payload_json=excluded.payload_json, updated_at_utc=excluded.updated_at_utc
            """,
            (json.dumps(state, sort_keys=True), now),
        )
        conn.commit()
    return {
        "config_error_detected": bool(detected),
        "config_error_resolved": bool(can_clear),
        "paper_state_transition": "PAPER_STATE_ERROR_TO_PAPER_STATE_READY_FOR_NEXT_RESET" if can_clear else "",
        "resolution_status": "CONFIG_ERROR_CLEARED_TO_READY_FOR_NEXT_RESET" if can_clear else ("CONFIG_ERROR_NOT_ACTIVE" if not detected else "CONFIG_ERROR_STILL_BLOCKED"),
        "open_trade_count": open_count,
        "active_corrupt_record_count": active_corrupt_count,
        "mt5_connected": mt5_connected,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _backup(path: Path, backup_dir: Path) -> dict[str, Any]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{path.stem}.{stamp}{path.suffix}"
    shutil.copy2(path, target)
    return {"backup_created": True, "backup_path": str(target)}


def _insert_quarantine_event(conn: sqlite3.Connection, trade_id: str, payload: dict[str, Any]) -> None:
    try:
        conn.execute(
            "INSERT INTO paper_trade_events (paper_trade_id, event_type, timestamp_utc, payload_json) VALUES (?, ?, ?, ?)",
            (trade_id, "PAPER_STATE_SCHEMA_UNKNOWN_FIELDS_QUARANTINED", datetime.now(timezone.utc).isoformat(), json.dumps(payload, sort_keys=True)),
        )
    except sqlite3.Error:
        return


def _open_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT count(*) AS count FROM paper_trades WHERE lower(coalesce(status,'')) in ('open','active')").fetchone()
        return int(row["count"] or 0)
    except sqlite3.Error:
        return 0


def _mt5_connected(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT mt5_connected, payload_json FROM heartbeats ORDER BY timestamp_utc DESC, id DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return False
    if not row:
        return False
    payload = _loads(row["payload_json"])
    return bool(row["mt5_connected"]) or bool(payload.get("mt5_connected", False))


def _runtime_state(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = conn.execute("SELECT payload_json FROM operational_state WHERE state_key='runtime'").fetchone()
    except sqlite3.Error:
        return {}
    if not row:
        return {}
    return _loads(row["payload_json"])


def _active_corrupt(payload: dict[str, Any], status: str) -> bool:
    if status.upper() != "OPEN":
        return False
    required = ("paper_trade_id", "symbol", "entry_price", "sl_price", "tp_price")
    return any(payload.get(key) in {None, ""} for key in required)


def _record(row_id: int, trade_id: str, status: str, symbol: str, reason: str, fields: list[str], legacy: list[str]) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "paper_trade_id": trade_id,
        "status": status,
        "symbol": symbol,
        "reason": reason,
        "fields": ",".join(fields),
        "legacy_fields": ",".join(legacy),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(str(value or ""))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _empty_result(status: str) -> dict[str, Any]:
    return {
        "schema_scan_status": status,
        "incompatible_records": [],
        "repaired_records": [],
        "quarantine_records": [],
        "incompatible_record_count": 0,
        "repaired_record_count": 0,
        "quarantine_record_count": 0,
        "active_corrupt_record_count": 0,
        "open_trade_count": 0,
        "mt5_connected": False,
        "config_error_resolution": {"config_error_resolved": False, "resolution_status": status},
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

"""Apply paper-only quarantine to invalid V2 paper trades."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .before_after_snapshot import QUARANTINE_STATUS


OPEN_STATUSES = {"OPEN", "ACTIVE"}


def quarantine_invalid_paper_trade(sqlite_path: str | Path, *, trade_id: str, expected_symbol: str, root_cause: str) -> dict[str, Any]:
    path = Path(sqlite_path)
    if not path.exists():
        return _blocked("MICRO_V2_REPAIR_BLOCKED_TRADE_NOT_FOUND", "SQLITE_MISSING", trade_id)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        if "paper_trades" not in tables:
            return _blocked("MICRO_V2_REPAIR_BLOCKED_TRADE_NOT_FOUND", "PAPER_TRADES_TABLE_MISSING", trade_id)
        row = conn.execute("SELECT * FROM paper_trades WHERE paper_trade_id = ?", (trade_id,)).fetchone()
        if row is None:
            return _blocked("MICRO_V2_REPAIR_BLOCKED_TRADE_NOT_FOUND", "TRADE_NOT_FOUND", trade_id)
        trade = dict(row)
        status = str(trade.get("status", "")).upper()
        if status not in OPEN_STATUSES:
            return _blocked("MICRO_V2_REPAIR_BLOCKED_TRADE_ALREADY_CLOSED", f"STATUS_{status}", trade_id)
        if str(trade.get("symbol", "")).upper() != expected_symbol.upper():
            return _blocked("MICRO_V2_REPAIR_BLOCKED_PLAN_MISMATCH", "SYMBOL_MISMATCH", trade_id)
        payload = _loads(trade.get("payload_json"))
        if root_cause != "SL_EQUALS_ENTRY" or not _sl_equals_entry(payload):
            return _blocked("MICRO_V2_REPAIR_BLOCKED_PLAN_MISMATCH", "ROOT_CAUSE_OR_SL_ENTRY_MISMATCH", trade_id)
        if any(key in payload for key in ("close_price", "realized_pnl", "close_reason")) or trade.get("closed_at_utc"):
            return _blocked("MICRO_V2_REPAIR_BLOCKED_TRADE_ALREADY_CLOSED", "CLOSE_FIELDS_PRESENT", trade_id)
        now = datetime.now(timezone.utc).isoformat()
        payload["status"] = QUARANTINE_STATUS
        payload["invalid_close"] = False
        payload["quarantine"] = {
            "quarantined": True,
            "quarantine_reason": root_cause,
            "quarantined_by": "micro-v2-guarded-paper-state-repair",
            "timestamp_utc": now,
            "paper_only": True,
            "pnl_created": False,
            "closed_trade_created": False,
        }
        columns = _columns(conn, "paper_trades")
        if "updated_at_utc" in columns:
            conn.execute("UPDATE paper_trades SET status = ?, payload_json = ?, updated_at_utc = ? WHERE paper_trade_id = ?", (QUARANTINE_STATUS, json.dumps(payload, sort_keys=True), now, trade_id))
        else:
            conn.execute("UPDATE paper_trades SET status = ?, payload_json = ? WHERE paper_trade_id = ?", (QUARANTINE_STATUS, json.dumps(payload, sort_keys=True), trade_id))
        event = _event_payload(trade_id, expected_symbol, root_cause, now)
        if "paper_trade_events" in tables:
            conn.execute(
                "INSERT INTO paper_trade_events (paper_trade_id, event_type, timestamp_utc, payload_json) VALUES (?, ?, ?, ?)",
                (trade_id, "PAPER_TRADE_QUARANTINED_INVALID", now, json.dumps(event, sort_keys=True)),
            )
        conn.commit()
        return {
            "quarantine_applied": True,
            "quarantined_trade_ids": [trade_id],
            "quarantined_trade_count": 1,
            "quarantine_event": event,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    finally:
        conn.close()


def _event_payload(trade_id: str, symbol: str, root_cause: str, timestamp: str) -> dict[str, Any]:
    return {
        "event_type": "PAPER_TRADE_QUARANTINED_INVALID",
        "paper_trade_id": trade_id,
        "symbol": symbol,
        "root_cause": root_cause,
        "timestamp_utc": timestamp,
        "paper_only": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "event_id": f"ptrq_{uuid.uuid4().hex}",
    }


def _blocked(status: str, reason: str, trade_id: str) -> dict[str, Any]:
    return {
        "quarantine_applied": False,
        "blocked_status": status,
        "blocked_reason": reason,
        "quarantined_trade_ids": [],
        "quarantined_trade_count": 0,
        "target_trade_id": trade_id,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _sl_equals_entry(payload: dict[str, Any]) -> bool:
    entry = _float(payload.get("entry_price") or payload.get("open_price") or payload.get("price"))
    sl = _float(payload.get("sl_price") or payload.get("stop_loss") or payload.get("sl"))
    return entry is not None and sl is not None and abs(entry - sl) <= 1e-12


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


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

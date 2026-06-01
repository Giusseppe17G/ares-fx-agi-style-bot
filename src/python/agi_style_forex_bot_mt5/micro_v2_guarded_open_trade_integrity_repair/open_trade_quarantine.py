"""Apply paper-only quarantine to invalid open V2 paper trades."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .before_after_snapshot import QUARANTINE_STATUS


def quarantine_invalid_open_trades(sqlite_path: str | Path, target_trades: list[dict[str, Any]]) -> dict[str, Any]:
    path = Path(sqlite_path)
    if not path.exists():
        return _blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_NOT_FOUND", "SQLITE_MISSING")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    quarantined: list[str] = []
    events: list[dict[str, Any]] = []
    try:
        tables = {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_trades" not in tables:
            return _blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_NOT_FOUND", "PAPER_TRADES_TABLE_MISSING")
        now = datetime.now(timezone.utc).isoformat()
        for target in target_trades:
            trade_id = str(target.get("paper_trade_id") or "")
            row = conn.execute("SELECT * FROM paper_trades WHERE paper_trade_id = ?", (trade_id,)).fetchone()
            if row is None:
                return _blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_NOT_FOUND", f"{trade_id}:NOT_FOUND")
            payload = _loads(row["payload_json"])
            payload["status"] = QUARANTINE_STATUS
            payload["invalid_close"] = False
            payload["quarantine"] = {
                "quarantined": True,
                "quarantine_reason": "ZERO_RISK_DISTANCE_ENTRY_EQUALS_SL",
                "quarantined_by": "micro-v2-guarded-open-trade-integrity-repair",
                "timestamp_utc": now,
                "paper_only": True,
                "pnl_created": False,
                "closed_trade_created": False,
                "normal_close_created": False,
            }
            payload["metadata"] = {**(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), "open_trade_integrity_repair": payload["quarantine"]}
            conn.execute(
                "UPDATE paper_trades SET status = ?, payload_json = ?, updated_at_utc = ? WHERE paper_trade_id = ?",
                (QUARANTINE_STATUS, json.dumps(payload, sort_keys=True), now, trade_id),
            )
            event = _event_payload(trade_id, str(target.get("symbol") or ""), now)
            events.append(event)
            quarantined.append(trade_id)
            if "paper_trade_events" in tables:
                conn.execute(
                    "INSERT INTO paper_trade_events (paper_trade_id, event_type, timestamp_utc, payload_json) VALUES (?, ?, ?, ?)",
                    (trade_id, "PAPER_TRADE_QUARANTINED_OPEN_INTEGRITY", now, json.dumps(event, sort_keys=True)),
                )
        conn.commit()
        return {
            "quarantine_applied": True,
            "quarantined_trade_ids": quarantined,
            "quarantined_trade_count": len(quarantined),
            "quarantine_events": events,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    finally:
        conn.close()


def _event_payload(trade_id: str, symbol: str, timestamp: str) -> dict[str, Any]:
    return {
        "event_id": f"ptrq_{uuid.uuid4().hex}",
        "event_type": "PAPER_TRADE_QUARANTINED_OPEN_INTEGRITY",
        "paper_trade_id": trade_id,
        "symbol": symbol,
        "root_cause": "ZERO_RISK_DISTANCE_ENTRY_EQUALS_SL",
        "timestamp_utc": timestamp,
        "paper_only": True,
        "closed_trade_created": False,
        "pnl_created": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _blocked(status: str, reason: str) -> dict[str, Any]:
    return {
        "quarantine_applied": False,
        "blocked_status": status,
        "blocked_reason": reason,
        "quarantined_trade_ids": [],
        "quarantined_trade_count": 0,
        "quarantine_events": [],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


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

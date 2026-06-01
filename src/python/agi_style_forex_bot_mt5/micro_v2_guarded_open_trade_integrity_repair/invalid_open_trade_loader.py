"""SQLite loader and preflight validation for invalid open V2 trades."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping


OPEN_STATUSES = {"OPEN", "ACTIVE"}
QUARANTINE_STATUS = "QUARANTINED_INVALID_PAPER_TRADE"


def load_invalid_open_trades(sqlite_path: str | Path, trade_ids: list[str]) -> dict[str, Any]:
    path = Path(sqlite_path)
    if not path.exists():
        return _blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_NOT_FOUND", "SQLITE_MISSING")
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_trades" not in tables:
            return _blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_NOT_FOUND", "PAPER_TRADES_TABLE_MISSING")
        rows = [dict(row) for row in conn.execute("SELECT * FROM paper_trades WHERE paper_trade_id IN (%s)" % ",".join("?" for _ in trade_ids), trade_ids)] if trade_ids else []
        found_ids = {str(row.get("paper_trade_id") or "") for row in rows}
        if found_ids != set(trade_ids):
            return {**_blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_NOT_FOUND", "TARGET_TRADE_NOT_FOUND"), "found_trade_ids": sorted(found_ids)}
        audited = [_audit_row(row) for row in rows]
        for item in audited:
            if item["status"] == "CLOSED":
                return {**_blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_ALREADY_CLOSED", "TARGET_ALREADY_CLOSED"), "target_trades": audited}
            if item["status"] == QUARANTINE_STATUS:
                return {**_blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_PLAN_MISMATCH", "TARGET_ALREADY_QUARANTINED"), "target_trades": audited}
            if item["status"] not in OPEN_STATUSES:
                return {**_blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_PLAN_MISMATCH", "TARGET_NOT_OPEN"), "target_trades": audited}
            if item["symbol"] != "USDJPY" or item["issue"] != "ZERO_RISK_DISTANCE_ENTRY_EQUALS_SL":
                return {**_blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_PLAN_MISMATCH", "TARGET_ISSUE_OR_SYMBOL_MISMATCH"), "target_trades": audited}
            if item["has_close_fields"] or item["has_nonzero_pnl"]:
                return {**_blocked("MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_UNSAFE_ACTION", "TARGET_HAS_CLOSE_OR_PNL_FIELDS"), "target_trades": audited}
        return {
            "target_validation_status": "TARGET_TRADES_VALID",
            "target_validation_passed": True,
            "target_trades": audited,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    finally:
        conn.close()


def _audit_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = _loads(row.get("payload_json"))
    entry = _float(payload.get("entry_price") or payload.get("open_price") or payload.get("price"))
    sl = _float(payload.get("sl_price") or payload.get("stop_loss") or payload.get("sl"))
    tp = _float(payload.get("tp_price") or payload.get("take_profit") or payload.get("tp"))
    issue = "ZERO_RISK_DISTANCE_ENTRY_EQUALS_SL" if entry is not None and sl is not None and abs(entry - sl) <= 1e-12 else "UNKNOWN"
    return {
        "paper_trade_id": str(row.get("paper_trade_id") or payload.get("paper_trade_id") or ""),
        "symbol": str(row.get("symbol") or payload.get("symbol") or "").upper(),
        "status": str(row.get("status") or payload.get("status") or "").upper(),
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": tp,
        "issue": issue,
        "has_close_fields": bool(payload.get("exit_time_utc") or payload.get("exit_price") not in (None, "")),
        "has_nonzero_pnl": any(abs(_float(payload.get(key)) or 0.0) > 1e-12 for key in ("profit", "raw_pnl", "scaled_paper_pnl", "realized_pnl")),
    }


def _blocked(status: str, reason: str) -> dict[str, Any]:
    return {
        "target_validation_status": status,
        "target_validation_passed": False,
        "blocked_status": status,
        "blocked_reason": reason,
        "target_trades": [],
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


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

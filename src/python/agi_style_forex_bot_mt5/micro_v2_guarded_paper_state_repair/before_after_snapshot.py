"""Before/after snapshots for guarded paper-state repair."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


OPEN_STATUSES = {"OPEN", "ACTIVE"}
QUARANTINE_STATUS = "QUARANTINED_INVALID_PAPER_TRADE"


def snapshot_sqlite(sqlite_path: str | Path, trade_ids: list[str]) -> dict[str, Any]:
    path = Path(sqlite_path)
    if not path.exists():
        return {"sqlite_exists": False, "snapshot_error": "SQLITE_MISSING", "execution_attempted": False, "order_send_called": False, "order_check_called": False}
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        trades = [dict(row) for row in conn.execute("SELECT * FROM paper_trades")] if "paper_trades" in tables else []
        target_trades = [trade for trade in trades if str(trade.get("paper_trade_id")) in set(trade_ids)]
        closed = [trade for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"]
        open_valid = [trade for trade in trades if str(trade.get("status", "")).upper() in OPEN_STATUSES]
        quarantined = [trade for trade in trades if str(trade.get("status", "")).upper() == QUARANTINE_STATUS]
        realized_pnl_total = sum(_payload_float(trade, ("realized_pnl", "scaled_paper_pnl", "profit")) for trade in closed)
        invalid_open = [trade for trade in open_valid if _is_invalid(trade)]
        return {
            "sqlite_exists": True,
            "trade_ids": trade_ids,
            "target_trades": [_redact_trade(trade) for trade in target_trades],
            "open_trade_count": len(open_valid),
            "closed_trade_count": len(closed),
            "quarantined_trade_count": len(quarantined),
            "invalid_open_trade_count": len(invalid_open),
            "realized_pnl_total": round(realized_pnl_total, 6),
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    finally:
        conn.close()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _is_invalid(trade: dict[str, Any]) -> bool:
    payload = _loads(trade.get("payload_json"))
    entry = _float(payload.get("entry_price") or payload.get("open_price") or payload.get("price"))
    sl = _float(payload.get("sl_price") or payload.get("stop_loss") or payload.get("sl"))
    tp = _float(payload.get("tp_price") or payload.get("take_profit") or payload.get("tp"))
    return entry is None or sl is None or tp is None or abs(entry - sl) <= 1e-12 or abs(tp - entry) <= 1e-12


def _redact_trade(trade: dict[str, Any]) -> dict[str, Any]:
    payload = _loads(trade.get("payload_json"))
    return {
        "paper_trade_id": trade.get("paper_trade_id", ""),
        "symbol": trade.get("symbol", ""),
        "status": trade.get("status", ""),
        "opened_at_utc": trade.get("opened_at_utc", ""),
        "closed_at_utc": trade.get("closed_at_utc", ""),
        "updated_at_utc": trade.get("updated_at_utc", ""),
        "entry_price": payload.get("entry_price"),
        "sl_price": payload.get("sl_price") or payload.get("stop_loss"),
        "tp_price": payload.get("tp_price") or payload.get("take_profit"),
        "quarantine": payload.get("quarantine", {}),
        "realized_pnl": payload.get("realized_pnl"),
    }


def _payload_float(trade: dict[str, Any], keys: tuple[str, ...]) -> float:
    payload = _loads(trade.get("payload_json"))
    for key in keys:
        if key in payload:
            return _float(payload.get(key)) or 0.0
    return 0.0


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

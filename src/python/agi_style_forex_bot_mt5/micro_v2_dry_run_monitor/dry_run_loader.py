"""Read-only SQLite and JSONL loaders for Micro V2 dry-run monitoring."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any


MAX_SQLITE_ROWS = 5000
MAX_JSONL_LINES_PER_FILE = 2000


def load_dry_run_dataset(*, sqlite_path: str | Path, log_dir: str | Path, label: str) -> dict[str, Any]:
    """Load dry-run telemetry without creating or migrating SQLite files."""

    sqlite_path = Path(sqlite_path)
    log_dir = Path(log_dir)
    sqlite_payload = _load_sqlite(sqlite_path)
    log_events = _load_jsonl_events(log_dir)
    return {
        "label": label,
        "sqlite_path": str(sqlite_path),
        "log_dir": str(log_dir),
        "sqlite_exists": sqlite_path.exists(),
        "log_dir_exists": log_dir.exists(),
        "events": [*_normalize_events(sqlite_payload.get("events", []), "sqlite:events"), *log_events],
        "heartbeats": _normalize_heartbeats(sqlite_payload.get("heartbeats", [])),
        "paper_trades": _normalize_paper_trades(sqlite_payload.get("paper_trades", [])),
        "alerts": _normalize_generic(sqlite_payload.get("alerts", []), "sqlite:alerts"),
        "operational_state": _normalize_generic(sqlite_payload.get("operational_state", []), "sqlite:operational_state"),
        "sqlite_read_error": sqlite_payload.get("sqlite_read_error", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _load_sqlite(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sqlite_read_error": "SQLITE_MISSING"}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return {"sqlite_read_error": f"SQLITE_READ_OPEN_FAILED: {exc}"}
    try:
        tables = _tables(conn)
        return {
            "events": _rows(conn, "events") if "events" in tables else [],
            "heartbeats": _rows(conn, "heartbeats") if "heartbeats" in tables else [],
            "paper_trades": _rows(conn, "paper_trades") if "paper_trades" in tables else [],
            "alerts": _rows(conn, "alerts") if "alerts" in tables else [],
            "operational_state": _rows(conn, "operational_state") if "operational_state" in tables else [],
            "sqlite_read_error": "",
        }
    except sqlite3.Error as exc:
        return {"sqlite_read_error": f"SQLITE_READ_FAILED: {exc}"}
    finally:
        conn.close()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns = [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")]
    order = "id" if "id" in columns else "rowid"
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", (MAX_SQLITE_ROWS,))]
    return list(reversed(rows))


def _normalize_events(rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        payload = _loads(row.get("payload_json"))
        normalized.append(
            {
                "source": source,
                "event_type": row.get("event_type") or payload.get("event_type") or payload.get("type") or "",
                "symbol": row.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "",
                "timestamp_utc": row.get("timestamp_utc") or payload.get("timestamp_utc") or payload.get("created_at_utc") or "",
                "severity": row.get("severity") or payload.get("severity") or "",
                "message": row.get("message") or payload.get("message") or "",
                "payload": payload,
                "execution_attempted": _bool(row.get("execution_attempted")) or _bool(payload.get("execution_attempted")),
                "order_send_called": _bool(row.get("order_send_called")) or _bool(payload.get("order_send_called")),
                "order_check_called": _bool(row.get("order_check_called")) or _bool(payload.get("order_check_called")),
            }
        )
    return normalized


def _normalize_heartbeats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        payload = _loads(row.get("payload_json"))
        normalized.append(
            {
                "source": "sqlite:heartbeats",
                "event_type": "HEARTBEAT",
                "timestamp_utc": row.get("timestamp_utc") or payload.get("timestamp_utc") or "",
                "mode": row.get("mode") or payload.get("mode") or "",
                "mt5_connected": _bool(row.get("mt5_connected")) or _bool(payload.get("mt5_connected")),
                "payload": payload,
                "execution_attempted": _bool(row.get("execution_attempted")) or _bool(payload.get("execution_attempted")),
                "order_send_called": _bool(payload.get("order_send_called")),
                "order_check_called": _bool(payload.get("order_check_called")),
            }
        )
    return normalized


def _normalize_paper_trades(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for row in rows:
        payload = _loads(row.get("payload_json"))
        trades.append(
            {
                **payload,
                "source": "sqlite:paper_trades",
                "paper_trade_id": payload.get("paper_trade_id") or row.get("paper_trade_id") or "",
                "symbol": payload.get("symbol") or row.get("symbol") or "",
                "status": payload.get("status") or row.get("status") or "",
                "opened_at_utc": payload.get("opened_at_utc") or payload.get("entry_time_utc") or row.get("opened_at_utc") or "",
                "closed_at_utc": payload.get("closed_at_utc") or payload.get("exit_time_utc") or row.get("closed_at_utc") or "",
                "execution_attempted": _bool(payload.get("execution_attempted")),
                "order_send_called": _bool(payload.get("order_send_called")),
                "order_check_called": _bool(payload.get("order_check_called")),
            }
        )
    return trades


def _normalize_generic(rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return [{**row, "source": source, "payload": _loads(row.get("payload_json"))} for row in rows]


def _load_jsonl_events(log_dir: Path) -> list[dict[str, Any]]:
    if not log_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                lines = deque(handle, maxlen=MAX_JSONL_LINES_PER_FILE)
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            payload = _loads(line)
            if not payload:
                continue
            nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            events.append(
                {
                    "source": f"jsonl:{path.name}:{line_no}",
                    "event_type": payload.get("event_type") or nested.get("event_type") or payload.get("type") or "",
                    "symbol": payload.get("symbol") or nested.get("symbol") or "",
                    "timestamp_utc": payload.get("timestamp_utc") or nested.get("timestamp_utc") or "",
                    "severity": payload.get("severity") or nested.get("severity") or "",
                    "message": payload.get("message") or nested.get("message") or "",
                    "payload": payload,
                    "execution_attempted": _bool(payload.get("execution_attempted")) or _bool(nested.get("execution_attempted")),
                    "order_send_called": _bool(payload.get("order_send_called")) or _bool(nested.get("order_send_called")),
                    "order_check_called": _bool(payload.get("order_check_called")) or _bool(nested.get("order_check_called")),
                }
            )
    return events


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


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False

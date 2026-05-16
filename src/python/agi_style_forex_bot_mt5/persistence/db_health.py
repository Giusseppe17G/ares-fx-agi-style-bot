"""SQLite health checks that do not mutate the database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry.logger_setup import utc_now_iso

REQUIRED_TABLES = {
    "events",
    "schema_migrations",
    "paper_trades",
    "heartbeats",
    "alerts",
    "model_predictions",
    "broker_quality",
    "telegram_outbox",
    "operational_state",
}


def check_db_health(*, sqlite_path: str | Path, report_dir: str | Path = "data/reports/persistence") -> dict[str, Any]:
    """Return fail-closed health information for a SQLite telemetry database."""

    path = Path(sqlite_path)
    report_path = Path(report_dir) / "db_health.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        summary = _summary("CRITICAL", path, ["sqlite file does not exist"])
        return _write(report_path, summary)
    errors: list[str] = []
    details: dict[str, Any] = {}
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            details["integrity_check"] = integrity
            if str(integrity).lower() != "ok":
                errors.append("PRAGMA integrity_check failed")
            journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
            details["journal_mode"] = journal
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted(REQUIRED_TABLES - tables)
            details["missing_tables"] = missing
            errors.extend(f"missing table: {table}" for table in missing)
            details["event_count"] = _count(conn, "events", tables)
            details["critical_errors_recent"] = _critical_errors(conn, tables)
            details["last_heartbeat_utc"] = _last_heartbeat(conn, tables)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        errors.append(str(exc))
    summary = _summary("OK" if not errors else "CRITICAL", path, errors, details)
    return _write(report_path, summary)


def _summary(status: str, path: Path, errors: list[str], details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "mode": "db-health",
        "status": status,
        "sqlite_path": str(path),
        "db_size_bytes": path.stat().st_size if path.exists() else 0,
        "errors": errors,
        "details": details or {},
        "timestamp_utc": utc_now_iso(),
        "execution_attempted": False,
    }


def _write(path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return {**summary, "report_path": str(path)}


def _count(conn: sqlite3.Connection, table: str, tables: set[str]) -> int:
    if table not in tables:
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _critical_errors(conn: sqlite3.Connection, tables: set[str]) -> int:
    if "events" not in tables:
        return 0
    row = conn.execute("SELECT COUNT(*) FROM events WHERE severity IN ('ERROR','CRITICAL')").fetchone()
    return int(row[0])


def _last_heartbeat(conn: sqlite3.Connection, tables: set[str]) -> str | None:
    if "heartbeats" not in tables:
        return None
    row = conn.execute("SELECT timestamp_utc FROM heartbeats ORDER BY id DESC LIMIT 1").fetchone()
    return str(row["timestamp_utc"]) if row else None


"""SQLite migration helpers for durable telemetry databases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry.logger_setup import utc_now_iso

from .backup_manager import create_backup

CURRENT_SCHEMA_VERSION = 1


def run_db_migrations(*, sqlite_path: str | Path, backup_dir: str | Path = "data/backups") -> dict[str, Any]:
    """Apply idempotent migrations, backing up existing databases first."""

    path = Path(sqlite_path)
    backup_report: dict[str, Any] | None = None
    if path.exists() and path.stat().st_size > 0:
        backup_report = create_backup(sqlite_path=path, backup_dir=backup_dir, log_dir=None)
    with TelemetryDatabase(path) as database:
        database.migrate()
        applied = database._conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    return {
        "mode": "db-migrate",
        "status": "OK",
        "schema_version": CURRENT_SCHEMA_VERSION,
        "migrations_applied": int(applied),
        "backup": backup_report,
        "timestamp_utc": utc_now_iso(),
        "execution_attempted": False,
    }

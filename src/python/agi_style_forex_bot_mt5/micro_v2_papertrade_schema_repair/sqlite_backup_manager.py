"""Backup helpers for guarded V2 SQLite repair."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_sqlite_backup(sqlite_path: str | Path, *, backup_root: str | Path = "data/backups/micro_v2_papertrade_schema_repair") -> dict[str, Any]:
    source = Path(sqlite_path)
    root = Path(backup_root)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    copied: list[str] = []
    if source.exists():
        target = root / f"{source.stem}.{timestamp}{source.suffix}"
        shutil.copy2(source, target)
        copied.append(str(target))
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(source) + suffix)
        if sidecar.exists():
            target = root / f"{source.name}{suffix}.{timestamp}.bak"
            shutil.copy2(sidecar, target)
            copied.append(str(target))
    return {
        "backup_created": bool(copied),
        "source_sqlite": str(source),
        "backup_paths": copied,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

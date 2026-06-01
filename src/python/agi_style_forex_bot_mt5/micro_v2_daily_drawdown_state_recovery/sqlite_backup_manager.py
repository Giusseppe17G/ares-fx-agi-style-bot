"""Backup helpers for V2 drawdown state recovery."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_v2_backup(sqlite_path: str | Path, *, backup_root: str | Path = "data/backups/micro_v2_daily_drawdown_state_recovery") -> dict[str, Any]:
    source = Path(sqlite_path)
    root = Path(backup_root)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    paths: list[str] = []
    if source.exists():
        target = root / f"{source.stem}.{timestamp}{source.suffix}"
        shutil.copy2(source, target)
        paths.append(str(target))
    return {
        "backup_created": bool(paths),
        "backup_paths": paths,
        "source_sqlite": str(source),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

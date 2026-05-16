"""Local backup manager for SQLite and JSONL audit logs."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_backup(
    *,
    sqlite_path: str | Path | None,
    log_dir: str | Path | None = "data/logs",
    backup_dir: str | Path = "data/backups",
    keep_last: int = 10,
) -> dict[str, Any]:
    """Create local backups without copying secrets such as `.env` files."""

    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    created: list[str] = []
    if sqlite_path is not None:
        db_path = Path(sqlite_path)
        if db_path.exists():
            target = backup_root / f"{db_path.stem}-{stamp}{db_path.suffix}"
            shutil.copy2(db_path, target)
            created.append(str(target))
    if log_dir is not None:
        source = Path(log_dir)
        if source.exists():
            for path in sorted(source.rglob("*.jsonl"))[-5:]:
                target = backup_root / f"{path.stem}-{stamp}.jsonl"
                shutil.copy2(path, target)
                created.append(str(target))
    _rotate(backup_root, keep_last=keep_last)
    report = {
        "mode": "backup",
        "status": "OK",
        "backup_files": created,
        "report_path": str(backup_root / "backup_report.json"),
        "execution_attempted": False,
    }
    Path(report["report_path"]).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _rotate(backup_root: Path, *, keep_last: int) -> None:
    files = [path for path in backup_root.iterdir() if path.is_file() and path.name != "backup_report.json" and path.suffix != ".env"]
    for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)[keep_last:]:
        path.unlink(missing_ok=True)


"""Local backup manager for SQLite and JSONL audit logs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.core import Clock, WorkspacePaths, resolve_clock, seal_report, workspace_paths


def create_backup(
    *,
    sqlite_path: str | Path | None,
    log_dir: str | Path | None = "data/logs",
    backup_dir: str | Path = "data/backups",
    keep_last: int = 10,
    workspace: WorkspacePaths | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Create local backups without copying secrets such as `.env` files.

    `_rotate` deletes files, so the destination must never be resolved against
    the process CWD: a caller that keeps the default would otherwise rotate away
    whichever `data/backups` happens to sit next to the working directory.
    """

    paths = workspace or workspace_paths()
    backup_root = paths.resolve_path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = resolve_clock(clock).now_utc().strftime("%Y%m%dT%H%M%SZ")
    created: list[str] = []
    if sqlite_path is not None:
        db_path = Path(sqlite_path)
        if db_path.exists():
            target = backup_root / f"{db_path.stem}-{stamp}{db_path.suffix}"
            shutil.copy2(db_path, target)
            created.append(str(target))
    if log_dir is not None:
        source = paths.resolve_path(log_dir)
        if source.exists():
            for path in sorted(source.rglob("*.jsonl"))[-5:]:
                target = backup_root / f"{path.stem}-{stamp}.jsonl"
                shutil.copy2(path, target)
                created.append(str(target))
    _rotate(backup_root, keep_last=keep_last)
    report = seal_report(
        {
            "mode": "backup",
            "status": "OK",
            "backup_files": created,
            "report_path": str(backup_root / "backup_report.json"),
        }
    )
    Path(report["report_path"]).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _rotate(backup_root: Path, *, keep_last: int) -> None:
    files = [path for path in backup_root.iterdir() if path.is_file() and path.name != "backup_report.json" and path.suffix != ".env"]
    for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)[keep_last:]:
        path.unlink(missing_ok=True)


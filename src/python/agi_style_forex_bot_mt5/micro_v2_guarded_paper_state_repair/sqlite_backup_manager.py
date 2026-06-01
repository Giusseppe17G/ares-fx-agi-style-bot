"""SQLite backup and hashing for guarded V2 repair."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_sqlite_backup(sqlite_path: str | Path, *, backup_root: str | Path = "data/backups/micro_v2_guarded_paper_state_repair") -> dict[str, Any]:
    source = Path(sqlite_path)
    if not source.exists():
        return {"backup_created": False, "backup_error": "SQLITE_SOURCE_MISSING", "backup_path": ""}
    backup_dir = Path(backup_root)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = backup_dir / f"{source.stem}.{stamp}.sqlite3"
        before_hash = sha256_file(source)
        shutil.copy2(source, target)
        backup_hash = sha256_file(target)
        return {
            "backup_created": backup_hash == before_hash,
            "backup_path": str(target),
            "source_path": str(source),
            "before_sha256": before_hash,
            "backup_sha256": backup_hash,
            "backup_error": "" if backup_hash == before_hash else "BACKUP_HASH_MISMATCH",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    except Exception as exc:
        return {"backup_created": False, "backup_error": str(exc), "backup_path": "", "source_path": str(source)}

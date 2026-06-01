"""Backup helpers for Micro V2 daily risk ledger scope repair."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    source = Path(path)
    if not source.exists():
        return ""
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_ledger_backup(ledger_path: str | Path, *, backup_root: str | Path = "data/backups/micro_v2_daily_risk_scope_repair") -> dict[str, Any]:
    source = Path(ledger_path)
    if not source.exists():
        return _failed(source, "LEDGER_MISSING")
    root = Path(backup_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = root / f"{source.stem}.{timestamp}{source.suffix}"
        before_hash = sha256_file(source)
        shutil.copy2(source, target)
        return {
            "backup_created": True,
            "backup_path": str(target),
            "source_ledger": str(source),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "before_sha256": before_hash,
            "backup_sha256": sha256_file(target),
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    except OSError as exc:
        return _failed(source, str(exc))


def _failed(source: Path, reason: str) -> dict[str, Any]:
    return {
        "backup_created": False,
        "backup_path": "",
        "source_ledger": str(source),
        "backup_error": reason,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

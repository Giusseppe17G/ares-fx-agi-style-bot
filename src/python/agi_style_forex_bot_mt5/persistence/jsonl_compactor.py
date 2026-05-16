"""JSONL rotation and compaction helpers."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def compact_jsonl_logs(
    *,
    log_dir: str | Path,
    backup_dir: str | Path = "data/backups",
    max_file_mb: float = 50.0,
    retention_days: int = 30,
) -> dict[str, Any]:
    """Rotate oversized JSONL files after backing them up."""

    source = Path(log_dir)
    backup = Path(backup_dir)
    backup.mkdir(parents=True, exist_ok=True)
    rotated: list[str] = []
    index: list[dict[str, Any]] = []
    if source.exists():
        threshold = max_file_mb * 1024 * 1024
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for path in source.rglob("*.jsonl"):
            size = path.stat().st_size
            if size <= threshold:
                continue
            backup_path = backup / f"{path.stem}-{stamp}.jsonl"
            shutil.copy2(path, backup_path)
            rotated_path = path.with_suffix(path.suffix + f".{stamp}.rotated")
            path.replace(rotated_path)
            path.touch()
            rotated.append(str(rotated_path))
            index.append({"source": str(path), "backup": str(backup_path), "rotated": str(rotated_path), "size_bytes": size})
    report = {
        "mode": "compact-logs",
        "status": "OK",
        "rotated_files": rotated,
        "retention_days": retention_days,
        "index": index,
        "execution_attempted": False,
    }
    (backup / "jsonl_compaction_index.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


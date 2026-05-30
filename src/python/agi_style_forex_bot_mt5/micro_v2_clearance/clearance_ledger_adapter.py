"""Read-only helpers for base and V2 paper risk clearance ledgers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def audit_base_clearance(path: str | Path | None) -> dict[str, Any]:
    file_path = Path(path) if path else None
    exists = bool(file_path and file_path.exists())
    content = file_path.read_bytes() if exists and file_path else b""
    payload = load_json(file_path) if exists else {}
    entries = payload.get("clearances", []) if isinstance(payload.get("clearances"), list) else []
    latest = dict(entries[-1]) if entries else {}
    return {
        "base_clearance_ledger": str(file_path or ""),
        "base_clearance_exists": exists,
        "base_clearance_sha256": hashlib.sha256(content).hexdigest() if content else "",
        "base_clearance_entry_count": len(entries),
        "base_latest_cleared_for_profile": latest.get("cleared_for_profile", latest.get("canonical_cleared_for_profile", "")),
        "base_clearance_preserved": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

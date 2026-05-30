"""INI profile loading helpers for micro V2 review."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_profile(path: str | Path | None) -> dict[str, Any]:
    profile_path = Path(path) if path else None
    if not profile_path or not profile_path.exists():
        return {"path": str(profile_path or ""), "exists": False, "values": {}, "lines": []}
    lines = profile_path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    comments: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ";")):
            comments.append(stripped)
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return {
        "path": str(profile_path),
        "exists": True,
        "values": values,
        "lines": lines,
        "comments": comments,
    }


def bool_value(values: dict[str, str], key: str, default: bool = False) -> bool:
    value = values.get(key.upper())
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def float_value(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key.upper(), default))
    except Exception:
        return default


def int_value(values: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(values.get(key.upper(), default)))
    except Exception:
        return default

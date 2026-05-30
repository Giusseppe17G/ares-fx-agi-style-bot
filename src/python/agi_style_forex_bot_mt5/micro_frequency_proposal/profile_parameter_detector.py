"""Detect existing profile parameters that can be safely mapped."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_profile(path: str | Path | None) -> dict[str, Any]:
    profile_path = Path(path) if path else None
    if not profile_path or not profile_path.exists():
        return {"path": str(profile_path or ""), "exists": False, "values": {}, "lines": []}
    lines = profile_path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return {"path": str(profile_path), "exists": True, "values": values, "lines": lines}


def detect_parameter_map(values: dict[str, str]) -> dict[str, str]:
    keys = set(values)
    mapping: dict[str, str] = {}
    if "COOLDOWN_AFTER_LOSS_MINUTES" in keys:
        mapping["COOLDOWN_BLOCK"] = "COOLDOWN_AFTER_LOSS_MINUTES"
    if "MAX_PAPER_TRADES_PER_DAY" in keys:
        mapping["PAPER_TRADE_LIMIT"] = "MAX_PAPER_TRADES_PER_DAY"
    if "MAX_SIGNAL_AGE_SECONDS" in keys:
        mapping["STALE_SIGNAL_BLOCK"] = "MAX_SIGNAL_AGE_SECONDS"
    if "MAX_LIQUIDITY_THRESHOLD" in keys:
        mapping["LIQUIDITY_BLOCK"] = "MAX_LIQUIDITY_THRESHOLD"
    if "MIN_LIQUIDITY_SCORE" in keys:
        mapping["LIQUIDITY_BLOCK"] = "MIN_LIQUIDITY_SCORE"
    if "MIN_SETUP_SCORE_STABLE" in keys:
        mapping["SCORE_THRESHOLD_BLOCK"] = "MIN_SETUP_SCORE_STABLE"
    if "MIN_SETUP_SCORE" in keys:
        mapping["SCORE_THRESHOLD_BLOCK"] = "MIN_SETUP_SCORE"
    if "ALLOWED_SESSIONS" in keys:
        mapping["SESSION_BLOCK"] = "ALLOWED_SESSIONS"
    if "REGIME_OBSERVE_MODE" in keys:
        mapping["REGIME_BLOCK"] = "REGIME_OBSERVE_MODE"
    return mapping


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

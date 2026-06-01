"""Stop/reward distance validation."""

from __future__ import annotations

from typing import Any


def validate_stop_distances(*, entry_price: float, sl_price: float, tp_price: float, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    risk_distance = abs(entry_price - sl_price)
    reward_distance = abs(tp_price - entry_price)
    if risk_distance <= 1e-12:
        return "PAPER_TRADE_REJECTED_ZERO_RISK_DISTANCE"
    if reward_distance <= 1e-12:
        return "PAPER_TRADE_REJECTED_INVALID_REWARD_DISTANCE"
    for key in ("atr_stop_distance", "stop_distance", "stop_distance_price"):
        if key in metadata and _float(metadata.get(key)) is not None and (_float(metadata.get(key)) or 0.0) <= 1e-12:
            return "PAPER_TRADE_REJECTED_ZERO_ATR_STOP_DISTANCE"
    return ""


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None

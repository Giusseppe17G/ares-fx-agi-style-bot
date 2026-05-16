"""Execution readiness scoring without execution permission."""

from __future__ import annotations

from typing import Any, Mapping


def score_symbol_readiness(payload: Mapping[str, Any], *, max_spread_points: float = 25.0) -> tuple[float, str, tuple[str, ...]]:
    score = 100.0
    reasons: list[str] = []
    if not payload.get("symbol_visible", False):
        score -= 25
        reasons.append("symbol not visible")
    if not payload.get("trade_allowed", False):
        score -= 20
        reasons.append("trading not allowed by symbol/account metadata")
    spread = float(payload.get("spread_points") or 0.0)
    if spread > max_spread_points:
        score -= 50
        reasons.append("spread above configured max")
    elif spread > max_spread_points * 0.75:
        score -= 10
        reasons.append("spread near configured max")
    age = payload.get("tick_age_seconds")
    if age is None or abs(float(age)) > 5.0:
        score -= 25
        reasons.append("tick stale or unavailable")
    if not payload.get("rates_available_m5") or not payload.get("rates_available_m15") or not payload.get("rates_available_h1"):
        score -= 20
        reasons.append("rates unavailable")
    if int(payload.get("stops_level_points") or -1) < 0 or int(payload.get("freeze_level_points") or -1) < 0:
        score -= 15
        reasons.append("stops/freeze levels unavailable")
    if float(payload.get("volume_min") or 0.0) <= 0 or float(payload.get("volume_step") or 0.0) <= 0:
        score -= 20
        reasons.append("volume restrictions invalid")
    if int(payload.get("read_latency_ms_tick") or 0) > 500 or int(payload.get("read_latency_ms_rates") or 0) > 2000:
        score -= 10
        reasons.append("read latency high")
    score = max(0.0, min(100.0, score))
    return score, classify_readiness(score, reasons), tuple(reasons)


def classify_readiness(score: float, reasons: tuple[str, ...] | list[str] = ()) -> str:
    if score >= 80 and not reasons:
        return "EXECUTION_READY_SHADOW_ONLY"
    if score >= 55:
        return "WATCHLIST"
    return "NOT_READY"

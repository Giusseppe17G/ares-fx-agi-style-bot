"""Analyze forward-shadow rejection reasons."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pandas as pd

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


KNOWN_REJECTIONS = {
    "STABLE_SYMBOL_DISABLED",
    "STABLE_STRATEGY_DISABLED",
    "STABLE_SESSION_BLOCK",
    "STABLE_REGIME_BLOCK",
    "SPREAD_BLOCK",
    "COST_BLOCK",
    "NO_SETUP_DETECTED",
    "ENSEMBLE_SCORE_LOW",
    "MARKET_CLOSED_OR_NO_TICKS",
    "MT5_CONNECTION_FAILED",
    "STALE_TICK",
}


def analyze_rejections(*, database: TelemetryDatabase) -> tuple[dict[str, Any], pd.DataFrame]:
    counter: Counter[str] = Counter()
    for row in database.fetch_all("events"):
        event_type = str(row["event_type"])
        if event_type not in {"SIGNAL_REJECTED", "STRATEGY_BLOCKED_BY_CONTEXT", "RISK_REJECTED", "SYMBOL_REJECTED"}:
            continue
        payload = _payload(row)
        reason = str(payload.get("reject_reason") or payload.get("reject_code") or _first(payload.get("blocking_reasons")) or event_type)
        counter[_canonical(reason)] += 1
    rows = [{"reason": reason, "count": count, "recommendation": _recommend(reason)} for reason, count in counter.most_common()]
    frame = pd.DataFrame(rows, columns=["reason", "count", "recommendation"])
    return {
        "mode": "rejection-analysis",
        "top_rejections": rows,
        "total_rejections": int(sum(counter.values())),
        "execution_attempted": False,
    }, frame


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _first(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _canonical(reason: str) -> str:
    text = reason.upper()
    for known in KNOWN_REJECTIONS:
        if known in text:
            return known
    if "SPREAD" in text:
        return "SPREAD_BLOCK"
    if "NO TICK" in text or "STALE" in text:
        return "STALE_TICK"
    return text or "UNKNOWN_REJECTION"


def _recommend(reason: str) -> str:
    if reason in {"SPREAD_BLOCK", "COST_BLOCK"}:
        return "investigate spread; do not relax cost gates"
    if reason in {"STABLE_SYMBOL_DISABLED", "STABLE_STRATEGY_DISABLED", "STABLE_SESSION_BLOCK", "STABLE_REGIME_BLOCK"}:
        return "keep stable filters"
    if reason in {"MARKET_CLOSED_OR_NO_TICKS", "MT5_CONNECTION_FAILED", "STALE_TICK"}:
        return "inspect symbol availability and MT5 connectivity"
    if reason in {"ENSEMBLE_SCORE_LOW", "NO_SETUP_DETECTED"}:
        return "adjust only in research, not live/paper gate"
    return "no action"

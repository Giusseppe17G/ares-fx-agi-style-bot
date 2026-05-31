"""Rejection taxonomy breakdown for Micro V2 filter analysis."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.rejection_funnel import REJECTION_EVENTS


MARKET_FILTERS = {"MARKET_CLOSED", "STALE_TICK", "FUTURE_SIGNAL", "INVALID_SNAPSHOT"}
REAL_FILTERS = {
    "REGIME_BLOCK",
    "LIQUIDITY_BLOCK",
    "SPREAD_BLOCK",
    "SCORE_THRESHOLD_BLOCK",
    "COOLDOWN_BLOCK",
    "SESSION_BLOCK",
    "RISK_BLOCK",
    "SYMBOL_BLOCK",
    "OTHER_FILTER",
}


def build_rejection_breakdown(dataset: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_filter: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    by_symbol: Counter[str] = Counter()
    by_session: Counter[str] = Counter()
    safety = {"execution_attempted_detected": False, "order_send_detected": False, "order_check_detected": False}
    for event in dataset.get("events", []):
        event_type = str(event.get("event_type", "")).upper()
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        if event.get("execution_attempted") or payload.get("execution_attempted"):
            safety["execution_attempted_detected"] = True
        if event.get("order_send_called") or payload.get("order_send_called"):
            safety["order_send_detected"] = True
        if event.get("order_check_called") or payload.get("order_check_called"):
            safety["order_check_detected"] = True
        if event_type not in REJECTION_EVENTS:
            continue
        reason = _reason(event, payload)
        filter_name = classify_filter(event_type, reason)
        symbol = str(event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "UNKNOWN").upper()
        session = str(payload.get("session") or payload.get("market_session") or payload.get("session_name") or "UNKNOWN").upper()
        by_filter[filter_name] += 1
        by_reason[reason] += 1
        by_symbol[symbol] += 1
        by_session[session] += 1
        rows.append(
            {
                "event_type": event_type,
                "filter_category": filter_name,
                "rejection_reason": reason,
                "symbol": symbol,
                "session": session,
                "timestamp_utc": event.get("timestamp_utc", ""),
                "source": event.get("source", ""),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    total = sum(by_filter.values())
    real_total = sum(count for name, count in by_filter.items() if name in REAL_FILTERS)
    market_total = sum(count for name, count in by_filter.items() if name in MARKET_FILTERS)
    return {
        "rows": rows,
        "total_rejections": total,
        "real_filter_rejections": real_total,
        "market_data_rejections": market_total,
        "by_filter": [{"filter_category": name, "count": count, "share": _share(count, total)} for name, count in by_filter.most_common()],
        "by_reason": [{"rejection_reason": name, "count": count, "share": _share(count, total)} for name, count in by_reason.most_common()],
        "by_symbol": [{"symbol": name, "count": count, "share": _share(count, total)} for name, count in by_symbol.most_common()],
        "by_session": [{"session": name, "count": count, "share": _share(count, total)} for name, count in by_session.most_common()],
        "market_closed_count": by_filter.get("MARKET_CLOSED", 0),
        "stale_tick_count": by_filter.get("STALE_TICK", 0),
        "invalid_snapshot_count": by_filter.get("INVALID_SNAPSHOT", 0),
        "dominant_real_filter": _dominant_real(by_filter),
        **safety,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def classify_filter(event_type: str, reason: str) -> str:
    text = f"{event_type} {reason}".upper()
    if "MARKET_CLOSED" in text or "MARKET CLOSED" in text:
        return "MARKET_CLOSED"
    if "STALE_TICK" in text or "STALE TICK" in text:
        return "STALE_TICK"
    if "FUTURE_SIGNAL" in text or "FUTURE" in text:
        return "FUTURE_SIGNAL"
    if "INVALID_MARKET_SNAPSHOT" in text or "INVALID_SNAPSHOT" in text or "SNAPSHOT" in text:
        return "INVALID_SNAPSHOT"
    if "REGIME" in text:
        return "REGIME_BLOCK"
    if "LIQUIDITY" in text or "SWEEP" in text:
        return "LIQUIDITY_BLOCK"
    if "SPREAD" in text or "COST" in text:
        return "SPREAD_BLOCK"
    if "SCORE" in text or "THRESHOLD" in text or "ENSEMBLE" in text or "COMPONENT" in text:
        return "SCORE_THRESHOLD_BLOCK"
    if "COOLDOWN" in text:
        return "COOLDOWN_BLOCK"
    if "SESSION" in text:
        return "SESSION_BLOCK"
    if "RISK" in text or "DRAWDOWN" in text or "LOT" in text:
        return "RISK_BLOCK"
    if "SYMBOL" in text:
        return "SYMBOL_BLOCK"
    return "OTHER_FILTER"


def _reason(event: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    reasons = payload.get("blocking_reasons")
    if isinstance(reasons, list) and reasons:
        return str(reasons[0]).upper()
    return str(
        payload.get("reject_reason")
        or payload.get("reject_code")
        or payload.get("blocking_reason")
        or payload.get("reason")
        or event.get("message")
        or event.get("event_type")
        or "UNKNOWN"
    ).upper()


def _dominant_real(counter: Counter[str]) -> dict[str, Any]:
    real = {name: count for name, count in counter.items() if name in REAL_FILTERS}
    total = sum(real.values())
    if not total:
        return {"filter_category": "", "count": 0, "real_filter_share": 0.0}
    name, count = max(real.items(), key=lambda item: item[1])
    return {"filter_category": name, "count": count, "real_filter_share": _share(count, total)}


def _share(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0

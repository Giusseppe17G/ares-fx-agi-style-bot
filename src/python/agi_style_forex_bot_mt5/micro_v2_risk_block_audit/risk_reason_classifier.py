"""RISK_REJECTED event extraction and reason classification."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


def extract_risk_rejections(dataset: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    session_counts: Counter[str] = Counter()
    safety = {"execution_attempted_detected": False, "order_send_detected": False, "order_check_detected": False}
    for event in dataset.get("events", []):
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        if event.get("execution_attempted") or payload.get("execution_attempted"):
            safety["execution_attempted_detected"] = True
        if event.get("order_send_called") or payload.get("order_send_called"):
            safety["order_send_detected"] = True
        if event.get("order_check_called") or payload.get("order_check_called"):
            safety["order_check_detected"] = True
        if str(event.get("event_type", "")).upper() != "RISK_REJECTED":
            continue
        reason_text = _reason_text(event, payload)
        reason = classify_risk_reason(reason_text, payload)
        symbol = str(event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "UNKNOWN").upper()
        session = str(payload.get("session") or payload.get("market_session") or payload.get("session_name") or "UNKNOWN").upper()
        reason_counts[reason] += 1
        symbol_counts[symbol] += 1
        session_counts[session] += 1
        rows.append(
            {
                "timestamp_utc": event.get("timestamp_utc", ""),
                "symbol": symbol,
                "session": session,
                "risk_block_reason": reason,
                "raw_reason": reason_text,
                "tick_scope": _tick_scope(payload),
                "source": event.get("source", ""),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    total = len(rows)
    return {
        "rows": rows,
        "risk_rejected_count": total,
        "reason_breakdown": [{"risk_block_reason": reason, "count": count, "share": _share(count, total)} for reason, count in reason_counts.most_common()],
        "by_symbol": [{"symbol": symbol, "count": count, "share": _share(count, total)} for symbol, count in symbol_counts.most_common()],
        "by_session": [{"session": session, "count": count, "share": _share(count, total)} for session, count in session_counts.most_common()],
        "dominant_risk_block_reason": _dominant(reason_counts, total),
        "affected_symbols": [symbol for symbol, _count in symbol_counts.most_common()],
        **safety,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def classify_risk_reason(reason_text: str, payload: Mapping[str, Any]) -> str:
    text = f"{reason_text} {payload}".upper()
    if "INVALID_RISK_DISTANCE" in text or "RISK_DISTANCE" in text and ("<= 0" in text or "ZERO" in text or "INVALID" in text):
        return "INVALID_RISK_DISTANCE"
    if "ZERO_POSITION" in text or "POSITION_SIZE_ZERO" in text or "SIZE 0" in text or "VOLUME 0" in text or "ZERO_SIZE" in text:
        return "ZERO_POSITION_SIZE"
    if "COOLDOWN" in text:
        return "COOLDOWN"
    if "MAX_PAPER_TRADES_PER_DAY" in text or "DAILY_TRADE_LIMIT" in text or "TRADE_LIMIT" in text:
        return "MAX_PAPER_TRADES_PER_DAY"
    if "MAX_OPEN_PAPER_TRADES" in text or "MAX_OPEN_TRADES" in text or "OPEN_TRADES" in text:
        return "MAX_OPEN_TRADES"
    if "DRAWDOWN" in text or "DAILY_HALT" in text or "HALT" in text:
        return "DRAWDOWN_HALT"
    if "DAILY_RISK_LEDGER" in text or "DAILY LEDGER" in text:
        return "DAILY_LEDGER_BLOCK"
    if "PROFILE_LIMIT" in text or "PROFILE LIMIT" in text or "PAPER_RISK_LIMIT" in text:
        return "PROFILE_LIMIT_BLOCK"
    if "EXPOSURE" in text or "CORRELATION" in text or "OPEN_RISK" in text:
        return "EXPOSURE_BLOCK"
    if "INVALID_OPEN_PAPER_TRADE" in text or "PAPER_STATE_ERROR" in text or "CONFIG_ERROR" in text:
        return "INVALID_TRADE_STATE"
    if "SL" in text or "TP" in text or "STOP_LOSS" in text or "TAKE_PROFIT" in text:
        return "INVALID_SL_TP"
    return "EXPECTED_SAFETY_GUARD"


def _reason_text(event: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    reasons = payload.get("blocking_reasons")
    if isinstance(reasons, list) and reasons:
        return " ".join(str(item) for item in reasons)
    return str(
        payload.get("risk_reason")
        or payload.get("reject_reason")
        or payload.get("reject_code")
        or payload.get("blocking_reason")
        or payload.get("reason")
        or event.get("message")
        or "RISK_REJECTED"
    )


def _tick_scope(payload: Mapping[str, Any]) -> str:
    text = str(payload.get("tick_time_status") or "").upper()
    if "FRESH" in text:
        return "FRESH_TICK"
    if "STALE" in text:
        return "STALE_TICK"
    if payload.get("market_is_probably_closed"):
        return "MARKET_CLOSED_CONTEXT"
    return "UNKNOWN_TICK_SCOPE"


def _dominant(counter: Counter[str], total: int) -> dict[str, Any]:
    if not counter or total <= 0:
        return {"risk_block_reason": "", "count": 0, "share": 0.0}
    reason, count = counter.most_common(1)[0]
    return {"risk_block_reason": reason, "count": count, "share": _share(count, total)}


def _share(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0

"""Activity summaries for Micro V2 dry-run telemetry."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.rejection_funnel import REJECTION_EVENTS
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


SIGNAL_EVENTS = {
    "SIGNAL_DETECTED",
    "SIGNAL_ACCEPTED",
    "SIGNAL_REJECTED",
    "RISK_REJECTED",
    "SYMBOL_REJECTED",
    "STRATEGY_BLOCKED_BY_CONTEXT",
    "FORWARD_CANDIDATE_EVALUATED",
    "FORWARD_CANDIDATE_BLOCKED",
    "FORWARD_NEAR_MISS",
    "PAPER_TRADE_OPENED",
}


def audit_activity(dataset: Mapping[str, Any], *, now_utc: datetime | None = None) -> dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events = list(dataset.get("events", []))
    trades = list(dataset.get("paper_trades", []))
    signals_detected = _signals_detected(events, trades)
    signals_rejected = sum(1 for event in events if str(event.get("event_type", "")).upper() in REJECTION_EVENTS)
    closed = [trade for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"]
    open_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "OPEN"]
    closed_today = [trade for trade in closed if _same_utc_day(trade.get("closed_at_utc") or trade.get("exit_time_utc"), now)]
    reasons = _reason_counter(events)
    symbols_seen = sorted({symbol for symbol in [_symbol(item) for item in [*events, *trades]] if symbol})
    rejected_symbols = sorted({str(event.get("symbol") or event.get("payload", {}).get("symbol") or "") for event in events if str(event.get("event_type", "")).upper() in REJECTION_EVENTS and (event.get("symbol") or event.get("payload", {}).get("symbol"))})
    paper_drawdown = round(sum(_float(trade.get("scaled_paper_pnl", trade.get("pnl", trade.get("realized_pnl", 0.0)))) for trade in closed), 6)
    config_error = _latest_config_error(events)
    return {
        "signals_detected": signals_detected,
        "signals_rejected": signals_rejected,
        "signals_accepted": max(signals_detected - signals_rejected, 0),
        "rejection_rate": round(signals_rejected / signals_detected, 4) if signals_detected else 0.0,
        "paper_trades_open": len(open_trades),
        "paper_trades_closed": len(closed),
        "paper_trades_closed_today": len(closed_today),
        "paper_drawdown": paper_drawdown,
        "rejected_by_reason": [{"rejection_reason": reason, "count": count} for reason, count in reasons.most_common()],
        "symbols_seen": symbols_seen,
        "symbols_rejected": rejected_symbols,
        "paper_state_recovery_status": "PAPER_STATE_RECOVERY_OK" if not config_error else "PAPER_STATE_RECOVERY_CONFIG_BLOCKED",
        "config_error_root_cause": config_error,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _signals_detected(events: list[Mapping[str, Any]], trades: list[Mapping[str, Any]]) -> int:
    count = 0
    for event in events:
        if str(event.get("event_type", "")).upper() in SIGNAL_EVENTS or str(event.get("event_type", "")).upper() in REJECTION_EVENTS:
            count += 1
    return max(count, len(trades))


def _reason_counter(events: list[Mapping[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in events:
        if str(event.get("event_type", "")).upper() not in REJECTION_EVENTS:
            continue
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        reasons = payload.get("blocking_reasons")
        if isinstance(reasons, list) and reasons:
            counter[str(reasons[0])] += 1
        else:
            counter[str(payload.get("reject_reason") or payload.get("reject_code") or payload.get("blocking_reason") or payload.get("reason") or event.get("message") or event.get("event_type") or "UNKNOWN")] += 1
    return counter


def _same_utc_day(value: Any, now: datetime) -> bool:
    parsed = safe_parse_datetime(value, field_name="closed_at_utc", source="micro_v2_activity")
    return parsed.value is not None and parsed.value.astimezone(timezone.utc).date() == now.date()


def _symbol(item: Mapping[str, Any]) -> str:
    payload = item.get("payload", {}) if isinstance(item.get("payload"), Mapping) else {}
    return str(item.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or item.get("symbol_name") or "").upper()


def _latest_config_error(events: list[Mapping[str, Any]]) -> str:
    for event in reversed(events):
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        event_type = str(event.get("event_type", "")).upper()
        if "CONFIG_ERROR" in event_type or str(payload.get("latest_exit_reason", "")).upper() == "CONFIG_ERROR":
            return str(payload.get("config_error_root_cause") or payload.get("reason") or event.get("message") or "UNKNOWN_CONFIG_ERROR")
    return ""


def _float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0

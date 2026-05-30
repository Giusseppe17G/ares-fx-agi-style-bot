"""Symbol-level forward activity aggregation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping


def audit_symbol_activity(events: list[Mapping[str, Any]], paper_trades: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"signals": 0, "rejections": 0, "paper_trades": 0, "closed_paper_trades": 0})
    for event in events:
        if not _is_activity_event(event):
            continue
        symbol = str(event.get("symbol") or _payload(event).get("symbol") or "UNKNOWN")
        if symbol:
            stats[symbol]["signals"] += 1
            if _is_rejection(event):
                stats[symbol]["rejections"] += 1
    for trade in paper_trades:
        symbol = str(trade.get("symbol") or "UNKNOWN")
        stats[symbol]["paper_trades"] += 1
        if str(trade.get("status", "")).upper() == "CLOSED":
            stats[symbol]["closed_paper_trades"] += 1
    rows = []
    for symbol, values in sorted(stats.items()):
        active = bool(values["signals"] or values["paper_trades"])
        rows.append(
            {
                "symbol": symbol,
                "signals_detected": values["signals"],
                "signals_rejected": values["rejections"],
                "paper_trades": values["paper_trades"],
                "closed_paper_trades": values["closed_paper_trades"],
                "active": active,
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    symbols_seen = [row["symbol"] for row in rows if row["symbol"] != "UNKNOWN"]
    symbols_active = [row["symbol"] for row in rows if row["active"] and row["symbol"] != "UNKNOWN"]
    return rows, {
        "symbols_seen": symbols_seen,
        "symbols_active": symbols_active,
        "symbols_with_zero_activity": [symbol for symbol in symbols_seen if symbol not in symbols_active],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _is_rejection(event: Mapping[str, Any]) -> bool:
    return str(event.get("event_type", "")).upper() in {
        "SIGNAL_REJECTED",
        "RISK_REJECTED",
        "SYMBOL_REJECTED",
        "STALE_TICK_REJECTION",
        "MARKET_CLOSED_REJECTION",
        "FUTURE_SIGNAL_REJECTION",
        "INVALID_MARKET_SNAPSHOT_REJECTION",
        "STRATEGY_BLOCKED_BY_CONTEXT",
        "FORWARD_CANDIDATE_BLOCKED",
        "FORWARD_NO_SIGNAL_DIAGNOSTIC",
    }


def _is_activity_event(event: Mapping[str, Any]) -> bool:
    event_type = str(event.get("event_type", "")).upper()
    return event_type in {
        "SIGNAL_DETECTED",
        "SIGNAL_ACCEPTED",
        "SIGNAL_REJECTED",
        "RISK_REJECTED",
        "SYMBOL_REJECTED",
        "STALE_TICK_REJECTION",
        "MARKET_CLOSED_REJECTION",
        "FUTURE_SIGNAL_REJECTION",
        "INVALID_MARKET_SNAPSHOT_REJECTION",
        "STRATEGY_BLOCKED_BY_CONTEXT",
        "FORWARD_CANDIDATE_EVALUATED",
        "FORWARD_CANDIDATE_BLOCKED",
        "FORWARD_NEAR_MISS",
        "FORWARD_NO_SIGNAL_DIAGNOSTIC",
        "PAPER_TRADE_OPENED",
    }

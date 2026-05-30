"""Symbol-level frequency and conversion diagnostics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.rejection_funnel import REJECTION_EVENTS


def audit_symbol_frequency(events: list[Mapping[str, Any]], paper_trades: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"signals": 0, "rejections": 0, "paper_trades": 0, "closed": 0})
    for event in events:
        symbol = str(event.get("symbol") or _payload(event).get("symbol") or "UNKNOWN")
        event_type = str(event.get("event_type", ""))
        if event_type in REJECTION_EVENTS or event_type.startswith("FORWARD_") or event_type in {"SIGNAL_ACCEPTED", "SIGNAL_DETECTED", "PAPER_TRADE_OPENED"}:
            stats[symbol]["signals"] += 1
        if event_type in REJECTION_EVENTS:
            stats[symbol]["rejections"] += 1
    for trade in paper_trades:
        symbol = str(trade.get("symbol") or "UNKNOWN")
        stats[symbol]["paper_trades"] += 1
        if str(trade.get("status", "")).upper() == "CLOSED":
            stats[symbol]["closed"] += 1
    rows: list[dict[str, Any]] = []
    for symbol, values in sorted(stats.items()):
        signals = values["signals"]
        closed = values["closed"]
        rows.append(
            {
                "symbol": symbol,
                "signals_detected": signals,
                "signals_rejected": values["rejections"],
                "paper_trades": values["paper_trades"],
                "closed_paper_trades": closed,
                "signal_to_closed_trade_conversion": round(closed / signals, 4) if signals else 0.0,
                "rejection_rate": round(values["rejections"] / signals, 4) if signals else 0.0,
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    low_activity = [row["symbol"] for row in rows if row["symbol"] != "UNKNOWN" and int(row["closed_paper_trades"]) == 0]
    return rows, {
        "symbols_with_low_activity": low_activity,
        "symbols_analyzed": len([row for row in rows if row["symbol"] != "UNKNOWN"]),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}

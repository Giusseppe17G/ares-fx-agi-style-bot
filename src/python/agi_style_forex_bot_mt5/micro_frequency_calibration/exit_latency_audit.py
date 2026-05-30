"""Paper trade exit latency diagnostics."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


def audit_exit_latency(paper_trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    durations: list[float] = []
    invalid = 0
    for trade in paper_trades:
        if str(trade.get("status", "")).upper() != "CLOSED":
            continue
        opened = safe_parse_datetime(trade.get("opened_at_utc") or trade.get("entry_time_utc"), field_name="opened_at_utc", source="paper_trades")
        closed = safe_parse_datetime(trade.get("closed_at_utc") or trade.get("exit_time_utc"), field_name="closed_at_utc", source="paper_trades")
        if not opened.value or not closed.value:
            invalid += 1
            continue
        durations.append(max((closed.value - opened.value).total_seconds() / 3600.0, 0.0))
    average = sum(durations) / len(durations) if durations else 0.0
    return {
        "closed_trade_duration_count": len(durations),
        "average_close_latency_hours": round(average, 4),
        "median_close_latency_hours": round(sorted(durations)[len(durations) // 2], 4) if durations else 0.0,
        "invalid_duration_count": invalid,
        "exit_latency_status": "EXIT_LATENCY_TOO_HIGH" if average > 24.0 else "EXIT_LATENCY_OK" if durations else "EXIT_LATENCY_UNKNOWN",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

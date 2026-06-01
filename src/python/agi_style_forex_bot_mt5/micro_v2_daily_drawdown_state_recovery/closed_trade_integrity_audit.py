"""Closed paper trade integrity audit for V2 drawdown recovery."""

from __future__ import annotations

from typing import Any, Mapping


def audit_closed_trade_integrity(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"]
    missing_exit_fields = [
        str(trade.get("paper_trade_id") or "")
        for trade in closed
        if not trade.get("exit_time_utc") or trade.get("exit_price") in (None, "")
    ]
    pnl_missing = [
        str(trade.get("paper_trade_id") or "")
        for trade in closed
        if _float(trade.get("scaled_paper_pnl", trade.get("profit"))) is None
    ]
    duplicate_ids = _duplicates(closed)
    total_scaled = round(sum(_float(trade.get("scaled_paper_pnl", trade.get("profit"))) or 0.0 for trade in closed), 10)
    total_raw = round(sum(_float(trade.get("raw_pnl", trade.get("profit"))) or 0.0 for trade in closed), 10)
    integrity_issue = bool(missing_exit_fields or pnl_missing or duplicate_ids)
    return {
        "closed_trade_integrity_status": "CLOSED_TRADE_INTEGRITY_ISSUE" if integrity_issue else "CLOSED_TRADE_INTEGRITY_OK",
        "closed_trade_count": len(closed),
        "closed_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in closed],
        "closed_missing_exit_fields": missing_exit_fields,
        "closed_missing_pnl_fields": pnl_missing,
        "duplicate_closed_trade_ids": duplicate_ids,
        "closed_scaled_pnl_total": total_scaled,
        "closed_raw_pnl_total": total_raw,
        "closed_losing_trade_count": sum(1 for trade in closed if (_float(trade.get("scaled_paper_pnl", trade.get("profit"))) or 0.0) < 0),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _duplicates(trades: list[Mapping[str, Any]]) -> list[str]:
    seen: dict[str, int] = {}
    for trade in trades:
        trade_id = str(trade.get("paper_trade_id") or "")
        seen[trade_id] = seen.get(trade_id, 0) + 1
    return sorted(trade_id for trade_id, count in seen.items() if trade_id and count > 1)


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

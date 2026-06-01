"""Open paper trade integrity audit for V2 drawdown recovery."""

from __future__ import annotations

from typing import Any, Mapping


def audit_open_trade_integrity(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    open_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "OPEN"]
    invalid = [trade for trade in open_trades if _invalid_open_trade(trade)]
    duplicates = _duplicates(open_trades)
    issue = bool(invalid or duplicates)
    return {
        "open_trade_integrity_status": "OPEN_TRADE_INTEGRITY_ISSUE" if issue else "OPEN_TRADE_INTEGRITY_OK",
        "open_trade_count": len(open_trades),
        "open_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in open_trades],
        "invalid_open_trade_count": len(invalid),
        "invalid_open_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in invalid],
        "invalid_open_trade_reasons": [_invalid_reason(trade) for trade in invalid],
        "duplicate_open_trade_ids": duplicates,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _invalid_open_trade(trade: Mapping[str, Any]) -> bool:
    entry = _float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"))
    sl = _float(trade.get("sl_price") or trade.get("stop_loss") or trade.get("sl"))
    tp = _float(trade.get("tp_price") or trade.get("take_profit") or trade.get("tp"))
    return entry is None or sl is None or tp is None or abs(entry - sl) <= 1e-12 or abs(tp - entry) <= 1e-12


def _invalid_reason(trade: Mapping[str, Any]) -> dict[str, Any]:
    entry = _float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"))
    sl = _float(trade.get("sl_price") or trade.get("stop_loss") or trade.get("sl"))
    tp = _float(trade.get("tp_price") or trade.get("take_profit") or trade.get("tp"))
    reason = "OK"
    if entry is None:
        reason = "MISSING_ENTRY_PRICE"
    elif sl is None:
        reason = "MISSING_SL_PRICE"
    elif tp is None:
        reason = "MISSING_TP_PRICE"
    elif abs(entry - sl) <= 1e-12:
        reason = "ZERO_RISK_DISTANCE_ENTRY_EQUALS_SL"
    elif abs(tp - entry) <= 1e-12:
        reason = "ZERO_TAKE_PROFIT_DISTANCE"
    return {
        "paper_trade_id": str(trade.get("paper_trade_id") or ""),
        "symbol": str(trade.get("symbol") or ""),
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": tp,
        "reason": reason,
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

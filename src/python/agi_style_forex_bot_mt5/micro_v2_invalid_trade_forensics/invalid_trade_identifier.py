"""Identify invalid open paper trades from lifecycle and SQLite evidence."""

from __future__ import annotations

from typing import Any, Mapping


def identify_invalid_open_trades(inputs: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle_rows = inputs.get("lifecycle_audit", {}).get("open_trades", [])
    rows = [dict(row) for row in lifecycle_rows if isinstance(row, Mapping)]
    if not rows:
        rows = [_trade_row(trade) for trade in inputs.get("v2_dataset", {}).get("paper_trades", []) if str(trade.get("status", "")).upper() == "OPEN"]
    invalid = [row for row in rows if _is_invalid(row)]
    return {
        "invalid_open_trade_count": len(invalid),
        "invalid_trade_ids": [str(row.get("trade_id") or row.get("paper_trade_id") or "") for row in invalid],
        "affected_symbols": sorted({str(row.get("symbol") or "").upper() for row in invalid if row.get("symbol")}),
        "invalid_open_trades": invalid,
        "all_open_trade_count": len(rows),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _is_invalid(row: Mapping[str, Any]) -> bool:
    if row.get("invalid_risk_distance") or row.get("invalid_sl_tp"):
        return True
    entry = _float(row.get("entry_price"))
    sl = _float(row.get("sl_price"))
    tp = _float(row.get("tp_price"))
    if entry is None or sl is None or tp is None:
        return True
    side = str(row.get("side") or row.get("direction") or "").upper()
    wrong_side = (
        (side == "BUY" and (sl >= entry or tp <= entry))
        or (side == "SELL" and (sl <= entry or tp >= entry))
    )
    return abs(entry - sl) <= 1e-12 or abs(tp - entry) <= 1e-12 or wrong_side


def _trade_row(trade: Mapping[str, Any]) -> dict[str, Any]:
    entry = _float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"))
    sl = _float(trade.get("sl_price") or trade.get("stop_loss") or trade.get("sl"))
    tp = _float(trade.get("tp_price") or trade.get("take_profit") or trade.get("tp"))
    return {
        "trade_id": trade.get("paper_trade_id") or trade.get("trade_id") or "",
        "symbol": trade.get("symbol") or "",
        "side": str(trade.get("side") or trade.get("direction") or "").upper(),
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": tp,
        "current_price": _float(trade.get("current_price")),
        "opened_at_utc": trade.get("opened_at_utc") or trade.get("entry_time_utc") or "",
        "risk_distance": abs(entry - sl) if entry is not None and sl is not None else None,
        "reward_distance": abs(tp - entry) if entry is not None and tp is not None else None,
        "missing_sl": sl is None,
        "missing_tp": tp is None,
        "sl_equals_entry": entry is not None and sl is not None and abs(entry - sl) <= 1e-12,
        "tp_equals_entry": entry is not None and tp is not None and abs(tp - entry) <= 1e-12,
    }


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

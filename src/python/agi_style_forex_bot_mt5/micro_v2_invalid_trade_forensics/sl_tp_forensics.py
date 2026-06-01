"""SL/TP forensics for invalid paper trades."""

from __future__ import annotations

from typing import Any, Mapping


def analyze_sl_tp(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for trade in trades:
        entry = _float(trade.get("entry_price"))
        sl = _float(trade.get("sl_price"))
        tp = _float(trade.get("tp_price"))
        side = str(trade.get("side") or trade.get("direction") or "").upper()
        rows.append(
            {
                "trade_id": trade.get("trade_id") or trade.get("paper_trade_id") or "",
                "symbol": trade.get("symbol") or "",
                "side": side,
                "entry_price": entry,
                "sl_price": sl,
                "tp_price": tp,
                "sl_missing": sl is None,
                "tp_missing": tp is None,
                "sl_equals_entry": entry is not None and sl is not None and abs(entry - sl) <= 1e-12,
                "tp_equals_entry": entry is not None and tp is not None and abs(tp - entry) <= 1e-12,
                "sl_wrong_side_for_long": side == "BUY" and entry is not None and sl is not None and sl >= entry,
                "sl_wrong_side_for_short": side == "SELL" and entry is not None and sl is not None and sl <= entry,
                "tp_wrong_side_for_long": side == "BUY" and entry is not None and tp is not None and tp <= entry,
                "tp_wrong_side_for_short": side == "SELL" and entry is not None and tp is not None and tp >= entry,
            }
        )
    return {
        "sl_tp_issue_count": sum(1 for row in rows if any(row[key] for key in row if key.endswith("_missing") or key.endswith("_entry") or "wrong_side" in key)),
        "sl_tp_forensics": rows,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

"""Risk distance forensics for invalid paper trades."""

from __future__ import annotations

from typing import Any, Mapping


def analyze_risk_distance(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for trade in trades:
        entry = _float(trade.get("entry_price"))
        sl = _float(trade.get("sl_price"))
        risk_distance = _float(trade.get("risk_distance"))
        if risk_distance is None and entry is not None and sl is not None:
            risk_distance = abs(entry - sl)
        rows.append(
            {
                "trade_id": trade.get("trade_id") or trade.get("paper_trade_id") or "",
                "symbol": trade.get("symbol") or "",
                "entry_price": entry,
                "sl_price": sl,
                "risk_distance": risk_distance,
                "zero_risk_distance": risk_distance is not None and risk_distance <= 0,
                "negative_risk_distance": risk_distance is not None and risk_distance < 0,
                "entry_missing": entry is None,
                "sl_missing": sl is None,
                "sl_equals_entry": entry is not None and sl is not None and abs(entry - sl) <= 1e-12,
                "precision_rounding_possible": _precision_rounding_possible(trade, entry, sl),
            }
        )
    return {
        "risk_distance_issue_count": sum(1 for row in rows if row["zero_risk_distance"] or row["entry_missing"] or row["sl_missing"]),
        "risk_distance_forensics": rows,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _precision_rounding_possible(trade: Mapping[str, Any], entry: float | None, sl: float | None) -> bool:
    if entry is None or sl is None or abs(entry - sl) > 1e-12:
        return False
    digits = _float(trade.get("digits"))
    point = _float(trade.get("point") or trade.get("pip_size"))
    return digits is not None or point is not None


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

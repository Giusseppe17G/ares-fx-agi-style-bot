"""Quarantined trade exclusion audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_quarantined_trade_exclusion(dataset: Mapping[str, Any]) -> dict[str, Any]:
    trades = list(dataset.get("paper_trades", []))
    quarantined = [trade for trade in trades if "QUARANTINED" in str(trade.get("status", "")).upper()]
    contamination = []
    for trade in quarantined:
        pnl = _float(trade.get("scaled_paper_pnl", trade.get("profit"))) or 0.0
        if str(trade.get("status", "")).upper() == "CLOSED" or abs(pnl) > 1e-12 or trade.get("exit_time_utc"):
            contamination.append(str(trade.get("paper_trade_id") or ""))
    return {
        "quarantined_trade_exclusion_status": "QUARANTINE_EXCLUSION_OK" if not contamination else "QUARANTINE_CONTAMINATION_DETECTED",
        "quarantined_trade_count": len(quarantined),
        "quarantined_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in quarantined],
        "quarantined_contamination_detected": bool(contamination),
        "quarantined_contamination_trade_ids": contamination,
        "quarantined_count_as_closed": False,
        "quarantined_count_as_pnl": False,
        "quarantined_count_as_drawdown": False,
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

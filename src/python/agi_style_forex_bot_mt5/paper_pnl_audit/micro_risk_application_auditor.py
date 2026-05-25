"""Audit whether BALANCED_STABLE_MICRO risk multipliers appear in paper trades."""

from __future__ import annotations

from typing import Any, Mapping


def audit_micro_risk_application(trades: list[Mapping[str, Any]], formula_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    flags = [str(row.get("audit_flags", "")) for row in formula_rows]
    micro_missing = sum("MICRO_MULTIPLIER_NOT_APPLIED" in flag for flag in flags)
    risk_missing = sum("RISK_MULTIPLIER_NOT_APPLIED" in flag for flag in flags)
    micro_values = [_float(trade.get("paper_risk_multiplier"), 1.0) for trade in trades]
    micro_trade_count = sum(1 for value in micro_values if value < 1.0)
    status = "MICRO_RISK_APPLICATION_OK"
    if micro_missing:
        status = "MICRO_MULTIPLIER_NOT_APPLIED"
    elif risk_missing:
        status = "RISK_MULTIPLIER_NOT_APPLIED"
    elif trades and not micro_trade_count:
        status = "MICRO_MULTIPLIER_NOT_PRESENT"
    return {
        "micro_risk_application_status": status,
        "micro_multiplier_applied": micro_missing == 0 and bool(micro_trade_count),
        "risk_multiplier_applied": risk_missing == 0,
        "micro_missing_count": micro_missing,
        "risk_missing_count": risk_missing,
        "micro_trade_count": micro_trade_count,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

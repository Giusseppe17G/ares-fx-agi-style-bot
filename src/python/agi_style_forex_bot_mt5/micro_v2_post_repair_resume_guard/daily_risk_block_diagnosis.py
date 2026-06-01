"""Diagnose daily-risk open-trade deadlock after V2 repair."""

from __future__ import annotations

from typing import Any, Mapping


def diagnose_daily_risk_block(lifecycle: Mapping[str, Any], daily_risk: Mapping[str, Any] | None = None) -> dict[str, Any]:
    daily_risk = daily_risk or {}
    open_count = int(lifecycle.get("open_trade_count", 0) or 0)
    invalid_count = int(lifecycle.get("invalid_open_trade_count", 0) or 0)
    blocked_open = open_count > 0
    return {
        "daily_risk_block_status": "PAPER_DAILY_RISK_BLOCKED_OPEN_TRADES" if blocked_open else "PAPER_DAILY_RISK_NO_OPEN_TRADE_BLOCK",
        "diagnosis": "OPEN_TRADES_PREVENT_STALE_DAILY_RISK_CLEARING" if blocked_open else "NO_OPEN_TRADES_TO_MANAGE",
        "open_trade_count": open_count,
        "invalid_open_trade_count": invalid_count,
        "daily_risk_ledger_present": bool(daily_risk),
        "daily_risk_ledger_status": daily_risk.get("daily_risk_ledger_status", daily_risk.get("paper_daily_risk_clearance_status", "")),
        "reason": "Runtime may need manage-open-trades-only mode to let existing paper trades resolve." if blocked_open and invalid_count == 0 else "",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

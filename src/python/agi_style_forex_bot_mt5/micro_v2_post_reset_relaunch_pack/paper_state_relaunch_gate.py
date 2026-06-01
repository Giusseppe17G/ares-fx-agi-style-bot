"""Paper state relaunch gate for Micro V2."""

from __future__ import annotations

from typing import Any, Mapping


def evaluate_paper_state_gate(readiness: Mapping[str, Any]) -> dict[str, Any]:
    open_count = int(readiness.get("open_trade_count", 0) or 0)
    invalid_count = int(readiness.get("invalid_open_trade_count", 0) or 0)
    clean = bool(readiness.get("paper_state_clean_for_relaunch", False))
    if open_count > 0:
        status = "PAPER_STATE_OPEN_TRADES_BLOCK"
    elif invalid_count > 0:
        status = "PAPER_STATE_INVALID_TRADES_BLOCK"
    elif not clean:
        status = "PAPER_STATE_RELAUNCH_BLOCK"
    else:
        status = "PAPER_STATE_CLEAN_FOR_RELAUNCH"
    return {
        "paper_state_relaunch_gate_status": status,
        "paper_state_clean_for_relaunch": clean,
        "open_trade_count": open_count,
        "invalid_open_trade_count": invalid_count,
        "quarantined_trade_count": int(readiness.get("quarantined_trade_count", 0) or 0),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

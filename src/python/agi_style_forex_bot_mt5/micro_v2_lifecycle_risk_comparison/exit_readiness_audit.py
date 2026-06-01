"""Exit readiness audit for open V2 paper trades."""

from __future__ import annotations

from typing import Any, Mapping


def audit_exit_readiness(lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(lifecycle.get("open_trades", []))
    open_count = len(rows)
    missing_price = sum(1 for row in rows if row.get("missing_current_price"))
    exit_evaluated = sum(1 for row in rows if row.get("exit_condition_evaluated"))
    notification_ready = sum(1 for row in rows if row.get("paper_close_notification_ready"))
    if open_count == 0:
        status = "NO_OPEN_TRADES"
    elif missing_price:
        status = "EXIT_READINESS_PRICE_DATA_MISSING"
    elif exit_evaluated < open_count:
        status = "EXIT_READINESS_WAITING_FOR_EXIT_EVALUATION"
    else:
        status = "EXIT_READINESS_OK"
    return {
        "exit_readiness_status": status,
        "open_trade_count": open_count,
        "missing_current_price_count": missing_price,
        "exit_condition_evaluated_count": exit_evaluated,
        "paper_close_notification_ready_count": notification_ready,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

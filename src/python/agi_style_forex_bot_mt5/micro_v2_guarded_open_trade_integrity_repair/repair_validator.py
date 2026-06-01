"""After-repair validation for guarded open-trade repair."""

from __future__ import annotations

from typing import Any, Mapping


def validate_open_trade_repair(before: Mapping[str, Any], after: Mapping[str, Any], quarantine: Mapping[str, Any]) -> dict[str, Any]:
    closed_changed = before.get("closed_trade_count") != after.get("closed_trade_count")
    pnl_changed = before.get("realized_pnl_total") != after.get("realized_pnl_total")
    invalid_after = int(after.get("invalid_open_trade_count", 0) or 0)
    open_after = int(after.get("open_trade_count", 0) or 0)
    quarantine_delta = int(after.get("quarantined_trade_count", 0) or 0) - int(before.get("quarantined_trade_count", 0) or 0)
    expected_delta = int(quarantine.get("quarantined_trade_count", 0) or 0)
    success = bool(quarantine.get("quarantine_applied")) and not closed_changed and not pnl_changed and invalid_after == 0 and quarantine_delta == expected_delta
    return {
        "repair_validation_status": "OPEN_TRADE_REPAIR_VALIDATION_PASSED" if success else "OPEN_TRADE_REPAIR_VALIDATION_FAILED",
        "validation_passed": success,
        "closed_trade_count_changed": closed_changed,
        "pnl_changed": pnl_changed,
        "invalid_open_trade_count_after": invalid_after,
        "open_trade_count_after": open_after,
        "quarantined_trade_count_delta": quarantine_delta,
        "no_closed_paper_trade_created": not closed_changed,
        "no_artificial_pnl_created": not pnl_changed,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

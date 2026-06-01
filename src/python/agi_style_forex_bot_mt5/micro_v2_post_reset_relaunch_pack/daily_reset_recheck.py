"""Daily reset recheck for Micro V2 post-reset pack."""

from __future__ import annotations

from typing import Any, Mapping


def recheck_daily_reset(readiness: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "daily_reset_recheck_status": "DAILY_RESET_READY" if readiness.get("relaunch_allowed") else "DAILY_RESET_NOT_READY",
        "daily_halt_active": bool(readiness.get("daily_halt_active", False)),
        "daily_reset_occurred": bool(readiness.get("daily_reset_occurred", False)),
        "current_operational_day": readiness.get("current_operational_day", ""),
        "latest_halt_operational_day": readiness.get("latest_halt_operational_day", ""),
        "relaunch_allowed": bool(readiness.get("relaunch_allowed", False)),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

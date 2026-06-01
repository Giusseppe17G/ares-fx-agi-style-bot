"""Verify Micro V2 daily risk ledger scope repair evidence."""

from __future__ import annotations

from typing import Any, Mapping


def verify_ledger_scope(scope_repair: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, Any]:
    verified = (
        scope_repair.get("daily_risk_scope_status_after") == "DAILY_RISK_SCOPE_OK_FOR_V2"
        and readiness.get("daily_risk_scope_status") == "DAILY_RISK_SCOPE_OK_FOR_V2"
    )
    return {
        "ledger_scope_verification_status": "DAILY_RISK_SCOPE_VERIFIED_FOR_V2" if verified else "DAILY_RISK_SCOPE_INVALID",
        "daily_risk_scope_verified": bool(verified),
        "daily_risk_scope_status": readiness.get("daily_risk_scope_status", scope_repair.get("daily_risk_scope_status_after", "")),
        "scope_repair_status": scope_repair.get("micro_v2_daily_risk_scope_repair_status", ""),
        "closed_scaled_pnl_total": scope_repair.get("closed_scaled_pnl_total", 0.0),
        "closed_trade_count": scope_repair.get("closed_trade_count", 0),
        "daily_halt_active_in_scope_repair": bool(scope_repair.get("daily_halt_active", False)),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

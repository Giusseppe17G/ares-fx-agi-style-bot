"""Verify Micro V2 zero-risk prevention guard evidence."""

from __future__ import annotations

from typing import Any, Mapping


def verify_zero_risk_guard(pre_relaunch: Mapping[str, Any]) -> dict[str, Any]:
    verified = bool(
        pre_relaunch.get("zero_risk_guard_enabled")
        and pre_relaunch.get("invalid_paper_trade_prevention_active")
        and pre_relaunch.get("sl_tp_side_guard_enabled")
        and pre_relaunch.get("precision_rounding_guard_enabled")
        and pre_relaunch.get("paper_trade_creation_guard_status") == "PAPER_TRADE_CREATION_GUARD_ENABLED"
    )
    return {
        "zero_risk_guard_verification_status": "ZERO_RISK_GUARD_VERIFIED" if verified else "ZERO_RISK_GUARD_MISSING",
        "zero_risk_guard_verified": verified,
        "zero_risk_guard_enabled": bool(pre_relaunch.get("zero_risk_guard_enabled", False)),
        "invalid_paper_trade_prevention_active": bool(pre_relaunch.get("invalid_paper_trade_prevention_active", False)),
        "sl_tp_side_guard_enabled": bool(pre_relaunch.get("sl_tp_side_guard_enabled", False)),
        "precision_rounding_guard_enabled": bool(pre_relaunch.get("precision_rounding_guard_enabled", False)),
        "paper_trade_creation_guard_status": pre_relaunch.get("paper_trade_creation_guard_status", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

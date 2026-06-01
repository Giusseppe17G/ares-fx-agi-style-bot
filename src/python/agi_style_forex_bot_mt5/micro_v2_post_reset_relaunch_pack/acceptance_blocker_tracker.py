"""Acceptance blocker tracker for Micro V2 post-reset relaunch."""

from __future__ import annotations

from typing import Any, Mapping


def build_acceptance_blocker_tracker(readiness: Mapping[str, Any], pre_relaunch: Mapping[str, Any], scope_repair: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "current_blockers": [
            "NEEDS_10_CLOSED_PAPER_TRADES",
            "NEEDS_24H_MARKET_OPEN_OBSERVATION",
            "NEEDS_POST_RELAUNCH_STABILITY",
        ],
        "resolved_blockers": [
            "DAILY_RISK_SCOPE_MISMATCH repaired" if scope_repair.get("daily_risk_scope_status_after") == "DAILY_RISK_SCOPE_OK_FOR_V2" else "DAILY_RISK_SCOPE_MISMATCH pending",
            "ZERO_RISK_DISTANCE prevention guard enabled" if pre_relaunch.get("zero_risk_guard_enabled") else "ZERO_RISK_DISTANCE prevention guard missing",
            "invalid open trades quarantined" if int(readiness.get("invalid_open_trade_count", 0) or 0) == 0 else "invalid open trades remain",
            "PaperTrade schema invalid_close fixed",
        ],
        "not_eligible_for_demo_live": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

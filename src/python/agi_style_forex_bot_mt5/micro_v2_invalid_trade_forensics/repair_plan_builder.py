"""Build a guarded, not-applied repair plan for invalid V2 paper trades."""

from __future__ import annotations

from typing import Any, Mapping


def build_repair_plan(root: Mapping[str, Any], invalid: Mapping[str, Any]) -> dict[str, Any]:
    cause = str(root.get("root_cause") or "")
    action = _action_for_cause(cause)
    return {
        "repair_plan_available": action != "REQUIRE_MANUAL_REVIEW_NO_AUTOMATED_REPAIR",
        "repair_action_recommended": action,
        "target_trade_ids": invalid.get("invalid_trade_ids", []),
        "root_cause": cause,
        "NOT_APPLIED": True,
        "PAPER_ONLY": True,
        "REQUIRES_BACKUP": True,
        "REQUIRES_RUNTIME_STOP": True,
        "REQUIRES_EXPLICIT_NEXT_PHASE": True,
        "APPROVED_FOR_RUNTIME": False,
        "APPROVED_FOR_DEMO": False,
        "APPROVED_FOR_LIVE": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _action_for_cause(cause: str) -> str:
    if cause in {"SL_EQUALS_ENTRY", "TP_EQUALS_ENTRY", "ZERO_ATR_OR_ZERO_STOP_DISTANCE", "SIGNAL_WITH_INVALID_STOP", "FALLBACK_STOP_NOT_APPLIED"}:
        return "QUARANTINE_INVALID_PAPER_TRADE"
    if cause in {"SL_MISSING", "TP_MISSING", "PRICE_DATA_MISSING_AT_ENTRY", "SERIALIZATION_OR_SCHEMA_ISSUE"}:
        return "MARK_INVALID_PAPER_TRADE_AS_REJECTED"
    if cause in {"SL_WRONG_SIDE_FOR_LONG", "SL_WRONG_SIDE_FOR_SHORT", "TP_WRONG_SIDE_FOR_LONG", "TP_WRONG_SIDE_FOR_SHORT"}:
        return "RECONSTRUCT_SL_TP_FROM_VALID_SIGNAL_CONTEXT"
    if cause in {"NEGATIVE_RISK_DISTANCE", "SYMBOL_PRECISION_ROUNDING_COLLAPSE"}:
        return "RECOMPUTE_RISK_DISTANCE_FROM_ENTRY_SL"
    return "REQUIRE_MANUAL_REVIEW_NO_AUTOMATED_REPAIR"

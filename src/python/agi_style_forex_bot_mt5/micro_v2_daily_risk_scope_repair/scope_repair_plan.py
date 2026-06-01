"""Build a safe Micro V2 daily-risk scope repair plan."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .ledger_scope_audit import EXPECTED_PROFILE


def build_scope_repair_plan(inputs: Mapping[str, Any], audit: Mapping[str, Any], *, safety_blocked: bool) -> dict[str, Any]:
    if safety_blocked:
        return _blocked("MICRO_V2_DAILY_RISK_SCOPE_SAFETY_BLOCKED", "SAFETY_FLAGS_TRUE")
    if audit.get("unsafe_reset_detected"):
        return _blocked("MICRO_V2_DAILY_RISK_SCOPE_BLOCKED_UNSAFE_RESET", "UNSAFE_RESET_DETECTED")
    if not audit.get("pnl_matches_expected"):
        return _blocked("MICRO_V2_DAILY_RISK_SCOPE_BLOCKED_PNL_MISMATCH", "CLOSED_SCALED_PNL_TOTAL_MISMATCH")
    if not audit.get("closed_loss_legitimate") or not audit.get("daily_halt_active"):
        return _blocked("MICRO_V2_DAILY_RISK_SCOPE_REQUIRES_MANUAL_REVIEW", "CLOSED_LOSS_OR_HALT_NOT_CONFIRMED")
    if audit.get("ledger_contains_v2_scope") and audit.get("daily_risk_scope_status_before") == "DAILY_RISK_SCOPE_OK_FOR_V2":
        return {
            **_base(False),
            "scope_repair_plan_status": "MICRO_V2_DAILY_RISK_SCOPE_NO_REPAIR_NEEDED",
            "repair_needed": False,
            "planned_entry": {},
            "recommended_next_action": "WAIT_FOR_DAILY_RESET_BEFORE_RESTART",
        }
    entry = _planned_entry(inputs, audit)
    return {
        **_base(True),
        "scope_repair_plan_status": "MICRO_V2_DAILY_RISK_SCOPE_DRY_RUN_READY",
        "repair_needed": True,
        "repair_action": "APPEND_V2_DAILY_RISK_SCOPE_ENTRY",
        "planned_entry": entry,
        "recommended_next_action": "APPLY_SCOPE_REPAIR_THEN_WAIT_FOR_DAILY_RESET",
    }


def _planned_entry(inputs: Mapping[str, Any], audit: Mapping[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    sqlite_scope = str(inputs.get("v2_sqlite") or "")
    closed_loss = inputs.get("closed_loss_summary") if isinstance(inputs.get("closed_loss_summary"), Mapping) else {}
    return {
        "daily_risk_clearance_id": f"pdrc_v2_{uuid.uuid4().hex}",
        "created_at_utc": now,
        "updated_at_utc": now,
        "reviewer": "operator",
        "reason": "Repair Micro V2 daily risk ledger scope after legitimate closed paper loss drawdown halt",
        "source_phase": "FASE_71_MICRO_V2_DAILY_RISK_LEDGER_SCOPE_REPAIR",
        "cleared_for_profile": EXPECTED_PROFILE,
        "canonical_cleared_for_profile": EXPECTED_PROFILE,
        "profile_canonical": EXPECTED_PROFILE,
        "clearance_scope": "PAPER_DRY_RUN_DAILY_RISK_SCOPE_ONLY",
        "halt_source": "V2_PAPER_DRY_RUN",
        "daily_halt_active": True,
        "active_halts_cleared": False,
        "stale_halts_cleared": False,
        "closed_scaled_pnl_total": audit.get("closed_scaled_pnl_total", -9.996),
        "closed_trade_count": audit.get("closed_trade_count", 2),
        "quarantined_trade_count": audit.get("quarantined_trade_count", 3),
        "closed_loss_legitimate": True,
        "sqlite_scope": _norm_path(sqlite_scope),
        "sqlite_scope_hash": hashlib.sha256(_norm_path(sqlite_scope).encode("utf-8")).hexdigest(),
        "stable_scope_untouched": True,
        "base_clearances_preserved": True,
        "not_for_demo_live": True,
        "approved_for_demo": False,
        "approved_for_live": False,
        "demo_only": True,
        "live_trading_approved": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "next_allowed_action": "WAIT_FOR_DAILY_RESET_BEFORE_RESTART",
        "recommended_next_action": "WAIT_FOR_DAILY_RESET_BEFORE_RESTART",
        "source_closed_loss_scope_status": closed_loss.get("micro_v2_closed_loss_scope_decision_status", ""),
    }


def _base(repair_allowed: bool) -> dict[str, Any]:
    return {
        "repair_allowed": repair_allowed,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _blocked(status: str, reason: str) -> dict[str, Any]:
    return {
        **_base(False),
        "scope_repair_plan_status": status,
        "repair_needed": False,
        "blocked_reason": reason,
        "planned_entry": {},
        "recommended_next_action": "MANUAL_REVIEW_REQUIRED",
    }


def _norm_path(value: str) -> str:
    return str(Path(value)).replace("/", "\\")

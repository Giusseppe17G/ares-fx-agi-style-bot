"""Strict safety audit for FASE 48 proposed micro V2 profiles."""

from __future__ import annotations

from typing import Any, Mapping

from .candidate_profile_loader import bool_value, float_value, int_value


def audit_proposed_profile_safety(base: Mapping[str, str], proposed: Mapping[str, str]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    _require_bool(proposed, "PAPER_ONLY", True, failures)
    _require_bool(proposed, "NOT_FOR_DEMO_LIVE", True, failures)
    _require_bool(proposed, "NOT_FOR_LIVE", True, failures)
    _require_bool(proposed, "REQUIRES_STABLE_GATE", True, failures)
    _require_bool(proposed, "REQUIRES_PAPER_RISK_CLEARANCE", True, failures)
    _require_bool(proposed, "REQUIRES_DAILY_RISK_LEDGER", True, failures)
    _require_bool(proposed, "NOT_ACTIVE_RESEARCH_ONLY", True, failures)
    if bool_value(dict(proposed), "APPROVED_FOR_PAPER_DRY_RUN_ONLY", True):
        failures.append(_failure("APPROVED_FOR_PAPER_DRY_RUN_ONLY", "Proposed profile must remain false until review approves it."))
    if bool_value(dict(proposed), "LIVE_TRADING_APPROVED", False):
        failures.append(_failure("LIVE_TRADING_APPROVED", "Proposed profile cannot approve live trading."))
    if bool_value(dict(proposed), "APPROVED_FOR_LIVE", False):
        failures.append(_failure("APPROVED_FOR_LIVE", "Proposed profile cannot approve live."))
    if bool_value(dict(proposed), "APPROVED_FOR_DEMO", False):
        failures.append(_failure("APPROVED_FOR_DEMO", "Proposed profile cannot approve demo execution."))
    base_risk = _risk_multiplier(base)
    proposed_risk = _risk_multiplier(proposed)
    if proposed_risk > base_risk:
        failures.append(_failure("PAPER_RISK_MULTIPLIER", f"Risk multiplier increased from {base_risk:g} to {proposed_risk:g}."))
    base_risk_multiplier = float_value(dict(base), "RISK_MULTIPLIER", 0.0)
    proposed_risk_multiplier = float_value(dict(proposed), "RISK_MULTIPLIER", base_risk_multiplier)
    if proposed_risk_multiplier > base_risk_multiplier:
        failures.append(_failure("RISK_MULTIPLIER", "Risk multiplier cannot increase."))
    if int_value(dict(proposed), "MAX_OPEN_PAPER_TRADES", 99) > 1:
        failures.append(_failure("MAX_OPEN_PAPER_TRADES", "Max open paper trades must remain <= 1."))
    if "MAX_OPEN_TRADES" in proposed and int_value(dict(proposed), "MAX_OPEN_TRADES", 99) > 1:
        failures.append(_failure("MAX_OPEN_TRADES", "Max open trades must remain <= 1."))
    if int_value(dict(proposed), "MAX_PAPER_TRADES_PER_DAY", 99) > 3:
        failures.append(_failure("MAX_PAPER_TRADES_PER_DAY", "Max paper trades per day cannot exceed 3."))
    base_halt = int_value(dict(base), "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", 0)
    proposed_halt = int_value(dict(proposed), "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", base_halt)
    if proposed_halt < base_halt:
        failures.append(_failure("COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", "Drawdown halt cooldown cannot be reduced."))
    base_loss = int_value(dict(base), "COOLDOWN_AFTER_LOSS_MINUTES", 0)
    proposed_loss = int_value(dict(proposed), "COOLDOWN_AFTER_LOSS_MINUTES", base_loss)
    max_reduction = max(0, int(round(base_loss * 0.10)))
    if proposed_loss < base_loss - max_reduction:
        failures.append(_failure("COOLDOWN_AFTER_LOSS_MINUTES", "Loss cooldown reduction exceeds 10%."))
    if not bool_value(dict(proposed), "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", True):
        failures.append(_failure("BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", "Drawdown halt blocking cannot be disabled."))
    return {
        "proposed_safety_passed": not failures,
        "failures": failures,
        "base_risk_multiplier": base_risk,
        "proposed_risk_multiplier": proposed_risk,
        "base_loss_cooldown_minutes": base_loss,
        "proposed_loss_cooldown_minutes": proposed_loss,
        "base_drawdown_halt_cooldown_minutes": base_halt,
        "proposed_drawdown_halt_cooldown_minutes": proposed_halt,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _risk_multiplier(values: Mapping[str, str]) -> float:
    if "PAPER_RISK_MULTIPLIER" in values:
        return float_value(dict(values), "PAPER_RISK_MULTIPLIER", 1.0)
    return float_value(dict(values), "RISK_MULTIPLIER", 1.0)


def _require_bool(values: Mapping[str, str], key: str, expected: bool, failures: list[dict[str, Any]]) -> None:
    if bool_value(dict(values), key, not expected) != expected:
        failures.append(_failure(key, f"{key} must be {str(expected).lower()}."))


def _failure(key: str, reason: str) -> dict[str, Any]:
    return {"key": key, "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}

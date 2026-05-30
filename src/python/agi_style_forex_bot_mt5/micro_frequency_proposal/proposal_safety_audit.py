"""Safety audit for controlled micro frequency proposals."""

from __future__ import annotations

from typing import Any

from .profile_parameter_detector import bool_value, float_value, int_value


def audit_proposal_safety(base_values: dict[str, str], proposed_values: dict[str, str], changes: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not bool_value(proposed_values, "PAPER_ONLY", False):
        failures.append(_failure("PAPER_ONLY", "Proposal must remain paper only."))
    if not bool_value(proposed_values, "NOT_FOR_DEMO_LIVE", False):
        failures.append(_failure("NOT_FOR_DEMO_LIVE", "Proposal must remain not for demo/live execution."))
    if bool_value(proposed_values, "LIVE_TRADING_APPROVED", False):
        failures.append(_failure("LIVE_TRADING_APPROVED", "Proposal cannot approve live trading."))
    if float_value(proposed_values, "PAPER_RISK_MULTIPLIER", 1.0) > float_value(base_values, "PAPER_RISK_MULTIPLIER", 1.0):
        failures.append(_failure("PAPER_RISK_MULTIPLIER", "Proposal cannot increase paper risk multiplier."))
    if float_value(proposed_values, "RISK_MULTIPLIER", 0.0) > float_value(base_values, "RISK_MULTIPLIER", 0.0):
        failures.append(_failure("RISK_MULTIPLIER", "Proposal cannot increase risk multiplier."))
    if int_value(proposed_values, "MAX_OPEN_PAPER_TRADES", 99) > 1:
        failures.append(_failure("MAX_OPEN_PAPER_TRADES", "Proposal cannot allow more than one open paper trade."))
    if int_value(proposed_values, "MAX_OPEN_TRADES", 1) > 1:
        failures.append(_failure("MAX_OPEN_TRADES", "Proposal cannot raise max open trades above one."))
    if int_value(proposed_values, "MAX_PAPER_TRADES_PER_DAY", 99) > 3:
        failures.append(_failure("MAX_PAPER_TRADES_PER_DAY", "Proposal cannot allow more than three paper trades per day."))
    if int_value(proposed_values, "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", 0) < int_value(base_values, "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", 0):
        failures.append(_failure("COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", "Drawdown halt cooldown cannot be reduced."))
    if not bool_value(proposed_values, "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", True):
        failures.append(_failure("BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", "Proposal cannot disable drawdown halt blocking."))
    return {
        "proposal_safety_passed": not failures,
        "failures": failures,
        "change_count": len(changes),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _failure(key: str, reason: str) -> dict[str, Any]:
    return {"key": key, "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}

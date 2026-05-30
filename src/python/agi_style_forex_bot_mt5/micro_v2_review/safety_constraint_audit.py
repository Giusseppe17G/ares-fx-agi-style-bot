"""Safety constraints for approving a micro V2 paper-dry-run profile."""

from __future__ import annotations

from typing import Any, Mapping

from .candidate_profile_loader import bool_value, float_value, int_value


def audit_safety_constraints(base: Mapping[str, str], candidate: Mapping[str, str], diff_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    warnings: list[str] = []
    _require_bool(candidate, "PAPER_ONLY", True, failures)
    _require_bool(candidate, "NOT_FOR_DEMO_LIVE", True, failures)
    if bool_value(candidate, "LIVE_TRADING_APPROVED", False):
        failures.append(_failure("LIVE_TRADING_APPROVED", "Candidate cannot approve live trading."))
    if bool_value(candidate, "DEMO_ONLY", True) is False:
        failures.append(_failure("DEMO_ONLY", "Candidate cannot disable DEMO_ONLY."))
    base_risk = _risk_multiplier(base)
    candidate_risk = _risk_multiplier(candidate)
    if candidate_risk > base_risk:
        failures.append(_failure("PAPER_RISK_MULTIPLIER", f"Risk multiplier increased from {base_risk:g} to {candidate_risk:g}."))
    if int_value(candidate, "MAX_OPEN_PAPER_TRADES", 99) > 1:
        failures.append(_failure("MAX_OPEN_PAPER_TRADES", "Micro V2 may not allow more than one open paper trade."))
    if int_value(candidate, "MAX_PAPER_TRADES_PER_DAY", 99) > 3:
        failures.append(_failure("MAX_PAPER_TRADES_PER_DAY", "Micro V2 daily paper trade limit may not exceed 3."))
    if _stable_gate_removed(candidate):
        failures.append(_failure("REQUIRE_STABLE_GATE", "Candidate cannot remove stable gate requirement."))
    if _clearance_removed(candidate):
        failures.append(_failure("REQUIRES_PAPER_RISK_CLEARANCE", "Candidate cannot remove paper risk clearance requirement."))
    if _daily_ledger_removed(candidate):
        failures.append(_failure("REQUIRES_DAILY_RISK_LEDGER", "Candidate cannot remove daily risk ledger requirement."))
    if bool_value(candidate, "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", True) is False:
        failures.append(_failure("BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", "Candidate cannot disable drawdown halt blocking."))
    cooldown = int_value(candidate, "COOLDOWN_AFTER_LOSS_MINUTES", 0)
    if cooldown <= 0:
        failures.append(_failure("COOLDOWN_AFTER_LOSS_MINUTES", "Candidate cannot disable cooldown."))
    if "NOT_ACTIVE_RESEARCH_ONLY" in candidate:
        warnings.append("Candidate contains NOT_ACTIVE_RESEARCH_ONLY marker; final builder will remove it and add paper dry-run markers.")
    aggressive = _aggressive_changes(base, candidate, diff_rows)
    failures.extend(aggressive)
    return {
        "safety_passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "base_risk_multiplier": base_risk,
        "candidate_risk_multiplier": candidate_risk,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _risk_multiplier(values: Mapping[str, str]) -> float:
    if "PAPER_RISK_MULTIPLIER" in values:
        return float_value(dict(values), "PAPER_RISK_MULTIPLIER", 1.0)
    return float_value(dict(values), "RISK_MULTIPLIER", 1.0)


def _stable_gate_removed(values: Mapping[str, str]) -> bool:
    return not (bool_value(dict(values), "REQUIRE_STABLE_GATE", False) or bool_value(dict(values), "REQUIRES_STABLE_GATE", False))


def _clearance_removed(values: Mapping[str, str]) -> bool:
    if "REQUIRES_PAPER_RISK_CLEARANCE" not in values:
        return False
    return not bool_value(dict(values), "REQUIRES_PAPER_RISK_CLEARANCE", False)


def _daily_ledger_removed(values: Mapping[str, str]) -> bool:
    if "REQUIRES_DAILY_RISK_LEDGER" not in values:
        return False
    return not bool_value(dict(values), "REQUIRES_DAILY_RISK_LEDGER", False)


def _aggressive_changes(base: Mapping[str, str], candidate: Mapping[str, str], diff_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    base_cooldown = int_value(dict(base), "COOLDOWN_AFTER_LOSS_MINUTES", 120)
    candidate_cooldown = int_value(dict(candidate), "COOLDOWN_AFTER_LOSS_MINUTES", base_cooldown)
    if candidate_cooldown < max(15, int(base_cooldown * 0.5)):
        failures.append(_failure("COOLDOWN_AFTER_LOSS_MINUTES", "Cooldown reduction is too aggressive for a micro profile."))
    critical_categories = {"risk", "session", "threshold", "symbol_universe", "paper_limit"}
    critical_changes = [row for row in diff_rows if row.get("change_category") in critical_categories]
    if len(critical_changes) > 3:
        failures.append(_failure("PROFILE_DIFF", "Candidate changes too many critical controls at once."))
    return failures


def _require_bool(values: Mapping[str, str], key: str, expected: bool, failures: list[dict[str, Any]]) -> None:
    if bool_value(dict(values), key, not expected) != expected:
        failures.append(_failure(key, f"{key} must be {str(expected).lower()}."))


def _failure(key: str, reason: str) -> dict[str, Any]:
    return {"key": key, "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}

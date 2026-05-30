"""Profile guard checks for BALANCED_STABLE_MICRO_V2 dry-run readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_review.candidate_profile_loader import bool_value, float_value, int_value, load_profile


def audit_v2_profile(profile_config: str | Path, *, base_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro.ini") -> dict[str, Any]:
    profile = load_profile(profile_config)
    base = load_profile(base_profile_config)
    values = profile.get("values", {}) if isinstance(profile.get("values"), dict) else {}
    base_values = base.get("values", {}) if isinstance(base.get("values"), dict) else {}
    failures: list[dict[str, Any]] = []
    if not profile.get("exists"):
        failures.append(_failure("PROFILE_EXISTS", "V2 profile config is missing."))
    _require_value(values, "PROFILE_NAME", "BALANCED_STABLE_MICRO_V2", failures)
    _require_bool(values, "PAPER_ONLY", True, failures)
    _require_bool(values, "NOT_FOR_DEMO_LIVE", True, failures)
    _require_bool(values, "NOT_FOR_LIVE", True, failures)
    _require_bool(values, "APPROVED_FOR_PAPER_DRY_RUN_ONLY", True, failures)
    _require_bool(values, "APPROVED_FOR_DEMO", False, failures)
    _require_bool(values, "APPROVED_FOR_LIVE", False, failures)
    _require_bool(values, "REQUIRES_STABLE_GATE", True, failures)
    _require_bool(values, "REQUIRES_PAPER_RISK_CLEARANCE", True, failures)
    _require_bool(values, "REQUIRES_DAILY_RISK_LEDGER", True, failures)
    if int_value(values, "MAX_OPEN_PAPER_TRADES", 99) > 1:
        failures.append(_failure("MAX_OPEN_PAPER_TRADES", "MAX_OPEN_PAPER_TRADES must remain <= 1."))
    if "MAX_OPEN_TRADES" in values and int_value(values, "MAX_OPEN_TRADES", 99) > 1:
        failures.append(_failure("MAX_OPEN_TRADES", "MAX_OPEN_TRADES must remain <= 1."))
    if int_value(values, "MAX_PAPER_TRADES_PER_DAY", 99) > 3:
        failures.append(_failure("MAX_PAPER_TRADES_PER_DAY", "MAX_PAPER_TRADES_PER_DAY must remain <= 3."))
    base_risk = _risk_multiplier(base_values)
    v2_risk = _risk_multiplier(values)
    if v2_risk > base_risk:
        failures.append(_failure("PAPER_RISK_MULTIPLIER", f"V2 risk multiplier {v2_risk:g} exceeds base {base_risk:g}."))
    return {
        "profile_guard_status": "PASS" if not failures else "FAIL",
        "profile_config": str(profile_config),
        "base_profile_config": str(base_profile_config),
        "failures": failures,
        "base_risk_multiplier": base_risk,
        "v2_risk_multiplier": v2_risk,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _risk_multiplier(values: Mapping[str, str]) -> float:
    if "PAPER_RISK_MULTIPLIER" in values:
        return float_value(dict(values), "PAPER_RISK_MULTIPLIER", 1.0)
    return float_value(dict(values), "RISK_MULTIPLIER", 1.0)


def _require_value(values: Mapping[str, str], key: str, expected: str, failures: list[dict[str, Any]]) -> None:
    if str(values.get(key, "")).upper() != expected.upper():
        failures.append(_failure(key, f"{key} must be {expected}."))


def _require_bool(values: Mapping[str, str], key: str, expected: bool, failures: list[dict[str, Any]]) -> None:
    if bool_value(dict(values), key, not expected) != expected:
        failures.append(_failure(key, f"{key} must be {str(expected).lower()}."))


def _failure(key: str, reason: str) -> dict[str, Any]:
    return {"key": key, "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}

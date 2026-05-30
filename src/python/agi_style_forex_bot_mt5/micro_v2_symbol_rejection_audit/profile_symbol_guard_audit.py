"""Profile-level symbol guard audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_profile_symbol_guard(profile: Mapping[str, Any]) -> dict[str, Any]:
    profile_name = str(profile.get("PROFILE_NAME") or profile.get("SIGNAL_PROFILE") or "")
    risk_profile = str(profile.get("RISK_PROFILE_USED") or "")
    allowed_for_shadow = str(profile.get("ALLOWED_FOR_SHADOW", "")).lower() in {"true", "1", "yes"}
    profile_loaded = bool(profile)
    return {
        "profile_symbol_guard_status": "PROFILE_LOADED" if profile_loaded else "PROFILE_MISSING",
        "profile_name": profile_name,
        "signal_profile": str(profile.get("SIGNAL_PROFILE") or ""),
        "risk_profile_used": risk_profile,
        "allowed_for_shadow": allowed_for_shadow,
        "inherits_base_micro_risk_profile": risk_profile.upper() == "BALANCED_STABLE_MICRO",
        "has_symbol_universe_keys": any(key in profile for key in ("ALLOWED_SYMBOLS", "SYMBOLS", "SYMBOL_UNIVERSE", "ENABLED_SYMBOLS", "DISABLED_SYMBOLS")),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

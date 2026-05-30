"""Allowed universe extraction for profile and launch symbol checks."""

from __future__ import annotations

from typing import Any, Mapping

from .symbol_normalization_audit import normalize_symbol


SYMBOL_KEYS = ("ALLOWED_SYMBOLS", "SYMBOLS", "SYMBOL_UNIVERSE", "ENABLED_SYMBOLS")
DISABLED_KEYS = ("DISABLED_SYMBOLS", "BLOCKED_SYMBOLS")


def audit_allowed_universe(profile: Mapping[str, Any], symbols_seen: list[str], rejected_symbols: list[str]) -> dict[str, Any]:
    allowed_raw = _first(profile, SYMBOL_KEYS)
    disabled_raw = _first(profile, DISABLED_KEYS)
    allowed = _parse_symbols(allowed_raw)
    disabled = _parse_symbols(disabled_raw)
    seen = sorted({normalize_symbol(symbol) for symbol in symbols_seen if normalize_symbol(symbol)})
    rejected = sorted({normalize_symbol(symbol) for symbol in rejected_symbols if normalize_symbol(symbol)})
    missing_from_allowed = [symbol for symbol in rejected if allowed and symbol not in allowed]
    disabled_rejections = [symbol for symbol in rejected if symbol in disabled]
    type_status = _type_status(allowed_raw)
    profile_universe_status = "PROFILE_UNIVERSE_NOT_CONFIGURED"
    if type_status != "OK":
        profile_universe_status = type_status
    elif missing_from_allowed:
        profile_universe_status = "PROFILE_UNIVERSE_MISMATCH"
    elif disabled_rejections:
        profile_universe_status = "PROFILE_DISABLED_SYMBOL_MATCH"
    elif allowed:
        profile_universe_status = "PROFILE_UNIVERSE_OK"
    return {
        "profile_universe_status": profile_universe_status,
        "allowed_symbols": allowed,
        "disabled_symbols": disabled,
        "symbols_seen": seen,
        "rejected_symbols": rejected,
        "missing_from_allowed_symbols": missing_from_allowed,
        "disabled_rejected_symbols": disabled_rejections,
        "allowed_symbols_raw": str(allowed_raw or ""),
        "allowed_symbols_type_status": type_status,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _parse_symbols(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            return []
        parts = text.split(",")
    return sorted({normalize_symbol(part) for part in parts if normalize_symbol(part)})


def _first(profile: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in profile:
            return profile.get(key)
    return ""


def _type_status(value: Any) -> str:
    if isinstance(value, str) and value.strip().startswith("[") and value.strip().endswith("]"):
        return "TYPE_MISMATCH_STRINGIFIED_LIST"
    if isinstance(value, str) and value.strip() and "," not in value and len(normalize_symbol(value)) > 6:
        return "TYPE_MISMATCH_STRING_SCALAR"
    return "OK"

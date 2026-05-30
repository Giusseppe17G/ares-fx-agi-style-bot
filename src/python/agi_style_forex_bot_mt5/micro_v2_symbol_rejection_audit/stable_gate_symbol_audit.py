"""Stable gate symbol-universe checks."""

from __future__ import annotations

from typing import Any, Mapping

from .allowed_universe_audit import _parse_symbols


def audit_stable_gate_symbols(stable_gate: Mapping[str, Any], rejected_symbols: list[str]) -> dict[str, Any]:
    allowed = _extract_symbols(stable_gate, ("allowed_symbols", "symbols_keep", "data_valid_symbols", "strategy_input_ready_symbols"))
    disabled = _extract_symbols(stable_gate, ("disabled_symbols", "disabled_symbols_stable", "symbols_reject"))
    rejected = _parse_symbols(rejected_symbols)
    missing = [symbol for symbol in rejected if allowed and symbol not in allowed]
    disabled_hits = [symbol for symbol in rejected if symbol in disabled]
    if not stable_gate:
        status = "STABLE_GATE_MISSING"
    elif missing:
        status = "STABLE_GATE_UNIVERSE_MISMATCH"
    elif disabled_hits:
        status = "STABLE_GATE_DISABLED_SYMBOL_MATCH"
    elif allowed:
        status = "STABLE_GATE_SYMBOLS_OK"
    else:
        status = "STABLE_GATE_SYMBOL_UNIVERSE_NOT_DECLARED"
    return {
        "stable_gate_symbol_status": status,
        "stable_gate_allowed_symbols": allowed,
        "stable_gate_disabled_symbols": disabled,
        "stable_gate_missing_symbols": missing,
        "stable_gate_disabled_rejected_symbols": disabled_hits,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _extract_symbols(payload: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        if key in payload:
            return _parse_symbols(payload.get(key))
    return []

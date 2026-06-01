"""Symbol readiness rows for Micro V2 stable market window."""

from __future__ import annotations

from typing import Any


def build_symbol_readiness(expected_symbols: list[str], fresh_symbols: list[str], stale_symbols: list[str]) -> list[dict[str, Any]]:
    fresh = {symbol.upper() for symbol in fresh_symbols}
    stale = {symbol.upper() for symbol in stale_symbols}
    rows: list[dict[str, Any]] = []
    for symbol in sorted({item.upper() for item in expected_symbols if item} | fresh | stale):
        status = "FRESH" if symbol in fresh else "STALE" if symbol in stale else "NO_TICK_EVIDENCE"
        rows.append(
            {
                "symbol": symbol,
                "symbol_readiness_status": status,
                "fresh_tick": symbol in fresh,
                "stale_tick": symbol in stale,
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows

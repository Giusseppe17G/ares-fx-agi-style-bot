"""Fresh tick coverage audit for Micro V2."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_market_open_readiness.fresh_tick_audit import audit_fresh_ticks


def audit_fresh_tick_coverage(
    dataset: Mapping[str, Any],
    *,
    expected_symbols: list[str],
    checkpoint: Mapping[str, Any],
    readiness: Mapping[str, Any],
    filter_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    _rows, tick_summary = audit_fresh_ticks(dataset)
    fresh = _merge_symbols(
        tick_summary.get("fresh_tick_symbols", []),
        readiness.get("fresh_tick_symbols", []),
        checkpoint.get("fresh_tick_symbols", []),
        filter_analysis.get("fresh_tick_symbols", []),
    )
    stale = _merge_symbols(
        tick_summary.get("stale_tick_symbols", []),
        readiness.get("stale_tick_symbols", []),
        checkpoint.get("stale_tick_symbols", []),
        filter_analysis.get("stale_tick_symbols", []),
    )
    expected = sorted({symbol.upper() for symbol in expected_symbols if symbol})
    denominator = len(expected) or 1
    coverage = round(len([symbol for symbol in expected if symbol in set(fresh)]) / denominator, 4)
    return {
        "expected_symbols": expected,
        "fresh_tick_symbols": fresh,
        "stale_tick_symbols": stale,
        "fresh_tick_coverage_ratio": coverage,
        "fresh_tick_symbol_count": len(fresh),
        "required_symbol_count": len(expected),
        "at_least_two_fresh_symbols": len(fresh) >= 2,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _merge_symbols(*groups: Any) -> list[str]:
    symbols: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            symbols.update(item.strip().upper() for item in group.split(",") if item.strip())
        elif isinstance(group, list):
            symbols.update(str(item).upper() for item in group if str(item))
    return sorted(symbols)

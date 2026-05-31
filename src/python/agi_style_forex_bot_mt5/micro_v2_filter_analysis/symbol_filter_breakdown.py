"""Symbol filter breakdown helpers."""

from __future__ import annotations

from typing import Any, Mapping


def build_symbol_rows(rows: list[Mapping[str, Any]], fresh_symbols: list[str], stale_symbols: list[str]) -> list[dict[str, Any]]:
    fresh = {symbol.upper() for symbol in fresh_symbols}
    stale = {symbol.upper() for symbol in stale_symbols}
    counts: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        item = counts.setdefault(
            symbol,
            {
                "symbol": symbol,
                "rejection_count": 0,
                "fresh_tick_symbol": symbol in fresh,
                "stale_tick_symbol": symbol in stale,
                "top_filter_category": "",
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
                "_filters": {},
            },
        )
        item["rejection_count"] += 1
        filters = item["_filters"]
        filters[row.get("filter_category", "OTHER_FILTER")] = filters.get(row.get("filter_category", "OTHER_FILTER"), 0) + 1
    result: list[dict[str, Any]] = []
    for item in counts.values():
        filters = dict(item.pop("_filters"))
        item["top_filter_category"] = max(filters.items(), key=lambda value: value[1])[0] if filters else ""
        result.append(item)
    return sorted(result, key=lambda value: int(value["rejection_count"]), reverse=True)

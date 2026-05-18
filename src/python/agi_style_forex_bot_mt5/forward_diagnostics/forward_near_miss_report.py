"""Near-miss aggregation for forward signal diagnostics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def summarize_near_misses(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = [dict(row) for row in rows]
    by_symbol = Counter(str(item.get("symbol", "")) for item in items if item.get("symbol"))
    by_strategy = Counter(str(item.get("strategy_name", "")) for item in items if item.get("strategy_name"))
    missing = Counter(_first(item.get("threshold_failures") or item.get("blocking_reasons") or ()) for item in items)
    return {
        "near_miss_count": len(items),
        "near_misses_by_symbol": [{"symbol": key, "count": value} for key, value in by_symbol.most_common()],
        "near_misses_by_strategy": [{"strategy_name": key, "count": value} for key, value in by_strategy.most_common()],
        "most_common_missing_component": missing.most_common(1)[0][0] if missing else "",
        "suggested_research_adjustments": _suggestions(missing),
        "execution_attempted": False,
    }


def _first(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        for item in value:
            return str(item)
    except TypeError:
        return ""
    return ""


def _suggestions(missing: Counter[str]) -> list[str]:
    if not missing:
        return []
    key = missing.most_common(1)[0][0]
    if "SPREAD" in key or "COST" in key:
        return ["Do not relax spread/cost guards; inspect broker costs in research only."]
    return [f"Inspect {key} in threshold-sweep research only; do not change forward-shadow thresholds automatically."]

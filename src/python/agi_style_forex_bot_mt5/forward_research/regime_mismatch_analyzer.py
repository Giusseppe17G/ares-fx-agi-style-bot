"""Research-only regime mismatch summaries for forward candidates."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping


def analyze_regime_mismatches(candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(candidate) for candidate in candidates]
    regime_distribution = Counter(str(row.get("regime") or "UNKNOWN") for row in rows)
    blocked = [row for row in rows if "REGIME_MISMATCH" in _as_tuple(row.get("blocking_reasons"))]
    by_strategy: dict[str, Counter[str]] = defaultdict(Counter)
    for row in blocked:
        by_strategy[str(row.get("strategy_name") or "UNKNOWN")][str(row.get("regime") or "UNKNOWN")] += 1
    suggestions = [
        {
            "strategy_name": strategy,
            "suggested_research_only_regime_test": f"Backtest {strategy} on currently blocked regimes only; do not change BALANCED_STABLE live filters.",
            "blocked_regimes": dict(counter),
        }
        for strategy, counter in sorted(by_strategy.items())
    ]
    return {
        "current_regime_distribution": dict(regime_distribution),
        "blocked_by_regime": dict(Counter(str(row.get("regime") or "UNKNOWN") for row in blocked)),
        "strategies_most_blocked_by_regime": [
            {"strategy_name": strategy, "count": sum(counter.values()), "regimes": dict(counter)}
            for strategy, counter in sorted(by_strategy.items(), key=lambda item: sum(item[1].values()), reverse=True)
        ],
        "suggested_research_only_regime_tests": suggestions,
        "execution_attempted": False,
    }


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return (str(value),)

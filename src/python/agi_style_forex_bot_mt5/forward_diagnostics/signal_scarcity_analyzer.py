"""Classification helpers for forward signal scarcity."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def analyze_signal_scarcity(
    *,
    data_rows: Iterable[Mapping[str, Any]],
    feature_rows: Iterable[Mapping[str, Any]],
    strategy_rows: Iterable[Mapping[str, Any]],
    near_miss_count: int,
    stable_filter: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify the most likely reason for zero/low forward signals."""

    data = [dict(row) for row in data_rows]
    features = [dict(row) for row in feature_rows]
    strategies = [dict(row) for row in strategy_rows]
    blockers = Counter()
    for row in [*data, *features, *strategies]:
        for blocker in _as_tuple(row.get("blockers") or row.get("blocking_reasons") or row.get("threshold_failures")):
            blockers[str(blocker)] += 1
    top = [{"blocking_reason": key, "count": value} for key, value in blockers.most_common(10)]
    if stable_filter.get("classification") == "STABLE_FILTER_TOO_RESTRICTIVE":
        classification = "STABLE_FILTER_TOO_RESTRICTIVE"
        action = "Run stability repair with less restrictive filters in research only."
    elif any(str(item.get("status")) == "NOT_READY" for item in data):
        classification = "FEATURE_PIPELINE_NOT_READY"
        action = "Fix runtime MT5 data/rates readiness before adjusting thresholds."
    elif any(not bool(item.get("features_generated")) for item in features):
        classification = "FEATURE_PIPELINE_NOT_READY"
        action = "Inspect live feature probe errors and runtime candle availability."
    elif near_miss_count > 0:
        classification = "STRATEGY_TOO_SELECTIVE"
        action = "Review near misses in research only; do not change live/shadow safety filters automatically."
    elif strategies and all(str(item.get("action")) == "NONE" for item in strategies):
        classification = "FORWARD_PIPELINE_OK_WAIT_FOR_SETUP"
        action = "Continue paper/shadow observation; market context has not produced a valid setup yet."
    else:
        classification = "NEEDS_MORE_FORWARD_TIME"
        action = "Keep forward-shadow running and collect more cycles."
    return {
        "classification": classification,
        "top_blockers": top,
        "recommended_action": action,
        "execution_attempted": False,
    }


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    try:
        return tuple(value)
    except TypeError:
        return (value,)

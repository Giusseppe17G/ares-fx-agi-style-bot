"""Spread quality analysis."""

from __future__ import annotations

from statistics import median
from typing import Any, Iterable, Mapping


def analyze_spreads(samples: Iterable[Mapping[str, Any]], *, max_spread_points: float = 25.0) -> dict[str, Any]:
    spreads = sorted(float(sample.get("spread_points") or 0.0) for sample in samples if sample.get("spread_points") is not None)
    if not spreads:
        return {
            "count": 0,
            "current": 0.0,
            "average": 0.0,
            "median": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "spikes": 0,
            "blocked_by_p95": True,
            "execution_attempted": False,
        }
    p90 = _percentile(spreads, 90)
    p95 = _percentile(spreads, 95)
    p99 = _percentile(spreads, 99)
    return {
        "count": len(spreads),
        "current": spreads[-1],
        "average": sum(spreads) / len(spreads),
        "median": median(spreads),
        "p90": p90,
        "p95": p95,
        "p99": p99,
        "spikes": sum(1 for value in spreads if value > max_spread_points),
        "spread_relative_to_max": p95 / max_spread_points if max_spread_points > 0 else float("inf"),
        "blocked_by_p95": p95 > max_spread_points,
        "by_hour_utc": _bucket_average(samples, "hour_utc"),
        "by_session": _bucket_average(samples, "session"),
        "execution_attempted": False,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = (len(values) - 1) * (percentile / 100.0)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _bucket_average(samples: Iterable[Mapping[str, Any]], key: str) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for sample in samples:
        if sample.get("spread_points") is None:
            continue
        bucket = str(sample.get(key) or "UNKNOWN")
        buckets.setdefault(bucket, []).append(float(sample["spread_points"]))
    return {bucket: sum(values) / len(values) for bucket, values in buckets.items() if values}


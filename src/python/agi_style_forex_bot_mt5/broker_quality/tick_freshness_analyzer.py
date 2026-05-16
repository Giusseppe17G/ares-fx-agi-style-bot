"""Tick freshness analysis."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .spread_analyzer import _percentile


def analyze_tick_freshness(samples: Iterable[Mapping[str, Any]], *, max_tick_age_seconds: float = 5.0) -> dict[str, Any]:
    ages = sorted(float(sample.get("tick_age_seconds") or 0.0) for sample in samples if sample.get("tick_age_seconds") is not None)
    if not ages:
        return {
            "count": 0,
            "tick_age_current": None,
            "tick_age_p95": None,
            "tick_age_p99": None,
            "fresh_pct": 0.0,
            "stale_pct": 100.0,
            "staleness_recurrent": True,
            "execution_attempted": False,
        }
    stale = sum(1 for age in ages if abs(age) > max_tick_age_seconds)
    return {
        "count": len(ages),
        "tick_age_current": ages[-1],
        "tick_age_p95": _percentile(ages, 95),
        "tick_age_p99": _percentile(ages, 99),
        "fresh_pct": ((len(ages) - stale) / len(ages)) * 100.0,
        "stale_pct": (stale / len(ages)) * 100.0,
        "staleness_recurrent": stale / len(ages) >= 0.2,
        "execution_attempted": False,
    }


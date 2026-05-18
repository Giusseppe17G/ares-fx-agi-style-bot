"""Analyze score distance and weak components for blocked forward candidates."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def analyze_ensemble_scores(candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(candidate) for candidate in candidates]
    distances: list[float] = []
    close = 0
    far = 0
    drags: Counter[str] = Counter()
    for row in rows:
        thresholds = dict(row.get("thresholds_used") or {})
        score = _float(row.get("ensemble_score"))
        threshold = _float(thresholds.get("ensemble_min_score", 0.0))
        distance = max(0.0, threshold - score)
        distances.append(distance)
        if distance <= 10.0:
            close += 1
        else:
            far += 1
        components = dict(row.get("component_scores") or {})
        if components:
            weakest = min(components.items(), key=lambda item: _float(item[1]))[0]
            drags[str(weakest)] += 1
        else:
            for key in ("cost_fit", "liquidity_fit", "momentum_fit", "structure_fit", "volatility_fit", "risk_reward_fit"):
                if _float(row.get(key)) > 0:
                    drags[key] += 1
                    break
    return {
        "candidate_count": len(rows),
        "top_score_drag_components": [{"component": key, "count": value} for key, value in drags.most_common(10)],
        "avg_distance_to_threshold": sum(distances) / len(distances) if distances else 0.0,
        "candidates_close_to_threshold": close,
        "candidates_far_from_threshold": far,
        "execution_attempted": False,
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

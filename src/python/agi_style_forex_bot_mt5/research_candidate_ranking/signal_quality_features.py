"""Signal quality features for offline research candidate ranking."""

from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Mapping


def signal_quality_features(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(events)
    signals = [row for row in rows if row.get("is_signal")]
    rejected = [row for row in rows if row.get("is_rejection")]
    scores = [float(row.get("ensemble_score", 0.0) or 0.0) for row in rows if float(row.get("ensemble_score", 0.0) or 0.0) > 0]
    setups = [float(row.get("setup_score", 0.0) or 0.0) for row in rows if float(row.get("setup_score", 0.0) or 0.0) > 0]
    rejection_rate = len(rejected) / max(1, len(signals)) * 100.0
    avg_score = mean(scores) if scores else 0.0
    avg_setup = mean(setups) if setups else 0.0
    quality = min(100.0, max(0.0, (avg_score or avg_setup or 50.0) - rejection_rate * 0.35))
    return {
        "signals_detected": len(signals),
        "signals_rejected": len(rejected),
        "rejection_rate": rejection_rate,
        "avg_ensemble_score": avg_score,
        "avg_setup_score": avg_setup,
        "signal_quality_score": quality,
        "execution_attempted": False,
    }

"""Regime/session context features for offline research ranking."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def regime_context_features(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(events)
    sessions = Counter(str(row.get("session") or "UNKNOWN") for row in rows if row.get("session"))
    regimes = Counter(str(row.get("regime") or "UNKNOWN") for row in rows if row.get("regime"))
    known_context = sum(sessions.values()) + sum(regimes.values())
    data_quality = 100.0 if known_context else (65.0 if rows else 25.0)
    if "UNKNOWN" in sessions:
        data_quality -= min(30.0, sessions["UNKNOWN"] * 5.0)
    if "UNKNOWN" in regimes:
        data_quality -= min(30.0, regimes["UNKNOWN"] * 5.0)
    return {
        "dominant_session": sessions.most_common(1)[0][0] if sessions else "",
        "dominant_regime": regimes.most_common(1)[0][0] if regimes else "",
        "session_distribution": ";".join(f"{key}:{value}" for key, value in sessions.most_common(5)),
        "regime_distribution": ";".join(f"{key}:{value}" for key, value in regimes.most_common(5)),
        "data_quality_score": max(0.0, min(100.0, data_quality)),
        "execution_attempted": False,
    }

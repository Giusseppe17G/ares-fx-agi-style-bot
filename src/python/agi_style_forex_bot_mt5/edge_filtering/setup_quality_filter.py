"""Setup quality filter suggestions from available edge artifacts."""

from __future__ import annotations

from typing import Any

import pandas as pd


def analyze_setup_quality(edge_summary: dict[str, Any], blockers: pd.DataFrame) -> dict[str, Any]:
    """Return conservative setup quality threshold suggestions."""

    blocker_names = set(blockers.get("blocking_reason", pd.Series(dtype=str)).astype(str).str.upper().tolist()) if not blockers.empty else set()
    minimum_setup_score = 62
    minimum_component_score = 50
    disabled = ["D"]
    active = False
    if "ENSEMBLE_SCORE_LOW" in blocker_names:
        minimum_setup_score = 60
        active = True
    if "SPREAD_BLOCK" in blocker_names or "COST_BLOCK" in blocker_names:
        minimum_component_score = 55
        active = True
    return {
        "active": active,
        "minimum_setup_score_filtered": minimum_setup_score,
        "minimum_component_score_filtered": minimum_component_score,
        "disabled_setup_quality": disabled,
        "reason": "conservative filtered thresholds; spread/cost guards remain strict",
    }

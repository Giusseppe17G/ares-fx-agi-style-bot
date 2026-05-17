"""Threshold comparison for signal profiles."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

import pandas as pd

from ..calibration import profile_allowed_for_shadow
from ..calibration.signal_profile import PROFILES, SignalProfileSettings


THRESHOLD_COLUMNS = (
    "ensemble_min_score",
    "min_component_score",
    "min_setup_score",
    "cost_fit_min",
    "session_fit_min",
    "structure_fit_min",
    "volatility_fit_min",
)


def build_profile_threshold_diff() -> dict[str, Any]:
    """Compare configured thresholds and flag identical profiles."""

    rows = [_row(profile) for profile in PROFILES.values()]
    frame = pd.DataFrame(rows)
    identical_pairs: list[dict[str, str]] = []
    for left_index, left in frame.iterrows():
        for _, right in frame.iloc[left_index + 1 :].iterrows():
            if all(left[column] == right[column] for column in THRESHOLD_COLUMNS):
                identical_pairs.append({"left": str(left["profile"]), "right": str(right["profile"])})
    return {
        "profile_similarity_status": "IDENTICAL_THRESHOLDS" if identical_pairs else "DIFFERENT_THRESHOLDS",
        "warning": bool(identical_pairs),
        "identical_pairs": identical_pairs,
        "thresholds": rows,
        "execution_attempted": False,
    }


def threshold_rows_frame(summary: dict[str, Any]) -> pd.DataFrame:
    """Return threshold rows as a DataFrame."""

    return pd.DataFrame(summary.get("thresholds", []))


def _row(profile: SignalProfileSettings) -> dict[str, Any]:
    payload = profile.to_dict()
    return {
        "profile": profile.name,
        "ensemble_min_score": profile.ensemble_min_score,
        "min_component_score": profile.min_component_score,
        "min_setup_score": profile.min_setup_score,
        "cost_fit_min": profile.cost_fit_min,
        "session_fit_min": profile.session_fit_min,
        "structure_fit_min": profile.structure_fit_min,
        "volatility_fit_min": profile.volatility_fit_min,
        "not_for_demo_live": bool(profile.not_for_demo_live),
        "allowed_for_shadow": profile_allowed_for_shadow(profile.name),
        "profile_hash": sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest(),
        "execution_attempted": False,
    }

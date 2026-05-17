"""Threshold comparison for signal profiles."""

from __future__ import annotations

from typing import Any
import json
from pathlib import Path

import pandas as pd

from ..calibration import effective_profile_config
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


def run_profile_threshold_audit(*, output_dir: str | Path) -> dict[str, Any]:
    """Write canonical effective threshold audit files."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary = build_profile_threshold_diff()
    json_path = output / "profile_threshold_audit.json"
    csv_path = output / "profile_threshold_audit.csv"
    payload = {
        "mode": "profile-threshold-audit",
        **summary,
        "reports_created": [str(json_path), str(csv_path)],
        "execution_attempted": False,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    threshold_rows_frame(summary).to_csv(csv_path, index=False)
    return payload


def threshold_rows_frame(summary: dict[str, Any]) -> pd.DataFrame:
    """Return threshold rows as a DataFrame."""

    return pd.DataFrame(summary.get("thresholds", []))


def _row(profile: SignalProfileSettings) -> dict[str, Any]:
    effective = effective_profile_config(profile.name)
    return {
        "profile": profile.name,
        "ensemble_min_score": effective.thresholds["ensemble_min_score"],
        "min_component_score": effective.thresholds["min_component_score"],
        "min_setup_score": effective.thresholds["min_setup_score"],
        "cost_fit_min": effective.thresholds["cost_fit_min"],
        "session_fit_min": effective.thresholds["session_fit_min"],
        "structure_fit_min": effective.thresholds["structure_fit_min"],
        "volatility_fit_min": effective.thresholds["volatility_fit_min"],
        "not_for_demo_live": bool(profile.not_for_demo_live),
        "allowed_for_shadow": effective.allowed_for_shadow,
        "profile_hash": effective.profile_hash,
        "execution_attempted": False,
    }

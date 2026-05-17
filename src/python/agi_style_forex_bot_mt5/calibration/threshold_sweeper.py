"""Threshold sweep execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .signal_frequency_analyzer import analyze_signal_frequency
from .signal_profile import SignalProfileSettings
from .threshold_config import ThresholdConfig, generate_threshold_grid, profile_threshold


def run_threshold_sweep(
    *,
    symbols: Iterable[str],
    data_dir: str | Path,
    profiles: Iterable[SignalProfileSettings],
    max_combinations_per_profile: int = 40,
) -> dict[str, Any]:
    """Evaluate controlled threshold combinations for sample generation."""

    rows: list[dict[str, Any]] = []
    profile_list = tuple(profiles)
    base_by_profile = {profile.name: analyze_signal_frequency(symbols=symbols, data_dir=data_dir, profile=profile) for profile in profile_list}
    for profile in profile_list:
        configs = _sample_grid(profile, max_combinations=max_combinations_per_profile)
        base = base_by_profile[profile.name]
        for config in configs:
            accepted = _estimate_acceptance(base["records"], config)
            rows.append(
                {
                    **config.to_dict(),
                    "signals_generated": base["signals_found"],
                    "accepted_candidates": accepted,
                    "blocked_candidates": max(0, len(base["records"]) - accepted),
                    "near_misses": base["near_misses"],
                    "average_setup_score": base["average_setup_score"],
                    "execution_attempted": False,
                }
            )
    best = _recommend(rows)
    return {
        "rows": rows,
        "signals_found": int(sum(row["signals_generated"] for row in rows[: len(profile_list)])) if rows else 0,
        "near_misses": int(sum(row["near_misses"] for row in rows[: len(profile_list)])) if rows else 0,
        "recommended_profile": best.get("profile", "CONSERVATIVE"),
        "suggested_threshold_changes": best,
        "execution_attempted": False,
    }


def _sample_grid(profile: SignalProfileSettings, *, max_combinations: int) -> tuple[ThresholdConfig, ...]:
    grid = [item for item in generate_threshold_grid((profile,)) if item.profile == profile.name]
    preferred = profile_threshold(profile)
    if len(grid) <= max_combinations:
        return tuple([preferred, *grid])
    stride = max(1, len(grid) // max_combinations)
    sampled = grid[::stride][:max_combinations]
    return tuple([preferred, *sampled])


def _estimate_acceptance(records: list[dict[str, Any]], config: ThresholdConfig) -> int:
    accepted = 0
    for record in records:
        components = dict(record.get("component_scores") or {})
        if float(record.get("setup_score", 0) or 0) < config.min_setup_score:
            continue
        if float(record.get("score", 0) or 0) < config.ensemble_min_score and record.get("action") != "NONE":
            continue
        if components and min(float(value) for value in components.values()) < config.min_component_score:
            continue
        if float(components.get("cost_fit", 100)) < config.cost_fit_min:
            continue
        if float(components.get("structure_fit", 100)) < config.structure_fit_min:
            continue
        if float(components.get("volatility_fit", 100)) < config.volatility_fit_min:
            continue
        if float(components.get("session_fit", 100)) < config.session_fit_min:
            continue
        accepted += 1
    return accepted


def _recommend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"profile": "CONSERVATIVE"}
    frame = pd.DataFrame(rows)
    frame["quality_proxy"] = frame["accepted_candidates"].astype(float) * 2.0 + frame["near_misses"].astype(float) * 0.25 + frame["average_setup_score"].astype(float)
    candidates = frame[frame["accepted_candidates"] > 0]
    if candidates.empty:
        candidates = frame
    row = candidates.sort_values(["quality_proxy", "accepted_candidates"], ascending=False).iloc[0]
    return row.to_dict()

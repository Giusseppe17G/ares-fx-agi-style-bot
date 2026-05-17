"""Threshold sweep execution."""

from __future__ import annotations

from collections import Counter
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
    all_records = [record for base in base_by_profile.values() for record in base.get("records", [])]
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
    best_frequency = _best_by(rows, "accepted_candidates")
    best_quality = _best_quality(rows)
    signals_found = int(sum(int(base.get("signals_found", 0) or 0) for base in base_by_profile.values()))
    near_misses = int(sum(int(base.get("near_misses", 0) or 0) for base in base_by_profile.values()))
    accepted_candidates = int(sum(int(base.get("accepted_candidates", 0) or 0) for base in base_by_profile.values()))
    blocked_candidates = int(sum(int(base.get("blocked_candidates", 0) or 0) for base in base_by_profile.values()))
    top_blockers = _top_blockers(all_records)
    all_zero = signals_found == 0 and accepted_candidates == 0
    recommended_profile = "RESEARCH_ONLY" if all_zero else str(best.get("profile", "BALANCED"))
    return {
        "rows": rows,
        "records": all_records,
        "candidates_evaluated": len(all_records),
        "accepted_candidates": accepted_candidates,
        "blocked_candidates": blocked_candidates,
        "signals_found": signals_found,
        "near_misses": near_misses,
        "top_blocking_reasons": top_blockers,
        "best_profile_by_frequency": str(best_frequency.get("profile", "")),
        "best_profile_by_quality_proxy": str(best_quality.get("profile", "")),
        "recommended_profile": recommended_profile,
        "suggested_threshold_changes": best,
        "classification": "NEEDS_STRATEGY_RESEARCH" if all_zero else "THRESHOLD_SWEEP_COMPLETED",
        "likely_next_step": "Relax diagnostic thresholds or inspect data/feature generation" if all_zero else "Validate selected profile with backtest/research.",
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


def _best_by(rows: list[dict[str, Any]], column: str) -> dict[str, Any]:
    if not rows:
        return {}
    frame = pd.DataFrame(rows)
    if column not in frame:
        return {}
    return frame.sort_values(column, ascending=False).iloc[0].to_dict()


def _best_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    frame = pd.DataFrame(rows)
    frame["quality_proxy"] = frame["accepted_candidates"].astype(float) * 2.0 + frame["near_misses"].astype(float) * 0.25 + frame["average_setup_score"].astype(float)
    return frame.sort_values(["quality_proxy", "accepted_candidates"], ascending=False).iloc[0].to_dict()


def _top_blockers(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(
        str(record.get("blocking_reason") or "UNKNOWN_BLOCKER")
        for record in records
        if not bool(record.get("accepted_candidate"))
    )
    return [{"blocking_reason": reason, "count": count} for reason, count in counter.most_common(10) if reason]

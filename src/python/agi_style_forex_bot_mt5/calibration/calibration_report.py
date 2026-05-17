"""Calibration report writers and CLI helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .blocking_reason_analyzer import analyze_blocking_reasons, load_strategy_diagnostics
from .signal_frequency_analyzer import analyze_signal_frequency
from .signal_profile import SignalProfileSettings, get_signal_profile, parse_profiles
from .threshold_sweeper import run_threshold_sweep


def run_signal_calibration(
    *,
    symbols: Iterable[str],
    data_dir: str | Path,
    report_dir: str | Path,
    profile_name: str = "BALANCED",
) -> dict[str, Any]:
    """Run signal frequency calibration and write reports."""

    profile = get_signal_profile(profile_name)
    result = analyze_signal_frequency(symbols=symbols, data_dir=data_dir, profile=profile)
    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    records = pd.DataFrame(result["records"])
    records_path = output / "signal_frequency.csv"
    records.to_csv(records_path, index=False)
    blocking = analyze_blocking_reasons(result["records"], output_dir=output)
    suggestions = write_config_suggestions(output / "config_suggestions")
    summary_path = output / "summary.json"
    summary = {
        "mode": "signal-calibration",
        "signals_found": result["signals_found"],
        "near_misses": result["near_misses"],
        "accepted_candidates": result["accepted_candidates"],
        "top_blocking_reasons": blocking["top_blocking_reasons"],
        "recommended_profile": _recommended_profile(result, profile),
        "suggested_threshold_changes": _suggested_changes(result),
        "expected_signal_frequency": result["accepted_candidates"],
        "reports_created": [str(summary_path), str(records_path), *blocking["reports_created"], *suggestions],
        "execution_attempted": False,
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return _jsonable(summary)


def run_threshold_sweep_report(
    *,
    symbols: Iterable[str],
    data_dir: str | Path,
    report_dir: str | Path,
    profiles_value: str | tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Run threshold sweep and write reports."""

    profiles = parse_profiles(profiles_value)
    sweep = run_threshold_sweep(symbols=symbols, data_dir=data_dir, profiles=profiles)
    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / "threshold_sweep.csv"
    summary_path = output / "threshold_sweep_summary.json"
    pd.DataFrame(sweep["rows"]).to_csv(rows_path, index=False)
    summary = {
        "mode": "threshold-sweep",
        "signals_found": sweep["signals_found"],
        "near_misses": sweep["near_misses"],
        "top_blocking_reasons": [],
        "recommended_profile": sweep["recommended_profile"],
        "suggested_threshold_changes": sweep["suggested_threshold_changes"],
        "reports_created": [str(summary_path), str(rows_path), *write_config_suggestions(output / "config_suggestions")],
        "execution_attempted": False,
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return _jsonable(summary)


def run_blocking_reasons_report(
    *,
    reports_root: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Analyze blocking reasons from existing reports."""

    records = load_strategy_diagnostics(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result = analyze_blocking_reasons(records, output_dir=output)
    summary_path = output / "blocking_summary.json"
    summary = {
        "mode": "blocking-reasons",
        "signals_found": 0,
        "near_misses": 0,
        "top_blocking_reasons": result["top_blocking_reasons"],
        "recommended_profile": "BALANCED" if result["records_analyzed"] else "CONSERVATIVE",
        "reports_created": [str(summary_path), *result["reports_created"]],
        "execution_attempted": False,
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return _jsonable(summary)


def write_config_suggestions(output_dir: str | Path) -> list[str]:
    """Write INI suggestions for all profiles."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for name in ("CONSERVATIVE", "BALANCED", "ACTIVE", "RESEARCH_ONLY"):
        profile = get_signal_profile(name)
        path = output / f"{name.lower()}.ini"
        lines = []
        if profile.not_for_demo_live:
            lines.append("; NOT FOR DEMO/LIVE EXECUTION")
        lines.extend(
            [
                f"SIGNAL_PROFILE={profile.name}",
                f"MIN_SETUP_SCORE={profile.min_setup_score}",
                f"MIN_COMPONENT_SCORE={profile.min_component_score}",
                f"COST_FIT_MIN={profile.cost_fit_min}",
                f"STRUCTURE_FIT_MIN={profile.structure_fit_min}",
                f"VOLATILITY_FIT_MIN={profile.volatility_fit_min}",
                f"SESSION_FIT_MIN={profile.session_fit_min}",
                f"ENSEMBLE_MIN_SCORE={profile.ensemble_min_score}",
            ]
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(str(path))
    return paths


def _recommended_profile(result: Mapping[str, Any], current: SignalProfileSettings) -> str:
    if int(result.get("accepted_candidates", 0) or 0) > 0:
        return current.name
    if int(result.get("near_misses", 0) or 0) > 0:
        return "BALANCED" if current.name == "CONSERVATIVE" else "ACTIVE"
    return "RESEARCH_ONLY"


def _suggested_changes(result: Mapping[str, Any]) -> dict[str, Any]:
    if int(result.get("accepted_candidates", 0) or 0) == 0:
        return {"review": "thresholds and blocking filters", "next_step": "threshold-sweep"}
    return {"review": "validate quality with backtest", "next_step": "real-data-research"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value

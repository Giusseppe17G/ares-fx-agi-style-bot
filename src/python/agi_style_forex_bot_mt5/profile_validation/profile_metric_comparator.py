"""Metric comparison for profile-comparison artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


METRIC_COLUMNS = (
    "trades_generated",
    "signals_generated",
    "winrate",
    "expectancy_r",
    "profit_factor",
    "net_profit",
    "max_drawdown_pct",
)


def compare_profile_metrics(profile_runs_dir: str | Path) -> dict[str, Any]:
    """Compare profile metrics and detect suspicious duplication."""

    rows = load_profile_rows(profile_runs_dir)
    frame = pd.DataFrame(rows)
    comparisons: list[dict[str, Any]] = []
    active_balanced_status = "MISSING_PROFILE"
    if not frame.empty and {"ACTIVE", "BALANCED"}.issubset(set(frame["profile"].astype(str))):
        active = frame.loc[frame["profile"].astype(str) == "ACTIVE"].iloc[0]
        balanced = frame.loc[frame["profile"].astype(str) == "BALANCED"].iloc[0]
        identical = _metrics_identical(active, balanced)
        same_hash = _value(active.get("profile_hash")) == _value(balanced.get("profile_hash"))
        same_counts = _value(active.get("signals_generated")) == _value(balanced.get("signals_generated")) and _value(active.get("trades_generated")) == _value(balanced.get("trades_generated"))
        if same_hash:
            active_balanced_status = "IDENTICAL_THRESHOLDS"
        elif identical:
            active_balanced_status = "DIFFERENT_THRESHOLDS_IDENTICAL_METRICS"
        elif not same_counts and _core_metrics_identical(active, balanced):
            active_balanced_status = "IDENTICAL_METRICS_WITH_DIFFERENT_SIGNAL_COUNTS"
        else:
            active_balanced_status = "DIFFERENT_THRESHOLDS_DIFFERENT_METRICS"
        comparisons.append(
            {
                "left": "BALANCED",
                "right": "ACTIVE",
                "metric_similarity_status": active_balanced_status,
                "possible_causes": "; ".join(_possible_causes()) if identical or same_hash else "",
                "recommendation": _recommendation(active_balanced_status),
            }
        )
    return {
        "metric_similarity_status": active_balanced_status,
        "active_vs_balanced_similarity": active_balanced_status,
        "profiles": rows,
        "comparisons": comparisons,
        "execution_attempted": False,
    }


def load_profile_rows(profile_runs_dir: str | Path) -> list[dict[str, Any]]:
    """Load profile rows from JSON or CSV artifacts."""

    root = Path(profile_runs_dir)
    payload_path = root / "profile_comparison.json"
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            profiles = payload.get("profiles", [])
            if isinstance(profiles, list):
                return [dict(item) for item in profiles if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    csv_path = root / "profile_comparison.csv"
    if csv_path.exists():
        try:
            return pd.read_csv(csv_path).to_dict("records")
        except (OSError, pd.errors.EmptyDataError):
            return []
    return []


def _metrics_identical(left: pd.Series, right: pd.Series) -> bool:
    for column in METRIC_COLUMNS:
        if _value(left.get(column)) != _value(right.get(column)):
            return False
    return True


def _core_metrics_identical(left: pd.Series, right: pd.Series) -> bool:
    for column in ("winrate", "expectancy_r", "profit_factor", "net_profit", "max_drawdown_pct"):
        if _value(left.get(column)) != _value(right.get(column)):
            return False
    return True


def _value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, float):
        return round(value, 10)
    return value


def _possible_causes() -> tuple[str, ...]:
    return (
        "profile thresholds not applied",
        "strategies ignore profile thresholds",
        "active profile same as balanced",
        "candidate generation capped identically",
    )


def _recommendation(status: str) -> str:
    if status == "IDENTICAL_THRESHOLDS":
        return "Repair profile threshold config before using comparison conclusions."
    if status == "DIFFERENT_THRESHOLDS_IDENTICAL_METRICS":
        return "Inspect strategy sensitivity; thresholds may not affect selected trades."
    if status == "IDENTICAL_METRICS_WITH_DIFFERENT_SIGNAL_COUNTS":
        return "Inspect aggregation/reporting because counts changed but metrics did not."
    return "Profile thresholds and metrics differ."

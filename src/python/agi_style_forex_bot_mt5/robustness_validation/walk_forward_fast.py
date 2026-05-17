"""Reduced walk-forward validation over existing trades."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .robustness_runner import metrics_from_values, trade_values


def run_walk_forward_fast(trades: pd.DataFrame, *, folds: int = 3, min_trades_per_fold: int = 20) -> tuple[dict[str, Any], pd.DataFrame]:
    """Split closed trades into temporal folds and measure stability."""

    if trades.empty or len(trades) < folds * min_trades_per_fold:
        return {
            "mode": "walk-forward-fast",
            "classification": "NEEDS_MORE_WALK_FORWARD_DATA",
            "fold_count": 0,
            "folds_profitable": 0,
            "avg_fold_expectancy": None,
            "min_fold_expectancy": None,
            "overfit_warning": True,
            "execution_attempted": False,
        }, pd.DataFrame()
    ordered = trades.copy()
    time_column = "exit_time" if "exit_time" in ordered.columns else ("entry_time" if "entry_time" in ordered.columns else "")
    if time_column:
        ordered["_sort_time"] = pd.to_datetime(ordered[time_column], errors="coerce", utc=True)
        ordered = ordered.sort_values(["_sort_time"], na_position="last").reset_index(drop=True)
    else:
        ordered = ordered.reset_index(drop=True)
    chunks = [chunk for chunk in _split_frame(ordered, folds) if not chunk.empty]
    rows = []
    for index, chunk in enumerate(chunks):
        values = trade_values(chunk)
        metrics = metrics_from_values(values.tolist())
        rows.append({"fold": index, **metrics, "profitable": bool(metrics["expectancy_r"] > 0 and metrics["profit_factor"] >= 1.0)})
    frame = pd.DataFrame(rows)
    profitable = int(frame["profitable"].sum()) if not frame.empty else 0
    min_expectancy = float(frame["expectancy_r"].min()) if not frame.empty else None
    overfit_warning = bool(profitable < max(2, len(frame) - 1) or (min_expectancy is not None and min_expectancy < 0))
    classification = "WALK_FORWARD_OK" if not overfit_warning else "WALK_FORWARD_WARNING"
    return {
        "mode": "walk-forward-fast",
        "classification": classification,
        "fold_count": len(frame),
        "folds_profitable": profitable,
        "avg_fold_expectancy": float(frame["expectancy_r"].mean()) if not frame.empty else None,
        "min_fold_expectancy": min_expectancy,
        "fold_profit_factor": float(frame["profit_factor"].mean()) if not frame.empty else None,
        "overfit_warning": overfit_warning,
        "execution_attempted": False,
    }, frame


def _split_frame(frame: pd.DataFrame, folds: int) -> list[pd.DataFrame]:
    size = len(frame)
    base = size // folds
    remainder = size % folds
    chunks: list[pd.DataFrame] = []
    start = 0
    for index in range(folds):
        extra = 1 if index < remainder else 0
        end = start + base + extra
        chunks.append(frame.iloc[start:end].copy())
        start = end
    return chunks

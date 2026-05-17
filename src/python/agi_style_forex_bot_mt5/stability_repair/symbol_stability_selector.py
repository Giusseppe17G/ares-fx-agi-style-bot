"""Symbol stability classification."""

from __future__ import annotations

import pandas as pd

from ..robustness_validation.robustness_runner import metrics_from_values, trade_values


def select_stable_symbols(trades: pd.DataFrame, fold_count: int = 3) -> pd.DataFrame:
    return _select_group(trades, "symbol", "symbol", disable_label="DISABLE_FOR_NOW", fold_count=fold_count)


def _select_group(trades: pd.DataFrame, column: str, output_column: str, *, disable_label: str, fold_count: int) -> pd.DataFrame:
    if trades.empty or column not in trades.columns:
        return pd.DataFrame(columns=[output_column, "trades", "positive_folds", "profit_factor", "expectancy_r", "decision"])
    rows = []
    for value, group in trades.groupby(column):
        metrics = metrics_from_values(trade_values(group).tolist())
        positives = _positive_folds(group, fold_count)
        decision = "NEEDS_MORE_DATA"
        if metrics["total_trades"] >= 20 and positives >= max(2, fold_count - 1) and metrics["expectancy_r"] >= 0 and metrics["profit_factor"] >= 1.0:
            decision = "STABLE_KEEP"
        elif metrics["total_trades"] >= 20 and (positives <= 1 or metrics["expectancy_r"] < 0 or metrics["profit_factor"] < 1.0):
            decision = disable_label
        elif metrics["total_trades"] >= 10:
            decision = "WATCHLIST"
        rows.append({output_column: value, "trades": metrics["total_trades"], "positive_folds": positives, "profit_factor": metrics["profit_factor"], "expectancy_r": metrics["expectancy_r"], "decision": decision})
    return pd.DataFrame(rows)


def _positive_folds(group: pd.DataFrame, fold_count: int) -> int:
    ordered = group.reset_index(drop=True)
    chunks = []
    base = len(ordered) // fold_count if fold_count else len(ordered)
    remainder = len(ordered) % fold_count if fold_count else 0
    start = 0
    for index in range(fold_count):
        size = base + (1 if index < remainder else 0)
        end = start + size
        if end > start:
            chunks.append(ordered.iloc[start:end])
        start = end
    return sum(1 for chunk in chunks if metrics_from_values(trade_values(chunk).tolist())["expectancy_r"] >= 0)

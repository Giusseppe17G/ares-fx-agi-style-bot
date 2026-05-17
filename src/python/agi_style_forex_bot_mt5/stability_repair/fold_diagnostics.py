"""Per-fold diagnostics for walk-forward failure analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..robustness_validation.robustness_runner import metrics_from_values, normalize_trade_frame, trade_values


def build_fold_diagnostics(trades: pd.DataFrame, *, folds: int = 3, min_trades_per_fold: int = 20) -> pd.DataFrame:
    """Split trades temporally and attach failure reasons to each fold."""

    normalized = _ordered_trades(normalize_trade_frame(trades))
    if normalized.empty:
        return pd.DataFrame(columns=_columns())
    rows: list[dict[str, Any]] = []
    for index, chunk in enumerate(_split_frame(normalized, folds)):
        values = trade_values(chunk)
        metrics = metrics_from_values(values.tolist())
        reasons = _failure_reasons(chunk, metrics, min_trades_per_fold=min_trades_per_fold)
        rows.append(
            {
                "fold": index,
                "start_time": _time_value(chunk, "min"),
                "end_time": _time_value(chunk, "max"),
                "trades": metrics["total_trades"],
                "winrate": metrics["winrate"],
                "profit_factor": metrics["profit_factor"],
                "expectancy_r": metrics["expectancy_r"],
                "net_profit": metrics["net_value"],
                "max_drawdown": metrics["max_drawdown_value"],
                "dominant_symbol": _dominant(chunk, "symbol"),
                "dominant_strategy": _dominant(chunk, "strategy_name"),
                "dominant_session": _dominant(chunk, "session"),
                "dominant_regime": _dominant(chunk, "regime"),
                "failure_reason": ";".join(reasons) if reasons else "STABLE_FOLD",
            }
        )
    return pd.DataFrame(rows, columns=_columns())


def _failure_reasons(chunk: pd.DataFrame, metrics: dict[str, Any], *, min_trades_per_fold: int) -> list[str]:
    reasons: list[str] = []
    if int(metrics["total_trades"]) < min_trades_per_fold:
        reasons.append("LOW_TRADES_IN_FOLD")
    if float(metrics["expectancy_r"]) < 0:
        reasons.append("NEGATIVE_EXPECTANCY")
    if float(metrics["profit_factor"]) < 1.0:
        reasons.append("PF_BELOW_1")
    if float(metrics["max_drawdown_value"]) <= -3.0:
        reasons.append("DRAWDOWN_SPIKE")
    if _dominance_ratio(chunk, "symbol") >= 0.70 and int(metrics["total_trades"]) >= min_trades_per_fold:
        reasons.append("SYMBOL_CONCENTRATION")
    for column, reason in (("session", "SESSION_FAILURE"), ("regime", "REGIME_FAILURE"), ("strategy_name", "STRATEGY_FAILURE")):
        if _worst_group_expectancy(chunk, column) < 0:
            reasons.append(reason)
    return reasons or []


def _ordered_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    ordered = trades.copy()
    time_column = "exit_time" if "exit_time" in ordered.columns else ("entry_time" if "entry_time" in ordered.columns else "")
    if time_column:
        ordered["_sort_time"] = pd.to_datetime(ordered[time_column], errors="coerce", utc=True)
        ordered = ordered.sort_values(["_sort_time"], na_position="last")
    return ordered.reset_index(drop=True)


def _split_frame(frame: pd.DataFrame, folds: int) -> list[pd.DataFrame]:
    base = len(frame) // folds
    remainder = len(frame) % folds
    chunks: list[pd.DataFrame] = []
    start = 0
    for index in range(folds):
        size = base + (1 if index < remainder else 0)
        end = start + size
        chunks.append(frame.iloc[start:end].copy())
        start = end
    return [chunk for chunk in chunks if not chunk.empty]


def _time_value(chunk: pd.DataFrame, kind: str) -> str:
    if "_sort_time" not in chunk.columns:
        return ""
    series = chunk["_sort_time"].dropna()
    if series.empty:
        return ""
    value = series.min() if kind == "min" else series.max()
    return value.isoformat()


def _dominant(chunk: pd.DataFrame, column: str) -> str:
    if column not in chunk.columns or chunk.empty:
        return "UNKNOWN"
    counts = chunk[column].astype(str).value_counts()
    return str(counts.index[0]) if not counts.empty else "UNKNOWN"


def _dominance_ratio(chunk: pd.DataFrame, column: str) -> float:
    if column not in chunk.columns or chunk.empty:
        return 0.0
    counts = chunk[column].astype(str).value_counts()
    return float(counts.iloc[0] / len(chunk)) if not counts.empty else 0.0


def _worst_group_expectancy(chunk: pd.DataFrame, column: str) -> float:
    if column not in chunk.columns or chunk.empty:
        return 0.0
    rows = []
    for _, group in chunk.groupby(column):
        rows.append(float(metrics_from_values(trade_values(group).tolist())["expectancy_r"]))
    return min(rows) if rows else 0.0


def _columns() -> list[str]:
    return [
        "fold",
        "start_time",
        "end_time",
        "trades",
        "winrate",
        "profit_factor",
        "expectancy_r",
        "net_profit",
        "max_drawdown",
        "dominant_symbol",
        "dominant_strategy",
        "dominant_session",
        "dominant_regime",
        "failure_reason",
    ]

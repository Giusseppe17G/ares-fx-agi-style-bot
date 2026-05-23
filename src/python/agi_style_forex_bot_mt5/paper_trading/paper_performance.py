"""Forward paper performance metrics."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime

from .paper_trade import PaperTrade


def paper_metrics(trades: Iterable[PaperTrade | Mapping[str, Any]]) -> dict[str, Any]:
    rows = [trade.to_dict() if isinstance(trade, PaperTrade) else dict(trade) for trade in trades]
    if not rows:
        return {
            "paper_total_trades": 0,
            "open_trades": 0,
            "closed_trades": 0,
            "winrate": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "average_r": 0.0,
            "max_drawdown_shadow": 0.0,
            "daily_drawdown_shadow": 0.0,
            "max_consecutive_losses": 0,
            "average_duration": None,
            "duration_parse_status": "NO_VALID_DURATIONS",
            "invalid_timestamp_count": 0,
            "invalid_timestamp_examples": [],
            "average_mae": 0.0,
            "average_mfe": 0.0,
        }
    frame = pd.DataFrame(rows)
    closed = frame[frame["status"] == "CLOSED"].copy()
    profits = closed["profit"].astype(float) if not closed.empty else pd.Series(dtype=float)
    wins = profits[profits > 0]
    losses = profits[profits < 0]
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    profit_factor = float(wins.sum()) / gross_loss if gross_loss > 0 else (float("inf") if len(wins) else 0.0)
    r_values = closed["r_multiple"].astype(float) if "r_multiple" in closed else pd.Series(dtype=float)
    duration = _duration_details(closed)
    return {
        "paper_total_trades": len(frame),
        "open_trades": int((frame["status"] == "OPEN").sum()),
        "closed_trades": len(closed),
        "winrate": len(wins) / len(closed) * 100.0 if len(closed) else 0.0,
        "profit_factor": profit_factor,
        "expectancy_r": float(r_values.mean()) if len(r_values) else 0.0,
        "average_r": float(r_values.mean()) if len(r_values) else 0.0,
        "max_drawdown_shadow": _drawdown(profits),
        "daily_drawdown_shadow": _drawdown(profits),
        "max_consecutive_losses": _max_loss_run(profits),
        "average_duration": duration["average_duration"],
        "duration_parse_status": duration["duration_parse_status"],
        "invalid_timestamp_count": duration["invalid_timestamp_count"],
        "invalid_timestamp_examples": duration["invalid_timestamp_examples"],
        "average_mae": float(closed["mae"].astype(float).mean()) if len(closed) else 0.0,
        "average_mfe": float(closed["mfe"].astype(float).mean()) if len(closed) else 0.0,
    }


def group_metrics(trades: Iterable[PaperTrade | Mapping[str, Any]], field: str) -> pd.DataFrame:
    rows = [trade.to_dict() if isinstance(trade, PaperTrade) else dict(trade) for trade in trades]
    if not rows:
        return pd.DataFrame(columns=[field, "trades", "profit", "expectancy_r"])
    frame = pd.DataFrame(rows)
    if field not in frame.columns:
        return pd.DataFrame(columns=[field, "trades", "profit", "expectancy_r"])
    output = []
    for value, group in frame.groupby(field):
        output.append(
            {
                field: value,
                "trades": len(group),
                "profit": float(group["profit"].astype(float).sum()),
                "expectancy_r": float(group["r_multiple"].astype(float).mean()) if "r_multiple" in group else 0.0,
            }
        )
    return pd.DataFrame(output)


def _drawdown(profits: pd.Series) -> float:
    if len(profits) == 0:
        return 0.0
    equity = profits.cumsum()
    running = equity.cummax()
    return float((equity - running).min())


def _max_loss_run(profits: pd.Series) -> int:
    best = 0
    current = 0
    for profit in profits:
        if profit < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _duration(closed: pd.DataFrame) -> float:
    details = _duration_details(closed)
    return float(details["average_duration"] or 0.0)


def _duration_details(closed: pd.DataFrame) -> dict[str, Any]:
    if closed.empty or "exit_time_utc" not in closed:
        return {"average_duration": None, "duration_parse_status": "NO_VALID_DURATIONS", "invalid_timestamp_count": 0, "invalid_timestamp_examples": []}
    durations: list[float] = []
    invalid: list[dict[str, Any]] = []
    for index, row in closed.iterrows():
        start = safe_parse_datetime(row.get("entry_time_utc"), field_name="entry_time_utc", source="paper_metrics")
        end = safe_parse_datetime(row.get("exit_time_utc"), field_name="exit_time_utc", source="paper_metrics")
        if start.value is None or end.value is None:
            invalid.append(
                {
                    "row": int(index) if isinstance(index, int) else str(index),
                    "entry_time_utc": str(row.get("entry_time_utc")),
                    "exit_time_utc": str(row.get("exit_time_utc")),
                    "entry_warning": start.warning,
                    "exit_warning": end.warning,
                }
            )
            continue
        durations.append((end.value - start.value).total_seconds())
    if not durations:
        status = "NO_VALID_DURATIONS" if invalid else "OK"
        return {"average_duration": None, "duration_parse_status": status, "invalid_timestamp_count": len(invalid), "invalid_timestamp_examples": invalid[:5]}
    status = "PARTIAL_INVALID_TIMESTAMPS" if invalid else "OK"
    return {"average_duration": float(sum(durations) / len(durations)), "duration_parse_status": status, "invalid_timestamp_count": len(invalid), "invalid_timestamp_examples": invalid[:5]}

"""Forward paper metrics for the evidence pack."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from agi_style_forex_bot_mt5.paper_trading.paper_performance import group_metrics, paper_metrics
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def calculate_forward_metrics(*, database: TelemetryDatabase, hours_observed: float = 0.0, signals_detected: int = 0, signals_rejected: int = 0) -> dict[str, Any]:
    rows = [_payload(row) for row in database.fetch_paper_trades()]
    metrics = paper_metrics(rows)
    closed = int(metrics.get("closed_trades", 0) or 0)
    days = max(hours_observed / 24.0, 1.0)
    r_values = pd.Series([float(row.get("r_multiple", 0.0) or 0.0) for row in rows if str(row.get("status", "")).upper() == "CLOSED"], dtype=float)
    output = {
        "mode": "forward-metrics",
        "forward_winrate": metrics.get("winrate", 0.0),
        "forward_profit_factor": metrics.get("profit_factor", 0.0),
        "forward_expectancy_r": metrics.get("expectancy_r", 0.0),
        "forward_net_r": float(r_values.sum()) if len(r_values) else 0.0,
        "max_forward_drawdown_r": _drawdown(r_values),
        "average_r": metrics.get("average_r", 0.0),
        "median_r": float(r_values.median()) if len(r_values) else 0.0,
        "trades_by_symbol": _records(group_metrics(rows, "symbol")),
        "trades_by_strategy": _records(group_metrics(rows, "strategy_name")),
        "trades_by_session": _records(group_metrics(rows, "session")),
        "trades_by_regime": _records(group_metrics(rows, "regime")),
        "rejection_rate": (signals_rejected / max(1, signals_detected) * 100.0) if signals_detected else 0.0,
        "signal_frequency_per_day": signals_detected / days,
        "trade_frequency_per_day": closed / days,
        "closed_trades": closed,
        "classification": "FORWARD_SAMPLE_TOO_SMALL" if closed < 10 else "FORWARD_SAMPLE_USABLE",
        "paper_state_status": _paper_state_status(rows, metrics),
        "paper_drawdown_status": "PAPER_DAILY_DRAWDOWN" if float(metrics.get("daily_drawdown_shadow", 0.0) or 0.0) <= -3.0 else "OK",
        "duration_parse_status": metrics.get("duration_parse_status", "OK"),
        "invalid_timestamp_count": metrics.get("invalid_timestamp_count", 0),
        "invalid_timestamp_examples": metrics.get("invalid_timestamp_examples", []),
        "execution_attempted": False,
    }
    return output


def _paper_state_status(rows: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    if int(metrics.get("open_trades", 0) or 0) > 0 and float(metrics.get("daily_drawdown_shadow", 0.0) or 0.0) <= -3.0:
        return "OPEN_TRADES_WITH_DRAWDOWN_REVIEW"
    if int(metrics.get("open_trades", 0) or 0) > 0:
        return "OPEN_PAPER_TRADES"
    return "OK" if rows else "NO_PAPER_TRADES"


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return frame.to_dict(orient="records") if not frame.empty else []


def _drawdown(values: pd.Series) -> float:
    if len(values) == 0:
        return 0.0
    equity = values.cumsum()
    return float((equity - equity.cummax()).min())

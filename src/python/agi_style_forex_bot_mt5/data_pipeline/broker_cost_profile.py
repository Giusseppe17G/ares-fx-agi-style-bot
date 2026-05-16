"""Broker cost profile generation from historical MT5 exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .history_quality import load_history_csv, parse_history_filename


def build_broker_cost_profile(
    *,
    data_dir: str | Path,
    report_dir: str | Path,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build spread/session/hour/day statistics by symbol."""

    data_path = Path(data_dir)
    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    selected = {item.strip().upper() for item in symbols or () if item.strip()}
    profile: dict[str, Any] = {
        "mode": "build-cost-profile",
        "symbols": {},
        "slippage": {"future_realized_slippage_points": None},
        "reports_created": [str(output / "broker_cost_profile.json")],
        "classification": "WATCHLIST",
        "execution_attempted": False,
    }
    for csv_path in sorted(data_path.glob("*_M5.csv")):
        parsed = parse_history_filename(csv_path)
        if parsed is None:
            continue
        symbol, timeframe = parsed
        if selected and symbol not in selected:
            continue
        frame = load_history_csv(csv_path, symbol=symbol, timeframe=timeframe)
        if "spread" not in frame.columns:
            continue
        spread = frame["spread"].astype(float)
        frame["session"] = frame["time"].apply(_session)
        frame["hour_utc"] = frame["time"].dt.hour
        frame["date"] = frame["time"].dt.date.astype(str)
        profile["symbols"][symbol] = {
            "spread_average": float(spread.mean()),
            "spread_median": float(spread.median()),
            "spread_p95": float(spread.quantile(0.95)),
            "spread_p99": float(spread.quantile(0.99)),
            "spread_by_session": _group_mean(frame, "session"),
            "spread_by_hour_utc": _group_mean(frame, "hour_utc"),
            "spread_by_day": _group_mean(frame, "date"),
            "tick_freshness_stats": {
                "source": "historical_bars",
                "bar_interval_seconds_median": float(frame["time"].diff().dt.total_seconds().median()),
            },
            "realized_slippage_points": None,
        }
    if profile["symbols"]:
        profile["classification"] = "OK"
    (output / "broker_cost_profile.json").write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")
    return profile


def cost_for_symbol(profile: Mapping[str, Any] | None, symbol: str, *, fallback: float = 10.0) -> float:
    """Return p95 spread points for a symbol, falling back conservatively."""

    if not profile:
        return fallback
    data = profile.get("symbols", {}).get(symbol.upper(), {})
    return float(data.get("spread_p95", fallback) or fallback)


def _group_mean(frame: pd.DataFrame, column: str) -> dict[str, float]:
    return {str(key): float(value) for key, value in frame.groupby(column)["spread"].mean().items()}


def _session(timestamp: pd.Timestamp) -> str:
    hour = pd.Timestamp(timestamp).hour
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 17:
        return "NY_OVERLAP"
    if 17 <= hour < 22:
        return "NEW_YORK"
    return "ASIA"

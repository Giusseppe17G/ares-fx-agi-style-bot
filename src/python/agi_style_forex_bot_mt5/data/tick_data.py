"""Tick data normalization helpers for research and shadow-mode pipelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.core.price_grid import spread_points_from_prices

from .market_data import MarketDataError


REQUIRED_TICK_COLUMNS: tuple[str, ...] = ("timestamp_utc", "bid", "ask", "spread_points")


def _as_frame(data: pd.DataFrame | Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    return pd.DataFrame(data)


def _canonicalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(
        columns={str(column): str(column).strip().strip("<>").lower().replace(" ", "_") for column in frame.columns}
    )
    if "timestamp_utc" not in frame.columns and {"date", "time"}.issubset(frame.columns):
        frame["timestamp_utc"] = frame["date"].astype(str) + " " + frame["time"].astype(str)
    aliases = {
        "time": "timestamp_utc",
        "datetime": "timestamp_utc",
        "timestamp": "timestamp_utc",
        "spread": "spread_points",
        "vol": "volume",
    }
    alias_map = {
        column: aliases[column]
        for column in frame.columns
        if column in aliases and not (column == "time" and "timestamp_utc" in frame.columns)
    }
    return frame.rename(columns=alias_map)


def normalize_ticks(
    data: pd.DataFrame | Iterable[Mapping[str, Any]],
    *,
    symbol: str | None = None,
    point: float | None = None,
) -> pd.DataFrame:
    """Return normalized tick data with UTC timestamps and spread in points.

    If ``spread_points`` is absent, ``point`` is required so spread can be
    derived in decimal price units as ``(ask - bid) / point``. This avoids mixing
    price-distance units with broker points and binary subtraction noise.
    """

    frame = _canonicalize_columns(_as_frame(data))
    if frame.empty:
        raise MarketDataError("tick data is empty")
    if symbol is not None:
        frame["symbol"] = symbol

    missing_without_spread = [column for column in ("timestamp_utc", "bid", "ask") if column not in frame.columns]
    if missing_without_spread:
        raise MarketDataError(f"tick data missing required columns: {', '.join(missing_without_spread)}")

    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    for column in ("bid", "ask", "spread_points", "volume", "last"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "spread_points" not in frame.columns:
        try:
            frame["spread_points"] = [spread_points_from_prices(bid, ask, point)
                                      for bid, ask in zip(frame["bid"], frame["ask"])]
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise MarketDataError("finite ordered prices and positive point are required to derive spread_points") from exc

    frame = frame.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    frame = frame.reset_index(drop=True)
    validate_tick_frame(frame)
    return frame


def validate_tick_frame(frame: pd.DataFrame) -> None:
    """Validate normalized tick data or raise ``MarketDataError``."""

    if frame.empty:
        raise MarketDataError("tick data is empty")
    missing = [column for column in REQUIRED_TICK_COLUMNS if column not in frame.columns]
    if missing:
        raise MarketDataError(f"tick data missing required columns: {', '.join(missing)}")
    if frame["timestamp_utc"].isna().any():
        raise MarketDataError("tick data contains invalid timestamps")
    numeric_columns = ["bid", "ask", "spread_points"]
    if "volume" in frame.columns:
        numeric_columns.append("volume")
    numeric = frame[numeric_columns]
    if numeric.isna().any().any():
        raise MarketDataError("tick data contains missing numeric values")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise MarketDataError("tick data contains non-finite numeric values")
    if (frame[["bid", "ask"]] <= 0).any().any():
        raise MarketDataError("bid and ask must be positive")
    if (frame["ask"] < frame["bid"]).any():
        raise MarketDataError("ask must be greater than or equal to bid")
    if (frame["spread_points"] < 0).any():
        raise MarketDataError("spread_points cannot be negative")
    if "volume" in frame.columns and (frame["volume"] < 0).any():
        raise MarketDataError("volume cannot be negative")


def latest_market_snapshot(
    ticks: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    digits: int,
    point: float,
    tick_value: float,
    tick_size: float,
    volume_min: float,
    volume_max: float,
    volume_step: float,
    stops_level_points: int,
    freeze_level_points: int,
) -> MarketSnapshot:
    """Build and validate a ``MarketSnapshot`` from the latest normalized tick."""

    validate_tick_frame(ticks)
    latest = ticks.iloc[-1]
    snapshot = MarketSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        timestamp_utc=latest["timestamp_utc"].to_pydatetime(),
        bid=float(latest["bid"]),
        ask=float(latest["ask"]),
        spread_points=float(latest["spread_points"]),
        digits=digits,
        point=point,
        tick_value=tick_value,
        tick_size=tick_size,
        volume_min=volume_min,
        volume_max=volume_max,
        volume_step=volume_step,
        stops_level_points=stops_level_points,
        freeze_level_points=freeze_level_points,
    )
    snapshot.validate()
    return snapshot

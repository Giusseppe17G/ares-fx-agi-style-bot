"""Daily FX price panels for portfolio research.

Every series is expressed as the price of one unit of the currency in US
dollars, so a long position in a column is long that currency and short USD.
Two sources are supported:

- the FRED H.10 noon buying rates as published by the open dataset
  github.com/datasets/exchange-rates (``data/daily.csv``: Date, Country,
  Exchange rate); and
- MetaTrader 5 daily bars written by ``--mode export-history --timeframes D1``
  (``<SYMBOL>_D1.csv`` with ``timestamp_utc`` and ``close``), e.g. from the
  operator's demo broker.

Nothing here reads a terminal or the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

# FRED H.10 country names: ISO code and whether the published rate is USD per
# unit of currency (True) or units of currency per USD (False).
FRED_COUNTRIES: Mapping[str, tuple[str, bool]] = {
    "Australia": ("AUD", True),
    "Canada": ("CAD", False),
    "Denmark": ("DKK", False),
    "Euro": ("EUR", True),
    "Japan": ("JPY", False),
    "New Zealand": ("NZD", True),
    "Norway": ("NOK", False),
    "Sweden": ("SEK", False),
    "Switzerland": ("CHF", False),
    "United Kingdom": ("GBP", True),
}

# MT5 symbol of each currency against USD and whether USD is the base currency.
MT5_USD_PAIRS: Mapping[str, tuple[str, bool]] = {
    "EUR": ("EURUSD", False),
    "GBP": ("GBPUSD", False),
    "AUD": ("AUDUSD", False),
    "NZD": ("NZDUSD", False),
    "JPY": ("USDJPY", True),
    "CHF": ("USDCHF", True),
    "CAD": ("USDCAD", True),
    "SEK": ("USDSEK", True),
    "NOK": ("USDNOK", True),
    "DKK": ("USDDKK", True),
}

MAX_FORWARD_FILL_DAYS = 5


@dataclass(frozen=True)
class PricePanel:
    """USD prices of each currency on a common business-day calendar."""

    prices: pd.DataFrame
    source: str
    source_sha256: str

    @property
    def currencies(self) -> tuple[str, ...]:
        return tuple(self.prices.columns)

    def log_returns(self) -> pd.DataFrame:
        return np.log(self.prices).diff().iloc[1:]

    def between(self, start: str | pd.Timestamp | None, end: str | pd.Timestamp | None) -> "PricePanel":
        return PricePanel(self.prices.loc[start:end], self.source, self.source_sha256)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _finalise(wide: pd.DataFrame, currencies: Iterable[str]) -> pd.DataFrame:
    selected = [code for code in currencies]
    missing = [code for code in selected if code not in wide.columns]
    if missing:
        raise ValueError(f"currencies not in source: {', '.join(missing)}")
    frame = wide[selected].sort_index()
    frame = frame.loc[frame.notna().all(axis=1).idxmax():] if frame.notna().all(axis=1).any() else frame.iloc[0:0]
    if frame.empty:
        raise ValueError("no date on which every selected currency has a price")
    # Holidays differ by market: carry the last price for a few days, never more.
    frame = frame.ffill(limit=MAX_FORWARD_FILL_DAYS)
    if frame.isna().any().any():
        gaps = frame.columns[frame.isna().any()].tolist()
        raise ValueError(f"price gaps longer than {MAX_FORWARD_FILL_DAYS} days in: {', '.join(gaps)}")
    if (frame <= 0).any().any():
        raise ValueError("prices must be positive")
    return frame


def load_fred_daily(path: str | Path, currencies: Iterable[str]) -> PricePanel:
    """Load ``data/daily.csv`` of github.com/datasets/exchange-rates."""

    source = Path(path)
    raw = pd.read_csv(source, dtype={"Country": str, "Exchange rate": str})
    if list(raw.columns) != ["Date", "Country", "Exchange rate"]:
        raise ValueError("unexpected FRED daily CSV columns")
    known = raw[raw["Country"].isin(FRED_COUNTRIES)].copy()
    known["value"] = pd.to_numeric(known["Exchange rate"], errors="coerce")
    known = known[known["value"] > 0]
    known["code"] = known["Country"].map(lambda name: FRED_COUNTRIES[name][0])
    known["usd_price"] = np.where(known["Country"].map(lambda name: FRED_COUNTRIES[name][1]),
                                  known["value"], 1.0 / known["value"])
    known["date"] = pd.to_datetime(known["Date"], format="%Y-%m-%d", utc=True)
    if known.duplicated(["date", "code"]).any():
        raise ValueError("duplicate FRED observations")
    wide = known.pivot(index="date", columns="code", values="usd_price")
    business_days = pd.bdate_range(wide.index.min(), wide.index.max(), tz="UTC")
    return PricePanel(_finalise(wide.reindex(business_days), currencies), "fred_h10_daily", _sha256(source))


def load_mt5_daily(directory: str | Path, currencies: Iterable[str]) -> PricePanel:
    """Load ``<SYMBOL>_D1.csv`` exports (UTC timestamps, see MT5_SERVER_TIME)."""

    folder = Path(directory)
    series, digests = {}, []
    for code in currencies:
        if code not in MT5_USD_PAIRS:
            raise ValueError(f"no USD pair known for {code}")
        symbol, usd_base = MT5_USD_PAIRS[code]
        path = folder / f"{symbol}_D1.csv"
        frame = pd.read_csv(path)
        if not {"timestamp_utc", "close"} <= set(frame.columns):
            raise ValueError(f"{path.name} needs timestamp_utc and close columns")
        dates = pd.to_datetime(frame["timestamp_utc"], utc=True).dt.normalize()
        close = pd.to_numeric(frame["close"], errors="coerce")
        if dates.duplicated().any() or close.isna().any() or (close <= 0).any():
            raise ValueError(f"{path.name} has duplicate days or invalid closes")
        series[code] = pd.Series((1.0 / close if usd_base else close).to_numpy(), index=dates)
        digests.append(f"{path.name}:{_sha256(path)}")
    wide = pd.DataFrame(series)
    business_days = pd.bdate_range(wide.index.min(), wide.index.max(), tz="UTC")
    digest = sha256("\n".join(sorted(digests)).encode("utf-8")).hexdigest()
    return PricePanel(_finalise(wide.reindex(business_days), currencies), "mt5_d1_export", digest)

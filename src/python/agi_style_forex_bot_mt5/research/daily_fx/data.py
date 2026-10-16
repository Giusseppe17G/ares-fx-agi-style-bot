"""Daily FX price panels for portfolio research.

Every series is expressed as the price of one unit of the currency in US
dollars, so a long position in a column is long that currency and short USD.
Two price sources are supported:

- the FRED H.10 noon buying rates as published by the open dataset
  github.com/datasets/exchange-rates (``data/daily.csv``: Date, Country,
  Exchange rate). Every series in that file is units of currency per USD,
  whatever its README says (at commit c023dd8b8f87 the Euro reads 0.8956 and
  the United Kingdom 0.7617 on 2020-01-02), so every series is inverted.
  Noon New York rates are not tradable prices: use them for development, and
  broker bars for anything about execution;
- MetaTrader 5 daily bars written by ``--mode export-history --timeframes D1``
  (``<SYMBOL>_D1.csv`` with ``timestamp_utc`` of the bar open and ``close``).
  A D1 bar is dated by the day on which it closes, so a broker on New York
  close time (bars opening at 21:00/22:00 UTC) and a broker on UTC midnight
  give the same calendar.

Short-term interest rates come from the OECD monthly 3-month interbank rates
(``short-term-interest.csv``: LOCATION, INDICATOR, SUBJECT, MEASURE,
FREQUENCY, TIME, Value; e.g. the copy in nautilus_trader's ``test_data``).

Nothing here reads a terminal or the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

# FRED H.10 country names and ISO codes; every rate is units of currency per USD.
FRED_COUNTRIES: Mapping[str, str] = {
    "Australia": "AUD",
    "Canada": "CAD",
    "Denmark": "DKK",
    "Euro": "EUR",
    "Japan": "JPY",
    "New Zealand": "NZD",
    "Norway": "NOK",
    "Sweden": "SEK",
    "Switzerland": "CHF",
    "United Kingdom": "GBP",
}

# OECD location codes of the short-term rate of each currency.
OECD_RATE_LOCATIONS: Mapping[str, str] = {
    "USA": "USD", "EA19": "EUR", "JPN": "JPY", "GBR": "GBP", "CHE": "CHF", "CAN": "CAD",
    "AUS": "AUD", "NZL": "NZD", "SWE": "SEK", "NOR": "NOK", "DNK": "DKK",
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
MAX_UNCHANGED_DAYS = 5  # a longer run of identical published values is a stale feed


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


def _longest_unchanged_run(series: pd.Series) -> int:
    values = series.dropna().to_numpy()
    if values.size < 2:
        return 0
    longest = current = 0
    for same in values[1:] == values[:-1]:
        current = current + 1 if same else 0
        longest = max(longest, current)
    return longest


def _finalise(wide: pd.DataFrame, currencies: Iterable[str]) -> pd.DataFrame:
    selected = [code for code in currencies]
    missing = [code for code in selected if code not in wide.columns]
    if missing:
        raise ValueError(f"currencies not in source: {', '.join(missing)}")
    frame = wide[selected].sort_index()
    frame = frame.loc[frame.notna().all(axis=1).idxmax():] if frame.notna().all(axis=1).any() else frame.iloc[0:0]
    if frame.empty:
        raise ValueError("no date on which every selected currency has a price")
    stale = [code for code in selected if _longest_unchanged_run(frame[code]) >= MAX_UNCHANGED_DAYS]
    if stale:
        raise ValueError(f"stale prices ({MAX_UNCHANGED_DAYS}+ unchanged days) in: {', '.join(stale)}")
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
    known["code"] = known["Country"].map(FRED_COUNTRIES)
    known["usd_price"] = 1.0 / known["value"]
    known["date"] = pd.to_datetime(known["Date"], format="%Y-%m-%d", utc=True)
    if known.duplicated(["date", "code"]).any():
        raise ValueError("duplicate FRED observations")
    wide = known.pivot(index="date", columns="code", values="usd_price")
    business_days = pd.bdate_range(wide.index.min(), wide.index.max(), tz="UTC")
    return PricePanel(_finalise(wide.reindex(business_days), currencies), "fred_h10_daily", _sha256(source))


def load_mt5_daily(directory: str | Path, currencies: Iterable[str]) -> PricePanel:
    """Load ``<SYMBOL>_D1.csv`` exports (UTC bar-open timestamps, see MT5_SERVER_TIME)."""

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
        opened = pd.to_datetime(frame["timestamp_utc"], utc=True)
        # Date each bar by its close: a bar opening at 21:00 UTC on Sunday is Monday's.
        dates = (opened + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).dt.normalize()
        close = pd.to_numeric(frame["close"], errors="coerce")
        if dates.duplicated().any() or close.isna().any() or (close <= 0).any():
            raise ValueError(f"{path.name} has duplicate days or invalid closes")
        series[code] = pd.Series((1.0 / close if usd_base else close).to_numpy(), index=dates)
        digests.append(f"{path.name}:{_sha256(path)}")
    wide = pd.DataFrame(series)
    business_days = pd.bdate_range(wide.index.min(), wide.index.max(), tz="UTC")
    digest = sha256("\n".join(sorted(digests)).encode("utf-8")).hexdigest()
    return PricePanel(_finalise(wide.reindex(business_days), currencies), "mt5_d1_export", digest)


def load_oecd_rates(path: str | Path, currencies: Iterable[str]) -> tuple[pd.DataFrame, str]:
    """Monthly 3-month rates in percent by currency (PeriodIndex), plus the file sha256.

    USD is always included because every position is against USD.
    """

    source = Path(path)
    raw = pd.read_csv(source, dtype=str)
    needed = {"LOCATION", "INDICATOR", "FREQUENCY", "TIME", "Value"}
    if not needed <= set(raw.columns):
        raise ValueError("unexpected OECD short-term rate CSV columns")
    monthly = raw[(raw["FREQUENCY"] == "M") & (raw["INDICATOR"] == "STINT")
                  & raw["LOCATION"].isin(OECD_RATE_LOCATIONS)].copy()
    monthly["code"] = monthly["LOCATION"].map(OECD_RATE_LOCATIONS)
    monthly["month"] = pd.PeriodIndex(monthly["TIME"], freq="M")
    monthly["value"] = pd.to_numeric(monthly["Value"], errors="coerce")
    if monthly["value"].isna().any() or monthly.duplicated(["month", "code"]).any():
        raise ValueError("OECD rates have missing or duplicate monthly values")
    wide = monthly.pivot(index="month", columns="code", values="value").sort_index()
    wanted = list(dict.fromkeys(["USD", *currencies]))
    missing = [code for code in wanted if code not in wide.columns]
    if missing:
        raise ValueError(f"no OECD rate for: {', '.join(missing)}")
    wide = wide[wanted]
    wide.columns.name = None
    return wide, _sha256(source)

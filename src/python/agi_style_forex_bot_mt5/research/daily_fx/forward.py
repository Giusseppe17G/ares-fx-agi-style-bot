"""Forward paper tracking of a frozen daily FX book (research only).

A frozen study book (plan v2's ``H1_XS_REAL_VALUE_5Y``) is simulated with the
unchanged engine on the operator's own broker daily bars, and only the days
after ``forward_start`` count. Those days did not exist when the plan was
frozen, so they cannot have been fitted. Nothing here builds, checks or sends
an order, and no verdict authorises execution.

The record is a hash-chained ledger of checkpoints on the operator's machine.
Each checkpoint stores the digest of the forward returns up to its last day,
the rebalance decisions it saw and the inflation figures it used. A later run
must recompute exactly the same past, or it refuses to append anything:
broker history revised after the fact (``FORWARD_HISTORY_CHANGED``) is never
absorbed silently.

Data conventions (all fail closed):

- **Prices.** MT5 ``D1`` exports (``<SYMBOL>_D1.csv`` written by
  ``--mode export-history``) are read from ``price_start``. The last bar of
  every file is dropped, because ``copy_rates_from_pos(..., 0, n)`` includes
  the bar still forming.
- **Inflation.** Years up to ``inflation_base_last_year`` come from the
  pinned World Bank file. Each later year comes from a supplement file and is
  taken the first time all ten series have it. That value is then fixed in
  the ledger, so a later revision never changes a past decision.
- **Missing data.** A rebalance whose inputs are missing stops the record
  just before it, and nothing after it is counted, until the data exist.

Two return series are reported:

- **Primary.** The study's own definition: spot returns, the study's trading
  costs and a 75 bps/yr mark-up on gross exposure. It drives the decision
  rule.
- **Broker swap.** The mark-up is replaced by the broker's real swap (carry
  plus mark-up) from the operator's ``capture-swap-snapshot`` files. A day is
  covered only when every held currency has captured swap terms no older than
  ``swap_max_age_days``.

Decision rule (group sequential, one-sided alpha 0.05):

- **Looks.** One look at each anniversary of ``forward_start``, at most ten.
- **CONFIRMED.** At look k the Newey-West t of the primary daily returns so
  far reaches the O'Brien-Fleming boundary ``boundaries[k-1]``. The broker-swap
  series must also cover at least ``min_swap_coverage`` of those days, with a
  positive total.
- **ABANDONED.**
  - ``ABANDONED_FUTILITY``: from look 2, the t is at or below ``futility_t``.
  - ``ABANDONED_DRAWDOWN``: at any time, the primary drawdown reaches
    ``max_drawdown``.
- **ENDED_WITHOUT_CONFIRMATION.** Ten looks pass without a confirmation.

A confirmation only allows opening a decision record about live trading,
which AGENTS.md keeps out of scope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
from typing import Any, Callable, Iterable, Mapping, Sequence
import urllib.request

import numpy as np
import pandas as pd

from ..edge_statistics import newey_west_t_stat
from ..trial_registry import TrialLedger
from .data import MT5_USD_PAIRS, PricePanel, WORLD_BANK_COUNTRIES, _finalise
from .portfolio import (CostModel, PortfolioConfig, RiskLimits, TRADING_DAYS, backtest, inflation_differentials,
    performance, target_weights)
from .study import ENGINE_FILES

FORWARD_VERSION = "daily_fx_forward_v1"
CHECKPOINT = "forward_checkpoint"
# Code that decides every forward number: the study engine, this module and the swap conversion.
FORWARD_FILES = (*ENGINE_FILES, "daily_fx/forward.py", "../broker_swap_snapshot.py")
WORLD_BANK_INDICATOR = "FP.CPI.TOTL.ZG"
WORLD_BANK_URL = ("https://api.worldbank.org/v2/country/{countries}/indicator/" + WORLD_BANK_INDICATOR
                  + "?date={first}:{last}&format=json&per_page=1000")


class ForwardRefused(ValueError):
    """The run would change or misstate the forward record; nothing was appended."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def forward_engine_sha256() -> str:
    """sha256 of every source that decides a forward number (line endings normalised)."""

    root = Path(__file__).resolve().parent.parent
    digest = sha256()
    for name in FORWARD_FILES:
        text = (root / name).resolve().read_text(encoding="utf-8").replace("\r\n", "\n")
        digest.update(name.encode("utf-8") + b"\0" + text.encode("utf-8") + b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class DecisionRule:
    # O'Brien-Fleming boundaries for ten annual looks, one-sided alpha 0.05 (c = 1.801, simulated).
    boundaries: tuple[float, ...] = (5.695, 4.027, 3.288, 2.848, 2.547, 2.325, 2.153, 2.014, 1.898, 1.801)
    futility_t: float = -1.0
    futility_from_look: int = 2
    max_drawdown: float = 0.12
    min_swap_coverage: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["boundaries"] = list(self.boundaries)
        return payload


@dataclass(frozen=True)
class ForwardPlan:
    name: str
    book_plan_hash: str  # the frozen study plan whose primary book is tracked
    hypothesis_id: str
    currencies: tuple[str, ...]
    config: PortfolioConfig
    costs: CostModel
    limits: RiskLimits
    price_start: str
    forward_start: str
    inflation_base_sha256: str
    inflation_base_last_year: int
    price_source: str = "mt5_d1_export"
    swap_max_age_days: int = 35
    rule: DecisionRule = field(default_factory=DecisionRule)
    engine: str = field(default_factory=forward_engine_sha256)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"forward_version": FORWARD_VERSION, "name": self.name, "book_plan_hash": self.book_plan_hash,
                "hypothesis_id": self.hypothesis_id, "currencies": list(self.currencies),
                "config": self.config.to_dict(),
                "costs": {"one_way_bps": dict(sorted(self.costs.one_way_bps.items())),
                          "financing_bps_per_year": self.costs.financing_bps_per_year},
                "limits": self.limits.to_dict(), "price_source": self.price_source,
                "price_start": self.price_start, "forward_start": self.forward_start,
                "inflation_base_sha256": self.inflation_base_sha256,
                "inflation_base_last_year": self.inflation_base_last_year,
                "swap_max_age_days": self.swap_max_age_days, "rule": self.rule.to_dict(),
                "engine_sha256": self.engine, "notes": list(self.notes)}

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def plan_hash(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def validate(self) -> None:
        self.config.validate()
        if self.config.signal != "xsvalue" or self.config.sizing != "equal_risk":
            raise ValueError("the forward tracker follows an equal-risk xsvalue book")
        if pd.Timestamp(self.price_start) >= pd.Timestamp(self.forward_start):
            raise ValueError("price_start must come before forward_start")
        if len(self.rule.boundaries) < 1 or self.swap_max_age_days < 1:
            raise ValueError("the rule needs at least one look and a positive swap age limit")
        if not 0 < self.rule.min_swap_coverage <= 1 or not 0 < self.rule.max_drawdown < 1:
            raise ValueError("min_swap_coverage and max_drawdown must lie in (0, 1]")


def environment() -> dict[str, str]:
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}


def _digest(payload: Any) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=float).encode("utf-8")).hexdigest()


def _series_digest(values: pd.Series) -> str:
    rows = [[str(day.date()), f"{float(value):.12e}"] for day, value in values.items()]
    return _digest(rows)


# --- data -------------------------------------------------------------------


def load_broker_daily(directory: str | Path, currencies: Iterable[str], start: str) -> PricePanel:
    """MT5 ``D1`` exports from ``start``, the last (possibly forming) bar of every file dropped."""

    folder = Path(directory)
    series = {}
    for code in currencies:
        if code not in MT5_USD_PAIRS:
            raise ValueError(f"no USD pair known for {code}")
        symbol, usd_base = MT5_USD_PAIRS[code]
        path = folder / f"{symbol}_D1.csv"
        if not path.exists():
            raise ForwardRefused("PRICES_MISSING", f"{path.name} not found: export D1 history for {symbol}")
        frame = pd.read_csv(path)
        if not {"timestamp_utc", "close"} <= set(frame.columns):
            raise ValueError(f"{path.name} needs timestamp_utc and close columns")
        frame = frame.assign(opened=pd.to_datetime(frame["timestamp_utc"], utc=True)).sort_values("opened")
        frame = frame.iloc[:-1]  # copy_rates_from_pos(..., 0, n) includes the bar still forming
        # Date each bar by its close: a bar opening at 21:00 UTC on Sunday is Monday's.
        dates = (frame["opened"] + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).dt.normalize()
        close = pd.to_numeric(frame["close"], errors="coerce")
        if dates.duplicated().any() or close.isna().any() or (close <= 0).any():
            raise ValueError(f"{path.name} has duplicate days or invalid closes")
        series[code] = pd.Series((1.0 / close if usd_base else close).to_numpy(), index=pd.DatetimeIndex(dates))
    wide = pd.DataFrame(series)
    first = pd.Timestamp(start, tz="UTC")
    if wide.index.min() > first:
        raise ForwardRefused("PRICES_TOO_SHORT", f"the D1 export starts on {wide.index.min().date()}, after "
                             f"{start}: export more bars")
    wide = wide.loc[first:]
    business_days = pd.bdate_range(wide.index.min(), wide.index.max(), tz="UTC")
    panel = _finalise(wide.reindex(business_days), tuple(currencies))
    if panel.index[0] > first + pd.Timedelta(days=7):
        raise ForwardRefused("PRICES_TOO_SHORT", f"some D1 export starts after {start}: export more bars")
    return PricePanel(panel, "mt5_d1_export", _digest([[str(d.date()), *map(float, row)]
                                                       for d, row in zip(panel.index, panel.to_numpy())]))


def read_inflation_supplement(path: str | Path, currencies: Iterable[str]) -> tuple[pd.DataFrame, str]:
    """Annual % CPI inflation by currency from a ``Country,Country Code,Year,CPI`` file (recent years)."""

    source = Path(path)
    raw = pd.read_csv(source, dtype=str)
    if list(raw.columns) != ["Country", "Country Code", "Year", "CPI"]:
        raise ValueError("unexpected inflation supplement columns")
    known = raw[raw["Country Code"].isin(WORLD_BANK_COUNTRIES)].copy()
    known["code"] = known["Country Code"].map(WORLD_BANK_COUNTRIES)
    known["year"] = pd.to_numeric(known["Year"], errors="coerce")
    known["value"] = pd.to_numeric(known["CPI"], errors="coerce")
    if known[["year", "value"]].isna().any().any() or known.duplicated(["year", "code"]).any():
        raise ValueError("the inflation supplement has missing or duplicate yearly values")
    wide = known.pivot(index="year", columns="code", values="value").sort_index()
    wide.index = wide.index.astype(int)
    wanted = list(dict.fromkeys(["USD", *currencies]))
    wide = wide.reindex(columns=wanted)
    wide.columns.name = None
    wide.index.name = None
    return wide, sha256(source.read_bytes()).hexdigest()


def assemble_inflation(base: pd.DataFrame, base_last_year: int, first_seen: Mapping[str, Mapping[str, float]],
                       supplement: pd.DataFrame | None) -> tuple[pd.DataFrame, dict[str, dict[str, float]], list[str]]:
    """Inflation table for the engine: the pinned base, then each later year as first seen.

    Returns the table, the years newly fixed by this run and a list of
    ignored differences (revisions of fixed years, base years in the
    supplement, partial years).
    """

    table = base.loc[base.index <= base_last_year].copy()
    columns = list(table.columns)
    notes: list[str] = []
    fixed = {int(year): dict(values) for year, values in first_seen.items()}
    added: dict[str, dict[str, float]] = {}
    later = sorted(set(fixed) | (set(int(y) for y in supplement.index if y > base_last_year)
                                 if supplement is not None else set()))
    for year in later:
        if year in fixed:
            values = fixed[year]
            if supplement is not None and year in supplement.index:
                for code in columns:
                    new = supplement.at[year, code]
                    if pd.notna(new) and abs(float(new) - float(values[code])) > 1e-9:
                        notes.append(f"{code} {year}: supplement {float(new):.4f} ignored, fixed at "
                                     f"{float(values[code]):.4f}")
        else:
            row = supplement.loc[year, columns] if supplement is not None else None
            if row is None or row.isna().any():
                notes.append(f"{year}: not every series has a value yet; the year is not used")
                break  # a later year cannot be used before an earlier one
            values = {code: float(row[code]) for code in columns}
            added[str(year)] = values
        if year != int(table.index.max()) + 1:
            raise ForwardRefused("INFLATION_GAP", f"inflation year {year} does not follow {int(table.index.max())}")
        table.loc[year] = [values[code] for code in columns]
    if supplement is not None:
        for year in supplement.index:
            if year <= base_last_year:
                notes.append(f"{year}: base year in the supplement ignored")
                break
    table.index = table.index.astype(int)
    return table, added, notes


def parse_world_bank_inflation(payload: Any) -> tuple[list[tuple[str, str, int, float]], str]:
    """Rows (country, ISO3, year, value) and ``lastupdated`` from a World Bank API v2 JSON response."""

    if not (isinstance(payload, list) and len(payload) == 2 and isinstance(payload[0], Mapping)
            and isinstance(payload[1], list)):
        raise ValueError("not a World Bank API v2 response")
    header = payload[0]
    if int(header.get("pages", 1)) != 1:
        raise ValueError("the World Bank response has more than one page")
    rows = []
    for item in payload[1]:
        indicator = (item.get("indicator") or {}).get("id")
        if indicator != WORLD_BANK_INDICATOR:
            raise ValueError(f"unexpected indicator {indicator!r}")
        iso3 = item.get("countryiso3code")
        if iso3 not in WORLD_BANK_COUNTRIES or item.get("value") is None:
            continue
        value = float(item["value"])
        if not math.isfinite(value):
            raise ValueError("non-finite inflation value")
        rows.append((str((item.get("country") or {}).get("value") or iso3), iso3, int(item["date"]), value))
    return sorted(rows, key=lambda row: (row[1], row[2])), str(header.get("lastupdated") or "")


def fetch_world_bank_inflation(output: str | Path, first_year: int, last_year: int,
                               opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """Download annual CPI inflation of the ten series; write a new CSV and a sidecar JSON (never overwrite)."""

    target = Path(output)
    sidecar = target.with_suffix(target.suffix + ".json")
    if target.exists() or sidecar.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    url = WORLD_BANK_URL.format(countries=";".join(sorted(WORLD_BANK_COUNTRIES)), first=int(first_year),
                                last=int(last_year))
    with opener(url, timeout=60) as response:
        body = response.read()
    rows, last_updated = parse_world_bank_inflation(json.loads(body.decode("utf-8")))
    if {row[1] for row in rows} != set(WORLD_BANK_COUNTRIES):
        missing = sorted(set(WORLD_BANK_COUNTRIES) - {row[1] for row in rows})
        raise ValueError(f"no value at all for: {', '.join(missing)}")
    lines = ["Country,Country Code,Year,CPI"] + [f"{name.replace(',', ' ')},{iso3},{year},{value!r}"
                                                  for name, iso3, year, value in rows]
    text = "\n".join(lines) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    meta = {"source": url, "indicator": WORLD_BANK_INDICATOR, "lastupdated": last_updated,
            "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha256": sha256(text.encode("utf-8")).hexdigest(), "rows": len(rows),
            "years": sorted({row[2] for row in rows})}
    with sidecar.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return meta


# --- broker swap ------------------------------------------------------------


def _swap_rates(snapshots: Sequence[Mapping[str, Any]], prices: pd.DataFrame, max_age_days: int,
                days: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Annual swap rate (fraction of notional) of a long and of a short in each currency vs USD, per day.

    The rate of day t comes from the latest snapshot captured before day t
    began (UTC) and no older than ``max_age_days``, converted at the previous
    close. NaN where no such snapshot holds captured terms for the pair.
    """

    from ...broker_swap_snapshot import annualised_swap_carry, verify_swap_snapshot

    verified = sorted((verify_swap_snapshot(item) for item in snapshots), key=lambda item: item["captured_at_utc"])
    long_rate = pd.DataFrame(np.nan, index=days, columns=prices.columns)
    short_rate = long_rate.copy()
    used: list[str] = []
    if not verified:
        return long_rate, short_rate, used
    stamps = pd.DatetimeIndex([pd.Timestamp(item["captured_at_utc"]) for item in verified]).tz_convert("UTC")
    previous = prices.shift(1)
    for row, day in enumerate(days):
        position = int(stamps.searchsorted(day, side="right")) - 1
        if position < 0 or (day - stamps[position]).days > max_age_days:
            continue
        snapshot = verified[position]
        if snapshot["payload_sha256"] not in used:
            used.append(snapshot["payload_sha256"])
        for code in prices.columns:
            symbol, usd_base = MT5_USD_PAIRS[code]
            record = snapshot["instruments"].get(symbol)
            usd_price = previous.at[day, code]
            if record is None or not np.isfinite(usd_price):
                continue
            try:
                carry = annualised_swap_carry(record, price=float(1.0 / usd_price if usd_base else usd_price))
            except Exception:  # an unconvertible record leaves the day uncovered
                continue
            pair_long = carry["long_annual_percent_of_notional"] / 100.0
            pair_short = carry["short_annual_percent_of_notional"] / 100.0
            # Long the currency is long XXXUSD or short USDXXX.
            long_rate.iat[row, prices.columns.get_loc(code)] = pair_short if usd_base else pair_long
            short_rate.iat[row, prices.columns.get_loc(code)] = pair_long if usd_base else pair_short
    return long_rate, short_rate, used


def broker_swap_returns(primary: pd.Series, positions: pd.DataFrame, prices: pd.DataFrame, costs: CostModel,
                        long_rate: pd.DataFrame, short_rate: pd.DataFrame) -> pd.Series:
    """Daily log returns with the assumed mark-up replaced by the broker's swap (NaN where uncovered)."""

    held = positions.shift(1).reindex(primary.index).fillna(0.0)
    stamps = pd.DatetimeIndex(prices.index)
    elapsed_all = pd.Series(np.r_[0.0, np.diff((stamps - stamps[0]) / pd.Timedelta(days=1))] / 365.0,
                            index=prices.index)
    elapsed = elapsed_all.reindex(primary.index)
    markup = held.abs().sum(axis=1) * costs.financing_bps_per_year / 10_000.0 * elapsed
    rate = long_rate.reindex(primary.index).where(held > 0, short_rate.reindex(primary.index)).where(held != 0, 0.0)
    covered = ~((held != 0) & rate.isna()).any(axis=1)
    swap = (held.abs() * rate.fillna(0.0)).sum(axis=1) * elapsed
    simple = np.expm1(primary) + markup + swap
    return pd.Series(np.log1p(simple), index=primary.index).where(covered)


# --- decision rule ----------------------------------------------------------


def _t_stat(values: pd.Series) -> float | None:
    clean = values.dropna().to_numpy(dtype=float)
    if clean.size < 3:
        return None
    try:
        return newey_west_t_stat(clean)
    except ValueError:
        return None


def _drawdown_breach(primary: pd.Series, limit: float) -> pd.Timestamp | None:
    equity = primary.cumsum()
    drawdown = 1.0 - np.exp(-(np.maximum.accumulate(np.r_[0.0, equity.to_numpy()])[1:] - equity.to_numpy()))
    breached = np.flatnonzero(drawdown >= limit)
    return primary.index[breached[0]] if breached.size else None


def rule_status(primary: pd.Series, swap_adjusted: pd.Series, forward_start: str, through_day: pd.Timestamp,
                rule: DecisionRule) -> dict[str, Any]:
    """Apply the predeclared rule to the forward returns, in date order."""

    start = pd.Timestamp(forward_start, tz="UTC")
    breach = _drawdown_breach(primary, rule.max_drawdown) if len(primary) else None
    looks = []
    for number, boundary in enumerate(rule.boundaries, start=1):
        look_day = start + pd.DateOffset(years=number)
        if look_day > through_day + pd.Timedelta(days=1):
            break
        if breach is not None and breach < look_day:
            return {"status": "ABANDONED_DRAWDOWN", "on": str(breach.date()), "looks": looks}
        window = primary.loc[:look_day - pd.Timedelta(days=1)]
        adjusted = swap_adjusted.loc[:look_day - pd.Timedelta(days=1)]
        t_value = _t_stat(window)
        coverage = float(adjusted.notna().mean()) if len(adjusted) else 0.0
        adjusted_total = float(adjusted.dropna().sum()) if adjusted.notna().any() else None
        swap_ok = coverage >= rule.min_swap_coverage and adjusted_total is not None and adjusted_total > 0
        look = {"look": number, "on": str(look_day.date()), "t": t_value, "boundary": boundary,
                "swap_coverage": coverage, "swap_adjusted_total_log_return": adjusted_total}
        looks.append(look)
        if t_value is not None and t_value >= boundary:
            if swap_ok:
                return {"status": "CONFIRMED", "on": look["on"], "looks": looks}
            look["confirmation_withheld"] = "broker swap coverage or total"
        if number >= rule.futility_from_look and (t_value is None or t_value <= rule.futility_t):
            return {"status": "ABANDONED_FUTILITY", "on": look["on"], "looks": looks}
    if breach is not None:
        return {"status": "ABANDONED_DRAWDOWN", "on": str(breach.date()), "looks": looks}
    if len(looks) == len(rule.boundaries):
        return {"status": "ENDED_WITHOUT_CONFIRMATION", "on": looks[-1]["on"], "looks": looks}
    next_look = start + pd.DateOffset(years=len(looks) + 1)
    return {"status": "ONGOING", "next_look": str(next_look.date()), "looks": looks}


# --- the run ----------------------------------------------------------------


def _stats(values: pd.Series) -> dict[str, Any] | None:
    clean = values.dropna()
    if len(clean) < 2:
        return None
    stats = performance(clean)
    stats["hac_t_stat"] = _t_stat(clean)
    return stats


def _decision_rows(prices: pd.DataFrame, config: PortfolioConfig, inflation: pd.DataFrame
                   ) -> tuple[list[int], pd.DataFrame]:
    gap = inflation_differentials(inflation, prices.index, tuple(prices.columns), config.inflation_years)
    target, _ = target_weights(prices, config, inflation_gap=gap)
    valid = target.notna().all(axis=1).to_numpy()
    if not valid.any():
        raise ForwardRefused("PRICES_TOO_SHORT", "no complete signal: the D1 history is too short")
    first = int(np.argmax(valid))
    return list(range(first, len(prices), config.rebalance_days)), target


def run_forward(plan: ForwardPlan, panel: PricePanel, inflation_base: pd.DataFrame, inflation_base_sha256: str,
                supplement: pd.DataFrame | None, swap_snapshots: Sequence[Mapping[str, Any]], ledger: TrialLedger,
                now_utc: datetime | None = None) -> dict[str, Any]:
    """Extend the forward record with every complete day since the last checkpoint."""

    plan.validate()
    plan_hash = plan.plan_hash()
    if plan.engine != forward_engine_sha256():
        raise ForwardRefused("ENGINE_CHANGED", "the engine code changed since the forward plan was frozen")
    if inflation_base_sha256 != plan.inflation_base_sha256:
        raise ForwardRefused("INFLATION_BASE_CHANGED", "the inflation base file differs from the pinned one")
    if tuple(panel.currencies) != tuple(plan.currencies) or panel.source != plan.price_source:
        raise ForwardRefused("PRICES_MISMATCH", "the price panel is not the plan's broker D1 panel")
    start = pd.Timestamp(plan.price_start, tz="UTC")
    if not start <= panel.prices.index[0] <= start + pd.Timedelta(days=7):
        raise ForwardRefused("PRICES_MISMATCH", "the price panel does not start at the plan's price_start")
    previous = [record for record in ledger.records() if record["kind"] == CHECKPOINT]
    if any(record["plan_hash"] != plan_hash for record in previous):
        raise ForwardRefused("LEDGER_MISMATCH", "the ledger holds checkpoints of another forward plan")
    first_seen: dict[str, dict[str, float]] = {}
    for record in previous:
        first_seen.update(record["payload"]["inflation_fixed"])
    inflation, added, notes = assemble_inflation(inflation_base, plan.inflation_base_last_year, first_seen,
                                                 supplement)
    prices = panel.prices
    result = backtest(prices, plan.config, plan.costs, plan.limits, inflation=inflation)
    rows, target = _decision_rows(prices, plan.config, inflation)
    forward_start = pd.Timestamp(plan.forward_start, tz="UTC")
    through = prices.index[-1]
    waiting = None
    incomplete = [day for day in result.incomplete_decisions if day >= forward_start - pd.Timedelta(days=45)]
    if incomplete:
        # Stop just before a rebalance whose inputs are missing: nothing after it is counted.
        waiting = incomplete[0]
        through = min(through, prices.index[prices.index.get_loc(waiting) - 1])
    primary = result.net_returns.loc[forward_start:through]
    long_rate, short_rate, snapshots_used = _swap_rates(swap_snapshots, prices, plan.swap_max_age_days,
                                                        primary.index)
    adjusted = broker_swap_returns(primary, result.positions, prices, plan.costs, long_rate, short_rate)
    decisions = []
    for row in rows:
        day = prices.index[row]
        if day < forward_start - pd.Timedelta(days=45) or day > through:
            continue
        lag = plan.config.execution_lag_days
        execution = prices.index[row + lag] if row + lag < len(prices) else None
        held = (result.positions.loc[execution].round(10).to_dict()
                if execution is not None and execution <= through else None)
        decisions.append({"decision_day": str(day.date()),
                          "execution_day": str(execution.date()) if execution is not None else None,
                          "directions": {code: float(value) for code, value in target.loc[day].items()},
                          "weights_after_execution": held})
    # The past must be recomputed exactly.
    if previous:
        last = previous[-1]["payload"]
        last_day = pd.Timestamp(last["through_day"], tz="UTC")
        if last_day > through:
            raise ForwardRefused("FORWARD_HISTORY_CHANGED", f"the data now end on {through.date()}, before the "
                                 f"recorded {last_day.date()} (missing bars or inflation)")
        if _series_digest(primary.loc[:last_day]) != last["returns_sha256"]:
            raise ForwardRefused("FORWARD_HISTORY_CHANGED", "recomputed forward returns differ from the record: "
                                 "the broker history or an input changed after the fact")
        sealed = {item["decision_day"]: item for record in previous for item in record["payload"]["decisions"]}
        for item in decisions:
            old = sealed.get(item["decision_day"])
            if old is not None and old["directions"] != item["directions"]:
                raise ForwardRefused("FORWARD_HISTORY_CHANGED", f"the decision of {item['decision_day']} changed")
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    status = rule_status(primary, adjusted, plan.forward_start, through, plan.rule)
    sealed_days = {item["decision_day"] for record in previous for item in record["payload"]["decisions"]}
    new_decisions = [{**item, "sealed_after_execution": bool(item["execution_day"] and
                                                             pd.Timestamp(item["execution_day"]).date() < now.date())}
                     for item in decisions if item["decision_day"] not in sealed_days]
    summary = {
        "forward_version": FORWARD_VERSION, "plan_hash": plan_hash, "book_plan_hash": plan.book_plan_hash,
        "run_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "environment": environment(),
        "forward_start": plan.forward_start, "through_day": str(through.date()),
        "waiting_for_inputs_on": str(waiting.date()) if waiting is not None else None,
        "forward_days": int(len(primary)), "returns_sha256": _series_digest(primary),
        "prices_sha256": panel.source_sha256,
        "inflation": {"base_sha256": inflation_base_sha256, "last_year_used": int(inflation.index.max()),
                      "notes": notes},
        "inflation_fixed": added,
        "swap_snapshots_used": snapshots_used,
        "primary": _stats(primary),
        "broker_swap": {"coverage": float(adjusted.notna().mean()) if len(adjusted) else 0.0,
                        "stats": _stats(adjusted)},
        "rule": status,
        "decisions": new_decisions,
        "execution_authorized": False,
    }
    advanced = not previous or pd.Timestamp(previous[-1]["payload"]["through_day"], tz="UTC") < through \
        or bool(added) or bool(new_decisions)
    if advanced and len(primary) > 0:
        ledger.append(CHECKPOINT, plan_hash, summary)
        summary["appended"] = True
    else:
        summary["appended"] = False
    return summary

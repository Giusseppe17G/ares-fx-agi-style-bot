"""Daily FX portfolio simulation inside the bot's risk invariants (research only).

Timing: target weights of decision day d use prices up to and including d.
They are executed at the close of day d + ``execution_lag_days`` and held,
drifting with prices, until the next rebalance (every ``rebalance_days``
trading days). Every position carries a catastrophe stop-loss and a
take-profit fixed at execution (AGENTS.md: never a position without SL/TP),
checked on daily closes (a close beyond the stop exits at that close, which
is worse than the stop). A stopped position stays flat until the next
rebalance.

Risk invariants applied at every rebalance (AGENTS.md / RiskEngine limits):
risk to the stop of at most ``risk_per_position`` of equity per position, at
most ``max_open_risk`` in total, at most ``max_net_usd_risk`` net on the USD
leg every position shares, at most ``max_positions`` positions, and no new or
larger position on a day whose loss reached ``daily_loss_halt`` or while open
positions are down ``floating_loss_halt`` of equity (re-entry only at the next
scheduled rebalance without a halt). A day whose target is incomplete is
traded flat.

Signals (all in [-1, 1] per currency, long = long the currency vs USD):

- ``tsmom``: mean over lookbacks of sign(log P_d - log P_{d-L})
  (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen 2017);
- ``tscarry``: sign of the currency's short rate minus the USD rate, using
  the monthly average of the previous month only (needs ``rates``; a month
  without a rate ends the simulation there instead of carrying a stale rate);
- ``blend``: equal-weight mean of ``tsmom`` and ``tscarry``;
- ``xsmom``: cross-sectional momentum, diagnostic only;
- ``xsvalue``: cross-sectional real-exchange-rate value (Asness, Moskowitz &
  Pedersen 2013). The score of a currency is minus its real appreciation vs
  USD: the log price on d minus its mean over ``average_rows`` rows ending
  ``lookbacks[0] - average_rows + 1`` rows earlier, plus its cumulative log
  inflation minus the USD one over the last ``inflation_years`` published
  years (``inflation_differentials``). USD is ranked with a score of zero; the
  ``xs_top`` highest scores are long and the ``xs_top`` lowest are short (a
  USD slot leaves its leg to the others), ties going to the ISO code first in
  alphabetical order. Needs ``inflation``;
- ``random``: random signs (control). Each sign flips at a rebalance with
  probability ``random_flip_probability`` (0.5: independent draws), so the
  control can match the turnover of the signal it is compared with.

``shift_days`` circularly shifts the signal in time (a turnover-matched
control: same persistence and cross-section, no alignment with returns).
``permute`` gives each currency's ``xsvalue`` score to another currency
(USD included), by a fixed permutation drawn from ``seed`` (a control: the
same ranking dynamics and turnover on the wrong currencies).

With ``sizing="vol_target"`` positions are scaled by inverse ex-ante
volatility and the book to ``target_annual_vol`` before the invariants cut
them down. With ``sizing="equal_risk"`` every position takes exactly
``risk_per_position`` of equity to its stop. Returns are net of
one-way trading costs, a financing mark-up on gross exposure and, when
``rates`` are given, the interest differential; both accrue by calendar days
elapsed (a Monday carries the weekend). Because positions drift, every live
position is resized at each rebalance and its entry, stop and take-profit are
re-anchored there. Nothing here builds, checks or sends an order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Mapping

import numpy as np
import pandas as pd

TRADING_DAYS = 252
SIGNALS = {"tsmom", "tscarry", "blend", "xsmom", "xsvalue", "random"}
SIZINGS = {"vol_target", "equal_risk"}
INFLATION_PUBLICATION_MONTH = 7  # annual inflation of year Y is used from 1 July of Y + 1


@dataclass(frozen=True)
class PortfolioConfig:
    signal: str = "tsmom"
    lookbacks: tuple[int, ...] = (252,)
    xs_top: int = 3
    vol_span: int = 60
    target_annual_vol: float = 0.10
    max_gross_leverage: float = 3.0
    rebalance_days: int = 21
    execution_lag_days: int = 1
    flip: bool = False
    seed: int = 0
    shift_days: int = 0
    random_flip_probability: float = 0.5
    sizing: str = "vol_target"
    average_rows: int = 261  # xsvalue: rows averaged into the past price level
    inflation_years: int = 5  # xsvalue: published years of inflation differential
    permute: bool = False  # control: xsvalue scores moved to other currencies

    def validate(self) -> None:
        if self.signal not in SIGNALS:
            raise ValueError(f"signal must be one of {sorted(SIGNALS)}")
        if self.sizing not in SIZINGS:
            raise ValueError(f"sizing must be one of {sorted(SIZINGS)}")
        if self.signal == "xsvalue" and not (1 <= self.average_rows < self.lookbacks[0] and self.inflation_years >= 1):
            raise ValueError("xsvalue needs 1 <= average_rows < lookbacks[0] and inflation_years >= 1")
        if self.permute and self.signal != "xsvalue":
            raise ValueError("permute is a control of the xsvalue signal only")
        if not self.lookbacks or any(int(value) < 2 for value in self.lookbacks):
            raise ValueError("lookbacks must be integers >= 2")
        if self.vol_span < 5 or self.rebalance_days < 1 or self.execution_lag_days < 0 or self.shift_days < 0:
            raise ValueError("vol_span >= 5, rebalance_days >= 1, execution_lag_days >= 0 and shift_days >= 0 "
                             "are required")
        if not 0 < self.target_annual_vol <= 0.5 or not 0 < self.max_gross_leverage <= 10:
            raise ValueError("target_annual_vol must be in (0, 0.5] and max_gross_leverage in (0, 10]")
        if not 0 < self.random_flip_probability <= 0.5:
            raise ValueError("random_flip_probability must be in (0, 0.5]")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["lookbacks"] = list(self.lookbacks)
        return payload


@dataclass(frozen=True)
class RiskLimits:
    """The bot's invariants, applied at every rebalance (None disables a limit)."""

    risk_per_position: float | None = 0.005
    max_open_risk: float | None = 0.05
    max_net_usd_risk: float | None = 0.03
    max_positions: int | None = 10
    stop_sigmas: float = 2.5  # catastrophe SL distance in rebalance-period sigmas
    take_profit_multiple: float = 3.0  # TP distance as a multiple of the SL distance
    daily_loss_halt: float | None = 0.03
    floating_loss_halt: float | None = 0.05

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


UNCONSTRAINED = RiskLimits(None, None, None, None, 1e9, 1.0, None, None)


@dataclass(frozen=True)
class CostModel:
    """One-way trading cost in basis points of notional, per currency."""

    one_way_bps: Mapping[str, float]
    financing_bps_per_year: float = 0.0  # broker swap mark-up charged on gross exposure

    def for_currencies(self, currencies: tuple[str, ...]) -> np.ndarray:
        missing = [code for code in currencies if code not in self.one_way_bps]
        if missing:
            raise ValueError(f"no cost for: {', '.join(missing)}")
        return np.array([float(self.one_way_bps[code]) for code in currencies]) / 10_000.0

    def scaled(self, factor: float) -> "CostModel":
        return CostModel({code: value * factor for code, value in self.one_way_bps.items()},
                         self.financing_bps_per_year * factor)


@dataclass(frozen=True)
class BacktestResult:
    net_returns: pd.Series  # daily log returns of equity
    gross_returns: pd.Series  # before trading costs and financing mark-up
    positions: pd.DataFrame  # weights held over each day (fraction of equity)
    costs: pd.Series
    turnover: pd.Series
    contributions: pd.DataFrame  # gross return of each currency (fraction of equity)
    stops: int
    take_profits: int
    blocked_rebalances: int
    config: PortfolioConfig = field(repr=False)


def tsmom_signal(log_prices: pd.DataFrame, lookbacks: tuple[int, ...]) -> pd.DataFrame:
    signs = [np.sign(log_prices - log_prices.shift(int(lookback))) for lookback in lookbacks]
    return sum(signs) / len(signs)


def xsmom_signal(log_prices: pd.DataFrame, lookback: int, top: int) -> pd.DataFrame:
    if top < 1 or 2 * top > log_prices.shape[1]:
        raise ValueError("xs_top must leave distinct long and short groups")
    past = log_prices - log_prices.shift(int(lookback))
    ranks = past.rank(axis=1, method="first")
    count = past.notna().sum(axis=1)
    signal = ranks.gt(count - top, axis=0).astype(float) - ranks.le(top).astype(float)
    return signal.where(past.notna().all(axis=1), np.nan, axis=0)


def rate_differentials(rates: pd.DataFrame, index: pd.DatetimeIndex, currencies: tuple[str, ...]) -> pd.DataFrame:
    """Annual rate of each currency minus USD known on each day, as a fraction.

    ``rates`` holds monthly averages in percent indexed by month (a
    ``PeriodIndex`` or month-start timestamps). An average is only known once
    its month ends, so every day uses the previous month's value and nothing
    older: a missing month gives NaN rather than a stale rate.
    """

    missing = [code for code in (*currencies, "USD") if code not in rates.columns]
    if missing:
        raise ValueError(f"no rates for: {', '.join(missing)}")
    monthly = rates.copy()
    if not isinstance(monthly.index, pd.PeriodIndex):
        stamps = pd.DatetimeIndex(monthly.index)
        monthly.index = (stamps.tz_convert(None) if stamps.tz is not None else stamps).to_period("M")
    if monthly.index.duplicated().any():
        raise ValueError("duplicate rate months")
    days = pd.DatetimeIndex(index)
    previous = (days.tz_convert(None) if days.tz is not None else days).to_period("M") - 1
    daily = monthly.reindex(previous)
    daily.index = index
    return daily[list(currencies)].sub(daily["USD"], axis=0) / 100.0


def inflation_differentials(inflation: pd.DataFrame, index: pd.DatetimeIndex, currencies: tuple[str, ...],
                            years: int) -> pd.DataFrame:
    """Cumulative log inflation of each currency minus USD over the last ``years`` published years.

    ``inflation`` holds annual % inflation indexed by integer year. Year Y is
    only used from 1 July of Y + 1 (``INFLATION_PUBLICATION_MONTH``), so a day
    before July uses the years up to Y - 2. A missing year gives NaN rather
    than a shorter sum.
    """

    missing = [code for code in (*currencies, "USD") if code not in inflation.columns]
    if missing:
        raise ValueError(f"no inflation for: {', '.join(missing)}")
    if years < 1:
        raise ValueError("years must be >= 1")
    table = inflation.copy()
    table.index = table.index.astype(int)
    table = table.reindex(range(int(table.index.min()), int(table.index.max()) + 1))
    logs = np.log1p(table[[*currencies, "USD"]].astype(float) / 100.0)
    gap = logs[list(currencies)].sub(logs["USD"], axis=0)
    cumulative = gap.rolling(years, min_periods=years).sum()
    days = pd.DatetimeIndex(index)
    days = days.tz_convert(None) if days.tz is not None else days
    published = days.year - 1 - (days.month < INFLATION_PUBLICATION_MONTH).astype(int)
    daily = cumulative.reindex(published)
    daily.index = index
    return daily


def currency_permutation(count: int, seed: int) -> tuple[int, ...]:
    """A permutation of ``range(count)`` other than the identity, fixed by ``seed``."""

    if count < 2:
        raise ValueError("a permutation needs 2+ currencies")
    rng = np.random.default_rng(seed)
    while True:
        order = rng.permutation(count)
        if not np.array_equal(order, np.arange(count)):
            return tuple(int(value) for value in order)


def xsvalue_signal(log_prices: pd.DataFrame, inflation_gap: pd.DataFrame, lookback: int, average_rows: int,
                   top: int, permutation: tuple[int, ...] | None = None) -> pd.DataFrame:
    """Long the ``top`` cheapest and short the ``top`` dearest of the currencies and USD in real terms."""

    if not 1 <= average_rows < lookback:
        raise ValueError("need 1 <= average_rows < lookback")
    past = log_prices.shift(lookback - average_rows + 1).rolling(average_rows, min_periods=average_rows).mean()
    scores = -((log_prices - past) + inflation_gap[list(log_prices.columns)])
    scores["USD"] = 0.0
    # Alphabetical columns: a tie goes to the ISO code that comes first.
    scores = scores[sorted(scores.columns)]
    if top < 1 or 2 * top > scores.shape[1]:
        raise ValueError("xs_top must leave distinct long and short groups")
    if permutation is not None:
        if sorted(permutation) != list(range(scores.shape[1])):
            raise ValueError("permutation must reorder every currency and USD")
        # The score of column j goes to column permutation[j].
        moved = np.empty_like(scores.to_numpy())
        moved[:, list(permutation)] = scores.to_numpy()
        scores = pd.DataFrame(moved, index=scores.index, columns=scores.columns)
    complete = scores.notna().all(axis=1)
    ranks = scores.rank(axis=1, method="first", ascending=False)
    signal = ranks.le(top).astype(float) - ranks.gt(scores.shape[1] - top).astype(float)
    return signal.where(complete, np.nan, axis=0)[list(log_prices.columns)]


def _signal(log_prices: pd.DataFrame, config: PortfolioConfig, carry: pd.DataFrame | None,
            inflation_gap: pd.DataFrame | None = None) -> pd.DataFrame:
    if config.signal in {"tscarry", "blend"} and carry is None:
        raise ValueError(f"signal {config.signal} needs rates")
    if config.signal == "xsvalue" and inflation_gap is None:
        raise ValueError("signal xsvalue needs inflation")
    if config.signal == "tsmom":
        signal = tsmom_signal(log_prices, config.lookbacks)
    elif config.signal == "tscarry":
        signal = np.sign(carry)
    elif config.signal == "blend":
        signal = (tsmom_signal(log_prices, config.lookbacks) + np.sign(carry)) / 2.0
    elif config.signal == "xsmom":
        signal = xsmom_signal(log_prices, config.lookbacks[0], config.xs_top)
    elif config.signal == "xsvalue":
        permutation = currency_permutation(log_prices.shape[1] + 1, config.seed) if config.permute else None
        signal = xsvalue_signal(log_prices, inflation_gap, config.lookbacks[0], config.average_rows,
                                config.xs_top, permutation)
    else:
        signal = _random_signs(log_prices, config)
    if config.shift_days:
        signal = _shifted(signal, config.shift_days)
    return -signal if config.flip else signal


def _random_signs(log_prices: pd.DataFrame, config: PortfolioConfig) -> pd.DataFrame:
    # A daily sign chain whose flip probability over one rebalance period is
    # random_flip_probability: (1 - (1 - 2q)^R) / 2 = p.
    rng = np.random.default_rng(config.seed)
    p = config.random_flip_probability
    daily_flip = 0.5 if p >= 0.5 else (1.0 - (1.0 - 2.0 * p) ** (1.0 / config.rebalance_days)) / 2.0
    start = rng.choice([-1.0, 1.0], size=(1, log_prices.shape[1]))
    flips = np.where(rng.random(log_prices.shape) < daily_flip, -1.0, 1.0)
    flips[0] = 1.0
    signs = start * np.cumprod(flips, axis=0)
    return pd.DataFrame(signs, index=log_prices.index, columns=log_prices.columns).where(
        log_prices.shift(max(config.lookbacks)).notna())


def signal_flip_rate(prices: pd.DataFrame, config: PortfolioConfig, rates: pd.DataFrame | None = None,
                     inflation: pd.DataFrame | None = None) -> float:
    """Share of currency signs that change from one rebalance to the next, in [0.01, 0.5].

    Used to give a random-sign control the persistence (turnover) of the signal it is
    compared with.
    """

    config.validate()
    carry = rate_differentials(rates, prices.index, tuple(prices.columns)) if rates is not None else None
    gap = (inflation_differentials(inflation, prices.index, tuple(prices.columns), config.inflation_years)
           if inflation is not None else None)
    signs = np.sign(_signal(np.log(prices), config, carry, gap))
    complete = signs.notna().all(axis=1).to_numpy()
    if not complete.any():
        raise ValueError("price history is too short for the signal")
    sampled = signs.to_numpy()[complete][::config.rebalance_days]
    if len(sampled) < 2:
        raise ValueError("price history is too short to measure the signal's persistence")
    # A move between +-1 and 0 is half a flip, so blended signals are not overcounted.
    changes = float(np.mean(np.abs(sampled[1:] - sampled[:-1]))) / 2.0
    return float(min(0.5, max(0.01, changes)))


def _shifted(signal: pd.DataFrame, shift_days: int) -> pd.DataFrame:
    """Circular shift of the complete rows of ``signal`` by ``shift_days`` rows."""

    complete = signal.notna().all(axis=1).to_numpy()
    rows = np.flatnonzero(complete)
    if rows.size == 0 or shift_days >= rows.size:
        raise ValueError("shift_days must be shorter than the signal history")
    shifted = signal.copy()
    shifted.iloc[rows] = np.roll(signal.to_numpy()[rows], shift_days, axis=0)
    return shifted


def target_weights(prices: pd.DataFrame, config: PortfolioConfig, carry: pd.DataFrame | None = None,
                   inflation_gap: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Unconstrained target weights and annual ex-ante volatility, from data up to each day.

    With ``equal_risk`` sizing the target is only the direction of each
    position; ``backtest`` sizes it to the risk cap at the rebalance.
    """

    log_prices = np.log(prices)
    returns = log_prices.diff()
    ex_ante_vol = returns.ewm(span=config.vol_span, min_periods=config.vol_span).std() * np.sqrt(TRADING_DAYS)
    signal = _signal(log_prices, config, carry, inflation_gap)
    if config.sizing == "equal_risk":
        target = signal.where(ex_ante_vol.notna())
        return target.where(target.notna().all(axis=1)), ex_ante_vol
    raw = (signal / ex_ante_vol).replace([np.inf, -np.inf], np.nan)
    unscaled_returns = (raw.shift(1) * returns).sum(axis=1, min_count=1)
    book_vol = unscaled_returns.ewm(span=config.vol_span, min_periods=config.vol_span).std() * np.sqrt(TRADING_DAYS)
    target = raw.mul(config.target_annual_vol / book_vol.where(book_vol > 0), axis=0)
    gross = target.abs().sum(axis=1)
    target = target.mul(np.minimum(1.0, config.max_gross_leverage / gross.where(gross > 0)), axis=0)
    return target.where(target.notna().all(axis=1)), ex_ante_vol


def _apply_limits(weights: np.ndarray, stop_distance: np.ndarray, limits: RiskLimits) -> np.ndarray:
    capped = weights.copy()
    if limits.risk_per_position is not None:
        cap = limits.risk_per_position / stop_distance
        capped = np.clip(capped, -cap, cap)
    if limits.max_positions is not None and np.count_nonzero(capped) > limits.max_positions:
        keep = np.argsort(-np.abs(capped))[:limits.max_positions]
        trimmed = np.zeros_like(capped)
        trimmed[keep] = capped[keep]
        capped = trimmed
    if limits.max_open_risk is not None:
        open_risk = float(np.sum(np.abs(capped) * stop_distance))
        if open_risk > limits.max_open_risk:
            capped = capped * (limits.max_open_risk / open_risk)
    if limits.max_net_usd_risk is not None:
        # Every position is against USD: their signed risks add up on the USD leg.
        usd_risk = abs(float(np.sum(capped * stop_distance)))
        if usd_risk > limits.max_net_usd_risk:
            capped = capped * (limits.max_net_usd_risk / usd_risk)
    return capped


def _open_pnl(entry_weight: np.ndarray, entry: np.ndarray, price: np.ndarray, entry_equity: np.ndarray,
              equity: float) -> float:
    """Unrealised P&L of the open positions as a fraction of current equity.

    A position opened with signed weight w on equity E0 holds w * E0 / entry
    units, so its open P&L is w * E0 * (price / entry - 1) whatever its weight
    has drifted to since.
    """

    if equity <= 0.0:
        return -math.inf
    live = (entry_weight != 0) & np.isfinite(entry)
    if not live.any():
        return 0.0
    pnl = entry_weight[live] * (price[live] / entry[live] - 1.0) * entry_equity[live]
    return float(np.sum(pnl)) / equity


def backtest(prices: pd.DataFrame, config: PortfolioConfig, costs: CostModel,
             limits: RiskLimits = RiskLimits(), rates: pd.DataFrame | None = None,
             inflation: pd.DataFrame | None = None) -> BacktestResult:
    """Simulate the book day by day over ``prices`` (USD price per currency)."""

    config.validate()
    if prices.shape[1] < 2 or prices.isna().any().any() or (prices <= 0).any().any():
        raise ValueError("prices must be a complete, positive panel with 2+ currencies")
    if config.sizing == "equal_risk" and limits.risk_per_position is None:
        raise ValueError("equal_risk sizing needs risk_per_position")
    if config.signal == "xsvalue" and inflation is None:
        raise ValueError("signal xsvalue needs inflation")
    currencies = tuple(prices.columns)
    carry = None
    if rates is not None:
        carry = rate_differentials(rates, prices.index, currencies)
        known = carry.notna().all(axis=1).to_numpy()
        if not known.any():
            raise ValueError("no day has a rate for every currency")
        begin, end = int(np.argmax(known)), len(known) - int(np.argmax(known[::-1]))
        if not known[begin:end].all():
            raise ValueError("rates have a missing month inside their history")
        # Fail closed at the end of the rate history: never carry a stale rate.
        prices, carry = prices.iloc[:end], carry.iloc[:end]
    gap = (inflation_differentials(inflation, prices.index, currencies, config.inflation_years)
           if config.signal == "xsvalue" else None)
    target, ex_ante_vol = target_weights(prices, config, carry, gap)
    valid = target.notna().all(axis=1).to_numpy().copy()
    if carry is not None:
        valid &= carry.notna().all(axis=1).to_numpy()
    if not valid.any():
        raise ValueError("price history is too short for the lookbacks and volatility span")
    first = int(np.argmax(valid))
    price = prices.to_numpy(dtype=float)
    targets = target.to_numpy(dtype=float)
    vols = ex_ante_vol.to_numpy(dtype=float)
    # Carry and the financing mark-up accrue by calendar days since the previous row.
    stamps = pd.DatetimeIndex(prices.index)
    elapsed = np.r_[0.0, np.diff(((stamps - stamps[0]) / pd.Timedelta(days=1)).to_numpy(dtype=float))] / 365.0
    accrual = carry.to_numpy(dtype=float) * elapsed[:, None] if carry is not None else np.zeros_like(price)
    one_way = costs.for_currencies(currencies)
    financing = costs.financing_bps_per_year / 10_000.0
    days, count = price.shape
    weights = np.zeros(count)
    entry = np.full(count, np.nan)
    entry_weight = np.zeros(count)  # signed weight when the position was (re)opened
    entry_equity = np.ones(count)  # equity index at that moment
    equity = 1.0
    stop = np.zeros(count)
    held = np.zeros((days, count))
    contrib = np.zeros((days, count))
    gross_out, net_out, cost_out, turn_out = (np.zeros(days) for _ in range(4))
    stops = take_profits = blocked = 0
    start = first + config.execution_lag_days
    for t in range(start, days):
        # 1) Return of the day on yesterday's book.
        moved = price[t] / price[t - 1] - 1.0
        contrib[t] = weights * (moved + np.nan_to_num(accrual[t]))
        gross = float(np.sum(contrib[t]))
        day_cost = float(np.sum(np.abs(weights))) * financing * elapsed[t]
        weights = weights * (1.0 + moved) / (1.0 + gross) if (1.0 + gross) > 0 else np.zeros(count)
        floating = _open_pnl(entry_weight, entry, price[t], entry_equity, equity * (1.0 + gross - day_cost))
        # 2) Protective exits on the close.
        live = weights != 0
        if live.any():
            with np.errstate(invalid="ignore"):
                change = price[t] / entry - 1.0
            adverse = np.where(weights > 0, -change, change)
            hit_stop = live & (adverse >= stop)
            hit_tp = live & (adverse <= -stop * limits.take_profit_multiple) & ~hit_stop
            exits = hit_stop | hit_tp
            if exits.any():
                day_cost += float(np.sum(np.abs(weights[exits]) * one_way[exits]))
                turn_out[t] += float(np.sum(np.abs(weights[exits])))
                stops += int(hit_stop.sum())
                take_profits += int(hit_tp.sum())
                weights[exits] = 0.0
                entry[exits] = np.nan
                entry_weight[exits] = 0.0
        # 3) Rebalance on schedule, inside the invariants.
        decision = t - config.execution_lag_days
        if (decision - first) % config.rebalance_days == 0 and decision >= first:
            stop_distance = np.maximum(limits.stop_sigmas * vols[decision] *
                                       math.sqrt(config.rebalance_days / TRADING_DAYS), 1e-6)
            wanted = targets[decision]
            if not (np.isfinite(wanted).all() and np.isfinite(stop_distance).all()):
                # Incomplete inputs: fail closed to a flat book.
                wanted, stop_distance = np.zeros(count), np.full(count, 1e-6)
            elif config.sizing == "equal_risk":
                wanted = wanted * (limits.risk_per_position / stop_distance)
                gross_wanted = float(np.sum(np.abs(wanted)))
                if gross_wanted > config.max_gross_leverage:
                    wanted = wanted * (config.max_gross_leverage / gross_wanted)
            new = _apply_limits(wanted, stop_distance, limits)
            # The day's loss counts its costs so far (financing and protective exits).
            halted = ((limits.daily_loss_halt is not None and gross - day_cost <= -limits.daily_loss_halt)
                      or (limits.floating_loss_halt is not None and floating <= -limits.floating_loss_halt))
            if halted:
                # Only reductions: no new position, no increase, no flip.
                same_side = np.sign(new) == np.sign(weights)
                new = np.where(same_side & (np.abs(new) < np.abs(weights)), new, np.where(same_side, weights, 0.0))
                blocked += 1
            delta = new - weights
            if np.any(delta != 0):
                day_cost += float(np.sum(np.abs(delta) * one_way))
                turn_out[t] += float(np.sum(np.abs(delta)))
                reset = (new != 0) & ((np.sign(new) != np.sign(weights)) | (np.abs(delta) > 0))
                entry = np.where(reset, price[t], entry)
                stop = np.where(reset, stop_distance, stop)
                entry = np.where(new == 0, np.nan, entry)
                entry_weight = np.where(new == 0, 0.0, np.where(reset, new, entry_weight))
                entry_equity = np.where(reset, equity * (1.0 + gross - day_cost), entry_equity)
                weights = new
        held[t] = weights
        gross_out[t] = gross
        cost_out[t] = day_cost
        net_out[t] = gross - day_cost
        equity *= 1.0 + net_out[t]
    index = prices.index[start:]
    sl = slice(start, days)
    net = pd.Series(np.log1p(net_out[sl]), index=index)
    return BacktestResult(
        net_returns=net,
        gross_returns=pd.Series(np.log1p(gross_out[sl]), index=index),
        positions=pd.DataFrame(held[sl], index=index, columns=list(currencies)),
        costs=pd.Series(cost_out[sl], index=index),
        turnover=pd.Series(turn_out[sl], index=index),
        contributions=pd.DataFrame(contrib[sl], index=index, columns=list(currencies)),
        stops=stops, take_profits=take_profits, blocked_rebalances=blocked, config=config,
    )


def performance(daily_returns: pd.Series) -> dict[str, float]:
    """Annualised summary of daily log returns (rows per year observed from the dates)."""

    values = daily_returns.to_numpy(dtype=float)
    if values.size < 2:
        raise ValueError("need at least two daily returns")
    mean, std = float(np.mean(values)), float(np.std(values, ddof=1))
    equity = np.cumsum(values)
    drawdown = float(np.max(np.maximum.accumulate(np.r_[0.0, equity])[1:] - equity))
    span_years = (daily_returns.index[-1] - daily_returns.index[0]).days / 365.25
    per_year = (values.size - 1) / span_years if span_years > 0 else float(TRADING_DAYS)
    annual = mean * per_year
    yearly = daily_returns.groupby(daily_returns.index.year).sum()
    max_dd = 1.0 - float(np.exp(-drawdown))
    return {
        "days": int(values.size),
        "years": span_years,
        "periods_per_year": per_year,
        "annual_return": annual,
        "annual_vol": std * np.sqrt(per_year),
        "sharpe": annual / (std * np.sqrt(per_year)) if std > 0 else 0.0,
        "max_drawdown": max_dd,
        "calmar": annual / max_dd if max_dd > 0 else float("inf"),
        "positive_years_share": float((yearly > 0).mean()) if len(yearly) else 0.0,
        "total_return": float(np.expm1(equity[-1])),
    }

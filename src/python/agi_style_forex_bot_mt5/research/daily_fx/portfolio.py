"""Volatility-targeted daily FX portfolio backtest (research only).

Timing: target weights at date t use prices up to and including t. With
``execution_lag_days = k`` the position held over the return of date t+1+k is
the target of date t, so ``k = 0`` trades at the signal close and ``k = 1``
one day later. Costs are charged on the day a position changes; financing is
charged daily on gross exposure. Signals are rebalanced every
``rebalance_days`` trading days and held in between.

Signals (all in [-1, 1] per currency):

- time-series momentum: mean over lookbacks of sign(log P_t - log P_{t-L})
  (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen 2017);
- cross-sectional momentum: +1 for the ``top`` currencies with the highest
  ``lookback`` return, -1 for the lowest (Menkhoff, Sarno, Schmeling &
  Schrimpf 2012).

Positions are scaled by inverse ex-ante volatility, then the portfolio is
scaled to ``target_annual_vol`` with ex-ante (lagged) volatility estimates and
capped at ``max_gross_leverage``. Nothing here builds or sends an order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class PortfolioConfig:
    signal: str = "tsmom"  # "tsmom", "xsmom" or "random" (control)
    lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    xs_top: int = 3
    vol_span: int = 60
    target_annual_vol: float = 0.10
    max_gross_leverage: float = 3.0
    rebalance_days: int = 5
    execution_lag_days: int = 1
    flip: bool = False
    seed: int = 0

    def validate(self) -> None:
        if self.signal not in {"tsmom", "xsmom", "random"}:
            raise ValueError("signal must be tsmom, xsmom or random")
        if not self.lookbacks or any(int(value) < 2 for value in self.lookbacks):
            raise ValueError("lookbacks must be integers >= 2")
        if self.vol_span < 5 or self.rebalance_days < 1 or self.execution_lag_days < 0:
            raise ValueError("vol_span >= 5, rebalance_days >= 1 and execution_lag_days >= 0 are required")
        if not 0 < self.target_annual_vol <= 0.5 or not 0 < self.max_gross_leverage <= 10:
            raise ValueError("target_annual_vol must be in (0, 0.5] and max_gross_leverage in (0, 10]")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["lookbacks"] = list(self.lookbacks)
        return payload


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
    net_returns: pd.Series
    gross_returns: pd.Series
    positions: pd.DataFrame
    costs: pd.Series
    turnover: pd.Series
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
    longs = ranks.gt(count - top, axis=0)
    shorts = ranks.le(top)
    signal = longs.astype(float) - shorts.astype(float)
    return signal.where(past.notna().all(axis=1), np.nan, axis=0) if past.shape[1] else signal


def random_signal(index: pd.Index, columns: pd.Index, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.choice([-1.0, 1.0], size=(len(index), len(columns))), index=index, columns=columns)


def _signal(log_prices: pd.DataFrame, config: PortfolioConfig) -> pd.DataFrame:
    if config.signal == "tsmom":
        signal = tsmom_signal(log_prices, config.lookbacks)
    elif config.signal == "xsmom":
        signal = xsmom_signal(log_prices, config.lookbacks[0], config.xs_top)
    else:
        signal = random_signal(log_prices.index, log_prices.columns, config.seed)
        signal = signal.where(log_prices.shift(max(config.lookbacks)).notna())
    return -signal if config.flip else signal


def backtest(prices: pd.DataFrame, config: PortfolioConfig, costs: CostModel) -> BacktestResult:
    """Run the portfolio over ``prices`` (USD price per currency, business days)."""

    config.validate()
    if prices.shape[1] < 2 or prices.isna().any().any() or (prices <= 0).any().any():
        raise ValueError("prices must be a complete, positive panel with 2+ currencies")
    log_prices = np.log(prices)
    returns = log_prices.diff()
    ex_ante_vol = returns.ewm(span=config.vol_span, min_periods=config.vol_span).std() * np.sqrt(TRADING_DAYS)
    raw = (_signal(log_prices, config) / ex_ante_vol).replace([np.inf, -np.inf], np.nan)
    # Portfolio-level ex-ante volatility of the unscaled book, from past returns only.
    unscaled_returns = (raw.shift(1) * returns).sum(axis=1, min_count=1)
    book_vol = unscaled_returns.ewm(span=config.vol_span, min_periods=config.vol_span).std() * np.sqrt(TRADING_DAYS)
    target = raw.mul(config.target_annual_vol / book_vol, axis=0)
    gross = target.abs().sum(axis=1)
    target = target.mul(np.minimum(1.0, config.max_gross_leverage / gross.where(gross > 0)), axis=0)
    target = target.where(target.notna().all(axis=1))
    # Hold between rebalances, counted from the first complete target.
    valid = target.notna().all(axis=1).to_numpy()
    if not valid.any():
        raise ValueError("price history is too short for the lookbacks and volatility span")
    first = int(np.argmax(valid))
    schedule = np.zeros(len(target), dtype=bool)
    schedule[first::config.rebalance_days] = True
    held_target = target.where(pd.Series(schedule, index=target.index), np.nan).ffill()
    positions = held_target.shift(1 + config.execution_lag_days).fillna(0.0)
    gross_returns = (positions * returns.fillna(0.0)).sum(axis=1)
    turnover = positions.diff().abs().fillna(positions.abs())
    one_way = costs.for_currencies(tuple(prices.columns))
    trading_costs = (turnover * one_way).sum(axis=1)
    financing = positions.abs().sum(axis=1) * costs.financing_bps_per_year / 10_000.0 / TRADING_DAYS
    total_costs = trading_costs + financing
    start = first + 1 + config.execution_lag_days
    return BacktestResult(
        net_returns=(gross_returns - total_costs).iloc[start:],
        gross_returns=gross_returns.iloc[start:],
        positions=positions.iloc[start:],
        costs=total_costs.iloc[start:],
        turnover=turnover.sum(axis=1).iloc[start:],
        config=config,
    )


def performance(daily_returns: pd.Series) -> dict[str, float]:
    """Annualised summary of daily log returns."""

    values = daily_returns.to_numpy(dtype=float)
    if values.size < 2:
        raise ValueError("need at least two daily returns")
    mean, std = float(np.mean(values)), float(np.std(values, ddof=1))
    equity = np.cumsum(values)
    drawdown = float(np.max(np.maximum.accumulate(np.r_[0.0, equity])[1:] - equity)) if values.size else 0.0
    years = values.size / TRADING_DAYS
    annual = mean * TRADING_DAYS
    yearly = daily_returns.groupby(daily_returns.index.year).sum()
    return {
        "days": int(values.size),
        "years": years,
        "annual_return": annual,
        "annual_vol": std * np.sqrt(TRADING_DAYS),
        "sharpe": annual / (std * np.sqrt(TRADING_DAYS)) if std > 0 else 0.0,
        "max_drawdown": 1.0 - float(np.exp(-drawdown)),
        "calmar": annual / (1.0 - float(np.exp(-drawdown))) if drawdown > 0 else float("inf"),
        "positive_years_share": float((yearly > 0).mean()) if len(yearly) else 0.0,
        "total_return": float(np.expm1(equity[-1])),
    }

"""Paper trades of the forward-tracked book, rebuilt from its sealed record (research only).

The forward ledger seals daily returns, closes and rebalance decisions, but it
lists no trades. This module re-runs the same book on the same inputs (the
broker exports and the inflation years the ledger fixed) and checks the run
before describing anything. Every sealed return must be reproduced within the
tracker's tolerance; otherwise it refuses (``RECORD_MISMATCH``), because the
trades would not describe the record. It then turns the daily positions into
trades, one per currency and direction:

- **Open.** A trade opens when a currency's position turns long or short at a
  rebalance. Its stop loss and take-profit come from that rebalance's anchor
  (the close on the execution day) and stop distance, exactly as the engine
  sets them. Its risk is the loss at the stop as a share of equity (at most
  ``risk_per_position``).
- **Re-anchor.** At a later rebalance that resizes the position, the engine
  re-anchors its entry, stop and take-profit; the trade stays open. A
  rebalance that leaves the weight unchanged (a loss halt keeps it) keeps the
  previous levels, as the engine does.
- **Close.** A trade closes when the position goes flat or flips, with one
  reason:
  - ``SL`` or ``TP``: the close crossed the level since the last anchor (the
    engine checks protective exits on closes, before any rebalance of the
    day);
  - ``REBALANCE``: the signal changed at a rebalance.
- **Result.** The gross contribution of the position to equity (before costs
  and swap), counted only on forward days. Trades still open at the forward
  start are flagged, and their pips count from the last close before it, so
  pips and result cover the same days.

The derivation is checked too: its stop-loss and take-profit closes must
equal the engine's counts, or it refuses (``TRADES_MISMATCH``).

Prices are shown as the MT5 pair (AUDUSD or USDJPY), so a long position in a
USD-base pair's currency is a SELL. Everything is paper: nothing here reads an
account or sends an order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

import numpy as np
import pandas as pd

from ..trial_registry import TrialLedger
from .data import MT5_USD_PAIRS
from .forward import (CHECKPOINT, TOLERANCE, BrokerPrices, ForwardPlan, _sealed, assemble_inflation)
from .portfolio import TRADING_DAYS, backtest, inflation_differentials, target_weights

REASONS = {"SL": "Stop loss", "TP": "Take profit", "REBALANCE": "Rebalanceo"}


class ReportUnavailable(ValueError):
    """The trades cannot be rebuilt faithfully from the record."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class PaperTrade:
    trade_id: str
    currency: str
    symbol: str
    side: str  # BUY or SELL of the MT5 pair
    opened_on: str
    open_price: float
    stop_loss: float
    take_profit: float
    risk_percent: float  # loss at the stop, % of equity
    opened_before_start: bool
    closed_on: str | None = None
    close_price: float | None = None
    reason: str | None = None
    pnl_percent: float = 0.0  # gross, % of equity, forward days only
    last_price: float | None = None
    start_price: float | None = None  # last close before the forward start, if opened before it
    # Levels and risk after the latest re-anchor (the engine's live levels); None until set.
    current_stop_loss: float | None = None
    current_take_profit: float | None = None
    current_risk_percent: float | None = None

    @property
    def pip_size(self) -> float:
        return 0.01 if self.symbol.endswith("JPY") else 0.0001

    @property
    def pips(self) -> float:
        """Pips over the days the result counts (from ``start_price`` when opened before the start)."""

        price = self.close_price if self.close_price is not None else self.last_price
        if price is None:
            return 0.0
        sign = 1.0 if self.side == "BUY" else -1.0
        base = self.start_price if self.start_price is not None else self.open_price
        return sign * (price - base) / self.pip_size

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "pips": self.pips}


@dataclass
class TradeBook:
    forward_start: str
    through_day: str
    trades: list[PaperTrade] = field(default_factory=list)
    daily_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))  # sealed primary, log
    swap_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    rule: dict[str, Any] = field(default_factory=dict)
    swap_coverage: float = 0.0

    def closed(self) -> list[PaperTrade]:
        return [trade for trade in self.trades if trade.closed_on is not None]

    def open(self) -> list[PaperTrade]:
        return [trade for trade in self.trades if trade.closed_on is None]


def _pair_price(usd_price: float, usd_base: bool) -> float:
    return 1.0 / usd_price if usd_base else usd_price


def rebuild_trades(plan: ForwardPlan, prices_in: BrokerPrices, inflation_base: pd.DataFrame,
                   ledger: TrialLedger, plan_hash: str | None = None) -> TradeBook:
    """Rebuild the paper trades of every forward day the ledger sealed.

    ``plan_hash`` is the frozen plan's hash (from its plan file); by default it
    is recomputed from ``plan``. The book is taken from ``plan`` and must
    reproduce the sealed returns, so a later code change cannot alter it unseen.
    """

    previous = [record for record in ledger.records() if record["kind"] == CHECKPOINT]
    if not previous:
        raise ReportUnavailable("NO_RECORD", "the ledger has no checkpoint yet")
    plan_hash = plan_hash or plan.plan_hash()
    if any(record["plan_hash"] != plan_hash for record in previous):
        raise ReportUnavailable("LEDGER_MISMATCH", "the ledger holds checkpoints of another forward plan")
    last = previous[-1]["payload"]
    first_seen: dict[str, dict[str, float]] = {}
    for record in previous:
        first_seen.update(record["payload"]["inflation_fixed"])
    inflation, _, _ = assemble_inflation(inflation_base, plan.inflation_base_last_year, first_seen, None)
    through = pd.Timestamp(last["through_day"], tz="UTC")
    prices = prices_in.panel.prices
    if prices.index[-1] < through:
        raise ReportUnavailable("PRICES_SHORTER_THAN_RECORD", "the exports end before the last sealed day")
    prices = prices.loc[:through]  # the record is described up to its last sealed day only
    config, limits = plan.config, plan.limits
    result = backtest(prices, config, plan.costs, limits, inflation=inflation)
    sealed_primary, sealed_swap = _sealed(previous)
    recomputed = result.net_returns.reindex(sealed_primary.index)
    if recomputed.isna().any() or ((recomputed - sealed_primary).abs() > TOLERANCE).any():
        raise ReportUnavailable("RECORD_MISMATCH", "re-running the book does not reproduce the sealed returns")
    gap = inflation_differentials(inflation, prices.index, tuple(prices.columns), config.inflation_years)
    target, vol = target_weights(prices, config, inflation_gap=gap)
    valid = target.notna().all(axis=1).to_numpy()
    first = int(np.argmax(valid))
    lag = config.execution_lag_days
    horizon = math.sqrt(config.rebalance_days / TRADING_DAYS)
    stops: dict[pd.Timestamp, pd.Series] = {}
    for row in range(first, len(prices) - lag, config.rebalance_days):
        stops[prices.index[row + lag]] = np.maximum(limits.stop_sigmas * vol.iloc[row] * horizon, 1e-6)
    forward_start = pd.Timestamp(plan.forward_start, tz="UTC")
    positions, contributions = result.positions, result.contributions
    # The engine re-anchors a position only when a rebalance changes its weight
    # from yesterday's weight drifted by the day's move.
    held = positions.to_numpy(dtype=float)
    previous = np.vstack([np.zeros((1, held.shape[1])), held[:-1]])
    moved = (prices.loc[positions.index].to_numpy(dtype=float)
             / prices.shift(1).loc[positions.index].to_numpy(dtype=float) - 1.0)
    gross = contributions.to_numpy(dtype=float).sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        drifted = np.nan_to_num(previous * (1.0 + moved) / (1.0 + gross))
    resized = np.abs(held - drifted) > 1e-9 * np.abs(drifted)
    trades: list[PaperTrade] = []
    for column, code in enumerate(prices.columns):
        symbol, usd_base = MT5_USD_PAIRS[code]
        trade: PaperTrade | None = None
        anchor = stop = 0.0
        direction = 0.0
        for row, day in enumerate(positions.index):
            price = float(prices.at[day, code])
            if trade is not None:
                if day >= forward_start:
                    if trade.opened_before_start and trade.start_price is None:
                        before = float(prices[code].iloc[prices.index.get_loc(day) - 1])
                        trade.start_price = _pair_price(before, usd_base)
                    trade.pnl_percent += 100.0 * float(contributions.at[day, code])
                move = direction * (price / anchor - 1.0)
                hit = "SL" if move <= -stop else "TP" if move >= limits.take_profit_multiple * stop else None
                sign = float(np.sign(positions.at[day, code]))
                rebalance = day in stops
                if hit is not None or sign != direction:
                    trade.closed_on, trade.close_price = str(day.date()), _pair_price(price, usd_base)
                    trade.reason = hit or "REBALANCE"
                    trades.append(trade)
                    trade = None
                elif rebalance and resized[row, column]:
                    anchor, stop = price, float(stops[day][code])
                    trade.current_stop_loss = _pair_price(anchor * (1.0 - direction * stop), usd_base)
                    trade.current_take_profit = _pair_price(
                        anchor * (1.0 + direction * limits.take_profit_multiple * stop), usd_base)
                    trade.current_risk_percent = 100.0 * abs(float(positions.at[day, code])) * stop
            sign = float(np.sign(positions.at[day, code]))
            if trade is None and sign != 0.0 and day in stops:
                direction, anchor, stop = sign, price, float(stops[day][code])
                side = ("SELL" if usd_base else "BUY") if sign > 0 else ("BUY" if usd_base else "SELL")
                stop_price = _pair_price(anchor * (1.0 - direction * stop), usd_base)
                target_price = _pair_price(anchor * (1.0 + direction * limits.take_profit_multiple * stop), usd_base)
                trade = PaperTrade(
                    trade_id=f"{symbol}-{day.date()}", currency=code, symbol=symbol, side=side,
                    opened_on=str(day.date()), open_price=_pair_price(price, usd_base), stop_loss=stop_price,
                    take_profit=target_price, risk_percent=100.0 * abs(float(positions.at[day, code])) * stop,
                    opened_before_start=day < forward_start)
                trade.current_stop_loss, trade.current_take_profit = stop_price, target_price
                trade.current_risk_percent = trade.risk_percent
        if trade is not None:
            trade.last_price = _pair_price(float(prices.iloc[-1][code]), usd_base)
            trades.append(trade)
    exits = {reason: sum(trade.reason == reason for trade in trades) for reason in ("SL", "TP")}
    if exits != {"SL": result.stops, "TP": result.take_profits}:
        raise ReportUnavailable("TRADES_MISMATCH", f"derived exits {exits} differ from the engine's "
                                f"{result.stops} stops and {result.take_profits} take-profits")
    trades = [trade for trade in trades if trade.closed_on is None or trade.closed_on >= plan.forward_start]
    trades.sort(key=lambda item: (item.opened_on, item.symbol))
    return TradeBook(forward_start=plan.forward_start, through_day=str(through.date()), trades=trades,
                     daily_returns=sealed_primary, swap_returns=sealed_swap, rule=dict(last["rule"]),
                     swap_coverage=float(sealed_swap.notna().mean()) if len(sealed_swap) else 0.0)

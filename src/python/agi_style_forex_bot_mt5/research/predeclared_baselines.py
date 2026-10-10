"""Matched baselines for the predeclared trend-pullback comparison; diagnostics only.

Every eligible decision bar (the bars where the strategy itself is evaluated:
warmup, full exit horizon and valid causal features) is simulated once in each
direction with the strategy's own SL/TP builder, lot, costs, management and
backtester. Candidates are independent fixed-lot simulations, so the strategy
and every baseline are subsets of the same outcomes and differ only in which
bars and directions they choose. Nothing here selects a hypothesis, turns
inspected development data into a holdout, or authorizes execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..backtesting.backtester import (Backtester, BacktestSettings, CostModel, ENGINE_VERSION, TradeCandidate,
                                      TradeResult, calculate_metrics)
from ..contracts import Direction, SignalAction
from ..core.decision.signal_builder import build_signal_prices
from ..core.instruments import InstrumentSpec
from ..data.strategy_features import prepare_strategy_features, strategy_features_at
from .experiment_plan import BAR_DURATION, ExperimentPlan, ResearchManagement, _binding, _utc, normalize_research_bars
from .trend_pullback_evaluator import _snapshot, generate_trend_pullback_candidates

BASELINE_VERSION = "predeclared_baselines_v1"
DIRECTIONS = ("BUY", "SELL")
REPLICATED_BASELINES = ("random_entries", "random_direction_same_bars", "trend_direction_random_bars")
DEFAULT_REPLICATIONS = 1000
LIMITATIONS = (
    "Development data already inspected; not out-of-sample evidence and not a holdout.",
    "Candidates are overlapping fixed-lot simulations, not independent observations or a portfolio.",
    "Empirical ranks are descriptive across many cells and baselines; no multiple-comparison correction.",
    "Costs, tick value and spreads are the plan's illustrative assumptions, not verified broker data.",
    "Replicated summaries cover closed-trade PnL, profit factor and win rate only; drawdowns are not resampled.",
)


@dataclass(frozen=True)
class EligibleBar:
    source_time: pd.Timestamp
    available_at: pd.Timestamp
    snapshot: Any
    atr: float
    trend: str | None


@dataclass(frozen=True)
class CellOutcomes:
    """Both-direction outcomes for every eligible bar of one symbol/split."""

    symbol: str
    split: str
    bars: tuple[EligibleBar, ...]
    trades: Mapping[tuple[int, str], TradeResult]
    unavailable: Mapping[tuple[int, str], str]

    def index_of(self) -> dict[pd.Timestamp, int]:
        return {bar.source_time: position for position, bar in enumerate(self.bars)}


def scan_eligible_bars(candles: pd.DataFrame, *, symbol: str, instrument: InstrumentSpec, cost_model: CostModel,
                       management: ResearchManagement, window_start, window_end) -> tuple[EligibleBar, ...]:
    """Bars the strategy evaluates, with the same causal scoping and boundary rules."""
    start, end = _utc(window_start), _utc(window_end)
    bars = normalize_research_bars(candles, symbol=symbol)
    history = bars.loc[bars["timestamp_utc"] + BAR_DURATION <= start].tail(250)
    active = bars.loc[(bars["timestamp_utc"] >= start) & (bars["timestamp_utc"] < end)]
    if active.empty:
        return ()
    scoped = pd.concat([history, active], ignore_index=True)
    enriched = prepare_strategy_features(scoped, point=instrument.point, max_spread_points=cost_model.max_spread_points)
    eligible = []
    for idx in range(len(history), len(enriched)):
        row = enriched.iloc[idx]
        source_time = row["timestamp_utc"]
        available = source_time + BAR_DURATION
        if available >= end or idx < 250:
            continue
        entry_idx = int(enriched["timestamp_utc"].searchsorted(available))
        final_idx = entry_idx + management.max_holding_bars - 1
        if final_idx >= len(enriched) or enriched.iloc[final_idx]["timestamp_utc"] + BAR_DURATION > end:
            continue
        try:
            snapshot = _snapshot(row, symbol, instrument)
            features = strategy_features_at(enriched, idx, snapshot, max_spread_points=cost_model.max_spread_points)
        except ValueError:
            continue
        fast, slow = float(features["ema_fast"]), float(features["ema_slow"])
        trend = "BUY" if fast > slow else "SELL" if fast < slow else None
        eligible.append(EligibleBar(source_time, available, snapshot, float(features["atr"]), trend))
    return tuple(eligible)


def _plan_cell(plan: ExperimentPlan, symbol: str, split: str):
    payload = plan.to_dict()
    entry = payload["datasets"][symbol]
    window = {item.name: item for item in plan.splits}[split]
    return (payload, entry, window, InstrumentSpec(**entry["instrument"]), CostModel(**entry["cost_model"]),
            ResearchManagement(**payload["management"]))


def simulate_cell(plan: ExperimentPlan, candles: pd.DataFrame, *, symbol: str, split: str) -> CellOutcomes:
    """Simulate BUY and SELL at every eligible bar with the strategy's execution model."""
    if not isinstance(plan, ExperimentPlan):
        raise ValueError("ExperimentPlan required")
    payload, entry, window, spec, costs, management = _plan_cell(plan, symbol, split)
    bars = normalize_research_bars(candles, symbol=symbol)
    if any(entry[key] != value for key, value in _binding(bars, payload["splits"]).items()):
        raise ValueError("dataset hash/rows/splits differ from plan")
    eligible = scan_eligible_bars(bars, symbol=symbol, instrument=spec, cost_model=costs, management=management,
                                  window_start=window.start_utc, window_end=window.end_utc)
    candidates, unavailable = [], {}
    for position, bar in enumerate(eligible):
        for direction in DIRECTIONS:
            try:
                sl, tp = build_signal_prices(bar.snapshot, SignalAction(direction), bar.atr)
            except ValueError as error:
                unavailable[(position, direction)] = f"PROTECTION_INVALID: {error}"
                continue
            candidates.append(TradeCandidate(timestamp=bar.source_time, symbol=symbol, direction=Direction(direction),
                sl_price=sl, tp_price=tp, timeframe="M5", signal_id=f"{position}:{direction}", lot=payload["lot"],
                available_at_utc=bar.available_at, metadata={"baseline_version": BASELINE_VERSION,
                    "full_risk_pipeline_applied": False, "promotion_eligible": False}))
    simulation_bars = bars.loc[(bars["timestamp_utc"] >= _utc(window.start_utc)) &
                               (bars["timestamp_utc"] + BAR_DURATION <= _utc(window.end_utc))].copy()
    settings = BacktestSettings(run_id=f"{BASELINE_VERSION}:{plan.plan_id}:{symbol}:{split}",
        strategy_name="predeclared_baselines", strategy_version=BASELINE_VERSION,
        initial_balance=payload["initial_balance"], cost_model=costs,
        break_even_trigger_r=management.break_even_trigger_r, break_even_lock_points=management.break_even_lock_points,
        trailing_start_r=management.trailing_start_r, trailing_distance_points=management.trailing_distance_points,
        max_bars_in_trade=management.max_holding_bars, data_source=entry["data_provenance"]["provider"],
        code_commit=payload["code_commit"], random_seed=payload["random_seed"], data_fingerprint=entry["data_sha256"],
        broker_profile=entry["instrument"], parameters={"plan_id": plan.plan_id, "data_role": payload["data_role"],
            "full_risk_pipeline_applied": False, "full_pipeline_verified": False, "promotion_eligible": False})
    outcome = Backtester(settings).run(simulation_bars.rename(columns={"timestamp_utc": "timestamp"}), candidates)
    trades = {}
    for trade in outcome.trades:
        position, direction = trade.signal_id.split(":")
        trades[(int(position), direction)] = trade
    for rejected in outcome.rejected_candidates:
        position, direction = rejected["signal_id"].split(":")
        unavailable[(int(position), direction)] = str(rejected["reason"])
    for position in range(len(eligible)):
        for direction in DIRECTIONS:
            if (position, direction) not in trades and (position, direction) not in unavailable:
                unavailable[(position, direction)] = "NO_TRADE_RESULT"
    return CellOutcomes(symbol, split, eligible, trades, unavailable)


def strategy_selection(plan: ExperimentPlan, candles: pd.DataFrame, cell: CellOutcomes, *,
                       hypothesis_id: str) -> tuple[tuple[int, str], ...]:
    """The strategy's own (bar, direction) choices; eligibility must match exactly."""
    payload, entry, window, spec, costs, management = _plan_cell(plan, cell.symbol, cell.split)
    hypothesis = {item.hypothesis_id: item for item in plan.hypotheses}[hypothesis_id]
    generation = generate_trend_pullback_candidates(normalize_research_bars(candles, symbol=cell.symbol),
        symbol=cell.symbol, params=hypothesis.params, instrument=spec, cost_model=costs, management=management,
        lot=payload["lot"], window_start=window.start_utc, window_end=window.end_utc, identity_prefix="baseline")
    evaluated = [pd.Timestamp(item["source_bar_timestamp_utc"]) for item in generation.decisions if "action" in item]
    if evaluated != [bar.source_time for bar in cell.bars]:
        raise ValueError("strategy evaluation bars differ from baseline eligibility")
    index = cell.index_of()
    return tuple((index[pd.Timestamp(candidate.timestamp)], candidate.direction.value)
                 for candidate in generation.candidates)


def _seed(*parts: Any) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _profits(cell: CellOutcomes, selection: Sequence[tuple[int, str]]) -> np.ndarray:
    return np.array([cell.trades[key].profit for key in selection if key in cell.trades], dtype=float)


def summarize_profits(profits: np.ndarray) -> dict[str, Any]:
    """Backtester definitions of net profit, profit factor and win rate."""
    total = int(len(profits))
    wins, losses = profits[profits > 0], profits[profits < 0]
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    if gross_loss > 0:
        profit_factor, status = gross_profit / gross_loss, "FINITE"
    else:
        profit_factor, status = (None, "UNBOUNDED_NO_LOSSES") if gross_profit > 0 else (0.0, "FINITE")
    return {"trades": total, "net_profit": float(profits.sum()) if total else 0.0, "gross_profit": gross_profit,
            "gross_loss": gross_loss, "profit_factor": profit_factor, "profit_factor_status": status,
            "win_rate_pct": len(wins) / total * 100.0 if total else 0.0,
            "expectancy": float(profits.mean()) if total else 0.0}


def _distribution(values: Sequence[float | None]) -> dict[str, Any]:
    finite = np.array([value for value in values if value is not None], dtype=float)
    if not len(finite):
        return {"count": 0, "mean": None, "p05": None, "p50": None, "p95": None}
    return {"count": int(len(finite)), "mean": float(finite.mean()),
            **{key: float(np.percentile(finite, q)) for key, q in (("p05", 5), ("p50", 50), ("p95", 95))}}


class _Pools:
    """Precomputed outcome arrays so each replication is vectorized."""

    def __init__(self, cell: CellOutcomes, strategy: Sequence[tuple[int, str]]):
        size = len(cell.bars)
        self.profit = {direction: np.full(size, np.nan) for direction in DIRECTIONS}
        for (position, direction), trade in cell.trades.items():
            self.profit[direction][position] = trade.profit
        available = {direction: ~np.isnan(self.profit[direction]) for direction in DIRECTIONS}
        self.both = np.flatnonzero(available["BUY"] & available["SELL"])
        trend = np.array([{"BUY": 0, "SELL": 1}.get(bar.trend, -1) for bar in cell.bars], dtype=int)
        trend_ok = (trend == 0) & available["BUY"] | (trend == 1) & available["SELL"]
        self.trend_positions = np.flatnonzero(trend_ok)
        self.trend_profits = np.where(trend[self.trend_positions] == 0, self.profit["BUY"][self.trend_positions],
                                      self.profit["SELL"][self.trend_positions]) if len(self.trend_positions) else np.array([])
        traded = [(position, direction) for position, direction in strategy if (position, direction) in cell.trades]
        self.traded_count = len(traded)
        both = set(self.both.tolist())
        self.same_bars = np.array([position for position, _ in traded if position in both], dtype=int)

    def draw(self, name: str, rng: np.random.Generator) -> np.ndarray:
        if name == "random_entries":
            size = min(self.traded_count, len(self.both))
            chosen = self.both[rng.choice(len(self.both), size=size, replace=False)] if size else self.both[:0]
            sell = rng.integers(0, 2, size=size).astype(bool)
            return np.where(sell, self.profit["SELL"][chosen], self.profit["BUY"][chosen])
        if name == "random_direction_same_bars":
            sell = rng.integers(0, 2, size=len(self.same_bars)).astype(bool)
            return np.where(sell, self.profit["SELL"][self.same_bars], self.profit["BUY"][self.same_bars])
        if name == "trend_direction_random_bars":
            size = min(self.traded_count, len(self.trend_positions))
            chosen = rng.choice(len(self.trend_positions), size=size, replace=False) if size else np.array([], dtype=int)
            return self.trend_profits[chosen]
        raise ValueError(f"unknown baseline {name}")


def evaluate_baselines(plan: ExperimentPlan, candles: pd.DataFrame, cell: CellOutcomes, *, hypothesis_id: str,
                       replications: int = DEFAULT_REPLICATIONS) -> dict[str, Any]:
    """Strategy versus no-trade, direction flip and three replicated random baselines."""
    if type(replications) is not int or replications < 1:
        raise ValueError("replications must be a positive integer")
    strategy = strategy_selection(plan, candles, cell, hypothesis_id=hypothesis_id)
    strategy_trades = [cell.trades[key] for key in strategy if key in cell.trades]
    strategy_summary = summarize_profits(_profits(cell, strategy))
    # Same definitions as the evaluator's backtester run on these candidates.
    metrics = calculate_metrics(strategy_trades, initial_balance=plan.to_dict()["initial_balance"])
    if not math.isclose(metrics.net_profit, strategy_summary["net_profit"], rel_tol=0, abs_tol=1e-6):
        raise ValueError("strategy subset does not reproduce backtester net profit")
    strategy_summary["max_drawdown_pct"] = metrics.max_drawdown_pct
    flipped = [(position, "SELL" if direction == "BUY" else "BUY") for position, direction in strategy]
    result = {"hypothesis_id": hypothesis_id, "symbol": cell.symbol, "split": cell.split,
              "eligible_bars": len(cell.bars), "strategy_candidates": len(strategy),
              "strategy": strategy_summary, "no_trade": summarize_profits(np.array([], dtype=float)),
              "direction_flip": summarize_profits(_profits(cell, flipped)), "replicated": {}}
    pools = _Pools(cell, strategy)
    for name in REPLICATED_BASELINES:
        rng = np.random.Generator(np.random.PCG64(_seed(BASELINE_VERSION, plan.plan_id,
            plan.to_dict()["random_seed"], cell.symbol, cell.split, hypothesis_id, name)))
        nets, factors, wins, sizes = [], [], [], []
        for _ in range(replications):
            summary = summarize_profits(pools.draw(name, rng))
            nets.append(summary["net_profit"])
            factors.append(summary["profit_factor"])
            wins.append(summary["win_rate_pct"])
            sizes.append(summary["trades"])
        at_least = sum(1 for value in nets if value >= strategy_summary["net_profit"])
        result["replicated"][name] = {
            "replications": replications, "sample_size": _distribution(sizes),
            "net_profit": _distribution(nets), "profit_factor": _distribution(factors),
            "win_rate_pct": _distribution(wins),
            # Share of baseline draws doing at least as well as the strategy (+1 smoothing).
            "baseline_at_least_strategy_share": (at_least + 1) / (replications + 1),
        }
    return result


def run_baseline_matrix(plan: ExperimentPlan, datasets: Mapping[str, pd.DataFrame], *,
                        replications: int = DEFAULT_REPLICATIONS) -> dict[str, Any]:
    """Every symbol, split and hypothesis; no winner is selected."""
    payload = plan.to_dict()
    cells = []
    for symbol in plan.symbols:
        for split in (item.name for item in plan.splits):
            outcomes = simulate_cell(plan, datasets[symbol], symbol=symbol, split=split)
            for hypothesis in plan.hypotheses:
                cell = evaluate_baselines(plan, datasets[symbol], outcomes, hypothesis_id=hypothesis.hypothesis_id,
                                          replications=replications)
                cell["min_score"] = hypothesis.params.to_dict()["min_score"]
                cell["unavailable_outcomes"] = len(outcomes.unavailable)
                cells.append(cell)
    return {"schema_version": BASELINE_VERSION, "engine_version": ENGINE_VERSION, "plan_id": plan.plan_id,
            "data_role": payload["data_role"], "random_seed": payload["random_seed"], "replications": replications,
            "selection_policy": "NONE_COMPARE_ALL", "final_holdout": "NOT_AVAILABLE",
            "baselines": ["no_trade", "direction_flip", *REPLICATED_BASELINES], "cells": cells,
            "limitations": list(LIMITATIONS), "full_risk_pipeline_applied": False, "full_pipeline_verified": False,
            "promotion_eligible": False, "execution_authorized": False}

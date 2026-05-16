"""Stress tests for cost sensitivity and trade concentration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .backtester import TradeResult, calculate_metrics, run_backtest_for_symbols


@dataclass(frozen=True)
class StressResult:
    scenario: str
    parameters: Mapping[str, Any]
    metrics: Any


class StressTester:
    """Apply deterministic degradation scenarios to closed trades."""

    def __init__(self, *, initial_balance: float = 10_000.0) -> None:
        self.initial_balance = initial_balance

    def spread_slippage_sensitivity(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any]],
        *,
        spread_multipliers: Iterable[float] = (1.0, 1.5, 2.0),
        extra_slippage_points: Iterable[float] = (0.0, 1.0, 2.0),
    ) -> list[StressResult]:
        source = [_ensure_trade(trade) for trade in trades]
        results: list[StressResult] = []
        for spread_multiplier in spread_multipliers:
            if spread_multiplier < 0:
                raise ValueError("spread multipliers must be non-negative")
            for slippage_points in extra_slippage_points:
                if slippage_points < 0:
                    raise ValueError("extra slippage must be non-negative")
                stressed = [
                    _apply_cost_penalty(
                        trade,
                        spread_multiplier=spread_multiplier,
                        extra_slippage_points=slippage_points,
                    )
                    for trade in source
                ]
                metrics = calculate_metrics(stressed, initial_balance=self.initial_balance)
                results.append(
                    StressResult(
                        scenario="spread_slippage",
                        parameters={
                            "spread_multiplier": spread_multiplier,
                            "extra_slippage_points": slippage_points,
                        },
                        metrics=metrics,
                    )
                )
        return results

    def remove_best_trades(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any]],
        *,
        counts: Iterable[int] = (1, 3, 5),
    ) -> list[StressResult]:
        source = [_ensure_trade(trade) for trade in trades]
        ordered = sorted(source, key=lambda trade: trade.profit, reverse=True)
        results: list[StressResult] = []
        for count in counts:
            if count < 0:
                raise ValueError("remove count must be non-negative")
            removed_ids = {id(trade) for trade in ordered[:count]}
            remaining = [trade for trade in source if id(trade) not in removed_ids]
            metrics = calculate_metrics(remaining, initial_balance=self.initial_balance)
            results.append(
                StressResult(
                    scenario="remove_best_trades",
                    parameters={"removed_count": min(count, len(source))},
                    metrics=metrics,
                )
            )
        return results

    def comprehensive(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any]],
    ) -> list[StressResult]:
        """Run the Phase 5 scenario set over closed trades."""

        source = [_ensure_trade(trade) for trade in trades]
        results: list[StressResult] = []
        for multiplier in (1.0, 1.5, 2.0, 3.0):
            stressed = [_apply_cost_penalty(trade, spread_multiplier=multiplier, extra_slippage_points=0.0) for trade in source]
            results.append(StressResult("spread_multiplier", {"spread_multiplier": multiplier}, calculate_metrics(stressed, initial_balance=self.initial_balance)))
        for multiplier in (1.0, 1.5, 2.0, 3.0):
            stressed = [_apply_cost_penalty(trade, spread_multiplier=1.0, extra_slippage_points=trade.slippage_points * (multiplier - 1.0)) for trade in source]
            results.append(StressResult("slippage_multiplier", {"slippage_multiplier": multiplier}, calculate_metrics(stressed, initial_balance=self.initial_balance)))
        for multiplier in (1.0, 1.5, 2.0):
            stressed = [replace(trade, profit=trade.profit - trade.commission * (multiplier - 1.0)) for trade in source]
            results.append(StressResult("commission_multiplier", {"commission_multiplier": multiplier}, calculate_metrics(stressed, initial_balance=self.initial_balance)))
        for pct in (1, 5, 10):
            results.append(self._remove_best_percent(source, pct))
        for count in (3, 5, 8):
            loss_trade = _synthetic_loss(source)
            stressed = list(source) + [loss_trade] * count if loss_trade is not None else list(source)
            results.append(StressResult("artificial_loss_streak", {"losses_added": count}, calculate_metrics(stressed, initial_balance=self.initial_balance)))
        for pct in (5, 10):
            kept = [trade for index, trade in enumerate(source) if (index + 1) % int(100 / pct) != 0]
            results.append(StressResult("missing_bars_proxy", {"removed_trade_pct": pct}, calculate_metrics(kept, initial_balance=self.initial_balance)))
        delayed = [replace(trade, profit=trade.profit - abs(trade.profit) * 0.05) for trade in source]
        results.append(StressResult("entry_delay_one_bar", {"profit_penalty_pct": 5}, calculate_metrics(delayed, initial_balance=self.initial_balance)))
        shifted = [replace(trade, metadata={**dict(trade.metadata), "session": "SHIFTED"}) for trade in source]
        results.append(StressResult("session_shift", {"session": "SHIFTED"}, calculate_metrics(shifted, initial_balance=self.initial_balance)))
        return results

    def _remove_best_percent(self, trades: list[TradeResult], pct: int) -> StressResult:
        count = max(1, int(len(trades) * pct / 100.0)) if trades else 0
        ordered = sorted(trades, key=lambda trade: trade.profit, reverse=True)
        removed_ids = {id(trade) for trade in ordered[:count]}
        remaining = [trade for trade in trades if id(trade) not in removed_ids]
        return StressResult(
            "remove_best_percent",
            {"removed_pct": pct, "removed_count": count},
            calculate_metrics(remaining, initial_balance=self.initial_balance),
        )


def run_stress_report(
    *,
    trades: Iterable[TradeResult | Mapping[str, Any]] | None = None,
    data_dir: str | Path | None = None,
    symbols: Iterable[str] | None = None,
    report_dir: str | Path,
    initial_balance: float = 10_000.0,
) -> dict[str, Any]:
    """Run stress scenarios and write JSON/CSV reports."""

    input_files: list[str] = []
    if trades is None:
        if data_dir is None or symbols is None:
            raise ValueError("either trades or data_dir+symbols is required")
        batch = run_backtest_for_symbols(data_dir=data_dir, symbols=symbols, report_dir=None)
        source = batch.trades.to_dict("records")
        input_files = [str(data_dir)]
    else:
        source = list(trades)
    results = StressTester(initial_balance=initial_balance).comprehensive(source)
    rows = [_stress_row(item) for item in results]
    classification = _classify_stress(rows)
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    summary_path = path / "summary.json"
    scenarios_path = path / "scenarios.csv"
    pd.DataFrame(rows).to_csv(scenarios_path, index=False)
    summary = {
        "mode": "stress-test",
        "input_files": input_files,
        "scenario_count": len(rows),
        "classification": classification,
        "reports_created": [str(summary_path), str(scenarios_path)],
        "execution_attempted": False,
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _ensure_trade(trade: TradeResult | Mapping[str, Any]) -> TradeResult:
    if isinstance(trade, TradeResult):
        return trade
    return TradeResult(**dict(trade))


def _apply_cost_penalty(
    trade: TradeResult,
    *,
    spread_multiplier: float,
    extra_slippage_points: float,
) -> TradeResult:
    extra_spread_points = max(0.0, trade.spread_points * (spread_multiplier - 1.0))
    extra_round_trip_points = extra_spread_points + (2.0 * extra_slippage_points)
    penalty = (
        extra_round_trip_points
        * trade.point
        / trade.tick_size
        * trade.tick_value
        * trade.lot
    )
    data = asdict(trade)
    data["profit"] = trade.profit - penalty
    if trade.r_multiple != 0 and trade.profit != 0:
        data["r_multiple"] = trade.r_multiple * (data["profit"] / trade.profit)
    return replace(trade, profit=data["profit"], r_multiple=data["r_multiple"])


def _synthetic_loss(trades: list[TradeResult]) -> TradeResult | None:
    if not trades:
        return None
    worst = min(trades, key=lambda trade: trade.profit)
    loss = worst.profit if worst.profit < 0 else -abs(worst.profit or 10.0)
    return replace(worst, profit=loss, r_multiple=-abs(worst.r_multiple or 1.0))


def _stress_row(result: StressResult) -> dict[str, Any]:
    return {
        "scenario": result.scenario,
        "parameters": json.dumps(dict(result.parameters), sort_keys=True),
        "trades": result.metrics.trades_total,
        "net_profit": result.metrics.net_profit,
        "net_return_pct": result.metrics.total_return_pct,
        "profit_factor": result.metrics.profit_factor,
        "max_drawdown_pct": result.metrics.max_drawdown_pct,
        "expectancy_r": result.metrics.average_r,
    }


def _classify_stress(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "REJECTED"
    spread_x2 = [row for row in rows if row["scenario"] == "spread_multiplier" and '"spread_multiplier": 2.0' in row["parameters"]]
    top5 = [row for row in rows if row["scenario"] == "remove_best_percent" and '"removed_pct": 5' in row["parameters"]]
    spread_ok = bool(spread_x2 and spread_x2[0]["net_profit"] > 0)
    top5_ok = bool(top5 and top5[0]["net_profit"] > 0)
    if spread_ok and top5_ok:
        return "APPROVED_FOR_SHADOW_OBSERVATION"
    if spread_ok or top5_ok:
        return "WATCHLIST"
    return "REJECTED"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and value in {float("inf"), float("-inf")}:
        return "Infinity" if value > 0 else "-Infinity"
    return value

"""Reproducible Monte Carlo validation for trade sequences."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .backtester import TradeResult, calculate_metrics, classify_sample_size


@dataclass(frozen=True)
class MonteCarloResult:
    seed: int
    iterations: int
    method: str
    final_equity_percentiles: Mapping[str, float]
    max_drawdown_percentiles: Mapping[str, float]
    max_consecutive_losses_percentiles: Mapping[str, float]
    risk_of_ruin_pct: float
    fifth_percentile_return_pct: float = 0.0
    ninety_fifth_percentile_drawdown_pct: float = 0.0
    simulations: tuple[Mapping[str, float], ...] = ()


class MonteCarloSimulator:
    """Bootstrap or permute trade profit sequences with a fixed RNG seed."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def run(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any] | float],
        *,
        initial_balance: float = 10_000.0,
        iterations: int = 1_000,
        method: str = "bootstrap",
        ruin_threshold_pct: float = 30.0,
    ) -> MonteCarloResult:
        if iterations <= 0:
            raise ValueError("iterations must be positive")
        profits = _extract_profits(trades)
        if len(profits) == 0:
            raise ValueError("at least one trade is required")
        rng = np.random.default_rng(self.seed)
        finals: list[float] = []
        drawdowns: list[float] = []
        loss_runs: list[float] = []
        simulation_rows: list[dict[str, float]] = []
        ruin_count = 0
        for index in range(iterations):
            if method == "bootstrap":
                sampled = rng.choice(profits, size=len(profits), replace=True)
            elif method == "permutation":
                sampled = rng.permutation(profits)
            else:
                raise ValueError("method must be bootstrap or permutation")
            equity = initial_balance + np.cumsum(sampled)
            curve = np.concatenate(([initial_balance], equity))
            running_max = np.maximum.accumulate(curve)
            dd = (curve - running_max) / running_max * 100.0
            finals.append(float(curve[-1]))
            drawdowns.append(float(dd.min()))
            loss_runs.append(float(_max_loss_run(sampled)))
            simulation_rows.append(
                {
                    "simulation": float(index),
                    "final_equity": float(curve[-1]),
                    "return_pct": float((curve[-1] - initial_balance) / initial_balance * 100.0),
                    "max_drawdown_pct": float(dd.min()),
                    "longest_losing_streak": float(_max_loss_run(sampled)),
                }
            )
            if dd.min() <= -abs(ruin_threshold_pct):
                ruin_count += 1
        return_pcts = [(value - initial_balance) / initial_balance * 100.0 for value in finals]
        return MonteCarloResult(
            seed=self.seed,
            iterations=iterations,
            method=method,
            final_equity_percentiles=_percentiles(finals),
            max_drawdown_percentiles=_percentiles(drawdowns),
            max_consecutive_losses_percentiles=_percentiles(loss_runs),
            risk_of_ruin_pct=ruin_count / iterations * 100.0,
            fifth_percentile_return_pct=float(np.percentile(return_pcts, 5)),
            ninety_fifth_percentile_drawdown_pct=float(np.percentile(drawdowns, 5)),
            simulations=tuple(simulation_rows),
        )


def monte_carlo_metrics(
    trades: Iterable[TradeResult | Mapping[str, Any] | float],
    *,
    seed: int = 0,
    initial_balance: float = 10_000.0,
    iterations: int = 1_000,
) -> MonteCarloResult:
    return MonteCarloSimulator(seed=seed).run(
        trades,
        initial_balance=initial_balance,
        iterations=iterations,
    )


def shuffled_metrics(
    trades: Iterable[TradeResult | Mapping[str, Any]],
    *,
    seed: int,
    initial_balance: float = 10_000.0,
) -> Any:
    """Return metrics for one deterministic permutation of closed trades."""

    normalized = list(trades)
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(normalized))
    shuffled = [normalized[int(idx)] for idx in order]
    return calculate_metrics(shuffled, initial_balance=initial_balance)


def run_monte_carlo_report(
    *,
    trades: Iterable[TradeResult | Mapping[str, Any] | float] | None = None,
    trades_path: str | Path | None = None,
    report_dir: str | Path,
    seed: int = 0,
    iterations: int = 1_000,
    initial_balance: float = 10_000.0,
    method: str = "bootstrap",
    ruin_threshold_pct: float = 30.0,
) -> dict[str, Any]:
    """Run Monte Carlo and export summary/simulation artifacts."""

    source = list(trades if trades is not None else _load_trades_csv(trades_path))
    sample_status = classify_sample_size(len(source))
    result = MonteCarloSimulator(seed=seed).run(
        source,
        initial_balance=initial_balance,
        iterations=iterations,
        method=method,
        ruin_threshold_pct=ruin_threshold_pct,
    )
    classification = _classify(result)
    if len(source) < 30:
        classification = "LOW_SAMPLE_WARNING"
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    summary_path = path / "summary.json"
    simulations_path = path / "simulations.csv"
    simulations = pd.DataFrame(result.simulations)
    simulations.to_csv(simulations_path, index=False)
    summary = {
        "mode": "monte-carlo",
        "input_files": [str(trades_path)] if trades_path is not None else [],
        "seed": seed,
        "simulations": iterations,
        "classification": classification,
        "total_trades": len(source),
        "sample_status": sample_status,
        "probability_of_ruin": result.risk_of_ruin_pct,
        "fifth_percentile_return_pct": result.fifth_percentile_return_pct,
        "ninety_fifth_percentile_drawdown_pct": result.ninety_fifth_percentile_drawdown_pct,
        "reports_created": [str(summary_path), str(simulations_path)],
        "execution_attempted": False,
        "result": _jsonable(asdict(result) | {"simulations": []}),
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _extract_profits(trades: Iterable[TradeResult | Mapping[str, Any] | float]) -> np.ndarray:
    profits: list[float] = []
    for trade in trades:
        if isinstance(trade, (int, float)):
            profits.append(float(trade))
        elif isinstance(trade, TradeResult):
            profits.append(float(trade.profit))
        else:
            profits.append(float(trade["profit"]))
    return np.array(profits, dtype=float)


def _load_trades_csv(path: str | Path | None) -> list[Mapping[str, Any]]:
    if path is None:
        raise ValueError("trades_path is required when trades are not supplied")
    frame = pd.read_csv(path)
    if frame.empty:
        raise ValueError("trades CSV is empty")
    if "profit" not in frame.columns:
        raise ValueError("trades CSV requires profit column")
    return frame.to_dict("records")


def _classify(result: MonteCarloResult) -> str:
    if result.risk_of_ruin_pct <= 2.0 and result.fifth_percentile_return_pct > 0:
        return "APPROVED_FOR_SHADOW_OBSERVATION"
    if result.risk_of_ruin_pct <= 10.0:
        return "WATCHLIST"
    return "REJECTED"


def _percentiles(values: Iterable[float]) -> dict[str, float]:
    arr = np.array(list(values), dtype=float)
    return {
        "p5": float(np.percentile(arr, 5)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
    }


def _max_loss_run(profits: Iterable[float]) -> int:
    best = 0
    current = 0
    for profit in profits:
        if profit < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and (np.isinf(value) or np.isnan(value)):
        if np.isnan(value):
            return None
        return "Infinity" if value > 0 else "-Infinity"
    return value

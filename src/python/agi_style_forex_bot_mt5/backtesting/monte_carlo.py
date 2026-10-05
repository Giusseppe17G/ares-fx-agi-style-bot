"""Reproducible Monte Carlo validation for trade sequences."""

from __future__ import annotations

import json
import math
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from ..core.clock import FrozenClock
from ..core.run_manifest import RunManifest
from .backtester import TradeResult, classify_sample_size


EVIDENCE_VERSION = "2.0"
SEQUENCE_AXIS = "SYNTHETIC_TRADE_INDEX"
DRAWDOWN_EVENT = "MAX_PEAK_DRAWDOWN_AT_LEAST_THRESHOLD"


@dataclass(frozen=True)
class SequenceMetrics:
    """PnL sequence economics, with no invented calendar or market observations.

    Common economic attribute names match BacktestMetrics. Calendar, annualized,
    exposure and excursion statistics are unavailable on this synthetic axis.
    """

    total_return_pct: float
    net_profit: float
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    expectancy: float
    expected_payoff: float
    average_r: float | None
    trades_total: int
    max_consecutive_losses: int
    average_consecutive_losses: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    recovery_factor: float | None
    drawdown_percentiles: Mapping[str, float]
    source_indices: tuple[int | None, ...]
    profit_sequence: tuple[float, ...]
    equity_sequence: tuple[float, ...]
    sequence_axis: str = SEQUENCE_AXIS
    calendar_metrics_available: bool = False
    daily_max_drawdown_pct: None = None
    sharpe: None = None
    sortino: None = None
    average_duration_seconds: None = None
    average_mae: None = None
    average_mfe: None = None
    exposure_time_pct: None = None
    positive_months: None = None
    negative_months: None = None
    worst_day_return_pct: None = None
    worst_week_return_pct: None = None
    worst_month_return_pct: None = None
    monthly_returns: Mapping[str, float] = field(default_factory=dict)
    trades_per_month: Mapping[str, int] = field(default_factory=dict)
    mae_mfe_summary: Mapping[str, float] = field(default_factory=dict)


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
    initial_balance: float = 10_000.0
    ruin_threshold_pct: float = 30.0
    ruin_event: str = DRAWDOWN_EVENT
    sequence_axis: str = SEQUENCE_AXIS
    sampling_model: str = "FIXED_CURRENCY_PNL_NO_RESIZING"


class MonteCarloSimulator:
    """Bootstrap or permute trade profit sequences with a fixed RNG seed."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = _integer(seed, "seed", minimum=0)

    def run(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any] | float],
        *,
        initial_balance: float = 10_000.0,
        iterations: int = 1_000,
        method: str = "bootstrap",
        ruin_threshold_pct: float = 30.0,
    ) -> MonteCarloResult:
        initial_balance = _positive_number(initial_balance, "initial_balance")
        iterations = _integer(iterations, "iterations", minimum=1)
        ruin_threshold_pct = _positive_number(ruin_threshold_pct, "ruin_threshold_pct")
        if ruin_threshold_pct > 100:
            raise ValueError("ruin_threshold_pct must be <= 100")
        if method not in ("bootstrap", "permutation"):
            raise ValueError("method must be bootstrap or permutation")
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
            curve, dd = _sequence_curve(sampled, initial_balance)
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
            if dd.min() <= -ruin_threshold_pct:
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
            fifth_percentile_return_pct=_percentiles(return_pcts)["p5"],
            ninety_fifth_percentile_drawdown_pct=_percentiles(drawdowns)["p5"],
            simulations=tuple(simulation_rows),
            initial_balance=initial_balance,
            ruin_threshold_pct=ruin_threshold_pct,
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
) -> SequenceMetrics:
    """Return synthetic-index metrics for one permutation; dates are not shuffled."""

    normalized = list(trades)
    rng = np.random.default_rng(_integer(seed, "seed", minimum=0))
    order = rng.permutation(len(normalized))
    shuffled = [normalized[int(idx)] for idx in order]
    return sequence_metrics(shuffled, initial_balance=initial_balance, source_indices=tuple(int(idx) for idx in order))


def sequence_metrics(
    trades: Iterable[TradeResult | Mapping[str, Any] | float],
    *,
    initial_balance: float,
    source_indices: tuple[int | None, ...] | None = None,
) -> SequenceMetrics:
    """Evaluate exactly the supplied order using baseline plus integer-index PnL."""
    source = list(trades)
    balance = _positive_number(initial_balance, "initial_balance")
    profits = _extract_profits(source)
    curve, dd = _sequence_curve(profits, balance)
    r_values = []
    for trade in source:
        value = trade.r_multiple if isinstance(trade, TradeResult) else trade.get("r_multiple") if isinstance(trade, Mapping) else None
        r_values.append(None if value is None else _finite_number(value, "r_multiple"))
    wins, losses = profits[profits > 0], profits[profits < 0]
    with np.errstate(over="raise", invalid="raise"):
        try:
            net = float(profits.sum())
            gross_win, gross_loss = float(wins.sum()), abs(float(losses.sum()))
            avg_win = float(wins.mean()) if len(wins) else 0.0
            avg_loss = float(losses.mean()) if len(losses) else 0.0
            mean_r = float(np.mean(r_values)) if r_values and all(value is not None for value in r_values) else None
        except FloatingPointError as exc:
            raise ValueError("sequence metrics overflow") from exc
    runs = _loss_runs(profits)
    maximum_loss = float((np.maximum.accumulate(curve) - curve).max())
    indices = tuple(range(len(source))) if source_indices is None else source_indices
    if len(indices) != len(source):
        raise ValueError("source_indices must match the sequence length")
    expectancy = net / len(profits) if len(profits) else 0.0
    profit_factor = _finite_number(gross_win / gross_loss, "profit_factor") if gross_loss else math.inf if gross_win else 0.0
    payoff_ratio = _finite_number(abs(avg_win / avg_loss), "payoff_ratio") if avg_loss else 0.0
    recovery_factor = _finite_number(net / maximum_loss, "recovery_factor") if maximum_loss else None
    return SequenceMetrics(
        total_return_pct=_finite_number(net / balance * 100, "total_return_pct"),
        net_profit=net, win_rate_pct=len(wins) / len(profits) * 100 if len(profits) else 0.0,
        profit_factor=profit_factor,
        max_drawdown_pct=float(dd.min()), expectancy=expectancy, expected_payoff=expectancy,
        average_r=mean_r, trades_total=len(profits), max_consecutive_losses=max(runs, default=0),
        average_consecutive_losses=float(np.mean(runs)) if runs else 0.0,
        avg_win=avg_win, avg_loss=avg_loss, payoff_ratio=payoff_ratio,
        recovery_factor=recovery_factor,
        drawdown_percentiles={f"p{p}": float(np.percentile(np.abs(dd), p)) for p in (50, 75, 95)},
        source_indices=indices, profit_sequence=tuple(float(value) for value in profits),
        equity_sequence=tuple(float(value) for value in curve),
    )


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
    inputs = {"profits": _extract_profits(source).tolist()}
    # Callers may supply a selected profit sequence plus its original CSV path.
    # Hashing the file records that reference, not a claim that they are equal.
    if trades_path is not None:
        inputs["source_file_sha256"] = sha256(Path(trades_path).read_bytes()).hexdigest()
    config = {
        "evidence_version": EVIDENCE_VERSION, "seed": result.seed, "iterations": result.iterations,
        "method": method, "initial_balance": result.initial_balance,
        "ruin_threshold_pct": result.ruin_threshold_pct, "ruin_event": result.ruin_event,
        "sampling_model": result.sampling_model, "sequence_axis": SEQUENCE_AXIS,
        "cost_basis": "INPUT_PROFIT_AS_SUPPLIED_NO_COST_RECALCULATION",
        "input_selection": "SUPPLIED_TRADES" if trades is not None else "CSV_PROFIT_COLUMN",
        "rng": "NUMPY_PCG64", "bootstrap_dependence": "IID_TRADES_ASSUMPTION",
        "runtime_versions": _runtime_versions(),
    }
    manifest = _evidence_manifest("monte-carlo", config, inputs, seed=result.seed)
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    summary_path = path / "summary.json"
    simulations_path = path / "simulations.csv"
    inputs_path = path / "inputs.json"
    simulations = pd.DataFrame(result.simulations)
    simulations.to_csv(simulations_path, index=False)
    inputs_path.write_text(_canonical_json(inputs), encoding="utf-8")
    summary = {
        "mode": "monte-carlo",
        "input_files": [str(trades_path)] if trades_path is not None else [],
        "seed": result.seed,
        "simulations": result.iterations,
        "classification": classification,
        "total_trades": len(source),
        "sample_status": sample_status,
        "probability_of_ruin": result.risk_of_ruin_pct,
        "fifth_percentile_return_pct": result.fifth_percentile_return_pct,
        "ninety_fifth_percentile_drawdown_pct": result.ninety_fifth_percentile_drawdown_pct,
        "reports_created": [str(summary_path), str(simulations_path), str(inputs_path)],
        "execution_attempted": False,
        "result": _jsonable(asdict(result) | {"simulations": []}),
        "evidence_version": EVIDENCE_VERSION,
        "evidence_scope": "CLOSED_TRADE_PNL_SEQUENCE_SIMULATION",
        "classification_scope": "OBSERVATIONAL_DIAGNOSTIC_ONLY",
        "effective_config": config,
        "probability_of_ruin_units": "PERCENT",
        "ruin_event": DRAWDOWN_EVENT,
        "upstream_provenance_status": "UNKNOWN",
        "operational_scenarios_tested": False,
        "promotion_eligible": False,
        "reference_time_policy": "FIXED_IDENTITY_ANCHOR_NOT_MARKET_TIME",
    }
    summary = manifest.attach(summary)
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _extract_profits(trades: Iterable[TradeResult | Mapping[str, Any] | float]) -> np.ndarray:
    profits: list[float] = []
    for trade in trades:
        if isinstance(trade, Real):
            profits.append(_finite_number(trade, "profit"))
        elif isinstance(trade, TradeResult):
            profits.append(_finite_number(trade.profit, "profit"))
        elif isinstance(trade, Mapping) and "profit" in trade:
            profits.append(_finite_number(trade["profit"], "profit"))
        else:
            raise ValueError("every input must contain a finite numeric profit")
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
    try:
        with np.errstate(over="raise", invalid="raise"):
            return {f"p{p}": _finite_number(float(np.percentile(arr, p)), "percentile") for p in (5, 50, 95)}
    except FloatingPointError as exc:
        raise ValueError("percentile arithmetic overflow") from exc


def _max_loss_run(profits: Iterable[float]) -> int:
    return max(_loss_runs(profits), default=0)


def _loss_runs(profits: Iterable[float]) -> list[int]:
    runs = []
    current = 0
    for profit in profits:
        if profit < 0:
            current += 1
        else:
            if current:
                runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number, not a boolean")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} cannot be represented as a finite float") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive_number(value: Any, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _integer(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _sequence_curve(profits: np.ndarray, balance: float) -> tuple[np.ndarray, np.ndarray]:
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            curve = np.concatenate(([balance], balance + np.cumsum(profits)))
            peaks = np.maximum.accumulate(curve)
            dd = (curve - peaks) / peaks * 100.0
            returns = (curve - balance) / balance * 100.0
    except FloatingPointError as exc:
        raise ValueError("sequence arithmetic overflow") from exc
    if not (np.isfinite(curve).all() and np.isfinite(dd).all() and np.isfinite(returns).all()):
        raise ValueError("sequence contains non-finite results")
    return curve, dd


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _runtime_versions() -> dict[str, str]:
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}


def _evidence_manifest(mode: str, config: Mapping[str, Any], inputs: Mapping[str, Any], *, seed: int | None = None) -> RunManifest:
    """A fixed identity anchor is not a synthetic historical event timestamp."""
    return RunManifest.build(
        mode=mode, config=config,
        dataset_hash=sha256(_canonical_json(inputs).encode("utf-8")).hexdigest(),
        seed=seed, clock=FrozenClock(datetime(1970, 1, 1, tzinfo=timezone.utc)),
    )


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

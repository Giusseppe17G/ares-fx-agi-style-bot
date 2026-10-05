"""Walk-forward orchestration with disjoint tests and purged trade evidence.

Callbacks retain their two-argument API. Frames include optional historical
warmup and ``attrs['walk_forward_context']`` with inclusive evaluation bounds.
Warmup is for indicators only: callbacks must suppress earlier entries. Only
trades fully contained in the evaluation interval count; callback metrics and
equity are rebuilt after purging. No callback receives later segment bars.

Programmatic warmup/purge defaults remain zero for compatibility. Calendar
research explicitly defaults to 250 warmup bars and one purged end bar. The
default parameter grid now holds execution costs fixed: cost stress belongs in
a separate run and cannot be selected as strategy performance. This module
does not certify external callback logic, data provenance or final holdout use.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

from .backtester import (
    BacktestOutcome,
    Backtester,
    BacktestMetrics,
    BacktestSettings,
    CostModel,
    build_equity_curve,
    calculate_metrics,
    generate_strategy_candidates,
    load_historical_csv,
)
from ..data_pipeline import resolve_historical_data
from ..config import BotConfig
from ..core.instruments import assumed_fx_spec


BacktestCallback = Callable[[pd.DataFrame, Mapping[str, Any]], BacktestOutcome]


@dataclass(frozen=True)
class WalkForwardFold:
    fold_index: int
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str
    best_parameters: Mapping[str, Any]
    train_metrics: BacktestMetrics
    validation_metrics: BacktestMetrics
    test_metrics: BacktestMetrics
    robust_score: float = 0.0
    classification: str = "WATCHLIST"
    reasons: tuple[str, ...] = ()
    temporal_audit: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WalkForwardResult:
    folds: tuple[WalkForwardFold, ...]
    aggregate_test_metrics: BacktestMetrics
    selection_metric: str
    classification: str = "WATCHLIST"
    reports_created: tuple[str, ...] = ()
    temporal_policy: str = "DISJOINT_TEST_PURGED_OUTCOMES_V1"


@dataclass(frozen=True)
class WalkForwardSettings:
    """Calendar-based walk-forward settings."""

    train_days: int = 90
    validation_days: int = 30
    test_days: int = 30
    step_days: int = 30
    window_mode: str = "rolling"
    min_trades_train: int = 30
    min_trades_validation: int = 10
    min_trades_test: int = 10
    objective_metric: str = "expectancy_r"
    initial_balance: float = 10_000.0
    warmup_bars: int = 250
    purge_bars: int = 1

    def validate(self) -> None:
        for name in ("train_days", "validation_days", "test_days", "step_days"):
            _validate_count(getattr(self, name), name, positive=True)
        for name in ("warmup_bars", "purge_bars"):
            _validate_count(getattr(self, name), name)
        if self.step_days < self.test_days:
            raise ValueError("step_days must be at least test_days to prevent overlapping test windows")
        if self.window_mode.lower() not in {"rolling", "expanding"}:
            raise ValueError("window_mode must be rolling or expanding")
        if not math.isfinite(self.initial_balance) or self.initial_balance <= 0:
            raise ValueError("initial_balance must be finite and positive")


@dataclass(frozen=True)
class RobustScore:
    """Anti-overfitting score and promotion classification."""

    score: float
    classification: str
    reasons: tuple[str, ...]
    checks: Mapping[str, bool]


class WalkForwardOptimizer:
    """Evaluate parameter grids without using test data for selection."""

    def __init__(
        self,
        *,
        train_size: int,
        validation_size: int,
        test_size: int,
        step_size: int | None = None,
        selection_metric: str = "profit_factor",
        maximize: bool = True,
        warmup_size: int = 0,
        purge_size: int = 0,
        initial_balance: float = 10_000.0,
    ) -> None:
        for name, value in (("train_size", train_size), ("validation_size", validation_size), ("test_size", test_size)):
            _validate_count(value, name, positive=True)
        step = test_size if step_size is None else step_size
        _validate_count(step, "step_size", positive=True)
        _validate_count(warmup_size, "warmup_size")
        _validate_count(purge_size, "purge_size")
        if step < test_size:
            raise ValueError("step_size must be at least test_size to prevent overlapping test windows")
        if purge_size >= min(train_size, validation_size, test_size):
            raise ValueError("purge_size must leave rows in every evaluation window")
        if not math.isfinite(initial_balance) or initial_balance <= 0:
            raise ValueError("initial_balance must be finite and positive")
        self.train_size = train_size
        self.validation_size = validation_size
        self.test_size = test_size
        self.step_size = step
        self.selection_metric = selection_metric
        self.maximize = maximize
        self.warmup_size = warmup_size
        self.purge_size = purge_size
        self.initial_balance = initial_balance

    def run(
        self,
        candles: pd.DataFrame,
        parameter_grid: Iterable[Mapping[str, Any]],
        backtest_callback: BacktestCallback,
    ) -> WalkForwardResult:
        params = [dict(item) for item in parameter_grid]
        if not params:
            raise ValueError("parameter_grid cannot be empty")
        _validate_parameter_grid(params)
        bars = _normalize_for_split(candles)
        folds: list[WalkForwardFold] = []
        all_test_trades: list[Any] = []
        start = 0
        fold_index = 0
        window = self.train_size + self.validation_size + self.test_size
        while start + window <= len(bars):
            train_end = start + self.train_size
            validation_end = train_end + self.validation_size
            train, validation, test = (
                _window_input(bars, first, stop, stage=stage, warmup=self.warmup_size,
                              purge=self.purge_size, initial_balance=self.initial_balance)
                for first, stop, stage in ((start, train_end, "train"),
                                          (train_end, validation_end, "validation"),
                                          (validation_end, validation_end + self.test_size, "test"))
            )
            scored: list[tuple[float, Mapping[str, Any], BacktestOutcome, BacktestOutcome]] = []
            for candidate_params in params:
                train_outcome = _scoped_outcome(backtest_callback(train.copy(), dict(candidate_params)), train)
                validation_outcome = _scoped_outcome(backtest_callback(validation.copy(), dict(candidate_params)), validation)
                score = _metric_value(validation_outcome.metrics, self.selection_metric)
                scored.append((score, candidate_params, train_outcome, validation_outcome))
            best = sorted(scored, key=lambda item: item[0], reverse=self.maximize)[0]
            _, best_params, train_outcome, validation_outcome = best
            test_outcome = _scoped_outcome(backtest_callback(test.copy(), dict(best_params)), test)
            all_test_trades.extend(test_outcome.trades)
            folds.append(
                WalkForwardFold(
                    fold_index=fold_index,
                    train_start=_first_ts(train),
                    train_end=_last_ts(train),
                    validation_start=_first_ts(validation),
                    validation_end=_last_ts(validation),
                    test_start=_first_ts(test),
                    test_end=_last_ts(test),
                    best_parameters=dict(best_params),
                    train_metrics=train_outcome.metrics,
                    validation_metrics=validation_outcome.metrics,
                    test_metrics=test_outcome.metrics,
                    temporal_audit=_temporal_audit(train, validation, test, train_outcome, validation_outcome, test_outcome),
                )
            )
            fold_index += 1
            start += self.step_size
        if not folds:
            raise ValueError("not enough rows to create a walk-forward fold")
        aggregate = calculate_metrics(all_test_trades, initial_balance=self.initial_balance)
        return WalkForwardResult(
            folds=tuple(folds),
            aggregate_test_metrics=aggregate,
            selection_metric=self.selection_metric,
        )


def robust_validation_score(
    *,
    train_metrics: BacktestMetrics,
    validation_metrics: BacktestMetrics,
    test_metrics: BacktestMetrics,
    min_trades_train: int = 30,
    min_trades_validation: int = 10,
    min_trades_test: int = 10,
    profit_concentration_ok: bool = True,
    cost_sensitivity_ok: bool = True,
) -> RobustScore:
    """Score validation evidence while penalizing overfit-looking results."""

    checks = {
        "train_sample": train_metrics.trades_total >= min_trades_train,
        "validation_sample": validation_metrics.trades_total >= min_trades_validation,
        "test_sample": test_metrics.trades_total >= min_trades_test,
        "test_positive": test_metrics.average_r > 0 and test_metrics.net_profit > 0,
        "drawdown": abs(test_metrics.max_drawdown_pct) < 12.0,
        "profit_factor": 1.05 < test_metrics.profit_factor < 5.0,
        "pf_not_suspicious": not (test_metrics.profit_factor > 3.0 and test_metrics.trades_total < 100),
        "deterioration": _metric_ratio(test_metrics.average_r, train_metrics.average_r) >= -0.5,
        "profit_concentration": profit_concentration_ok,
        "cost_sensitivity": cost_sensitivity_ok,
    }
    score = 100.0
    penalties = {
        "train_sample": 16,
        "validation_sample": 14,
        "test_sample": 18,
        "test_positive": 20,
        "drawdown": 12,
        "profit_factor": 10,
        "pf_not_suspicious": 8,
        "deterioration": 14,
        "profit_concentration": 10,
        "cost_sensitivity": 12,
    }
    reasons: list[str] = []
    for name, passed in checks.items():
        if not passed:
            score -= penalties[name]
            reasons.append(f"failed: {name}")
    score = max(0.0, min(100.0, score))
    if score >= 80 and all(checks.values()):
        classification = "APPROVED_FOR_SHADOW_OBSERVATION"
    elif score >= 45 and checks["test_positive"]:
        classification = "WATCHLIST"
    else:
        classification = "REJECTED"
    return RobustScore(score=score, classification=classification, reasons=tuple(reasons) or ("robust score passed",), checks=checks)


def run_walk_forward_for_symbols(
    *,
    data_dir: str | Path,
    symbols: Iterable[str],
    report_dir: str | Path | None = None,
    settings: WalkForwardSettings | None = None,
    parameter_grid: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run calendar walk-forward validation for one or more symbols."""

    cfg = settings or WalkForwardSettings()
    cfg.validate()
    params = [dict(item) for item in (_default_parameter_grid() if parameter_grid is None else parameter_grid)]
    if not params:
        raise ValueError("parameter_grid cannot be empty")
    _validate_parameter_grid(params)
    all_windows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    by_symbol_rows: list[dict[str, Any]] = []
    input_files: list[str] = []
    classifications: list[str] = []
    for symbol in [item.strip().upper() for item in symbols if item.strip()]:
        path = _find_history_csv(Path(data_dir), symbol)
        input_files.append(str(path))
        candles, _quality = load_historical_csv(path, symbol=symbol, timeframe="M5")
        candles = candles.sort_values("timestamp").reset_index(drop=True)
        windows = _calendar_windows(candles, cfg)
        symbol_test_trades: list[Any] = []
        for index, (train, validation, test) in enumerate(windows):
            scored: list[tuple[float, Mapping[str, Any], BacktestOutcome, BacktestOutcome]] = []
            for item in params:
                train_outcome = _scoped_outcome(_run_param_backtest(train.copy(), symbol, dict(item)), train)
                validation_outcome = _scoped_outcome(_run_param_backtest(validation.copy(), symbol, dict(item)), validation)
                score = _objective_value(validation_outcome.metrics, cfg.objective_metric)
                scored.append((score, item, train_outcome, validation_outcome))
            best = sorted(scored, key=lambda row: row[0], reverse=True)[0]
            _score, best_params, train_outcome, validation_outcome = best
            test_outcome = _scoped_outcome(_run_param_backtest(test.copy(), symbol, dict(best_params)), test)
            symbol_test_trades.extend(test_outcome.trades)
            robust = robust_validation_score(
                train_metrics=train_outcome.metrics,
                validation_metrics=validation_outcome.metrics,
                test_metrics=test_outcome.metrics,
                min_trades_train=cfg.min_trades_train,
                min_trades_validation=cfg.min_trades_validation,
                min_trades_test=cfg.min_trades_test,
            )
            classifications.append(robust.classification)
            selected_rows.append({"symbol": symbol, "window": index, **dict(best_params)})
            all_windows.append(
                {
                    "symbol": symbol,
                    "window": index,
                    "train_start": _first_ts(train),
                    "train_end": _last_ts(train),
                    "validation_start": _first_ts(validation),
                    "validation_end": _last_ts(validation),
                    "test_start": _first_ts(test),
                    "test_end": _last_ts(test),
                    "selected_params": json.dumps(dict(best_params), sort_keys=True),
                    "train_trades": train_outcome.metrics.trades_total,
                    "validation_trades": validation_outcome.metrics.trades_total,
                    "test_trades": test_outcome.metrics.trades_total,
                    "test_profit_factor": test_outcome.metrics.profit_factor,
                    "test_expectancy_r": test_outcome.metrics.average_r,
                    "test_max_drawdown_pct": test_outcome.metrics.max_drawdown_pct,
                    "robust_score": robust.score,
                    "classification": robust.classification,
                    "reasons": "; ".join(robust.reasons),
                    "temporal_audit": json.dumps(_temporal_audit(train, validation, test, train_outcome, validation_outcome, test_outcome), sort_keys=True),
                }
            )
        aggregate = calculate_metrics(symbol_test_trades, initial_balance=cfg.initial_balance)
        symbol_classification = _combine_classifications([row["classification"] for row in all_windows if row["symbol"] == symbol])
        by_symbol_rows.append(
            {
                "symbol": symbol,
                "windows": len(windows),
                "test_trades": aggregate.trades_total,
                "test_profit_factor": aggregate.profit_factor,
                "test_expectancy_r": aggregate.average_r,
                "test_max_drawdown_pct": aggregate.max_drawdown_pct,
                "classification": symbol_classification,
            }
        )
    final_classification = _combine_classifications(classifications)
    summary = {
        "mode": "walk-forward",
        "input_files": input_files,
        "symbols_tested": len(by_symbol_rows),
        "windows": len(all_windows),
        "classification": final_classification,
        "execution_attempted": False,
        "reports_created": [],
        "temporal_policy": "DISJOINT_TEST_PURGED_OUTCOMES_V1",
        "warmup_bars": cfg.warmup_bars,
        "purge_bars": cfg.purge_bars,
        "test_used_for_selection": False,
        "configurations_tested": len(params),
        "parameter_grid": params,
        "cost_scenarios_optimized": False,
        "operationally_eligible": False,
    }
    if report_dir is not None:
        reports = write_walk_forward_reports(
            summary=summary,
            windows=pd.DataFrame(all_windows),
            selected_params=pd.DataFrame(selected_rows),
            by_symbol=pd.DataFrame(by_symbol_rows),
            report_dir=report_dir,
        )
        summary["reports_created"] = reports
    return summary


def write_walk_forward_reports(
    *,
    summary: Mapping[str, Any],
    windows: pd.DataFrame,
    selected_params: pd.DataFrame,
    by_symbol: pd.DataFrame,
    report_dir: str | Path,
) -> list[str]:
    """Write walk-forward JSON/CSV artifacts."""

    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    files = {
        "summary": path / "summary.json",
        "windows": path / "windows.csv",
        "selected_params": path / "selected_params.csv",
        "by_symbol": path / "by_symbol.csv",
    }
    files["summary"].write_text(json.dumps(_jsonable(dict(summary)), indent=2, sort_keys=True), encoding="utf-8")
    windows.to_csv(files["windows"], index=False)
    selected_params.to_csv(files["selected_params"], index=False)
    by_symbol.to_csv(files["by_symbol"], index=False)
    return [str(item) for item in files.values()]


def _normalize_for_split(candles: pd.DataFrame) -> pd.DataFrame:
    bars = candles.copy()
    if "timestamp" not in bars.columns:
        if isinstance(bars.index, pd.DatetimeIndex):
            bars = bars.reset_index().rename(columns={bars.index.name or "index": "timestamp"})
        else:
            raise ValueError("candles require timestamp column or DatetimeIndex")
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    if bars.empty or bars["timestamp"].isna().any():
        raise ValueError("walk-forward requires non-empty valid timestamps")
    if bars["timestamp"].duplicated().any():
        raise ValueError("walk-forward timestamps must be unique")
    return bars.sort_values("timestamp").reset_index(drop=True)


def _metric_value(metrics: BacktestMetrics, metric_name: str) -> float:
    value = getattr(metrics, metric_name)
    if value is None:
        raise ValueError("selection metric is unavailable")
    value = float(value)
    if math.isnan(value):
        raise ValueError("selection metric must not be NaN")
    return value


def _objective_value(metrics: BacktestMetrics, metric_name: str) -> float:
    normalized = metric_name.strip().lower()
    if normalized == "expectancy_r":
        return metrics.average_r
    if normalized == "profit_factor":
        return metrics.profit_factor if not math.isinf(metrics.profit_factor) else 10.0
    if normalized == "max_drawdown_pct":
        return -abs(metrics.max_drawdown_pct)
    if normalized in {"score", "composite"}:
        pf = min(metrics.profit_factor if not math.isinf(metrics.profit_factor) else 5.0, 5.0)
        return metrics.average_r * 50.0 + pf * 10.0 - abs(metrics.max_drawdown_pct)
    return _metric_value(metrics, metric_name)


def _first_ts(frame: pd.DataFrame) -> str:
    return str(frame.attrs.get("walk_forward_context", {}).get("evaluation_start_utc") or pd.Timestamp(frame.iloc[0]["timestamp"]).isoformat())


def _last_ts(frame: pd.DataFrame) -> str:
    return str(frame.attrs.get("walk_forward_context", {}).get("evaluation_end_utc") or pd.Timestamp(frame.iloc[-1]["timestamp"]).isoformat())


def _metric_ratio(test_value: float, train_value: float) -> float:
    if train_value == 0:
        return 1.0 if test_value >= 0 else -1.0
    return float(test_value / abs(train_value))


def _default_parameter_grid() -> tuple[Mapping[str, Any], ...]:
    return (
        {"spread_points": 10.0, "slippage_points": 1.0, "trailing_distance_points": 60},
        {"spread_points": 10.0, "slippage_points": 1.0, "trailing_distance_points": 80},
        {"spread_points": 10.0, "slippage_points": 1.0, "trailing_distance_points": 100},
    )


def _find_history_csv(data_dir: Path, symbol: str) -> Path:
    resolution = resolve_historical_data(data_dir, symbol=symbol, timeframe="M5", min_bars=0)
    if resolution.found:
        return Path(resolution.path)
    raise FileNotFoundError(f"no M5 CSV found for {symbol} in {data_dir}: {resolution.reason}")


def _calendar_windows(
    candles: pd.DataFrame,
    settings: WalkForwardSettings,
) -> list[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    settings.validate()
    bars = _normalize_for_split(candles)
    start = pd.Timestamp(bars["timestamp"].min())
    last = pd.Timestamp(bars["timestamp"].max())
    windows: list[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = []
    cursor = start
    while True:
        train_start = start if settings.window_mode.lower() == "expanding" else cursor
        train_end = cursor + pd.Timedelta(days=settings.train_days)
        validation_end = train_end + pd.Timedelta(days=settings.validation_days)
        test_end = validation_end + pd.Timedelta(days=settings.test_days)
        if test_end > last + pd.Timedelta(seconds=1):
            break
        train = bars[(bars["timestamp"] >= train_start) & (bars["timestamp"] < train_end)]
        validation = bars[(bars["timestamp"] >= train_end) & (bars["timestamp"] < validation_end)]
        test = bars[(bars["timestamp"] >= validation_end) & (bars["timestamp"] < test_end)]
        if not train.empty and not validation.empty and not test.empty:
            windows.append(tuple(
                _window_input(bars, int(part.index[0]), int(part.index[-1]) + 1,
                              stage=stage, warmup=settings.warmup_bars, purge=settings.purge_bars,
                              initial_balance=settings.initial_balance)
                for part, stage in ((train, "train"), (validation, "validation"), (test, "test"))
            ))
        cursor += pd.Timedelta(days=settings.step_days)
    if not windows:
        raise ValueError("not enough data to create walk-forward windows")
    return windows


def _run_param_backtest(frame: pd.DataFrame, symbol: str, params: Mapping[str, Any]) -> BacktestOutcome:
    context = frame.attrs.get("walk_forward_context", {})
    settings = BacktestSettings(
        initial_balance=float(context.get("initial_balance", 10_000.0)),
        cost_model=CostModel(
            spread_points=float(params.get("spread_points", 10.0)),
            slippage_points=float(params.get("slippage_points", 1.0)),
            commission_per_lot_round_turn=float(params.get("commission", 0.0)),
            max_spread_points=float(params.get("max_spread_points", 25.0)),
        ),
        break_even_trigger_r=float(params.get("break_even_trigger_r", 0.6)),
        trailing_start_r=float(params.get("trailing_start_r", 0.8)),
        trailing_distance_points=float(params.get("trailing_distance_points", 80)),
        max_bars_in_trade=int(params.get("max_bars_in_trade", 96)),
    )
    instrument = assumed_fx_spec(symbol)
    settings = replace(settings, cost_model=settings.cost_model.with_instrument(instrument))
    candidates = generate_strategy_candidates(
        frame, symbol=symbol, timeframe="M5", config=BotConfig(),
        point=instrument.point, instrument=instrument,
    )
    if context:
        first, last = pd.Timestamp(context["evaluation_start_utc"]), pd.Timestamp(context["evaluation_end_utc"])
        candidates = tuple(candidate for candidate in candidates
                           if candidate.available_at_utc is not None
                           and first <= pd.Timestamp(candidate.available_at_utc) <= last)
    return Backtester(settings).run(frame, candidates)


def _validate_count(value: int, name: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise ValueError(f"{name} must be a {'positive' if positive else 'non-negative'} integer")


def _validate_parameter_grid(params: list[Mapping[str, Any]]) -> None:
    """Execution costs are scenario assumptions, never tunable strategy alpha."""
    defaults = {"spread_points": 10.0, "slippage_points": 1.0, "commission": 0.0, "max_spread_points": 25.0}
    reference = {name: float(params[0].get(name, value)) for name, value in defaults.items()}
    if not all(math.isfinite(value) and value >= 0 for value in reference.values()):
        raise ValueError("walk-forward cost assumptions must be finite and non-negative")
    for candidate in params[1:]:
        costs = {name: float(candidate.get(name, value)) for name, value in defaults.items()}
        if costs != reference:
            raise ValueError("execution costs must be fixed across the parameter grid; use a separate stress run")


def _window_input(
    bars: pd.DataFrame, first: int, stop: int, *, stage: str,
    warmup: int, purge: int, initial_balance: float,
) -> pd.DataFrame:
    """Attach evaluation bounds while exposing only historical warmup to a callback.

    Custom callbacks must use the attrs context to suppress entries in warmup.
    Outcome sanitation is a second boundary: it cannot undo a callback that
    independently reads future files or fits indicators using external data.
    """
    final = stop - purge
    if final <= first:
        raise ValueError("purge must leave rows in each evaluation window")
    history_start = max(0, first - warmup)
    result = bars.iloc[history_start:final].copy()
    result.attrs["walk_forward_context"] = {
        "stage": stage,
        "evaluation_start_utc": pd.Timestamp(bars.iloc[first].timestamp).isoformat(),
        "evaluation_end_utc": pd.Timestamp(bars.iloc[final - 1].timestamp).isoformat(),
        "evaluation_end_inclusive": True,
        "evaluation_rows": final - first,
        "warmup_rows": first - history_start,
        "purge_rows": purge,
        "initial_balance": initial_balance,
        "warmup_for_indicators_only": True,
        "test_used_for_selection": False,
    }
    return result


def _scoped_outcome(outcome: BacktestOutcome, frame: pd.DataFrame) -> BacktestOutcome:
    """Recompute evidence solely from trades contained in the evaluable segment."""
    context = frame.attrs["walk_forward_context"]
    first = pd.Timestamp(context["evaluation_start_utc"])
    last = pd.Timestamp(context["evaluation_end_utc"])
    balance = float(context["initial_balance"])
    valid = []
    rejected = list(outcome.rejected_candidates)
    for trade in outcome.trades:
        reason = ""
        try:
            entry, exit_time = pd.Timestamp(trade.entry_time), pd.Timestamp(trade.exit_time)
            if pd.isna(entry) or pd.isna(exit_time) or entry.tzinfo is None or exit_time.tzinfo is None or exit_time < entry:
                reason = "WF_INVALID_TRADE_TIMESTAMPS"
            elif entry < first:
                reason = "WF_WARMUP_ENTRY"
            elif entry > last or exit_time > last:
                reason = "WF_CROSS_BOUNDARY"
            elif trade.exit_reason == "END_OF_DATA" and (
                outcome.settings.max_bars_in_trade is None
                or trade.duration_bars < outcome.settings.max_bars_in_trade
            ):
                # The bar simulator uses the same reason for a completed known
                # max-holding horizon and for an unknown exit cut by data end.
                reason = "WF_TRUNCATED_EXIT"
            elif not all(math.isfinite(value) for value in (trade.profit, trade.r_multiple, trade.duration_seconds, trade.mae, trade.mfe)):
                reason = "WF_INVALID_TRADE_METRICS"
        except (TypeError, ValueError, OverflowError):
            reason = "WF_INVALID_TRADE_TIMESTAMPS"
        if reason:
            rejected.append({"signal_id": trade.signal_id, "symbol": trade.symbol,
                             "timestamp": str(trade.entry_time), "reason": reason})
        else:
            valid.append(trade)
    valid.sort(key=lambda trade: (pd.Timestamp(trade.exit_time), pd.Timestamp(trade.entry_time), trade.signal_id))
    evaluation = frame.loc[frame.timestamp.between(first, last)].copy()
    equity = build_equity_curve(valid, initial_balance=balance, candles=evaluation)
    exposed = pd.Series(False, index=evaluation.index)
    for trade in valid:
        exposed |= evaluation.timestamp.between(pd.Timestamp(trade.entry_time), pd.Timestamp(trade.exit_time))
    metrics = calculate_metrics(valid, initial_balance=balance, equity_curve=equity,
                                total_bars=len(evaluation), exposed_bars=int(exposed.sum()))
    return replace(outcome, settings=replace(outcome.settings, initial_balance=balance),
                   trades=tuple(valid), rejected_candidates=tuple(rejected), metrics=metrics, equity_curve=equity)


def _temporal_audit(train, validation, test, train_outcome, validation_outcome, test_outcome) -> dict[str, Any]:
    results = {}
    for stage, frame, outcome in (("train", train, train_outcome), ("validation", validation, validation_outcome), ("test", test, test_outcome)):
        counts: dict[str, int] = {}
        for rejected in outcome.rejected_candidates:
            reason = str(rejected.get("reason", ""))
            if reason.startswith("WF_"):
                counts[reason] = counts.get(reason, 0) + 1
        results[stage] = {**frame.attrs["walk_forward_context"], "purged_outcomes": counts}
    return results


def _combine_classifications(values: Iterable[str]) -> str:
    labels = set(values)
    if not labels:
        return "REJECTED"
    if "REJECTED" in labels:
        return "REJECTED"
    if "WATCHLIST" in labels:
        return "WATCHLIST"
    return "APPROVED_FOR_SHADOW_OBSERVATION"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value

"""Walk-forward train/validation/test orchestration."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

from .backtester import (
    BacktestOutcome,
    BacktestMetrics,
    BacktestSettings,
    CostModel,
    calculate_metrics,
    load_historical_csv,
    run_strategy_backtest,
)


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


@dataclass(frozen=True)
class WalkForwardResult:
    folds: tuple[WalkForwardFold, ...]
    aggregate_test_metrics: BacktestMetrics
    selection_metric: str
    classification: str = "WATCHLIST"
    reports_created: tuple[str, ...] = ()


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
    ) -> None:
        if train_size <= 0 or validation_size <= 0 or test_size <= 0:
            raise ValueError("train, validation and test sizes must be positive")
        self.train_size = train_size
        self.validation_size = validation_size
        self.test_size = test_size
        self.step_size = step_size or test_size
        self.selection_metric = selection_metric
        self.maximize = maximize

    def run(
        self,
        candles: pd.DataFrame,
        parameter_grid: Iterable[Mapping[str, Any]],
        backtest_callback: BacktestCallback,
    ) -> WalkForwardResult:
        params = [dict(item) for item in parameter_grid]
        if not params:
            raise ValueError("parameter_grid cannot be empty")
        bars = _normalize_for_split(candles)
        folds: list[WalkForwardFold] = []
        all_test_trades: list[Any] = []
        start = 0
        fold_index = 0
        window = self.train_size + self.validation_size + self.test_size
        while start + window <= len(bars):
            train = bars.iloc[start : start + self.train_size]
            validation = bars.iloc[
                start + self.train_size : start + self.train_size + self.validation_size
            ]
            test = bars.iloc[
                start
                + self.train_size
                + self.validation_size : start
                + self.train_size
                + self.validation_size
                + self.test_size
            ]
            scored: list[tuple[float, Mapping[str, Any], BacktestOutcome, BacktestOutcome]] = []
            for candidate_params in params:
                train_outcome = backtest_callback(train.copy(), candidate_params)
                validation_outcome = backtest_callback(validation.copy(), candidate_params)
                score = _metric_value(validation_outcome.metrics, self.selection_metric)
                scored.append((score, candidate_params, train_outcome, validation_outcome))
            best = sorted(scored, key=lambda item: item[0], reverse=self.maximize)[0]
            _, best_params, train_outcome, validation_outcome = best
            test_outcome = backtest_callback(test.copy(), best_params)
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
                )
            )
            fold_index += 1
            start += self.step_size
        if not folds:
            raise ValueError("not enough rows to create a walk-forward fold")
        aggregate = calculate_metrics(all_test_trades)
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
    params = [dict(item) for item in (parameter_grid or _default_parameter_grid())]
    if not params:
        raise ValueError("parameter_grid cannot be empty")
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
                train_outcome = _run_param_backtest(train, symbol, item)
                validation_outcome = _run_param_backtest(validation, symbol, item)
                score = _objective_value(validation_outcome.metrics, cfg.objective_metric)
                scored.append((score, item, train_outcome, validation_outcome))
            best = sorted(scored, key=lambda row: row[0], reverse=True)[0]
            _score, best_params, train_outcome, validation_outcome = best
            test_outcome = _run_param_backtest(test, symbol, best_params)
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
    return bars.sort_values("timestamp").reset_index(drop=True)


def _metric_value(metrics: BacktestMetrics, metric_name: str) -> float:
    value = getattr(metrics, metric_name)
    if value is None:
        return float("-inf")
    return float(value)


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
    return pd.Timestamp(frame.iloc[0]["timestamp"]).isoformat()


def _last_ts(frame: pd.DataFrame) -> str:
    return pd.Timestamp(frame.iloc[-1]["timestamp"]).isoformat()


def _metric_ratio(test_value: float, train_value: float) -> float:
    if train_value == 0:
        return 1.0 if test_value >= 0 else -1.0
    return float(test_value / abs(train_value))


def _default_parameter_grid() -> tuple[Mapping[str, Any], ...]:
    return (
        {"spread_points": 8.0, "slippage_points": 0.5, "trailing_distance_points": 60},
        {"spread_points": 10.0, "slippage_points": 1.0, "trailing_distance_points": 80},
        {"spread_points": 12.0, "slippage_points": 1.5, "trailing_distance_points": 100},
    )


def _find_history_csv(data_dir: Path, symbol: str) -> Path:
    for candidate in (
        data_dir / f"{symbol}_M5.csv",
        data_dir / f"{symbol}.csv",
        data_dir / f"{symbol.lower()}_m5.csv",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no M5 CSV found for {symbol} in {data_dir}")


def _calendar_windows(
    candles: pd.DataFrame,
    settings: WalkForwardSettings,
) -> list[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
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
            windows.append((train.copy(), validation.copy(), test.copy()))
        cursor += pd.Timedelta(days=settings.step_days)
    if not windows:
        raise ValueError("not enough data to create walk-forward windows")
    return windows


def _run_param_backtest(frame: pd.DataFrame, symbol: str, params: Mapping[str, Any]) -> BacktestOutcome:
    settings = BacktestSettings(
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
    return run_strategy_backtest(frame, symbol=symbol, settings=settings)


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

"""Run strategy ensemble against simple baseline strategies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from ..backtesting import BacktestSettings, Backtester, CostModel, load_historical_csv, run_strategy_backtest
from ..data_pipeline import cost_for_symbol
from .baseline_strategies import BASELINES, generate_baseline_candidates


def run_benchmarks(
    *,
    data_dir: str | Path,
    symbols: Iterable[str],
    report_dir: str | Path,
    broker_cost_profile: Mapping[str, Any] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Compare ensemble vs simple baselines after costs."""

    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    input_files: list[str] = []
    for symbol in [item.strip().upper() for item in symbols if item.strip()]:
        csv_path = _find_csv(Path(data_dir), symbol)
        input_files.append(str(csv_path))
        candles, _quality = load_historical_csv(csv_path, symbol=symbol, timeframe="M5")
        spread = cost_for_symbol(broker_cost_profile, symbol, fallback=10.0)
        settings = BacktestSettings(cost_model=CostModel(spread_points=spread, slippage_points=1.0, max_spread_points=max(25.0, spread * 2)))
        ensemble = run_strategy_backtest(candles, symbol=symbol, settings=settings)
        rows.append(_metrics_row(symbol, "STRATEGY_ENSEMBLE", ensemble.metrics))
        frequency = max(12, int(len(candles) / max(1, ensemble.metrics.trades_total or 10)))
        for baseline in BASELINES:
            candidates = generate_baseline_candidates(baseline, candles, symbol=symbol, frequency=frequency, seed=seed)
            outcome = Backtester(settings).run(candles, candidates)
            rows.append(_metrics_row(symbol, baseline, outcome.metrics))
    frame = pd.DataFrame(rows)
    comparison = _comparison(frame)
    classification = "WATCHLIST" if (comparison["baselines_beaten_global"] >= 3 and comparison["symbols_with_edge"] > 0) else "REJECTED"
    summary_path = output / "summary.json"
    results_path = output / "benchmark_results.csv"
    comparison_path = output / "comparison.csv"
    frame.to_csv(results_path, index=False)
    pd.DataFrame([comparison]).to_csv(comparison_path, index=False)
    summary = {
        "mode": "benchmark",
        "input_files": input_files,
        "classification": classification,
        "baselines_beaten_global": comparison["baselines_beaten_global"],
        "reports_created": [str(summary_path), str(results_path), str(comparison_path)],
        "execution_attempted": False,
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _find_csv(data_dir: Path, symbol: str) -> Path:
    for candidate in (data_dir / f"{symbol}_M5.csv", data_dir / f"{symbol}.csv"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no M5 CSV found for {symbol}")


def _metrics_row(symbol: str, strategy: str, metrics: Any) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "net_return_pct": metrics.total_return_pct,
        "profit_factor": metrics.profit_factor,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "expectancy_r": metrics.average_r,
        "sharpe": metrics.sharpe,
        "sortino": metrics.sortino,
        "winrate": metrics.win_rate_pct,
        "max_consecutive_losses": metrics.max_consecutive_losses,
        "exposure_time": metrics.exposure_time_pct,
        "trades_count": metrics.trades_total,
    }


def _comparison(frame: pd.DataFrame) -> dict[str, Any]:
    beaten_total = 0
    symbols_with_edge = 0
    for symbol, group in frame.groupby("symbol"):
        ensemble = group[group["strategy"] == "STRATEGY_ENSEMBLE"].iloc[0]
        baselines = group[group["strategy"] != "STRATEGY_ENSEMBLE"]
        beaten = int((ensemble["expectancy_r"] > baselines["expectancy_r"]).sum())
        beaten_total += beaten
        if beaten >= 3:
            symbols_with_edge += 1
    symbol_count = int(frame["symbol"].nunique())
    return {
        "symbols": symbol_count,
        "baselines_beaten_global": int(beaten_total / max(1, symbol_count)),
        "symbols_with_edge": symbols_with_edge,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and value in {float("inf"), float("-inf")}:
        return "Infinity" if value > 0 else "-Infinity"
    return value

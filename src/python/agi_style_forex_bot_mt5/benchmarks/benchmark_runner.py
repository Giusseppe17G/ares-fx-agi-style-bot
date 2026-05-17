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
    skipped_rows: list[dict[str, Any]] = []
    input_files: list[str] = []
    for symbol in _coerce_symbols(symbols):
        csv_path = _find_csv(Path(data_dir), symbol)
        if csv_path is None:
            skipped_rows.append(_skipped_row(symbol, "ALL", "missing M5 CSV"))
            continue
        input_files.append(str(csv_path))
        try:
            candles, _quality = load_historical_csv(csv_path, symbol=symbol, timeframe="M5")
        except Exception as exc:
            skipped_rows.append(_skipped_row(symbol, "ALL", f"invalid historical CSV: {exc}"))
            continue
        if len(candles) < 60:
            skipped_rows.append(_skipped_row(symbol, "ALL", "insufficient bars for benchmark"))
            continue
        spread = cost_for_symbol(broker_cost_profile, symbol, fallback=10.0)
        settings = BacktestSettings(cost_model=CostModel(spread_points=spread, slippage_points=1.0, max_spread_points=max(25.0, spread * 2)))
        try:
            ensemble = run_strategy_backtest(candles, symbol=symbol, settings=settings)
            rows.append(_metrics_row(symbol, "STRATEGY_ENSEMBLE", ensemble.metrics, status="OK"))
        except Exception as exc:
            skipped_rows.append(_skipped_row(symbol, "STRATEGY_ENSEMBLE", f"ensemble benchmark failed: {exc}"))
            ensemble = None
        ensemble_trades = int(ensemble.metrics.trades_total) if ensemble is not None else 10
        frequency = max(12, int(len(candles) / max(1, ensemble_trades or 10)))
        for baseline in BASELINES:
            try:
                candidates = generate_baseline_candidates(baseline, candles, symbol=symbol, frequency=frequency, seed=seed)
                outcome = Backtester(settings).run(candles, candidates)
                rows.append(_metrics_row(symbol, baseline, outcome.metrics, status="OK"))
            except Exception as exc:
                skipped_rows.append(_skipped_row(symbol, baseline, str(exc)))
    frame = pd.DataFrame(rows)
    skipped_frame = pd.DataFrame(skipped_rows)
    comparison = _comparison(frame)
    baselines_run = int(len(frame[frame.get("strategy", pd.Series(dtype=str)) != "STRATEGY_ENSEMBLE"])) if not frame.empty else 0
    baselines_skipped = int(len(skipped_frame))
    if frame.empty or comparison["symbols"] == 0:
        classification = "NEEDS_MORE_DATA"
    elif baselines_run == 0:
        classification = "NEEDS_MORE_DATA"
    else:
        classification = "WATCHLIST" if (comparison["baselines_beaten_global"] >= 3 and comparison["symbols_with_edge"] > 0) else "REJECTED"
    summary_path = output / "summary.json"
    results_path = output / "benchmark_results.csv"
    comparison_path = output / "comparison.csv"
    by_symbol_path = output / "by_symbol.csv"
    baselines_path = output / "baselines.csv"
    frame.to_csv(results_path, index=False)
    _by_symbol_frame(frame, skipped_frame).to_csv(by_symbol_path, index=False)
    _baselines_frame(frame, skipped_frame).to_csv(baselines_path, index=False)
    pd.DataFrame([comparison]).to_csv(comparison_path, index=False)
    summary = {
        "mode": "benchmark",
        "input_files": input_files,
        "classification": classification,
        "baselines_beaten_global": comparison["baselines_beaten_global"],
        "baselines_run": baselines_run,
        "baselines_skipped": baselines_skipped,
        "reports_created": [str(summary_path), str(by_symbol_path), str(baselines_path), str(results_path), str(comparison_path)],
        "execution_attempted": False,
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _find_csv(data_dir: Path, symbol: str) -> Path | None:
    for candidate in (data_dir / f"{symbol}_M5.csv", data_dir / f"{symbol}.csv"):
        if candidate.exists():
            return candidate
    return None


def _coerce_symbols(symbols: Iterable[str] | str) -> tuple[str, ...]:
    parts = symbols.split(",") if isinstance(symbols, str) else list(symbols)
    return tuple(str(item).strip().upper() for item in parts if str(item).strip())


def _metrics_row(symbol: str, strategy: str, metrics: Any, *, status: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "status": status,
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


def _skipped_row(symbol: str, strategy: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "status": "SKIPPED",
        "skip_reason": reason,
        "net_return_pct": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
        "expectancy_r": 0.0,
        "sharpe": None,
        "sortino": None,
        "winrate": 0.0,
        "max_consecutive_losses": 0,
        "exposure_time": 0.0,
        "trades_count": 0,
    }


def _comparison(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty or "symbol" not in frame.columns or "strategy" not in frame.columns:
        return {"symbols": 0, "baselines_beaten_global": 0, "symbols_with_edge": 0}
    beaten_total = 0
    symbols_with_edge = 0
    for symbol, group in frame.groupby("symbol"):
        ensemble_rows = group[group["strategy"] == "STRATEGY_ENSEMBLE"]
        if ensemble_rows.empty:
            continue
        ensemble = ensemble_rows.iloc[0]
        baselines = group[group["strategy"] != "STRATEGY_ENSEMBLE"]
        if baselines.empty:
            continue
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


def _by_symbol_frame(frame: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([frame, skipped], ignore_index=True) if not skipped.empty else frame.copy()
    if combined.empty:
        return pd.DataFrame(columns=["symbol", "baselines_run", "baselines_skipped"])
    rows = []
    for symbol, group in combined.groupby("symbol"):
        rows.append(
            {
                "symbol": symbol,
                "baselines_run": int(((group["strategy"] != "STRATEGY_ENSEMBLE") & (group["status"] == "OK")).sum()),
                "baselines_skipped": int((group["status"] == "SKIPPED").sum()),
            }
        )
    return pd.DataFrame(rows)


def _baselines_frame(frame: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([frame, skipped], ignore_index=True) if not skipped.empty else frame.copy()
    if combined.empty:
        return pd.DataFrame(columns=["symbol", "strategy", "status", "skip_reason", "expectancy_r", "trades_count"])
    if "skip_reason" not in combined.columns:
        combined["skip_reason"] = ""
    return combined[["symbol", "strategy", "status", "skip_reason", "expectancy_r", "trades_count"]]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and value in {float("inf"), float("-inf")}:
        return "Infinity" if value > 0 else "-Infinity"
    return value

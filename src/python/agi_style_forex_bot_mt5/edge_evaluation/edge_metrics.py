"""Load and calculate fast edge metrics from existing artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..backtesting import calculate_metrics, classify_sample_size


@dataclass(frozen=True)
class EdgeMetricsBundle:
    """In-memory bundle used by edge selectors and report writers."""

    run_dir: Path | None
    run_id: str
    reports_root: Path
    compact_summary: Mapping[str, Any]
    backtest_summary: Mapping[str, Any]
    trades: pd.DataFrame
    blockers: pd.DataFrame
    classification: str
    global_metrics: Mapping[str, Any]
    by_symbol: pd.DataFrame
    by_strategy: pd.DataFrame
    by_session: pd.DataFrame
    by_regime: pd.DataFrame


def load_edge_metrics(*, runs_root: str | Path = "data/runs", reports_root: str | Path | None = None) -> EdgeMetricsBundle:
    """Load latest-run artifacts and compute metrics available without rerunning research."""

    run_dir = _latest_run_dir(Path(runs_root))
    root = Path(reports_root) if reports_root is not None else (run_dir / "reports" if run_dir else Path("data/reports"))
    compact = _read_json(run_dir / "final_summary_compact.json") if run_dir else {}
    backtest = _read_json(root / "backtests" / "summary.json")
    trades_path = root / "backtests" / "trades.csv"
    trades = _read_trades(trades_path)
    blockers = _load_blockers(root, backtest)
    run_id = str(compact.get("run_id") or (run_dir.name if run_dir else ""))
    if trades.empty:
        global_metrics = _empty_global_metrics()
        classification = "NEEDS_TRADES"
    else:
        global_metrics = _metrics_for_frame(trades)
        classification = "OK"
    by_symbol = _group_metrics(trades, "symbol")
    by_strategy = _group_metrics(_ensure_column(trades, "strategy_name", "UNKNOWN"), "strategy_name")
    by_session = _group_metrics(_ensure_column(trades, "session", "UNKNOWN"), "session")
    by_regime = _group_metrics(_ensure_column(trades, "regime", "UNKNOWN"), "regime")
    return EdgeMetricsBundle(
        run_dir=run_dir,
        run_id=run_id,
        reports_root=root,
        compact_summary=compact,
        backtest_summary=backtest,
        trades=trades,
        blockers=blockers,
        classification=classification,
        global_metrics=global_metrics,
        by_symbol=by_symbol,
        by_strategy=by_strategy,
        by_session=by_session,
        by_regime=by_regime,
    )


def _latest_run_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    candidates = [path for path in root.iterdir() if path.is_dir() and (path / "reports").exists()]
    return sorted(candidates, key=lambda path: (path.name, path.stat().st_mtime))[-1] if candidates else None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_trades()
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError):
        return _empty_trades()
    if frame.empty:
        return _empty_trades()
    for column in ("profit", "r_multiple", "duration_seconds"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["signal_id", "symbol", "strategy_name", "session", "regime", "profit", "r_multiple"])


def _metrics_for_frame(frame: pd.DataFrame) -> dict[str, Any]:
    records = frame.to_dict("records")
    metrics = calculate_metrics(records)
    return {
        "total_trades": metrics.trades_total,
        "sample_status": classify_sample_size(metrics.trades_total),
        "winrate": metrics.win_rate_pct,
        "profit_factor": metrics.profit_factor,
        "expectancy_r": metrics.average_r,
        "average_r": metrics.average_r,
        "net_profit": metrics.net_profit,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "return_pct": metrics.total_return_pct,
        "average_trade_duration": metrics.average_duration_seconds,
        "execution_attempted": False,
    }


def _empty_global_metrics() -> dict[str, Any]:
    return {
        "total_trades": 0,
        "sample_status": "LOW_SAMPLE",
        "winrate": 0.0,
        "profit_factor": 0.0,
        "expectancy_r": 0.0,
        "average_r": 0.0,
        "net_profit": 0.0,
        "max_drawdown_pct": 0.0,
        "return_pct": 0.0,
        "average_trade_duration": 0.0,
        "execution_attempted": False,
    }


def _group_metrics(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[column, "total_trades", "sample_status", "winrate", "profit_factor", "expectancy_r", "net_profit", "max_drawdown_pct", "return_pct"])
    rows: list[dict[str, Any]] = []
    for value, group in frame.groupby(column, dropna=False):
        metrics = _metrics_for_frame(group)
        rows.append({column: value, **metrics})
    return pd.DataFrame(rows).sort_values(column).reset_index(drop=True)


def _ensure_column(frame: pd.DataFrame, column: str, default: str) -> pd.DataFrame:
    copy = frame.copy()
    if column not in copy.columns:
        copy[column] = default
    copy[column] = copy[column].fillna(default).replace("", default)
    return copy


def _load_blockers(root: Path, backtest: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in backtest.get("top_blocking_reasons", []) if isinstance(backtest, Mapping) else []:
        if isinstance(item, Mapping):
            rows.append({"blocking_reason": item.get("blocking_reason", "UNKNOWN_BLOCKER"), "count": int(item.get("count", 1) or 1), "source": "backtest"})
    for path in (root / "calibration").glob("**/blocking_reasons.csv"):
        try:
            frame = pd.read_csv(path)
        except (OSError, pd.errors.EmptyDataError):
            continue
        for _, row in frame.iterrows():
            reason = row.get("blocking_reason", row.get("reason", "UNKNOWN_BLOCKER"))
            count = int(row.get("count", 1) or 1)
            rows.append({"blocking_reason": reason, "count": count, "source": "calibration"})
    for path in (root / "strategy_diagnostics").glob("**/*.json"):
        payload = _read_json(path)
        reasons = payload.get("blocking_reasons") or payload.get("metadata", {}).get("blocking_reasons", [])
        for reason in reasons if isinstance(reasons, list) else [reasons]:
            rows.append({"blocking_reason": str(reason or "UNKNOWN_BLOCKER"), "count": 1, "source": "strategy_diagnostics"})
    return pd.DataFrame(rows, columns=["blocking_reason", "count", "source"])

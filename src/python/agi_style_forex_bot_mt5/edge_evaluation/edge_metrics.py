"""Load and calculate fast edge metrics from existing artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from ..backtesting import calculate_metrics, classify_sample_size


@dataclass(frozen=True)
class EdgeMetricsBundle:
    """In-memory bundle used by edge selectors and report writers."""

    run_dir: Path | None
    run_id: str
    reports_root: Path
    compact_summary: Mapping[str, Any]
    final_summary: Mapping[str, Any]
    backtest_summary: Mapping[str, Any]
    trades: pd.DataFrame
    blockers: pd.DataFrame
    classification: str
    global_metrics: Mapping[str, Any]
    by_symbol: pd.DataFrame
    by_strategy: pd.DataFrame
    by_session: pd.DataFrame
    by_regime: pd.DataFrame


def load_edge_metrics(*, runs_root: str | Path = "data/runs", reports_root: str | Path | None = None, run_id: str | None = None) -> EdgeMetricsBundle:
    """Load latest-run artifacts and compute metrics available without rerunning research."""

    run_dir = _resolve_run_dir(Path(runs_root), run_id)
    root = Path(reports_root) if reports_root is not None else (run_dir / "reports" if run_dir else Path("data/reports"))
    compact = _read_json(run_dir / "final_summary_compact.json") if run_dir else {}
    final = _read_json(run_dir / "final_summary.json") if run_dir else {}
    backtest = _find_backtest_summary(root)
    trades = _read_first_trades(_candidate_trades_paths(root))
    summary_source = _summary_source(compact, final, backtest)
    blockers = _load_blockers(root, backtest, compact, final)
    resolved_run_id = str(compact.get("run_id") or final.get("run_id") or (run_dir.name if run_dir else ""))
    if trades.empty:
        global_metrics = _metrics_from_summaries(summary_source)
        classification = "COUNTS_ONLY" if int(global_metrics.get("total_trades", 0) or 0) > 0 else "NEEDS_TRADES"
    else:
        global_metrics = _metrics_for_frame(trades)
        global_metrics["metrics_source"] = "trades_csv"
        global_metrics["metrics_status"] = "FULL_EDGE_METRICS"
        global_metrics["missing_metrics"] = []
        classification = "OK"
    by_symbol = _group_metrics(trades, "symbol") if not trades.empty else _counts_frame(summary_source.get("trades_by_symbol"), "symbol")
    by_strategy = _group_metrics(_ensure_column(trades, "strategy_name", "UNKNOWN"), "strategy_name") if not trades.empty else _counts_frame(summary_source.get("trades_by_strategy"), "strategy_name")
    by_session = _group_metrics(_ensure_column(trades, "session", "UNKNOWN"), "session") if not trades.empty else _counts_frame(summary_source.get("trades_by_session"), "session")
    by_regime = _group_metrics(_ensure_column(trades, "regime", "UNKNOWN"), "regime") if not trades.empty else _counts_frame(summary_source.get("trades_by_regime"), "regime")
    return EdgeMetricsBundle(
        run_dir=run_dir,
        run_id=resolved_run_id,
        reports_root=root,
        compact_summary=compact,
        final_summary=final,
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


def _resolve_run_dir(root: Path, run_id: str | None) -> Path | None:
    if not root.exists():
        return None
    if run_id:
        exact = root / run_id
        return exact if exact.is_dir() else None
    candidates = [path for path in root.iterdir() if path.is_dir() and ((path / "reports").exists() or (path / "final_summary_compact.json").exists() or (path / "final_summary.json").exists())]
    return sorted(candidates, key=lambda path: (_run_mtime(path), path.name))[-1] if candidates else None


def _run_mtime(path: Path) -> float:
    files = [path / "final_summary_compact.json", path / "final_summary.json", path / "reports" / "backtests" / "trades.csv"]
    times = [item.stat().st_mtime for item in files if item.exists()]
    return max(times) if times else path.stat().st_mtime


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _candidate_trades_paths(root: Path) -> list[Path]:
    paths = [root / "backtests" / "trades.csv"]
    if (root / "backtests").exists():
        paths.extend(sorted((root / "backtests").glob("**/trades.csv")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve() if path.exists() else path
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def _read_first_trades(paths: Iterable[Path]) -> pd.DataFrame:
    for path in paths:
        trades = _read_trades(path)
        if not trades.empty:
            return trades
    return _empty_trades()


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


def _find_backtest_summary(root: Path) -> dict[str, Any]:
    direct = _read_json(root / "backtests" / "summary.json")
    if direct:
        return direct
    for path in sorted(root.glob("**/summary.json")) if root.exists() else []:
        payload = _read_json(path)
        mode = str(payload.get("mode", "")).lower()
        if mode == "backtest" or "total_trades" in payload or "trades_generated" in payload:
            return payload
    return {}


def _summary_source(compact: Mapping[str, Any], final: Mapping[str, Any], backtest: Mapping[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = {}
    for payload in (final.get("backtest_summary", {}) if isinstance(final.get("backtest_summary"), Mapping) else {}, final, backtest, compact):
        if isinstance(payload, Mapping):
            source.update({key: value for key, value in payload.items() if value not in (None, "")})
    for key in ("total_trades", "sample_status", "trade_frequency_status", "trades_by_symbol", "trades_by_strategy"):
        for payload in (compact, backtest, final):
            if isinstance(payload, Mapping) and payload.get(key) not in (None, ""):
                source[key] = payload.get(key)
                break
    return source


def _metrics_from_summaries(source: Mapping[str, Any]) -> dict[str, Any]:
    total = int(_number(source.get("total_trades", source.get("trades_generated", 0))) or 0)
    sample_status = str(source.get("sample_status") or source.get("trade_frequency_status") or classify_sample_size(total))
    profit_factor = _optional_number(source.get("profit_factor", source.get("global_profit_factor")))
    expectancy = _optional_number(source.get("expectancy_r", source.get("global_expectancy_r")))
    winrate = _optional_number(source.get("winrate", source.get("global_winrate")))
    missing = [name for name, value in {"profit_factor": profit_factor, "expectancy_r": expectancy, "winrate": winrate}.items() if value is None]
    metrics_status = "COUNTS_ONLY" if total > 0 and missing else ("FULL_EDGE_METRICS" if total > 0 else "NO_TRADES")
    metrics_source = "summary_counts" if metrics_status == "COUNTS_ONLY" else "summary_metrics"
    return {
        "total_trades": total,
        "sample_status": sample_status,
        "trade_frequency_status": source.get("trade_frequency_status", sample_status),
        "winrate": winrate,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy,
        "average_r": _optional_number(source.get("average_r")),
        "net_profit": _optional_number(source.get("net_profit")),
        "max_drawdown_pct": _optional_number(source.get("max_drawdown_pct")),
        "return_pct": _optional_number(source.get("return_pct", source.get("net_return_pct"))),
        "average_trade_duration": _optional_number(source.get("average_trade_duration")),
        "metrics_source": metrics_source,
        "metrics_status": metrics_status,
        "missing_metrics": missing,
        "execution_attempted": False,
    }


def _empty_global_metrics() -> dict[str, Any]:
    return {
        "total_trades": 0,
        "sample_status": "LOW_SAMPLE",
        "winrate": None,
        "profit_factor": None,
        "expectancy_r": None,
        "average_r": None,
        "net_profit": None,
        "max_drawdown_pct": None,
        "return_pct": None,
        "average_trade_duration": None,
        "metrics_source": "none",
        "metrics_status": "NO_TRADES",
        "missing_metrics": ["profit_factor", "expectancy_r", "winrate"],
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


def _counts_frame(raw: Any, column: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            rows.append(_count_row(column, key, value))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                name = item.get(column) or item.get("symbol") or item.get("strategy_name") or item.get("name")
                count = item.get("total_trades", item.get("trades", item.get("count", 0)))
                row = _count_row(column, name, count)
                row.update({key: value for key, value in item.items() if key not in row})
                rows.append(row)
    return pd.DataFrame(rows, columns=[column, "total_trades", "sample_status", "winrate", "profit_factor", "expectancy_r", "metrics_status", "missing_metrics"]) if rows else pd.DataFrame(columns=[column, "total_trades", "sample_status", "winrate", "profit_factor", "expectancy_r", "metrics_status", "missing_metrics"])


def _count_row(column: str, name: Any, count: Any) -> dict[str, Any]:
    if isinstance(count, Mapping):
        count = count.get("total_trades", count.get("trades", count.get("count", 0)))
    trades = int(_number(count) or 0)
    return {
        column: str(name or "UNKNOWN"),
        "total_trades": trades,
        "sample_status": classify_sample_size(trades),
        "winrate": None,
        "profit_factor": None,
        "expectancy_r": None,
        "metrics_status": "COUNTS_ONLY",
        "missing_metrics": "profit_factor; expectancy_r; winrate",
    }


def _ensure_column(frame: pd.DataFrame, column: str, default: str) -> pd.DataFrame:
    copy = frame.copy()
    if column not in copy.columns:
        copy[column] = default
    copy[column] = copy[column].fillna(default).replace("", default)
    return copy


def _load_blockers(root: Path, backtest: Mapping[str, Any], compact: Mapping[str, Any] | None = None, final: Mapping[str, Any] | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for source_name, payload in (("backtest", backtest), ("compact", compact or {}), ("final", final or {})):
        for key in ("top_blocking_reasons", "top_strategy_blockers", "top_blockers"):
            for item in payload.get(key, []) if isinstance(payload, Mapping) else []:
                if isinstance(item, Mapping):
                    rows.append({"blocking_reason": item.get("blocking_reason", item.get("reason", item.get("blocker", "UNKNOWN_BLOCKER"))), "count": int(item.get("count", 1) or 1), "source": source_name})
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


def _number(value: Any) -> float | None:
    if isinstance(value, Mapping):
        return None
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_number(value: Any) -> float | None:
    return _number(value)

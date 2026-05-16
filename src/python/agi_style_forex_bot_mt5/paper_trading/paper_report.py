"""Paper trading report exporter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .paper_performance import group_metrics, paper_metrics
from .paper_trade import PaperTrade


def write_forward_shadow_report(trades: Iterable[PaperTrade], report_dir: str | Path) -> list[str]:
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    rows = [trade.to_dict() for trade in trades]
    frame = pd.DataFrame(rows)
    metrics = paper_metrics(rows)
    files = {
        "summary": path / "summary.json",
        "trades": path / "trades.csv",
        "equity": path / "equity_curve.csv",
        "by_symbol": path / "by_symbol.csv",
        "by_strategy": path / "by_strategy.csv",
        "by_regime": path / "by_regime.csv",
        "by_session": path / "by_session.csv",
        "rejections": path / "rejections.csv",
        "html": path / "report.html",
    }
    files["summary"].write_text(json.dumps({"mode": "forward-shadow", **metrics, "execution_attempted": False}, indent=2, sort_keys=True), encoding="utf-8")
    frame.to_csv(files["trades"], index=False)
    _equity(frame).to_csv(files["equity"], index=False)
    group_metrics(rows, "symbol").to_csv(files["by_symbol"], index=False)
    group_metrics(rows, "strategy_name").to_csv(files["by_strategy"], index=False)
    group_metrics(rows, "regime").to_csv(files["by_regime"], index=False)
    group_metrics(rows, "session").to_csv(files["by_session"], index=False)
    pd.DataFrame(columns=["reason", "count"]).to_csv(files["rejections"], index=False)
    files["html"].write_text(f"<html><body><h1>Forward Shadow</h1><pre>{json.dumps(metrics, indent=2)}</pre></body></html>", encoding="utf-8")
    return [str(item) for item in files.values()]


def _equity(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["timestamp_utc", "equity"])
    closed = frame[frame["status"] == "CLOSED"].copy()
    if closed.empty:
        return pd.DataFrame(columns=["timestamp_utc", "equity"])
    closed["timestamp_utc"] = pd.to_datetime(closed["exit_time_utc"], utc=True)
    closed = closed.sort_values("timestamp_utc")
    closed["equity"] = closed["profit"].astype(float).cumsum()
    return closed[["timestamp_utc", "equity"]]

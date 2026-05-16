"""Paper-vs-backtest calibration comparison."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def compare_paper_vs_backtest(*, database: TelemetryDatabase, reports_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    root = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    backtest = _read_json(root / "backtests" / "summary.json")
    trades = [json.loads(row["payload_json"]) for row in database.fetch_paper_trades()]
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    paper_expectancy = _avg([float(trade.get("r_multiple") or 0.0) for trade in closed])
    paper_winrate = (sum(1 for trade in closed if float(trade.get("r_multiple") or 0.0) > 0) / len(closed) * 100.0) if closed else 0.0
    backtest_expectancy = float(backtest.get("expectancy_r") or 0.0)
    backtest_winrate = float(backtest.get("winrate") or 0.0)
    classification = "CALIBRATED_OK"
    if len(closed) < 20:
        classification = "NEEDS_MORE_FORWARD_DATA"
    if backtest and closed and backtest_expectancy > 0 and paper_expectancy < 0:
        classification = "BACKTEST_TOO_OPTIMISTIC"
    if backtest and _observed_spread(trades) > float(backtest.get("spread_points") or backtest.get("assumed_spread_points") or 999):
        classification = "COST_ASSUMPTION_TOO_LOW"
    summary = {
        "mode": "paper-vs-backtest",
        "classification": classification,
        "backtest_expectancy_r": backtest_expectancy,
        "paper_expectancy_r": paper_expectancy,
        "backtest_winrate": backtest_winrate,
        "paper_winrate": paper_winrate,
        "paper_trades_closed": len(closed),
        "execution_attempted": False,
    }
    paths = {
        "summary": output / "summary.json",
        "by_symbol": output / "by_symbol.csv",
        "by_strategy": output / "by_strategy.csv",
        "by_regime": output / "by_regime.csv",
        "html": output / "report.html",
    }
    summary["reports_created"] = [str(path) for path in paths.values()]
    paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_group(paths["by_symbol"], closed, "symbol")
    _write_group(paths["by_strategy"], closed, "strategy_name")
    _write_group(paths["by_regime"], closed, "regime")
    paths["html"].write_text("<html><body><h1>Paper vs Backtest</h1><pre>" + json.dumps(summary, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return summary


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _observed_spread(trades: list[dict[str, Any]]) -> float:
    values = [float(trade.get("spread_at_entry") or 0.0) for trade in trades if float(trade.get("spread_at_entry") or 0.0) > 0]
    return _avg(values)


def _write_group(path: Path, trades: list[dict[str, Any]], key: str) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(trade.get(key) or "")].append(trade)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[key, "trades", "expectancy_r", "winrate"])
        writer.writeheader()
        for name, rows in sorted(groups.items()):
            r_values = [float(row.get("r_multiple") or 0.0) for row in rows]
            writer.writerow({key: name, "trades": len(rows), "expectancy_r": _avg(r_values), "winrate": (sum(1 for item in r_values if item > 0) / len(r_values) * 100.0) if r_values else 0.0})


"""Execution simulation calibration report."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def run_simulation_calibration(*, database: TelemetryDatabase, reports_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trades = [_payload(row) for row in database.fetch_paper_trades()]
    qualities = [str(trade.get("metadata", {}).get("fill_quality") or trade.get("metadata", {}).get("entry_fill", {}).get("fill_quality") or "UNKNOWN") for trade in trades]
    slippages = [float(trade.get("slippage_assumed_points") or 0.0) for trade in trades]
    poor = sum(1 for quality in qualities if quality == "POOR")
    rejected = sum(1 for quality in qualities if quality == "REJECTED")
    ambiguous = sum(1 for trade in trades if trade.get("metadata", {}).get("ambiguity_flags"))
    classification = "CALIBRATED_OK"
    if not trades:
        classification = "NEEDS_MORE_FORWARD_DATA"
    elif poor + rejected > max(1, len(trades) * 0.25):
        classification = "COST_ASSUMPTION_TOO_LOW"
    paths = {
        "summary": output / "simulation_calibration.json",
        "fill_quality": output / "fill_quality.csv",
        "assumptions": output / "spread_slippage_assumptions.csv",
        "ambiguous": output / "ambiguous_events.csv",
        "html": output / "report.html",
    }
    summary = {
        "mode": "simulation-calibration",
        "classification": classification,
        "paper_trades": len(trades),
        "fill_quality_poor_count": poor,
        "rejected_by_spread_model": rejected,
        "ambiguous_intrabar_events": ambiguous,
        "assumed_slippage_avg": mean(slippages) if slippages else 0.0,
        "cost_model_status": "CONSERVATIVE" if classification == "CALIBRATED_OK" else "WATCHLIST",
        "reports_created": [str(path) for path in paths.values()],
        "execution_attempted": False,
    }
    paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_rows(paths["fill_quality"], [{"fill_quality": quality, "count": qualities.count(quality)} for quality in sorted(set(qualities))], ["fill_quality", "count"])
    _write_rows(paths["assumptions"], [{"symbol": trade.get("symbol", ""), "slippage_points": trade.get("slippage_assumed_points", 0), "spread_at_entry": trade.get("spread_at_entry", 0)} for trade in trades], ["symbol", "slippage_points", "spread_at_entry"])
    _write_rows(paths["ambiguous"], [trade for trade in trades if trade.get("metadata", {}).get("ambiguity_flags")], ["paper_trade_id", "symbol", "metadata"])
    paths["html"].write_text("<html><body><h1>Execution Simulation Calibration</h1><pre>" + json.dumps(summary, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return summary


def _payload(row: Any) -> dict[str, Any]:
    return json.loads(row["payload_json"])


def _write_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


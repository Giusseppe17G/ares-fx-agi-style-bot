"""Broker quality and readiness report writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .spread_analyzer import analyze_spreads
from .tick_freshness_analyzer import analyze_tick_freshness


def write_broker_quality_report(summary: Mapping[str, Any], report_dir: str | Path) -> dict[str, str]:
    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    symbols = list(summary.get("symbols", []))
    spread = analyze_spreads(symbols)
    freshness = analyze_tick_freshness(symbols)
    paths = {
        "summary": output / "summary.json",
        "by_symbol": output / "by_symbol.csv",
        "spread_by_session": output / "spread_by_session.csv",
        "tick_freshness": output / "tick_freshness.csv",
        "latency": output / "latency.csv",
        "readiness_score": output / "readiness_score.csv",
        "html": output / "report.html",
    }
    paths["summary"].write_text(json.dumps({**dict(summary), "spread": spread, "tick_freshness": freshness}, indent=2, sort_keys=True), encoding="utf-8")
    _write_rows(paths["by_symbol"], symbols)
    _write_rows(paths["tick_freshness"], [{"canonical_symbol": item.get("canonical_symbol"), "tick_age_seconds": item.get("tick_age_seconds"), "status": item.get("status")} for item in symbols])
    _write_rows(paths["latency"], [{"canonical_symbol": item.get("canonical_symbol"), "read_latency_ms_tick": item.get("read_latency_ms_tick"), "read_latency_ms_rates": item.get("read_latency_ms_rates")} for item in symbols])
    _write_rows(paths["readiness_score"], [{"canonical_symbol": item.get("canonical_symbol"), "readiness_score": item.get("readiness_score"), "status": item.get("status"), "reasons": "; ".join(item.get("reasons", []))} for item in symbols])
    _write_rows(paths["spread_by_session"], [{"session": "CURRENT", "spread_p95": spread.get("p95", 0.0), "spread_p99": spread.get("p99", 0.0)}])
    paths["html"].write_text(_html("Broker Quality Report", summary), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def build_readiness_report(*, reports_root: str | Path, output_dir: str | Path, database: TelemetryDatabase | None = None) -> dict[str, Any]:
    root = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    broker_summary = _read_json(root / "broker_quality" / "summary.json")
    symbols = list(broker_summary.get("symbols", []))
    ready = sum(1 for item in symbols if item.get("status") == "EXECUTION_READY_SHADOW_ONLY")
    not_ready = sum(1 for item in symbols if item.get("status") == "NOT_READY")
    classification = "CONTINUE_FORWARD_SHADOW" if ready and not not_ready else "NEEDS_BROKER_FIX" if not_ready else "NEEDS_MORE_DATA"
    report = {
        "mode": "readiness-report",
        "broker_quality_available": bool(broker_summary),
        "symbols_checked": len(symbols),
        "ready": ready,
        "watchlist": sum(1 for item in symbols if item.get("status") == "WATCHLIST"),
        "not_ready": not_ready,
        "classification": classification,
        "decision": classification,
        "execution_attempted": False,
        "order_send_called": False,
        "summaries": {"broker_quality": broker_summary},
        "reports_created": [],
    }
    json_path = output / "execution_readiness_report.json"
    csv_path = output / "execution_readiness_report.csv"
    html_path = output / "execution_readiness_report.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _write_rows(csv_path, [{"symbol": item.get("canonical_symbol"), "status": item.get("status"), "score": item.get("readiness_score"), "reasons": "; ".join(item.get("reasons", []))} for item in symbols])
    html_path.write_text(_html("Execution Readiness Report", report), encoding="utf-8")
    report["reports_created"] = [str(json_path), str(csv_path), str(html_path)]
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_rows(path: Path, rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _html(title: str, payload: Mapping[str, Any]) -> str:
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<h1>{title}</h1>
<p>Read-only audit. No real or demo orders are enabled.</p>
<pre>{json.dumps(payload, indent=2, sort_keys=True)}</pre>
</body>
</html>
"""


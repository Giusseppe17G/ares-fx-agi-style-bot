"""Replay audit state from SQLite telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .event_integrity import validate_event_integrity


def replay_audit(*, database: TelemetryDatabase, output_dir: str | Path = "data/reports/persistence") -> dict[str, Any]:
    """Reconstruct forward-shadow paper state and write a replay report."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trades = [json.loads(row["payload_json"]) for row in database.fetch_paper_trades()]
    events = database.fetch_all("events")
    alerts = database.fetch_all("alerts")
    equity = 0.0
    curve = []
    for trade in trades:
        if trade.get("status") == "CLOSED":
            equity += float(trade.get("profit") or 0.0)
            curve.append({"timestamp_utc": trade.get("exit_time_utc"), "equity": equity, "paper_trade_id": trade.get("paper_trade_id")})
    portfolio_decisions = sum(1 for row in events if row["event_type"] == "PORTFOLIO_DECISION")
    integrity = validate_event_integrity(database=database)
    report = {
        "mode": "audit-replay",
        "status": "OK" if integrity["status"] == "OK" else "WARNING",
        "paper_trades_open": sum(1 for trade in trades if trade.get("status") == "OPEN"),
        "paper_trades_closed": sum(1 for trade in trades if trade.get("status") == "CLOSED"),
        "equity_curve": curve,
        "alerts": len(alerts),
        "portfolio_decisions": portfolio_decisions,
        "integrity": integrity,
        "execution_attempted": False,
    }
    path = output / "audit_replay_report.json"
    integrity_path = output / "event_integrity_report.json"
    html_path = output / "report.html"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    integrity_path.write_text(json.dumps(integrity, indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text("<html><body><h1>Audit Replay</h1><pre>" + json.dumps(report, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return {**report, "report_path": str(path), "reports_created": [str(path), str(integrity_path), str(html_path)]}

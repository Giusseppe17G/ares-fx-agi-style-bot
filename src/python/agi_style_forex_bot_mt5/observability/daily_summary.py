"""Daily forward-shadow summary report."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agi_style_forex_bot_mt5.observability.metrics_collector import MetricsCollector
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


class DailySummary:
    """Generate JSON and HTML daily operational summaries."""

    def __init__(self, database: TelemetryDatabase, report_dir: str | Path) -> None:
        self.database = database
        self.report_dir = Path(report_dir)

    def generate(self, *, summary_date: date | None = None) -> dict[str, Any]:
        day = summary_date or date.today()
        self.report_dir.mkdir(parents=True, exist_ok=True)
        metrics = MetricsCollector(self.database).collect()
        alerts = [json.loads(row["payload_json"]) for row in self.database.fetch_all("alerts")]
        payload = {
            "summary_id": f"ds_{uuid4().hex}",
            "summary_date": day.isoformat(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_signals": metrics["signals_detected"],
            "signals_rejected": metrics["signals_rejected"],
            "paper_trades_open": metrics["paper_trades_open"],
            "paper_trades_closed": metrics["paper_trades_closed"],
            "winrate": metrics["winrate_paper"],
            "profit_factor": metrics["profit_factor_paper"],
            "expectancy_r": metrics["expectancy_r_paper"],
            "drawdown": metrics["drawdown_paper"],
            "top_rejection_reasons": metrics["rejected_signals_by_reason"],
            "drift_status": "NEEDS_MORE_DATA",
            "critical_alerts": [alert for alert in alerts if alert.get("severity") == "CRITICAL"],
            "recommended_actions": ["Keep DEMO_ONLY=True and continue forward-shadow observation."],
            "execution_attempted": False,
        }
        json_path = self.report_dir / f"{day.isoformat()}-summary.json"
        html_path = self.report_dir / f"{day.isoformat()}-summary.html"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        html_path.write_text(
            "<html><body><h1>Forward Shadow Daily Summary</h1><pre>"
            + json.dumps(payload, indent=2, sort_keys=True)
            + "</pre></body></html>",
            encoding="utf-8",
        )
        self.database.insert_daily_summary(payload)
        self.database.update_operational_state({"last_daily_summary_utc": payload["timestamp_utc"]})
        return {**payload, "reports_created": [str(json_path), str(html_path)]}


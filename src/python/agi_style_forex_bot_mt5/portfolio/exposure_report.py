"""Currency exposure report."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .portfolio_state import build_portfolio_state


def build_exposure_report(*, database: TelemetryDatabase, output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state = build_portfolio_state(database).to_dict()
    exposure = state["currency_exposure"]
    json_path = output / "portfolio_status.json"
    csv_path = output / "currency_exposure.csv"
    html_path = output / "report.html"
    json_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["currency", "net", "gross", "limit", "breach"])
        writer.writeheader()
        currencies = sorted(set(exposure.get("net", {})) | set(exposure.get("gross", {})))
        for currency in currencies:
            writer.writerow(
                {
                    "currency": currency,
                    "net": exposure.get("net", {}).get(currency, 0.0),
                    "gross": exposure.get("gross", {}).get(currency, 0.0),
                    "limit": exposure.get("limits", {}).get(currency, 0.0),
                    "breach": exposure.get("breaches", {}).get(currency, 0.0),
                }
            )
    html_path.write_text("<html><body><h1>Portfolio Exposure</h1><pre>" + json.dumps(state, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return {**state, "mode": "exposure-report", "reports_created": [str(json_path), str(csv_path), str(html_path)], "execution_attempted": False}


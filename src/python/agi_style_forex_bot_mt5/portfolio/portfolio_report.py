"""Portfolio status report."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .portfolio_state import build_portfolio_state


def build_portfolio_status(*, database: TelemetryDatabase, reports_root: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    output = Path(output_dir or Path(reports_root) / "portfolio")
    output.mkdir(parents=True, exist_ok=True)
    state = build_portfolio_state(database).to_dict()
    paths = {
        "status": output / "portfolio_status.json",
        "exposure": output / "currency_exposure.csv",
        "correlation": output / "correlation_matrix.csv",
        "clusters": output / "correlation_clusters.csv",
        "decisions": output / "portfolio_decisions.csv",
        "ranking": output / "signal_ranking.csv",
        "html": output / "report.html",
    }
    paths["status"].write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    _write_exposure(paths["exposure"], state["currency_exposure"])
    _empty_csv(paths["correlation"], ["symbol"])
    _empty_csv(paths["clusters"], ["symbol_a", "symbol_b", "correlation"])
    _empty_csv(paths["decisions"], ["timestamp_utc", "symbol", "accepted", "reject_code", "risk_multiplier"])
    _empty_csv(paths["ranking"], ["timestamp_utc", "symbol", "rank", "ranking_score", "ranking_decision"])
    paths["html"].write_text("<html><body><h1>Portfolio Status</h1><pre>" + json.dumps(state, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return {**state, "mode": "portfolio-status", "reports_created": [str(path) for path in paths.values()], "execution_attempted": False}


def _empty_csv(path: Path, fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()


def _write_exposure(path: Path, exposure: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
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

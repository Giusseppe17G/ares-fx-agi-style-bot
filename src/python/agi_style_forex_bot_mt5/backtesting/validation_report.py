"""Master validation report consolidation."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping


CLASSIFICATION_ORDER = {
    "APPROVED_FOR_SHADOW_OBSERVATION": 2,
    "WATCHLIST": 1,
    "REJECTED": 0,
}


def build_master_validation_report(
    *,
    reports_root: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Consolidate backtest, walk-forward, Monte Carlo and stress summaries."""

    root = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summaries = {
        "data_quality": _read_json(root / "data_quality" / "summary.json"),
        "broker_cost_profile": _read_json(root / "broker_costs" / "broker_cost_profile.json"),
        "backtest": _read_json(root / "backtests" / "summary.json"),
        "walk_forward": _read_json(root / "walk_forward" / "summary.json"),
        "monte_carlo": _read_json(root / "monte_carlo" / "summary.json"),
        "stress": _read_json(root / "stress" / "summary.json"),
        "benchmark": _read_json(root / "benchmarks" / "summary.json"),
        "competitive_scorecard": _read_json(root / "competitive_scorecard" / "competitive_scorecard.json"),
    }
    final_decision, reasons = _final_decision(summaries)
    report = {
        "mode": "validation-report",
        "input_files": [str(path) for path in _existing_summary_paths(root)],
        "classification": final_decision,
        "reasons": reasons,
        "summaries": summaries,
        "reports_created": [],
        "execution_attempted": False,
    }
    json_path = output / "master_validation_report.json"
    csv_path = output / "master_validation_report.csv"
    html_path = output / "master_validation_report.html"
    json_path.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["section", "classification", "available"])
        writer.writeheader()
        for section, summary in summaries.items():
            writer.writerow(
                {
                    "section": section,
                    "classification": _section_classification(section, summary),
                    "available": bool(summary),
                }
            )
    html_path.write_text(_html(report), encoding="utf-8")
    report["reports_created"] = [str(json_path), str(csv_path), str(html_path)]
    json_path.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True), encoding="utf-8")
    return report


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _existing_summary_paths(root: Path) -> list[Path]:
    return [
        path
        for path in (
            root / "backtests" / "summary.json",
            root / "walk_forward" / "summary.json",
            root / "monte_carlo" / "summary.json",
            root / "stress" / "summary.json",
            root / "data_quality" / "summary.json",
            root / "broker_costs" / "broker_cost_profile.json",
            root / "benchmarks" / "summary.json",
            root / "competitive_scorecard" / "competitive_scorecard.json",
        )
        if path.exists()
    ]


def _section_classification(section: str, summary: Mapping[str, Any]) -> str:
    if not summary:
        return "REJECTED"
    if section == "backtest":
        pf = float(summary.get("profit_factor", 0) if summary.get("profit_factor") != "Infinity" else 999)
        expectancy = float(summary.get("expectancy_r", 0) or 0)
        drawdown = abs(float(summary.get("max_drawdown_pct", 100) or 100))
        trades = int(summary.get("total_trades", 0) or 0)
        if trades >= 300 and pf > 1.25 and expectancy > 0 and drawdown < 12:
            return "APPROVED_FOR_SHADOW_OBSERVATION"
        if pf > 1.0 and expectancy >= 0:
            return "WATCHLIST"
        return "REJECTED"
    if section == "data_quality":
        value = str(summary.get("classification") or "REJECTED")
        return "APPROVED_FOR_SHADOW_OBSERVATION" if value == "OK" else value
    if section == "broker_cost_profile":
        value = str(summary.get("classification") or "REJECTED")
        return "APPROVED_FOR_SHADOW_OBSERVATION" if value == "OK" else value
    if section == "competitive_scorecard":
        value = str(summary.get("classification") or "REJECTED")
        if value == "COMPETITIVE_CANDIDATE":
            return "APPROVED_FOR_SHADOW_OBSERVATION"
        if value in {"NEEDS_OPTIMIZATION", "WEAK_EDGE"}:
            return "WATCHLIST"
        return "REJECTED"
    if section == "benchmark":
        value = str(summary.get("classification") or "REJECTED")
        return "WATCHLIST" if value == "WATCHLIST" else value
    return str(summary.get("classification") or "REJECTED")


def _final_decision(summaries: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]:
    classifications = {
        section: _section_classification(section, summary)
        for section, summary in summaries.items()
    }
    reasons = [f"{section}: {classification}" for section, classification in classifications.items()]
    if classifications.get("data_quality") == "REJECTED":
        return "NEEDS_MORE_DATA", reasons
    if classifications.get("benchmark") in {"REJECTED", "WATCHLIST"} or classifications.get("competitive_scorecard") in {"REJECTED", "WATCHLIST"}:
        return "NEEDS_OPTIMIZATION", reasons
    if any(classification == "REJECTED" for classification in classifications.values()):
        return "REJECTED", reasons
    if any(classification == "WATCHLIST" for classification in classifications.values()):
        return "NEEDS_OPTIMIZATION", reasons
    return "APPROVED_FOR_SHADOW_OBSERVATION", reasons


def _html(report: Mapping[str, Any]) -> str:
    rows = "\n".join(
        f"<tr><th>{key}</th><td>{_jsonable(value)}</td></tr>"
        for key, value in report.items()
        if key != "summaries"
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Master Validation Report</title></head>
<body>
<h1>Master Validation Report</h1>
<p>Research-only validation. No real or demo orders are enabled.</p>
<table>{rows}</table>
</body>
</html>
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

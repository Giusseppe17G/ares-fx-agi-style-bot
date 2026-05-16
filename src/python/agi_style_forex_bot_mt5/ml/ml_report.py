"""ML meta-filter report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model_registry import load_model_bundle


def build_ml_report(*, model_dir: str | Path, report_dir: str | Path) -> dict[str, Any]:
    report = Path(report_dir)
    report.mkdir(parents=True, exist_ok=True)
    bundle = load_model_bundle(model_dir)
    summary = {
        "mode": "ml-report",
        "samples": 0,
        "model_status": "ML_DISABLED" if bundle is None else "ML_APPROVED" if bundle["metadata"].get("approved_for_shadow_filtering") else "WATCHLIST",
        "approved_for_shadow_filtering": bool(bundle and bundle["metadata"].get("approved_for_shadow_filtering", False)),
        "metadata": {} if bundle is None else bundle["metadata"],
        "metrics": {} if bundle is None else bundle["metrics"],
        "reports_created": [],
        "execution_attempted": False,
    }
    json_path = report / "ml_report.json"
    html_path = report / "ml_report.html"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text("<html><body><h1>ML Meta-Filter Report</h1><pre>" + json.dumps(summary, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    summary["reports_created"] = [str(json_path), str(html_path)]
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


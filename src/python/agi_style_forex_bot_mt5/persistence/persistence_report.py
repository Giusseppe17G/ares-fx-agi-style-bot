"""Persistence report consolidation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_persistence_report(*, output_dir: str | Path, sections: dict[str, Any]) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = {"mode": "persistence-report", "sections": sections, "execution_attempted": False}
    json_path = output / "report.json"
    html_path = output / "report.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text("<html><body><h1>Persistence Report</h1><pre>" + json.dumps(report, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return {**report, "reports_created": [str(json_path), str(html_path)]}


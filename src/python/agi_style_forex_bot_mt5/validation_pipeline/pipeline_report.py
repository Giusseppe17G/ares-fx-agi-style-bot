"""Full validation pipeline report writer."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .master_decision_engine import MasterDecision
from .stage_results import StageResult
from .validation_artifacts import artifact_paths


def write_pipeline_reports(
    *,
    output_dir: str | Path,
    reports_root: str | Path,
    pipeline_summary: dict[str, Any],
    stage_results: Iterable[StageResult],
    decision: MasterDecision,
) -> list[str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(reports_root, output)
    stage_list = list(stage_results)
    paths["pipeline_summary"].write_text(json.dumps(_jsonable(pipeline_summary), indent=2, sort_keys=True), encoding="utf-8")
    with paths["stage_results"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "status", "duration_seconds", "command_or_function", "input_paths", "output_paths", "error_message", "execution_attempted"])
        writer.writeheader()
        for result in stage_list:
            row = result.to_dict()
            row["input_paths"] = ";".join(row["input_paths"])
            row["output_paths"] = ";".join(row["output_paths"])
            writer.writerow({key: row.get(key) for key in writer.fieldnames})
    decision_payload = {"mode": "master-decision", **decision.to_dict()}
    paths["master_decision"].write_text(json.dumps(_jsonable(decision_payload), indent=2, sort_keys=True), encoding="utf-8")
    with paths["master_decision_csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scope", "name", "decision", "reasons"])
        writer.writeheader()
        writer.writerow({"scope": "global", "name": "ALL", "decision": decision.final_decision, "reasons": " | ".join(decision.reasons)})
        for symbol, payload in decision.by_symbol.items():
            writer.writerow({"scope": "symbol", "name": symbol, "decision": payload.get("decision"), "reasons": " | ".join(payload.get("reasons", ()))})
    paths["html"].write_text(_html(pipeline_summary, stage_list, decision), encoding="utf-8")
    return [str(paths["pipeline_summary"]), str(paths["stage_results"]), str(paths["master_decision"]), str(paths["master_decision_csv"]), str(paths["html"])]


def _html(summary: dict[str, Any], stages: list[StageResult], decision: MasterDecision) -> str:
    rows = "\n".join(f"<tr><td>{stage.name}</td><td>{stage.status}</td><td>{stage.error_message}</td></tr>" for stage in stages)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Full Validation Pipeline</title></head>
<body>
<h1>Full Validation Pipeline</h1>
<p>Final decision: <strong>{decision.final_decision}</strong></p>
<p>execution_attempted=false. No demo/live execution is enabled.</p>
<table><tr><th>Stage</th><th>Status</th><th>Error</th></tr>{rows}</table>
<pre>{json.dumps(_jsonable(summary), indent=2, sort_keys=True)}</pre>
</body>
</html>
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


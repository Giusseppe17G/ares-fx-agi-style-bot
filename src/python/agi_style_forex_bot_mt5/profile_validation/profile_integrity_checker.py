"""Profile comparison integrity orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .profile_metric_comparator import compare_profile_metrics
from .profile_threshold_diff import build_profile_threshold_diff, threshold_rows_frame


def run_profile_integrity(*, profile_runs_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Run threshold and metric integrity checks and write reports."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    thresholds = build_profile_threshold_diff()
    metrics = compare_profile_metrics(profile_runs_dir)
    failed = metrics.get("metric_similarity_status") == "IDENTICAL_METRICS"
    summary = {
        "mode": "profile-integrity",
        "profile_integrity_status": "FAILED" if failed else ("WARNING" if thresholds.get("warning") else "PASSED"),
        "profile_similarity_status": thresholds.get("profile_similarity_status"),
        "metric_similarity_status": metrics.get("metric_similarity_status"),
        "active_vs_balanced_similarity": metrics.get("active_vs_balanced_similarity"),
        "threshold_warning": thresholds.get("warning", False),
        "possible_causes": metrics.get("comparisons", [{}])[0].get("possible_causes", "") if metrics.get("comparisons") else "",
        "recommendation": metrics.get("comparisons", [{}])[0].get("recommendation", "") if metrics.get("comparisons") else "",
        "execution_attempted": False,
        "reports_created": [],
    }
    paths = {
        "integrity": output / "profile_integrity.json",
        "thresholds": output / "profile_threshold_diff.csv",
        "metrics": output / "profile_metric_comparison.csv",
        "html": output / "report.html",
    }
    paths["integrity"].write_text(json.dumps(_jsonable(summary | {"thresholds": thresholds, "metrics": metrics}), indent=2, sort_keys=True), encoding="utf-8")
    threshold_rows_frame(thresholds).to_csv(paths["thresholds"], index=False)
    pd.DataFrame(metrics.get("comparisons", []) or [{"metric_similarity_status": metrics.get("metric_similarity_status", "")}]).to_csv(paths["metrics"], index=False)
    paths["html"].write_text(_html(summary), encoding="utf-8")
    summary["reports_created"] = [str(path) for path in paths.values()]
    paths["integrity"].write_text(json.dumps(_jsonable(summary | {"thresholds": thresholds, "metrics": metrics}), indent=2, sort_keys=True), encoding="utf-8")
    return _jsonable(summary)


def _html(summary: dict[str, Any]) -> str:
    rows = "\n".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in summary.items() if key != "reports_created")
    return f"<html><body><h1>Profile Integrity</h1><p>Research only. No execution.</p><table>{rows}</table></body></html>"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value

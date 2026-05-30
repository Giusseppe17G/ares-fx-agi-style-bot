"""Report orchestration for manual BALANCED_STABLE_MICRO_V2 review."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .candidate_profile_loader import load_profile
from .frequency_gain_audit import estimate_frequency_gain
from .micro_v2_profile_builder import build_micro_v2_profile
from .profile_diff_audit import build_profile_diff
from .safety_constraint_audit import audit_safety_constraints


def run_micro_v2_review(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    base_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro.ini",
    candidate_profile_config: str | Path = "data/reports/micro_frequency_calibration/balanced_stable_micro_v2_candidate.ini",
    output_dir: str | Path = "data/reports/micro_v2_review",
) -> dict[str, Any]:
    """Review a micro V2 candidate and build a separate profile only if approved."""

    before_counts = _db_counts(database)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = load_profile(base_profile_config)
    candidate = load_profile(candidate_profile_config)
    diff_rows = build_profile_diff(base.get("values", {}), candidate.get("values", {})) if base.get("exists") and candidate.get("exists") else []
    safety = audit_safety_constraints(base.get("values", {}), candidate.get("values", {}), diff_rows) if candidate.get("exists") else _invalid_safety("Candidate profile missing.")
    frequency = estimate_frequency_gain(reports_root, diff_rows)
    approved_changes, rejected_changes = _split_changes(diff_rows, safety)
    status = _status(base, candidate, diff_rows, safety, frequency)
    final_profile: dict[str, Any] = {"micro_v2_profile_created": False, "micro_v2_profile_path": ""}
    if status == "MICRO_V2_APPROVED_FOR_PAPER_DRY_RUN":
        final_profile = build_micro_v2_profile(candidate.get("values", {}), output_path=Path(reports_root) / "paper_risk" / "balanced_stable_micro_v2.ini")
    summary = {
        "mode": "micro-v2-review",
        "micro_v2_review_status": status,
        "base_profile_config": str(base_profile_config),
        "candidate_profile_config": str(candidate_profile_config),
        "base_profile_exists": bool(base.get("exists")),
        "candidate_profile_exists": bool(candidate.get("exists")),
        "parameters_added": sum(1 for row in diff_rows if row.get("change_type") == "ADDED"),
        "parameters_removed": sum(1 for row in diff_rows if row.get("change_type") == "REMOVED"),
        "parameters_modified": sum(1 for row in diff_rows if row.get("change_type") == "MODIFIED"),
        "approved_changes": approved_changes,
        "rejected_changes": rejected_changes,
        "safety_constraints_passed": safety.get("safety_passed", False),
        "frequency_gain_status": frequency.get("frequency_gain_status", ""),
        "recommended_next_action": _recommended_action(status),
        **final_profile,
        "sqlite_unchanged": before_counts == _db_counts(database),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, diff_rows, safety, frequency, rejected_changes, approved_changes)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(base: Mapping[str, Any], candidate: Mapping[str, Any], diff_rows: list[Mapping[str, Any]], safety: Mapping[str, Any], frequency: Mapping[str, Any]) -> str:
    if not base.get("exists") or not candidate.get("exists"):
        return "MICRO_V2_INVALID_CANDIDATE"
    if not safety.get("safety_passed", False):
        failure_text = json.dumps(safety.get("failures", [])).upper()
        if "RISK" in failure_text or "PAPER_RISK_MULTIPLIER" in failure_text:
            return "MICRO_V2_REJECTED_RISK_INCREASE"
        return "MICRO_V2_REJECTED_UNSAFE_CHANGE"
    actionable = int(frequency.get("actionable_change_count", 0) or 0)
    if actionable <= 0:
        return "MICRO_V2_NO_ACTIONABLE_CHANGES"
    if any(row.get("change_type") == "REMOVED" for row in diff_rows if row.get("change_category") != "metadata"):
        return "MICRO_V2_REQUIRES_MANUAL_EDIT"
    return "MICRO_V2_APPROVED_FOR_PAPER_DRY_RUN"


def _split_changes(diff_rows: list[Mapping[str, Any]], safety: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failed_keys = {str(item.get("key", "")).upper() for item in safety.get("failures", []) if isinstance(item, Mapping)}
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in diff_rows:
        target = rejected if str(row.get("key", "")).upper() in failed_keys else approved
        target.append({**dict(row), "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    for failure in safety.get("failures", []):
        if not isinstance(failure, Mapping):
            continue
        if not any(str(row.get("key", "")).upper() == str(failure.get("key", "")).upper() for row in rejected):
            rejected.append({"key": failure.get("key", ""), "reason": failure.get("reason", ""), "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    return approved, rejected


def _invalid_safety(reason: str) -> dict[str, Any]:
    return {
        "safety_passed": False,
        "failures": [{"key": "CANDIDATE_PROFILE", "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}],
        "warnings": [],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _recommended_action(status: str) -> str:
    return {
        "MICRO_V2_APPROVED_FOR_PAPER_DRY_RUN": "KEEP_V2_FOR_FUTURE_PAPER_DRY_RUN_PHASE",
        "MICRO_V2_REJECTED_RISK_INCREASE": "DO_NOT_BUILD_V2_REDUCE_RISK_FIRST",
        "MICRO_V2_REJECTED_UNSAFE_CHANGE": "DO_NOT_BUILD_V2_FIX_UNSAFE_CHANGES",
        "MICRO_V2_REQUIRES_MANUAL_EDIT": "EDIT_CANDIDATE_OFFLINE_AND_REVIEW_AGAIN",
        "MICRO_V2_NO_ACTIONABLE_CHANGES": "NO_V2_PROFILE_CREATED_REVIEW_CANDIDATE_MANUALLY",
        "MICRO_V2_INVALID_CANDIDATE": "REGENERATE_MICRO_FREQUENCY_CANDIDATE",
    }.get(status, "MANUAL_REVIEW_REQUIRED")


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    diff_rows: list[Mapping[str, Any]],
    safety: Mapping[str, Any],
    frequency: Mapping[str, Any],
    rejected: list[Mapping[str, Any]],
    approved: list[Mapping[str, Any]],
) -> list[Path]:
    paths = [
        output / "micro_v2_review_summary.json",
        output / "profile_diff.csv",
        output / "safety_constraints.json",
        output / "frequency_gain_estimate.json",
        output / "rejected_changes.csv",
        output / "approved_changes.csv",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], diff_rows)
    _write_json(paths[2], safety)
    _write_json(paths[3], frequency)
    _write_csv(paths[4], rejected)
    _write_csv(paths[5], approved)
    paths[6].write_text(_recommendations_markdown(summary), encoding="utf-8")
    paths[7].write_text(
        f"<html><body><h1>Micro V2 Review</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>",
        encoding="utf-8",
    )
    return paths


def _recommendations_markdown(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Review

Status: `{summary.get('micro_v2_review_status')}`

Profile created: `{summary.get('micro_v2_profile_created')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This review is offline only. A generated V2 profile is approved only for a future paper dry-run phase and is not active.
"""


def _db_counts(database: TelemetryDatabase) -> tuple[int, int, dict[str, Any]]:
    return (database.count_rows("events"), database.count_rows("paper_trades"), database.get_operational_state())


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

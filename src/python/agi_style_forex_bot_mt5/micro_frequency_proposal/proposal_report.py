"""Controlled micro frequency proposal report orchestration."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .bottleneck_loader import load_bottleneck_context
from .conservative_change_policy import propose_conservative_changes
from .micro_v2_proposal_builder import apply_changes, write_proposed_profile
from .profile_parameter_detector import load_profile
from .proposal_safety_audit import audit_proposal_safety


def run_micro_frequency_proposal(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    base_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro.ini",
    frequency_dir: str | Path = "data/reports/micro_frequency_calibration",
    v2_review_dir: str | Path = "data/reports/micro_v2_review",
    output_dir: str | Path = "data/reports/micro_frequency_proposal",
) -> dict[str, Any]:
    """Build a non-active conservative V2 proposed profile from existing keys only."""

    before_counts = _db_counts(database)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = load_profile(base_profile_config)
    context = load_bottleneck_context(frequency_dir=frequency_dir, v2_review_dir=v2_review_dir)
    base_values = dict(base.get("values", {}))
    changes, rejected = propose_conservative_changes(base_values, context) if base.get("exists") else ([], [{"bottleneck": "BASE_PROFILE", "reason": "Base profile config missing."}])
    proposed_values = apply_changes(base_values, changes) if changes else {}
    safety = audit_proposal_safety(base_values, proposed_values, changes) if changes else _no_safety(changes)
    status = _status(base_exists=bool(base.get("exists")), changes=changes, safety=safety)
    profile_result = {"proposed_profile_created": False, "proposed_profile_path": ""}
    if status == "MICRO_FREQUENCY_PROPOSAL_CREATED":
        profile_result = write_proposed_profile(output / "balanced_stable_micro_v2_proposed.ini", proposed_values)
    summary = {
        "mode": "micro-frequency-proposal",
        "proposal_status": status,
        "base_profile_config": str(base_profile_config),
        "frequency_dir": str(frequency_dir),
        "v2_review_dir": str(v2_review_dir),
        "proposed_changes": changes,
        "rejected_possible_changes": rejected,
        "proposed_change_count": len(changes),
        "rejected_change_count": len(rejected),
        "recommended_next_action": _recommended_action(status),
        **profile_result,
        "sqlite_unchanged": before_counts == _db_counts(database),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, base_values, proposed_values, changes, rejected, safety)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(*, base_exists: bool, changes: list[Mapping[str, Any]], safety: Mapping[str, Any]) -> str:
    if not base_exists:
        return "PROPOSAL_REQUIRES_MANUAL_REVIEW"
    if not changes:
        return "NO_SAFE_PARAMETER_MAPPING_FOUND"
    if not safety.get("proposal_safety_passed", False):
        return "PROPOSAL_REJECTED_UNSAFE"
    return "MICRO_FREQUENCY_PROPOSAL_CREATED"


def _recommended_action(status: str) -> str:
    return {
        "MICRO_FREQUENCY_PROPOSAL_CREATED": "RUN_MICRO_V2_REVIEW_ON_PROPOSED_PROFILE_IN_NEXT_PHASE",
        "NO_SAFE_PARAMETER_MAPPING_FOUND": "MANUAL_PROFILE_REVIEW_REQUIRED_NO_RUNTIME_CHANGE",
        "PROPOSAL_REJECTED_UNSAFE": "DO_NOT_USE_PROPOSED_PROFILE",
        "PROPOSAL_REQUIRES_MANUAL_REVIEW": "FIX_INPUTS_AND_REVIEW_OFFLINE",
        "PROPOSAL_NO_ACTIONABLE_CHANGES": "NO_RUNTIME_CHANGE",
    }.get(status, "MANUAL_REVIEW_REQUIRED")


def _no_safety(changes: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "proposal_safety_passed": False,
        "failures": [],
        "change_count": len(changes),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    base_values: Mapping[str, str],
    proposed_values: Mapping[str, str],
    changes: list[Mapping[str, Any]],
    rejected: list[Mapping[str, Any]],
    safety: Mapping[str, Any],
) -> list[Path]:
    diff_rows = _diff_rows(base_values, proposed_values)
    paths = [
        output / "micro_frequency_proposal_summary.json",
        output / "proposed_profile_diff.csv",
        output / "proposed_changes.csv",
        output / "rejected_possible_changes.csv",
        output / "safety_audit.json",
        output / "recommendations.md",
        output / "report.html",
    ]
    if summary.get("proposed_profile_created"):
        paths.insert(5, output / "balanced_stable_micro_v2_proposed.ini")
    _write_json(paths[0], summary)
    _write_csv(paths[1], diff_rows)
    _write_csv(paths[2], changes)
    _write_csv(paths[3], rejected)
    _write_json(paths[4], safety)
    rec_path = output / "recommendations.md"
    html_path = output / "report.html"
    rec_path.write_text(_recommendations_markdown(summary), encoding="utf-8")
    html_path.write_text(
        f"<html><body><h1>Micro Frequency Proposal</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>",
        encoding="utf-8",
    )
    return [path for path in paths if path.exists()]


def _diff_rows(base_values: Mapping[str, str], proposed_values: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(base_values) | set(proposed_values)):
        before = base_values.get(key)
        after = proposed_values.get(key)
        if before == after:
            continue
        rows.append(
            {
                "key": key,
                "base_value": "" if before is None else before,
                "proposed_value": "" if after is None else after,
                "change_type": "ADDED" if before is None else "REMOVED" if after is None else "MODIFIED",
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows


def _recommendations_markdown(summary: Mapping[str, Any]) -> str:
    return f"""# Micro Frequency Proposal

Status: `{summary.get('proposal_status')}`

Proposed profile created: `{summary.get('proposed_profile_created')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This proposal is offline only. It is not active, does not replace existing profiles, and does not authorize demo/live execution.
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

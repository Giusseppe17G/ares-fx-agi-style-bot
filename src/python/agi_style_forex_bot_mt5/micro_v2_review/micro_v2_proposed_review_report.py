"""FASE 48 review for controlled BALANCED_STABLE_MICRO_V2 proposed profile."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .candidate_profile_loader import load_profile
from .micro_v2_profile_builder import build_micro_v2_profile_from_proposed
from .profile_diff_audit import build_profile_diff
from .proposed_safety_audit import audit_proposed_profile_safety


def run_micro_v2_proposed_review(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    base_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro.ini",
    proposed_profile_config: str | Path = "data/reports/micro_frequency_proposal/balanced_stable_micro_v2_proposed.ini",
    output_dir: str | Path = "data/reports/micro_v2_review_proposed",
) -> dict[str, Any]:
    """Review proposed micro V2 profile and create final V2 only if safe."""

    before_counts = _db_counts(database)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = load_profile(base_profile_config)
    proposed = load_profile(proposed_profile_config)
    diff_rows = build_profile_diff(base.get("values", {}), proposed.get("values", {})) if base.get("exists") and proposed.get("exists") else []
    safety = audit_proposed_profile_safety(base.get("values", {}), proposed.get("values", {})) if proposed.get("exists") else _invalid_safety("Proposed profile missing.")
    approved, rejected = _split_changes(diff_rows, safety)
    status = _status(base, proposed, diff_rows, safety)
    final_profile: dict[str, Any] = {"micro_v2_profile_created": False, "micro_v2_profile_path": ""}
    if status == "MICRO_V2_PROPOSED_APPROVED_FOR_PAPER_DRY_RUN":
        final_profile = build_micro_v2_profile_from_proposed(proposed.get("values", {}), output_path=Path(reports_root) / "paper_risk" / "balanced_stable_micro_v2.ini")
    summary = {
        "mode": "micro-v2-proposed-review",
        "micro_v2_proposed_review_status": status,
        "base_profile_config": str(base_profile_config),
        "proposed_profile_config": str(proposed_profile_config),
        "base_profile_exists": bool(base.get("exists")),
        "proposed_profile_exists": bool(proposed.get("exists")),
        "approved_changes": approved,
        "rejected_changes": rejected,
        "proposed_safety_passed": safety.get("proposed_safety_passed", False),
        "recommended_next_action": _recommended_action(status),
        **final_profile,
        "sqlite_unchanged": before_counts == _db_counts(database),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, diff_rows, safety, approved, rejected)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(base: Mapping[str, Any], proposed: Mapping[str, Any], diff_rows: list[Mapping[str, Any]], safety: Mapping[str, Any]) -> str:
    if not base.get("exists") or not proposed.get("exists"):
        return "MICRO_V2_PROPOSED_INVALID"
    if not safety.get("proposed_safety_passed", False):
        failure_text = json.dumps(safety.get("failures", [])).upper()
        if "RISK" in failure_text or "PAPER_RISK_MULTIPLIER" in failure_text:
            return "MICRO_V2_PROPOSED_REJECTED_RISK_INCREASE"
        return "MICRO_V2_PROPOSED_REJECTED_UNSAFE_CHANGE"
    actionable = [row for row in diff_rows if row.get("change_category") in {"cooldown", "paper_limit", "risk", "threshold", "session", "symbol_universe"}]
    if not actionable:
        return "MICRO_V2_PROPOSED_NO_ACTIONABLE_CHANGES"
    if any(row.get("change_type") == "REMOVED" for row in actionable):
        return "MICRO_V2_PROPOSED_REQUIRES_MANUAL_EDIT"
    return "MICRO_V2_PROPOSED_APPROVED_FOR_PAPER_DRY_RUN"


def _split_changes(diff_rows: list[Mapping[str, Any]], safety: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failed_keys = {str(item.get("key", "")).upper() for item in safety.get("failures", []) if isinstance(item, Mapping)}
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in diff_rows:
        item = {**dict(row), "execution_attempted": False, "order_send_called": False, "order_check_called": False}
        if str(row.get("key", "")).upper() in failed_keys:
            rejected.append(item)
        else:
            approved.append(item)
    for failure in safety.get("failures", []):
        if not isinstance(failure, Mapping):
            continue
        key = str(failure.get("key", "")).upper()
        if not any(str(row.get("key", "")).upper() == key for row in rejected):
            rejected.append({"key": key, "reason": failure.get("reason", ""), "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    return approved, rejected


def _invalid_safety(reason: str) -> dict[str, Any]:
    return {
        "proposed_safety_passed": False,
        "failures": [{"key": "PROPOSED_PROFILE", "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _recommended_action(status: str) -> str:
    return {
        "MICRO_V2_PROPOSED_APPROVED_FOR_PAPER_DRY_RUN": "KEEP_V2_FOR_EXPLICIT_FUTURE_PAPER_DRY_RUN_PHASE",
        "MICRO_V2_PROPOSED_REJECTED_RISK_INCREASE": "DO_NOT_BUILD_V2_REDUCE_RISK_FIRST",
        "MICRO_V2_PROPOSED_REJECTED_UNSAFE_CHANGE": "DO_NOT_BUILD_V2_FIX_UNSAFE_CHANGES",
        "MICRO_V2_PROPOSED_REQUIRES_MANUAL_EDIT": "EDIT_PROPOSED_PROFILE_OFFLINE_AND_REVIEW_AGAIN",
        "MICRO_V2_PROPOSED_INVALID": "REGENERATE_MICRO_FREQUENCY_PROPOSAL",
        "MICRO_V2_PROPOSED_NO_ACTIONABLE_CHANGES": "NO_V2_PROFILE_CREATED_REVIEW_PROPOSAL",
    }.get(status, "MANUAL_REVIEW_REQUIRED")


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    diff_rows: list[Mapping[str, Any]],
    safety: Mapping[str, Any],
    approved: list[Mapping[str, Any]],
    rejected: list[Mapping[str, Any]],
) -> list[Path]:
    paths = [
        output / "micro_v2_proposed_review_summary.json",
        output / "proposed_profile_diff.csv",
        output / "proposed_safety_constraints.json",
        output / "approved_changes.csv",
        output / "rejected_changes.csv",
        output / "recommendations.md",
        output / "report.html",
    ]
    if summary.get("micro_v2_profile_created"):
        paths.insert(5, Path(summary.get("micro_v2_profile_path", "")))
    _write_json(paths[0], summary)
    _write_csv(paths[1], diff_rows)
    _write_json(paths[2], safety)
    _write_csv(paths[3], approved)
    _write_csv(paths[4], rejected)
    rec_path = output / "recommendations.md"
    html_path = output / "report.html"
    rec_path.write_text(_recommendations_markdown(summary), encoding="utf-8")
    html_path.write_text(
        f"<html><body><h1>Micro V2 Proposed Review</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>",
        encoding="utf-8",
    )
    return [path for path in paths if path.exists()]


def _recommendations_markdown(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Proposed Review

Status: `{summary.get('micro_v2_proposed_review_status')}`

Profile created: `{summary.get('micro_v2_profile_created')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This review approves V2 only for a future explicit paper dry-run phase. It does not activate forward-shadow and does not authorize demo/live execution.
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

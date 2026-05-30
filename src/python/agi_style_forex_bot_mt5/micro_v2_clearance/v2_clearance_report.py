"""Report writer for BALANCED_STABLE_MICRO_V2 paper risk clearance."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .clearance_ledger_adapter import audit_base_clearance, write_json
from .v2_clearance_builder import build_v2_clearance_ledger
from .v2_clearance_guard import audit_v2_clearance_prerequisites


def run_micro_v2_paper_risk_clearance(
    *,
    sqlite_path: str | Path,
    reports_root: str | Path = "data/reports",
    base_clearance_ledger: str | Path = "data/reports/paper_risk_review/paper_risk_clearance_ledger.json",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    micro_v2_review_dir: str | Path = "data/reports/micro_v2_review_proposed",
    runtime_profile_check_dir: str | Path = "data/reports/micro_v2_runtime_profile_check",
    output_dir: str | Path = "data/reports/micro_v2_clearance",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base_audit_before = audit_base_clearance(base_clearance_ledger)
    guard = audit_v2_clearance_prerequisites(
        v2_profile_config=v2_profile_config,
        micro_v2_review_dir=micro_v2_review_dir,
        runtime_profile_check_dir=runtime_profile_check_dir,
    )
    clearance: dict[str, Any] = {}
    if guard.get("clearance_guard_status") == "PASS":
        clearance = build_v2_clearance_ledger(output_dir=output, base_clearance_audit=base_audit_before, v2_profile_config=v2_profile_config)
    base_audit_after = audit_base_clearance(base_clearance_ledger)
    base_preserved = base_audit_before.get("base_clearance_sha256") == base_audit_after.get("base_clearance_sha256")
    status = str(guard.get("micro_v2_clearance_status") or "MICRO_V2_CLEARANCE_REQUIRES_MANUAL_REVIEW")
    summary = {
        "mode": "micro-v2-paper-risk-clearance",
        "micro_v2_clearance_status": status,
        "v2_clearance_granted": status == "MICRO_V2_PAPER_RISK_CLEARANCE_GRANTED",
        "paper_risk_clearance_v2_ledger": clearance.get("ledger_path", ""),
        "cleared_for_profile": clearance.get("cleared_for_profile", ""),
        "cleared_for_profile_canonical": clearance.get("canonical_cleared_for_profile", ""),
        "clearance_scope": clearance.get("clearance_scope", ""),
        "approved_for_demo": bool(clearance.get("approved_for_demo", False)),
        "approved_for_live": bool(clearance.get("approved_for_live", False)),
        "source_phase": clearance.get("source_phase", ""),
        "depends_on_phase_48": bool(clearance.get("depends_on_phase_48", False)),
        "depends_on_phase_50": bool(clearance.get("depends_on_phase_50", False)),
        "base_clearance_ledger": str(base_clearance_ledger),
        "base_clearance_preserved": bool(base_preserved),
        "sqlite_read_only_reference": str(sqlite_path),
        "reports_root": str(reports_root),
        "guard_failures": guard.get("failures", []),
        "recommended_next_action": _recommended_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, guard, base_audit_after)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _recommended_action(status: str) -> str:
    return {
        "MICRO_V2_PAPER_RISK_CLEARANCE_GRANTED": "LAUNCH_V2_DRY_RUN_ONLY_WITH_MICRO_V2_CLEARANCE_LEDGER_WHEN_OPERATOR_APPROVES",
        "MICRO_V2_CLEARANCE_REJECTED_PROFILE_INVALID": "FIX_V2_PROFILE_GUARDS_OFFLINE",
        "MICRO_V2_CLEARANCE_REJECTED_PHASE48_MISSING": "RERUN_MICRO_V2_PROPOSED_REVIEW",
        "MICRO_V2_CLEARANCE_REJECTED_PHASE50_MISSING": "RERUN_MICRO_V2_RUNTIME_PROFILE_CHECK",
        "MICRO_V2_CLEARANCE_REJECTED_UNSAFE": "DO_NOT_LAUNCH_V2_REVIEW_GUARD_FAILURES",
    }.get(status, "MANUAL_REVIEW_REQUIRED")


def _write_reports(output: Path, summary: Mapping[str, Any], guard: Mapping[str, Any], base_audit: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "micro_v2_clearance_summary.json",
        output / "clearance_guard.json",
        output / "base_clearance_audit.json",
        output / "recommendations.md",
        output / "report.html",
    ]
    if summary.get("paper_risk_clearance_v2_ledger"):
        paths.insert(1, Path(str(summary["paper_risk_clearance_v2_ledger"])))
    write_json(paths[0], summary)
    write_json(output / "clearance_guard.json", guard)
    write_json(output / "base_clearance_audit.json", base_audit)
    (output / "recommendations.md").write_text(_recommendations(summary), encoding="utf-8")
    (output / "report.html").write_text(f"<html><body><h1>Micro V2 Paper Risk Clearance</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    ledger = summary.get("paper_risk_clearance_v2_ledger") or "not created"
    return f"""# Micro V2 Paper Risk Clearance

Status: `{summary.get('micro_v2_clearance_status')}`

V2 ledger: `{ledger}`

Recommended next action: `{summary.get('recommended_next_action')}`

Use the V2 ledger only with `BALANCED_STABLE_MICRO_V2` paper dry-run. It does not authorize demo/live execution and does not replace the base micro clearance.
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

"""Offline runtime match check for BALANCED_STABLE_MICRO_V2 clearance."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_runtime_profile import MICRO_V2_SIGNAL_PROFILE, validate_micro_v2_forward_shadow_runtime
from agi_style_forex_bot_mt5.paper_daily_risk_state import validate_micro_daily_risk
from agi_style_forex_bot_mt5.paper_risk_review import validate_micro_resume_clearance
from agi_style_forex_bot_mt5.paper_risk_review.clearance_ledger import latest_clearance, load_clearance_ledger
from agi_style_forex_bot_mt5.paper_risk_review.profile_matching import effective_requested_profile, normalize_profile_name
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .clearance_ledger_adapter import write_json


def run_micro_v2_clearance_runtime_check(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path,
    reports_root: str | Path,
    signal_profile: str,
    profile_config: str | Path,
    paper_risk_clearance: str | Path,
    daily_risk_ledger: str | Path | None,
    output_dir: str | Path = "data/reports/micro_v2_clearance_runtime_check",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    requested = effective_requested_profile(signal_profile, profile_config)
    ledger = load_clearance_ledger(paper_risk_clearance)
    clearance = latest_clearance(ledger)
    cleared_canonical = normalize_profile_name(clearance.get("canonical_cleared_for_profile") or clearance.get("cleared_for_profile"))
    runtime_guard = validate_micro_v2_forward_shadow_runtime(
        mode="forward-shadow",
        signal_profile=signal_profile,
        profile_config=profile_config,
        sqlite_path=database.path,
        log_dir=log_dir,
    )
    clearance_validation = validate_micro_resume_clearance(
        database=database,
        clearance_ledger=paper_risk_clearance,
        profile=signal_profile,
        profile_config=profile_config,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=Path(reports_root) / "paper_risk",
        daily_risk_ledger=daily_risk_ledger,
    )
    daily_validation = validate_micro_daily_risk(
        database=database,
        clearance_ledger=paper_risk_clearance,
        daily_risk_ledger=daily_risk_ledger,
        profile_config=profile_config,
        profile=signal_profile,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=Path(reports_root) / "paper_risk",
    )
    daily_ledger_exists = bool(daily_risk_ledger and Path(daily_risk_ledger).exists())
    clearance_match = (
        str(requested.get("requested_profile_canonical", "")) == MICRO_V2_SIGNAL_PROFILE
        and cleared_canonical == MICRO_V2_SIGNAL_PROFILE
        and bool(clearance_validation.get("accepted", False))
    )
    status = _status(runtime_guard, clearance_validation, clearance, daily_validation, clearance_match, daily_ledger_exists)
    summary = {
        "mode": "micro-v2-clearance-runtime-check",
        "micro_v2_clearance_runtime_check_status": status,
        "clearance_profile_match": clearance_match,
        "requested_profile": requested.get("requested_profile", ""),
        "requested_profile_canonical": requested.get("requested_profile_canonical", ""),
        "cleared_for_profile": clearance.get("cleared_for_profile", ""),
        "cleared_for_profile_canonical": cleared_canonical,
        "clearance_scope": clearance.get("clearance_scope", ""),
        "approved_for_demo": bool(clearance.get("approved_for_demo", False)),
        "approved_for_live": bool(clearance.get("approved_for_live", False)),
        "runtime_guard_status": runtime_guard.get("micro_v2_runtime_guard_status", ""),
        "paper_risk_clearance_status": clearance_validation.get("paper_risk_clearance_status", ""),
        "daily_risk_ledger_status": daily_validation.get("daily_risk_ledger_status", "DAILY_RISK_LEDGER_ACCEPTED") if daily_ledger_exists else "DAILY_RISK_LEDGER_MISSING",
        "daily_risk_accepted": bool(daily_validation.get("accepted", False) and daily_ledger_exists),
        "launch_would_not_fail_paper_risk_clearance_required": status == "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK",
        "blocking_reason": "" if status == "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK" else _blocking_reason(runtime_guard, clearance_validation, daily_validation, daily_ledger_exists),
        "recommended_action": _recommended_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, requested, clearance, runtime_guard, clearance_validation, daily_validation)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(
    runtime_guard: Mapping[str, Any],
    clearance_validation: Mapping[str, Any],
    clearance: Mapping[str, Any],
    daily_validation: Mapping[str, Any],
    clearance_match: bool,
    daily_ledger_exists: bool,
) -> str:
    if runtime_guard.get("micro_v2_runtime_guard_status") != "MICRO_V2_RUNTIME_GUARDS_PASSED":
        return "MICRO_V2_CLEARANCE_PATH_GUARD_FAILED"
    if str(clearance.get("clearance_scope", "")).upper() != "PAPER_DRY_RUN_ONLY":
        return "MICRO_V2_CLEARANCE_SCOPE_INVALID"
    if bool(clearance.get("approved_for_demo", False)) or bool(clearance.get("approved_for_live", False)):
        return "MICRO_V2_CLEARANCE_LEDGER_INVALID"
    if not clearance_match or not clearance_validation.get("accepted", False):
        return "MICRO_V2_CLEARANCE_RUNTIME_MATCH_FAILED"
    if not daily_ledger_exists or not daily_validation.get("accepted", False):
        return "MICRO_V2_CLEARANCE_RUNTIME_MATCH_FAILED"
    return "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK"


def _blocking_reason(runtime_guard: Mapping[str, Any], clearance_validation: Mapping[str, Any], daily_validation: Mapping[str, Any], daily_ledger_exists: bool) -> str:
    if runtime_guard.get("micro_v2_runtime_guard_status") != "MICRO_V2_RUNTIME_GUARDS_PASSED":
        return str(runtime_guard.get("micro_v2_runtime_guard_status", "MICRO_V2_CLEARANCE_PATH_GUARD_FAILED"))
    if not clearance_validation.get("accepted", False):
        return str(clearance_validation.get("paper_risk_clearance_status") or clearance_validation.get("reason") or "PAPER_RISK_CLEARANCE_REQUIRED")
    if not daily_ledger_exists:
        return "DAILY_RISK_LEDGER_MISSING"
    if not daily_validation.get("accepted", False):
        return str(daily_validation.get("paper_daily_risk_status") or daily_validation.get("reason") or "PAPER_DAILY_RISK_REQUIRED")
    return ""


def _recommended_action(status: str) -> str:
    return {
        "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK": "LAUNCH_V2_DRY_RUN_ONLY_WITH_V2_LEDGER_WHEN_OPERATOR_APPROVES",
        "MICRO_V2_CLEARANCE_RUNTIME_MATCH_FAILED": "USE_V2_LEDGER_WITH_BALANCED_STABLE_MICRO_V2_AND_VERIFY_DAILY_RISK_LEDGER",
        "MICRO_V2_CLEARANCE_LEDGER_INVALID": "REGENERATE_MICRO_V2_CLEARANCE_LEDGER",
        "MICRO_V2_CLEARANCE_PATH_GUARD_FAILED": "USE_ISOLATED_V2_SQLITE_AND_LOG_DIR",
        "MICRO_V2_CLEARANCE_SCOPE_INVALID": "REGENERATE_V2_LEDGER_WITH_PAPER_DRY_RUN_ONLY_SCOPE",
    }.get(status, "MANUAL_REVIEW_REQUIRED")


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    requested: Mapping[str, Any],
    clearance: Mapping[str, Any],
    runtime_guard: Mapping[str, Any],
    clearance_validation: Mapping[str, Any],
    daily_validation: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_clearance_runtime_check_summary.json",
        output / "clearance_runtime_match.json",
        output / "requested_vs_cleared_profile.json",
        output / "guard_trace.json",
        output / "recommendations.md",
        output / "report.html",
    ]
    write_json(paths[0], summary)
    write_json(paths[1], {"clearance_profile_match": summary.get("clearance_profile_match"), "clearance_validation": clearance_validation, "daily_validation": daily_validation, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    write_json(paths[2], {"requested": requested, "clearance": clearance, "requested_profile_canonical": summary.get("requested_profile_canonical"), "cleared_for_profile_canonical": summary.get("cleared_for_profile_canonical"), "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    write_json(paths[3], {"runtime_guard": runtime_guard, "clearance_validation": clearance_validation, "daily_validation": daily_validation, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    paths[4].write_text(_recommendations(summary), encoding="utf-8")
    paths[5].write_text(f"<html><body><h1>Micro V2 Clearance Runtime Check</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Clearance Runtime Check

Status: `{summary.get('micro_v2_clearance_runtime_check_status')}`

Profile match: `{summary.get('clearance_profile_match')}`

Recommended next action: `{summary.get('recommended_action')}`

This check is offline/read-only and does not execute forward-shadow.
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

"""Offline report for BALANCED_STABLE_MICRO_V2 runtime registration."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .runtime_profile_guard import MICRO_V2_SIGNAL_PROFILE, signal_profile_choices, validate_micro_v2_forward_shadow_runtime


def run_micro_v2_runtime_profile_check(
    *,
    sqlite_path: str | Path,
    log_dir: str | Path,
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    output_dir: str | Path = "data/reports/micro_v2_runtime_profile_check",
) -> dict[str, Any]:
    """Verify V2 is registered and guarded without launching forward-shadow."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    choices = signal_profile_choices()
    registered = MICRO_V2_SIGNAL_PROFILE in choices
    runtime_guard = validate_micro_v2_forward_shadow_runtime(
        mode="forward-shadow",
        signal_profile=MICRO_V2_SIGNAL_PROFILE,
        profile_config=v2_profile_config,
        sqlite_path="data/sqlite/forward-shadow-v2-dryrun.sqlite3",
        log_dir="data/logs/forward-shadow-v2-dryrun",
    )
    if not registered:
        status = "MICRO_V2_SIGNAL_PROFILE_NOT_REGISTERED"
    elif runtime_guard.get("micro_v2_runtime_guard_status") == "MICRO_V2_RUNTIME_GUARDS_PASSED":
        status = "MICRO_V2_SIGNAL_PROFILE_REGISTERED"
    else:
        status = str(runtime_guard.get("micro_v2_runtime_guard_status") or "MICRO_V2_RUNTIME_GUARDS_FAILED")
    summary = {
        "mode": "micro-v2-runtime-profile-check",
        "micro_v2_runtime_profile_check_status": status,
        "signal_profile_registered": registered,
        "registered_signal_profiles": choices,
        "v2_profile_config": str(v2_profile_config),
        "stable_sqlite_reference": str(sqlite_path),
        "stable_log_dir_reference": str(log_dir),
        "reports_root": str(reports_root),
        "launch_command_invalid_choice_resolved": registered,
        "runtime_guard_status": runtime_guard.get("micro_v2_runtime_guard_status"),
        "runtime_guard_failures": runtime_guard.get("failures", []),
        "recommended_action": _recommended_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, choices, runtime_guard)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _recommended_action(status: str) -> str:
    return {
        "MICRO_V2_SIGNAL_PROFILE_REGISTERED": "MANUALLY_LAUNCH_V2_DRY_RUN_ONLY_WHEN_OPERATOR_APPROVES",
        "MICRO_V2_SIGNAL_PROFILE_NOT_REGISTERED": "REGISTER_BALANCED_STABLE_MICRO_V2_IN_SIGNAL_PROFILE_CHOICES",
        "MICRO_V2_RUNTIME_GUARDS_FAILED": "FIX_MICRO_V2_RUNTIME_GUARDS_BEFORE_LAUNCH",
        "MICRO_V2_PROFILE_INVALID": "FIX_BALANCED_STABLE_MICRO_V2_PROFILE_MARKERS",
        "MICRO_V2_PATH_GUARD_REQUIRED": "USE_ISOLATED_V2_SQLITE_AND_LOG_DIR",
    }.get(status, "MANUAL_REVIEW_REQUIRED")


def _write_reports(output: Path, summary: Mapping[str, Any], choices: list[str], runtime_guard: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "micro_v2_runtime_profile_check_summary.json",
        output / "signal_profile_registry.json",
        output / "v2_runtime_guards.json",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], {"registered_signal_profiles": choices, "balanced_stable_micro_v2_registered": MICRO_V2_SIGNAL_PROFILE in choices, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(paths[2], runtime_guard)
    paths[3].write_text(_recommendations(summary), encoding="utf-8")
    paths[4].write_text(f"<html><body><h1>Micro V2 Runtime Profile Check</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Runtime Profile Check

Status: `{summary.get('micro_v2_runtime_profile_check_status')}`

Launch command invalid choice resolved: `{summary.get('launch_command_invalid_choice_resolved')}`

Recommended next action: `{summary.get('recommended_action')}`

This check does not execute forward-shadow and does not authorize demo/live execution.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

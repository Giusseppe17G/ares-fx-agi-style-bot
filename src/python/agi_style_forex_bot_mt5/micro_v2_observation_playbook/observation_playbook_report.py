"""Report orchestration for the Micro V2 observation playbook."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .command_pack_builder import build_command_pack
from .evidence_pack_builder import build_evidence_pack
from .observation_window_planner import build_observation_schedule, schedule_markdown
from .stop_condition_builder import advancement_markdown, build_path_isolation_audit, operator_checklist_markdown, stop_rollback_markdown


def run_micro_v2_observation_playbook(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    output_dir: str | Path = "data/reports/micro_v2_observation_playbook",
) -> dict[str, Any]:
    """Create a read-only playbook and evidence command pack for V2 observation."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path_audit = build_path_isolation_audit(v2_sqlite=v2_sqlite, v2_log_dir=v2_log_dir, base_sqlite=base_sqlite, base_log_dir=base_log_dir)
    profile_audit = _audit_v2_profile(Path(v2_profile_config))
    command_pack = build_command_pack(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
    )
    evidence_pack = build_evidence_pack(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
    )
    schedule = build_observation_schedule()
    status, action = _classify(path_audit, profile_audit)
    summary = {
        "mode": "micro-v2-observation-playbook",
        "micro_v2_observation_playbook_status": status,
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "base_sqlite": str(base_sqlite),
        "base_log_dir": str(base_log_dir),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "path_isolation_valid": path_audit.get("path_isolation_valid", False),
        "path_isolation_failures": path_audit.get("path_isolation_failures", []),
        "v2_profile_valid": profile_audit.get("v2_profile_valid", False),
        "v2_profile_findings": profile_audit.get("profile_findings", []),
        "minimum_market_open_hours": schedule["minimum_market_open_hours"],
        "minimum_closed_paper_trades": schedule["minimum_closed_paper_trades"],
        "checkpoint_interval_hours_first_8h": schedule["first_8h_checkpoint_interval_hours"],
        "advancement_criteria": _advancement_criteria(),
        "stop_rollback_criteria": _stop_rollback_criteria(),
        "launch_commands_created": True,
        "monitoring_commands_created": True,
        "evidence_commands_created": True,
        "advancement_criteria_created": True,
        "stop_rollback_criteria_created": True,
        "observation_schedule_created": True,
        "operator_checklist_created": True,
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, path_audit, profile_audit, command_pack, evidence_pack, schedule)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _classify(path_audit: Mapping[str, Any], profile_audit: Mapping[str, Any]) -> tuple[str, str]:
    if not path_audit.get("path_isolation_valid", False):
        return "MICRO_V2_OBSERVATION_PLAYBOOK_BLOCKED", "FIX_V2_PATH_ISOLATION_BEFORE_OBSERVATION"
    if not profile_audit.get("v2_profile_valid", False):
        return "MICRO_V2_OBSERVATION_PLAYBOOK_REQUIRES_MANUAL_REVIEW", "REVIEW_V2_PROFILE_GUARDS_BEFORE_MARKET_OPEN_OBSERVATION"
    return "MICRO_V2_OBSERVATION_PLAYBOOK_READY", "WAIT_FOR_MARKET_OPEN_AND_RUN_PLAYBOOK_CHECKPOINTS"


def _audit_v2_profile(path: Path) -> dict[str, Any]:
    values = _read_ini_like(path)
    required = {
        "PROFILE_NAME": "BALANCED_STABLE_MICRO_V2",
        "PAPER_ONLY": "true",
        "NOT_FOR_DEMO_LIVE": "true",
        "NOT_FOR_LIVE": "true",
        "APPROVED_FOR_PAPER_DRY_RUN_ONLY": "true",
        "APPROVED_FOR_DEMO": "false",
        "APPROVED_FOR_LIVE": "false",
    }
    findings: list[str] = []
    if not path.exists():
        findings.append("V2_PROFILE_CONFIG_MISSING")
    for key, expected in required.items():
        actual = str(values.get(key, "")).strip()
        if actual.lower() != expected.lower():
            findings.append(f"{key}_EXPECTED_{expected.upper()}_FOUND_{actual or 'MISSING'}")
    return {
        "v2_profile_config": str(path),
        "v2_profile_exists": path.exists(),
        "v2_profile_valid": not findings,
        "profile_findings": findings,
        "profile_values_checked": required,
    }


def _read_ini_like(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    path_audit: Mapping[str, Any],
    profile_audit: Mapping[str, Any],
    command_pack: Mapping[str, Any],
    evidence_pack: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_observation_playbook_summary.json",
        output / "launch_commands.md",
        output / "monitoring_commands.md",
        output / "evidence_commands.md",
        output / "advancement_criteria.md",
        output / "stop_rollback_criteria.md",
        output / "observation_schedule.md",
        output / "operator_checklist.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    paths[1].write_text(str(command_pack["launch_commands_md"]), encoding="utf-8")
    paths[2].write_text(str(command_pack["monitoring_commands_md"]), encoding="utf-8")
    paths[3].write_text(str(evidence_pack["evidence_commands_md"]), encoding="utf-8")
    paths[4].write_text(advancement_markdown(), encoding="utf-8")
    paths[5].write_text(stop_rollback_markdown(), encoding="utf-8")
    paths[6].write_text(schedule_markdown(dict(schedule)), encoding="utf-8")
    paths[7].write_text(operator_checklist_markdown(dict(path_audit)), encoding="utf-8")
    paths[8].write_text(_recommendations(summary, path_audit, profile_audit), encoding="utf-8")
    paths[9].write_text(_html_report(summary, path_audit, profile_audit), encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any], path_audit: Mapping[str, Any], profile_audit: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Observation Playbook Recommendations

Status: `{summary.get('micro_v2_observation_playbook_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

Path isolation valid: `{path_audit.get('path_isolation_valid')}`

V2 profile valid: `{profile_audit.get('v2_profile_valid')}`

Run the monitoring and evidence commands when market-open ticks are fresh. This playbook does not launch V2, does not pause/resume shadow, does not open or close paper trades, and does not authorize demo/live execution.
"""


def _html_report(summary: Mapping[str, Any], path_audit: Mapping[str, Any], profile_audit: Mapping[str, Any]) -> str:
    payload = {"summary": summary, "path_isolation_audit": path_audit, "profile_audit": profile_audit}
    return f"<html><body><h1>Micro V2 Observation Playbook</h1><pre>{html.escape(json.dumps(_jsonable(payload), indent=2, sort_keys=True))}</pre></body></html>"


def _advancement_criteria() -> list[str]:
    return [
        "fresh_tick_symbols_not_empty",
        "market_closed_rejection_count_no_longer_dominates",
        "v2_runtime_active_true",
        "mt5_connected_true",
        "execution_attempted_false",
        "order_send_called_false",
        "order_check_called_false",
        "paper_state_recovery_ok",
    ]


def _stop_rollback_criteria() -> list[str]:
    return [
        "execution_attempted_true",
        "order_send_called_true",
        "order_check_called_true",
        "paper_state_error",
        "config_error",
        "active_scaled_drawdown_count_gt_zero",
        "invalid_open_paper_trade",
        "active_daily_risk_halt",
        "v2_uses_stable_paths",
        "heartbeat_stale",
    ]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

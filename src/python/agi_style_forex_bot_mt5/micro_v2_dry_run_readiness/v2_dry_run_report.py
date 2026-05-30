"""Report writer for BALANCED_STABLE_MICRO_V2 paper dry-run readiness."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .dry_run_path_planner import DEFAULT_V2_LOG_DIR, DEFAULT_V2_REPORTS_DIR, DEFAULT_V2_SQLITE, audit_path_isolation
from .v2_launch_command_builder import build_launch_checklist, build_launch_command, build_monitoring_commands, build_rollback_plan
from .v2_profile_guard import audit_v2_profile
from .v2_readiness_audit import audit_readiness


def run_micro_v2_dry_run_readiness(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    stable_gate: str | Path = "data/reports/stable_gate/stable_gate_summary.json",
    paper_risk_clearance: str | Path | None = None,
    daily_risk_ledger: str | Path | None = None,
    output_dir: str | Path = "data/reports/micro_v2_dry_run_readiness",
    v2_sqlite: str | Path = DEFAULT_V2_SQLITE,
    v2_log_dir: str | Path = DEFAULT_V2_LOG_DIR,
    v2_reports_dir: str | Path = DEFAULT_V2_REPORTS_DIR,
) -> dict[str, Any]:
    """Prepare V2 dry-run launch reports without executing forward-shadow."""

    before_counts = _db_counts(database)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    profile_guard = audit_v2_profile(v2_profile_config)
    path_isolation = audit_path_isolation(stable_sqlite=database.path, stable_log_dir=log_dir, v2_sqlite=v2_sqlite, v2_log_dir=v2_log_dir, v2_reports_dir=v2_reports_dir)
    readiness = audit_readiness(profile_guard=profile_guard, path_isolation=path_isolation, stable_gate=stable_gate, paper_risk_clearance=paper_risk_clearance, daily_risk_ledger=daily_risk_ledger)
    launch_command = build_launch_command(
        profile_config=v2_profile_config,
        stable_gate=stable_gate,
        paper_risk_clearance=paper_risk_clearance or "MISSING_PAPER_RISK_CLEARANCE",
        daily_risk_ledger=daily_risk_ledger or "MISSING_DAILY_RISK_LEDGER",
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
    )
    monitoring = build_monitoring_commands(v2_sqlite=v2_sqlite, v2_log_dir=v2_log_dir, reports_root=reports_root, v2_reports_dir=v2_reports_dir)
    summary = {
        "mode": "micro-v2-dry-run-readiness",
        **readiness,
        "v2_profile_config": str(v2_profile_config),
        "stable_gate": str(stable_gate),
        "paper_risk_clearance": str(paper_risk_clearance or ""),
        "daily_risk_ledger": str(daily_risk_ledger or ""),
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "v2_reports_dir": str(v2_reports_dir),
        "micro_v2_launch_command_available": readiness.get("micro_v2_dry_run_readiness_status") == "MICRO_V2_DRY_RUN_READY",
        "launch_command": launch_command,
        "sqlite_stable_unchanged": before_counts == _db_counts(database),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, profile_guard, path_isolation, launch_command, monitoring)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    profile_guard: Mapping[str, Any],
    path_isolation: Mapping[str, Any],
    launch_command: str,
    monitoring: str,
) -> list[Path]:
    paths = [
        output / "micro_v2_dry_run_readiness_summary.json",
        output / "v2_profile_guard.json",
        output / "path_isolation_audit.json",
        output / "launch_command.txt",
        output / "launch_checklist.md",
        output / "rollback_plan.md",
        output / "monitoring_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], profile_guard)
    _write_json(paths[2], path_isolation)
    paths[3].write_text(launch_command + "\n", encoding="utf-8")
    paths[4].write_text(build_launch_checklist(launch_command), encoding="utf-8")
    paths[5].write_text(build_rollback_plan(), encoding="utf-8")
    paths[6].write_text(monitoring, encoding="utf-8")
    paths[7].write_text(_recommendations(summary), encoding="utf-8")
    paths[8].write_text(f"<html><body><h1>Micro V2 Dry-Run Readiness</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Dry-Run Readiness

Status: `{summary.get('micro_v2_dry_run_readiness_status')}`

Launch command available: `{summary.get('micro_v2_launch_command_available')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This phase does not execute V2. The command is for a future explicit manual paper dry-run only.
"""


def _db_counts(database: TelemetryDatabase) -> tuple[int, int, dict[str, Any]]:
    return (database.count_rows("events"), database.count_rows("paper_trades"), database.get_operational_state())


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

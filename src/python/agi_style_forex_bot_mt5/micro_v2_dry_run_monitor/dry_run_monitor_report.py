"""Report orchestration for Micro V2 dry-run monitoring."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .base_vs_v2_comparator import compare_base_vs_v2, comparison_metric_rows
from .dry_run_loader import load_dry_run_dataset
from .heartbeat_audit import audit_heartbeat
from .safety_status_audit import audit_safety_status
from .v2_activity_audit import audit_activity


def run_micro_v2_dry_run_monitor(
    *,
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/micro_v2_dry_run_monitor",
) -> dict[str, Any]:
    """Build an offline/read-only monitoring pack for the isolated V2 dry-run."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = load_dry_run_dataset(sqlite_path=base_sqlite, log_dir=base_log_dir, label="base")
    v2 = load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2")
    base_heartbeat = audit_heartbeat(base)
    v2_heartbeat = audit_heartbeat(v2)
    base_activity = audit_activity(base)
    v2_activity = audit_activity(v2)
    safety = audit_safety_status(base, v2)
    comparison = compare_base_vs_v2(
        base_activity=base_activity,
        base_window=base_heartbeat,
        v2_activity=v2_activity,
        v2_window=v2_heartbeat,
    )
    status, action = _classify(v2, v2_heartbeat, v2_activity, safety, comparison)
    summary = {
        "mode": "micro-v2-dry-run-monitor",
        "micro_v2_dry_run_monitor_status": status,
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "base_sqlite": str(base_sqlite),
        "base_log_dir": str(base_log_dir),
        "reports_root": str(reports_root),
        "v2_hours_observed": v2_heartbeat.get("hours_observed", 0.0),
        "v2_paper_trades_open": v2_activity.get("paper_trades_open", 0),
        "v2_paper_trades_closed": v2_activity.get("paper_trades_closed", 0),
        "v2_paper_trades_closed_today": v2_activity.get("paper_trades_closed_today", 0),
        "v2_signals_detected": v2_activity.get("signals_detected", 0),
        "v2_signals_rejected": v2_activity.get("signals_rejected", 0),
        "v2_rejection_rate": v2_activity.get("rejection_rate", 0.0),
        "v2_heartbeat_recent": v2_heartbeat.get("heartbeat_recent", False),
        "v2_process_appears_active": v2_heartbeat.get("process_appears_active", False),
        "v2_paper_state_recovery_status": v2_activity.get("paper_state_recovery_status", ""),
        "v2_config_error_root_cause": v2_activity.get("config_error_root_cause", ""),
        "base_closed_trade_rate_per_24h": comparison.get("base_metrics", {}).get("closed_trade_rate_per_24h", 0.0),
        "v2_closed_trade_rate_per_24h": comparison.get("v2_metrics", {}).get("closed_trade_rate_per_24h", 0.0),
        "base_signal_detection_rate_per_24h": comparison.get("base_metrics", {}).get("signal_detection_rate_per_24h", 0.0),
        "v2_signal_detection_rate_per_24h": comparison.get("v2_metrics", {}).get("signal_detection_rate_per_24h", 0.0),
        "v2_improves_frequency": comparison.get("v2_improves_frequency", False),
        "v2_worsens_safety": comparison.get("v2_worsens_safety", False),
        "recommended_next_action": action,
        "acceptance_approved_by_monitor": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, v2_heartbeat, v2_activity, comparison, safety)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _classify(
    v2_dataset: Mapping[str, Any],
    v2_heartbeat: Mapping[str, Any],
    v2_activity: Mapping[str, Any],
    safety: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> tuple[str, str]:
    if safety.get("safety_status") == "SAFETY_BLOCKED":
        return "MICRO_V2_DRY_RUN_SAFETY_BLOCKED", "STOP_V2_DRY_RUN_AND_REVIEW_SAFETY_FLAGS"
    if v2_dataset.get("sqlite_read_error"):
        return "MICRO_V2_DRY_RUN_DATA_INVALID", "REVIEW_V2_SQLITE_AND_LOG_PATHS"
    if v2_heartbeat.get("heartbeat_stale") or (int(v2_heartbeat.get("heartbeat_count", 0) or 0) == 0 and int(v2_activity.get("signals_detected", 0) or 0) == 0 and int(v2_activity.get("paper_trades_closed", 0) or 0) == 0):
        return "MICRO_V2_DRY_RUN_NOT_RUNNING", "RESTART_OR_VERIFY_V2_DRY_RUN_TERMINAL_WITHOUT_TOUCHING_STABLE"
    if bool(v2_heartbeat.get("heartbeat_recent")) and int(v2_activity.get("signals_detected", 0) or 0) == 0 and int(v2_activity.get("paper_trades_closed", 0) or 0) == 0 and int(v2_activity.get("paper_trades_open", 0) or 0) == 0:
        return "MICRO_V2_DRY_RUN_ACTIVE_NO_DATA_YET", "KEEP_COLLECTING_V2_DATA"
    hours = float(v2_heartbeat.get("hours_observed", 0.0) or 0.0)
    closed = int(v2_activity.get("paper_trades_closed", 0) or 0)
    if hours < 24 or closed < 10:
        return "MICRO_V2_DRY_RUN_NEEDS_MORE_TIME", "KEEP_COLLECTING_V2_DATA"
    if comparison.get("v2_worsens_safety", False):
        return "MICRO_V2_DRY_RUN_UNDERPERFORMING_BASE", "REVIEW_V2_SAFETY_BEFORE_ANY_NEXT_PHASE"
    if comparison.get("v2_improves_frequency", False):
        return "MICRO_V2_DRY_RUN_OUTPERFORMING_BASE", "CONTINUE_OBSERVATION_AND_RUN_FORWARD_ACCEPTANCE_SEPARATELY"
    return "MICRO_V2_DRY_RUN_COLLECTING_DATA", "KEEP_COLLECTING_V2_DATA"


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
    activity: Mapping[str, Any],
    comparison: Mapping[str, Any],
    safety: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_dry_run_monitor_summary.json",
        output / "heartbeat_audit.json",
        output / "v2_activity_summary.json",
        output / "base_vs_v2_comparison.json",
        output / "base_vs_v2_metrics.csv",
        output / "v2_rejections.csv",
        output / "safety_status.json",
        output / "monitoring_recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], heartbeat)
    _write_json(paths[2], activity)
    _write_json(paths[3], comparison)
    _write_csv(paths[4], comparison_metric_rows(comparison))
    _write_csv(paths[5], _rejection_rows(activity))
    _write_json(paths[6], safety)
    paths[7].write_text(_recommendations(summary), encoding="utf-8")
    paths[8].write_text(f"<html><body><h1>Micro V2 Dry-Run Monitor</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _rejection_rows(activity: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **dict(row),
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
        for row in activity.get("rejected_by_reason", [])
    ]


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Dry-Run Monitor

Status: `{summary.get('micro_v2_dry_run_monitor_status')}`

V2 hours observed: `{summary.get('v2_hours_observed')}`

V2 closed paper trades: `{summary.get('v2_paper_trades_closed')}`

V2 signals detected: `{summary.get('v2_signals_detected')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This monitor is offline/read-only. It does not approve forward acceptance, does not execute V2, does not pause/resume shadow, and does not authorize demo/live execution.
"""


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

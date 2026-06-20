"""Report orchestration for Micro V2 reset watcher."""

from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any, Mapping

from .relaunch_notification_builder import build_relaunch_notification
from .reset_gate_recheck import recheck_reset_gate
from .reset_watcher_loader import load_reset_watcher_inputs
from .watcher_command_builder import recommended_commands


def run_micro_v2_reset_watcher(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    post_reset_relaunch_dir: str | Path = "data/reports/micro_v2_post_reset_relaunch_pack",
    pre_relaunch_safety_dir: str | Path = "data/reports/micro_v2_pre_relaunch_safety_pack",
    daily_risk_scope_repair_dir: str | Path = "data/reports/micro_v2_daily_risk_scope_repair",
    output_dir: str | Path = "data/reports/micro_v2_reset_watcher",
    watch: bool = False,
    interval_seconds: int = 300,
    max_checks: int = 12,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    last: dict[str, Any] = {}
    checks = max(1, int(max_checks or 1)) if watch else 1
    for index in range(checks):
        last = _run_once(
            v2_sqlite=v2_sqlite,
            v2_log_dir=v2_log_dir,
            reports_root=reports_root,
            v2_profile_config=v2_profile_config,
            daily_risk_ledger=daily_risk_ledger,
            post_reset_relaunch_dir=post_reset_relaunch_dir,
            pre_relaunch_safety_dir=pre_relaunch_safety_dir,
            daily_risk_scope_repair_dir=daily_risk_scope_repair_dir,
            check_index=index + 1,
            watch=watch,
        )
        if last.get("micro_v2_reset_watcher_status") == "MICRO_V2_RESET_WATCHER_READY_FOR_MANUAL_RELAUNCH":
            break
        if watch and index + 1 < checks:
            time.sleep(max(0, int(interval_seconds or 0)))
    paths = _write_reports(output, last)
    return {**last, "reports_created": [str(path) for path in paths]}


def _run_once(**kwargs: Any) -> dict[str, Any]:
    inputs = load_reset_watcher_inputs(
        v2_sqlite=kwargs["v2_sqlite"],
        v2_log_dir=kwargs["v2_log_dir"],
        reports_root=kwargs["reports_root"],
        v2_profile_config=kwargs["v2_profile_config"],
        daily_risk_ledger=kwargs["daily_risk_ledger"],
        post_reset_relaunch_dir=kwargs["post_reset_relaunch_dir"],
        pre_relaunch_safety_dir=kwargs["pre_relaunch_safety_dir"],
        daily_risk_scope_repair_dir=kwargs["daily_risk_scope_repair_dir"],
    )
    recheck = recheck_reset_gate(inputs)
    notification = build_relaunch_notification(recheck)
    status = str(recheck.get("reset_gate_recheck_status") or "")
    ready = status == "MICRO_V2_RESET_WATCHER_READY_FOR_MANUAL_RELAUNCH"
    return {
        "mode": "micro-v2-reset-watcher",
        "micro_v2_reset_watcher_status": status,
        "daily_halt_active": recheck.get("daily_halt_active", False),
        "daily_reset_occurred": recheck.get("daily_reset_occurred", False),
        "post_reset_relaunch_allowed": recheck.get("post_reset_relaunch_allowed", False),
        "daily_risk_scope_verified": recheck.get("daily_risk_scope_verified", False),
        "zero_risk_guard_verified": recheck.get("zero_risk_guard_verified", False),
        "paper_state_clean_for_relaunch": recheck.get("paper_state_clean_for_relaunch", False),
        "relaunch_command_available": ready,
        "recommended_next_action": notification.get("recommended_next_action", ""),
        "watch": bool(kwargs.get("watch", False)),
        "checks_completed": int(kwargs.get("check_index", 1) or 1),
        "forward_shadow_executed": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "_recheck": recheck,
        "_notification": notification,
    }


def _write_reports(output: Path, summary: Mapping[str, Any]) -> list[Path]:
    recheck = summary.get("_recheck") if isinstance(summary.get("_recheck"), Mapping) else {}
    notification = summary.get("_notification") if isinstance(summary.get("_notification"), Mapping) else {}
    clean_summary = {key: value for key, value in summary.items() if not str(key).startswith("_")}
    paths = [
        output / "micro_v2_reset_watcher_summary.json",
        output / "reset_gate_recheck.json",
        output / "relaunch_notification.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], clean_summary)
    _write_json(paths[1], recheck)
    _write_json(paths[2], notification)
    paths[3].write_text(recommended_commands(ready=bool(clean_summary.get("relaunch_command_available"))), encoding="utf-8")
    paths[4].write_text(_recommendations(clean_summary), encoding="utf-8")
    paths[5].write_text(f"<html><body><h1>Micro V2 Reset Watcher</h1><pre>{html.escape(json.dumps(_jsonable(clean_summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Recommendations

Status: `{summary.get('micro_v2_reset_watcher_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This watcher never executes forward-shadow.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

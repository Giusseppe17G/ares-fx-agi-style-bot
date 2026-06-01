"""Report orchestration for Micro V2 post-repair resume guard."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .daily_risk_block_diagnosis import diagnose_daily_risk_block
from .lifecycle_recheck import recheck_lifecycle, safety_flags
from .post_repair_loader import load_post_repair_inputs
from .resume_guard_policy import evaluate_post_repair_resume_guard


def run_micro_v2_post_repair_resume_guard(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    repair_dir: str | Path = "data/reports/micro_v2_guarded_paper_state_repair",
    lifecycle_dir: str | Path = "data/reports/micro_v2_lifecycle_risk_comparison",
    daily_risk_ledger: str | Path | None = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    output_dir: str | Path = "data/reports/micro_v2_post_repair_resume_guard",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_post_repair_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        repair_dir=repair_dir,
        lifecycle_dir=lifecycle_dir,
        daily_risk_ledger=daily_risk_ledger,
    )
    lifecycle = recheck_lifecycle(inputs["v2_dataset"], inputs.get("repair_after", {}))
    daily = diagnose_daily_risk_block(lifecycle, inputs.get("daily_risk_ledger_payload", {}))
    safety = safety_flags(inputs["v2_dataset"])
    signal_profile = inputs["profile_values"].get("SIGNAL_PROFILE") or inputs["profile_values"].get("PROFILE_NAME") or ""
    policy = evaluate_post_repair_resume_guard(
        signal_profile=signal_profile,
        sqlite_path=v2_sqlite,
        profile_values=inputs["profile_values"],
        lifecycle=lifecycle,
        safety_flags=safety,
        daily_risk_status=str(daily.get("daily_risk_block_status") or ""),
    )
    summary = {
        "mode": "micro-v2-post-repair-resume-guard",
        "micro_v2_post_repair_resume_guard_status": policy.get("micro_v2_post_repair_resume_guard_status", ""),
        "open_trade_count": lifecycle.get("open_trade_count", 0),
        "invalid_open_trade_count": lifecycle.get("invalid_open_trade_count", 0),
        "quarantined_trade_count": lifecycle.get("quarantined_trade_count", 0),
        "manage_open_trades_only_enabled": bool(policy.get("manage_open_trades_only_enabled", False)),
        "new_entries_blocked": bool(policy.get("new_entries_blocked", False)),
        "paper_exit_evaluation_allowed": bool(policy.get("paper_exit_evaluation_allowed", False)),
        "daily_risk_block_status": daily.get("daily_risk_block_status", ""),
        "recommended_next_action": _next_action(policy),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, lifecycle, daily, policy)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _next_action(policy: Mapping[str, Any]) -> str:
    status = str(policy.get("micro_v2_post_repair_resume_guard_status") or "")
    if status == "MICRO_V2_POST_REPAIR_MANAGE_OPEN_TRADES_ONLY_ENABLED":
        return "RELAUNCH_V2_FORWARD_SHADOW_TO_MANAGE_OPEN_TRADES_ONLY"
    if status == "MICRO_V2_POST_REPAIR_BLOCKED_INVALID_OPEN_TRADES":
        return "RERUN_INVALID_TRADE_FORENSICS"
    if status == "MICRO_V2_POST_REPAIR_BLOCKED_NO_OPEN_TRADES":
        return "RERUN_DAILY_RISK_CLEAR_AND_NORMAL_V2_LAUNCH"
    return "REVIEW_POST_REPAIR_RESUME_GUARD_REPORT"


def _write_reports(output: Path, summary: Mapping[str, Any], lifecycle: Mapping[str, Any], daily: Mapping[str, Any], policy: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "micro_v2_post_repair_resume_guard_summary.json",
        output / "lifecycle_recheck.json",
        output / "daily_risk_block_diagnosis.json",
        output / "resume_guard_policy.json",
        output / "manage_open_trades_only_policy.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], lifecycle)
    _write_json(paths[2], daily)
    _write_json(paths[3], policy)
    _write_json(paths[4], {key: policy.get(key) for key in ("paper_resume_mode", "manage_open_trades_only_enabled", "new_entries_blocked", "new_paper_trades_blocked", "paper_exit_evaluation_allowed", "daily_risk_clearing_blocked_until_open_trades_zero", "real_trading_allowed", "demo_live_allowed", "execution_attempted", "order_send_called", "order_check_called")})
    paths[5].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[6].write_text(_recommendations(summary), encoding="utf-8")
    paths[7].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Post-Repair Resume Guard

Status: `{summary.get('micro_v2_post_repair_resume_guard_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

Manage-open-trades-only blocks new entries and permits only paper management of existing open trades.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Post-Repair Resume Guard

Open trades: `{summary.get('open_trade_count')}`

Invalid open trades: `{summary.get('invalid_open_trade_count')}`

Manage-only enabled: `{summary.get('manage_open_trades_only_enabled')}`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Post-Repair Resume Guard</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

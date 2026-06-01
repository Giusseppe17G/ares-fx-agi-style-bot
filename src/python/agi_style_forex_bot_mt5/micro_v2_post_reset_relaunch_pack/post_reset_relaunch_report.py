"""Report orchestration for Micro V2 post-reset relaunch pack."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .acceptance_blocker_tracker import build_acceptance_blocker_tracker
from .daily_reset_recheck import recheck_daily_reset
from .ledger_scope_verifier import verify_ledger_scope
from .paper_state_relaunch_gate import evaluate_paper_state_gate
from .post_relaunch_observation_plan import observation_plan_markdown
from .post_reset_loader import load_post_reset_inputs
from .relaunch_command_builder import command_pack, commands_markdown
from .zero_risk_guard_verifier import verify_zero_risk_guard


def run_micro_v2_post_reset_relaunch_pack(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    daily_reset_readiness_dir: str | Path = "data/reports/micro_v2_daily_reset_readiness",
    pre_relaunch_safety_dir: str | Path = "data/reports/micro_v2_pre_relaunch_safety_pack",
    daily_risk_scope_repair_dir: str | Path = "data/reports/micro_v2_daily_risk_scope_repair",
    closed_loss_scope_dir: str | Path = "data/reports/micro_v2_closed_loss_scope_decision",
    output_dir: str | Path = "data/reports/micro_v2_post_reset_relaunch_pack",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_post_reset_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        daily_risk_ledger=daily_risk_ledger,
        daily_reset_readiness_dir=daily_reset_readiness_dir,
        pre_relaunch_safety_dir=pre_relaunch_safety_dir,
        daily_risk_scope_repair_dir=daily_risk_scope_repair_dir,
        closed_loss_scope_dir=closed_loss_scope_dir,
    )
    readiness = inputs["daily_reset_readiness"]
    pre_relaunch = inputs["pre_relaunch_safety"]
    scope_repair = inputs["daily_risk_scope_repair"]
    daily = recheck_daily_reset(readiness)
    guard = verify_zero_risk_guard(pre_relaunch)
    scope = verify_ledger_scope(scope_repair, readiness)
    paper = evaluate_paper_state_gate(readiness)
    blockers = build_acceptance_blocker_tracker(readiness, pre_relaunch, scope_repair)
    safety_blocked = any(bool(source.get(key, False)) for source in (readiness, pre_relaunch, scope_repair) for key in ("execution_attempted", "order_send_called", "order_check_called"))
    status = _status(daily, guard, scope, paper, readiness, safety_blocked=safety_blocked)
    relaunch_allowed = status == "MICRO_V2_POST_RESET_READY_FOR_RELAUNCH"
    commands = command_pack(relaunch_allowed=relaunch_allowed)
    summary = {
        "mode": "micro-v2-post-reset-relaunch-pack",
        "micro_v2_post_reset_relaunch_pack_status": status,
        "daily_halt_active": daily.get("daily_halt_active", False),
        "daily_reset_occurred": daily.get("daily_reset_occurred", False),
        "current_operational_day": daily.get("current_operational_day", ""),
        "latest_halt_operational_day": daily.get("latest_halt_operational_day", ""),
        "daily_risk_scope_verified": scope.get("daily_risk_scope_verified", False),
        "daily_risk_scope_status": scope.get("daily_risk_scope_status", ""),
        "zero_risk_guard_verified": guard.get("zero_risk_guard_verified", False),
        "paper_state_clean_for_relaunch": paper.get("paper_state_clean_for_relaunch", False),
        "open_trade_count": paper.get("open_trade_count", 0),
        "invalid_open_trade_count": paper.get("invalid_open_trade_count", 0),
        "quarantined_trade_count": paper.get("quarantined_trade_count", 0),
        "closed_trade_count": scope.get("closed_trade_count", 0),
        "closed_scaled_pnl_total": scope.get("closed_scaled_pnl_total", 0.0),
        "post_reset_relaunch_allowed": relaunch_allowed,
        "recommended_next_action": "MANUAL_RELAUNCH_V2_PAPER_DRY_RUN" if relaunch_allowed else "KEEP_V2_STOPPED_AND_RERUN_POST_RESET_RELAUNCH_PACK_LATER",
        "acceptance_blockers": blockers.get("current_blockers", []),
        "resolved_blockers": blockers.get("resolved_blockers", []),
        "forward_shadow_executed": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, daily, guard, scope, paper, commands, blockers)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(
    daily: Mapping[str, Any],
    guard: Mapping[str, Any],
    scope: Mapping[str, Any],
    paper: Mapping[str, Any],
    readiness: Mapping[str, Any],
    *,
    safety_blocked: bool,
) -> str:
    if safety_blocked:
        return "MICRO_V2_POST_RESET_SAFETY_BLOCKED"
    if daily.get("daily_halt_active") and not daily.get("daily_reset_occurred"):
        return "MICRO_V2_POST_RESET_KEEP_HALTED_DAILY_HALT_ACTIVE"
    if not scope.get("daily_risk_scope_verified"):
        return "MICRO_V2_POST_RESET_SCOPE_INVALID"
    if not guard.get("zero_risk_guard_verified"):
        return "MICRO_V2_POST_RESET_ZERO_RISK_GUARD_MISSING"
    if int(paper.get("open_trade_count", 0) or 0) > 0:
        return "MICRO_V2_POST_RESET_OPEN_TRADES_BLOCK"
    if int(paper.get("invalid_open_trade_count", 0) or 0) > 0:
        return "MICRO_V2_POST_RESET_INVALID_TRADES_BLOCK"
    if not paper.get("paper_state_clean_for_relaunch"):
        return "MICRO_V2_POST_RESET_PAPER_STATE_BLOCK"
    if daily.get("daily_reset_occurred") and readiness.get("relaunch_allowed"):
        return "MICRO_V2_POST_RESET_READY_FOR_RELAUNCH"
    return "MICRO_V2_POST_RESET_REQUIRES_MANUAL_REVIEW"


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    daily: Mapping[str, Any],
    guard: Mapping[str, Any],
    scope: Mapping[str, Any],
    paper: Mapping[str, Any],
    commands: Mapping[str, Any],
    blockers: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_post_reset_relaunch_pack_summary.json",
        output / "daily_reset_recheck.json",
        output / "zero_risk_guard_verification.json",
        output / "ledger_scope_verification.json",
        output / "paper_state_relaunch_gate.json",
        output / "relaunch_command_pack.json",
        output / "acceptance_blocker_tracker.json",
        output / "post_relaunch_observation_plan.md",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], daily)
    _write_json(paths[2], guard)
    _write_json(paths[3], scope)
    _write_json(paths[4], paper)
    _write_json(paths[5], commands)
    _write_json(paths[6], blockers)
    paths[7].write_text(observation_plan_markdown(), encoding="utf-8")
    paths[8].write_text(commands_markdown(relaunch_allowed=bool(summary.get("post_reset_relaunch_allowed"))), encoding="utf-8")
    paths[9].write_text(_recommendations(summary), encoding="utf-8")
    paths[10].write_text(f"<html><body><h1>Micro V2 Post-Reset Relaunch Pack</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Recommendations

Status: `{summary.get('micro_v2_post_reset_relaunch_pack_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This phase does not execute forward-shadow and does not modify SQLite or ledgers.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

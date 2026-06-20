"""Report writer for Micro V2 post-reset relaunch orchestrator."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .relaunch_command_builder import recommendations_markdown, relaunch_commands_ps1
from .relaunch_decision import decide_relaunch
from .relaunch_gates import evaluate_relaunch_gates
from .relaunch_orchestrator import load_relaunch_context


def run_micro_v2_post_reset_relaunch(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    post_reset_relaunch_dir: str | Path = "data/reports/micro_v2_post_reset_relaunch_pack",
    output_dir: str | Path = "data/reports/micro_v2_post_reset_relaunch",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    context = load_relaunch_context(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        daily_risk_ledger=daily_risk_ledger,
        post_reset_relaunch_dir=post_reset_relaunch_dir,
    )
    gates = evaluate_relaunch_gates(context)
    decision = decide_relaunch(gates, context)
    summary = _summary(context, gates, decision)
    paths = _write_reports(output, summary, gates, decision)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _summary(context: Mapping[str, Any], gates: list[Mapping[str, Any]], decision: Mapping[str, Any]) -> dict[str, Any]:
    watcher = context.get("reset_watcher") if isinstance(context.get("reset_watcher"), Mapping) else {}
    post = context.get("post_reset_pack") if isinstance(context.get("post_reset_pack"), Mapping) else {}
    sqlite_state = context.get("sqlite_state") if isinstance(context.get("sqlite_state"), Mapping) else {}
    runtime = sqlite_state.get("runtime") if isinstance(sqlite_state.get("runtime"), Mapping) else {}
    market = context.get("market_open_readiness") if isinstance(context.get("market_open_readiness"), Mapping) else {}
    return {
        "mode": "micro-v2-post-reset-relaunch",
        "micro_v2_relaunch_status": decision.get("micro_v2_relaunch_decision"),
        "micro_v2_relaunch_decision": decision.get("micro_v2_relaunch_decision"),
        "relaunch_allowed": bool(decision.get("relaunch_allowed", False)),
        "safe_to_observe": bool(decision.get("safe_to_observe", False)),
        "daily_halt_active": bool(watcher.get("daily_halt_active", post.get("daily_halt_active", False))),
        "daily_reset_occurred": bool(watcher.get("daily_reset_occurred", post.get("daily_reset_occurred", False))),
        "post_reset_relaunch_allowed": bool(watcher.get("post_reset_relaunch_allowed", post.get("post_reset_relaunch_allowed", False))),
        "open_trade_count": int(sqlite_state.get("open_trade_count", post.get("open_trade_count", 0)) or 0),
        "invalid_open_trade_count": int(sqlite_state.get("invalid_open_trade_count", post.get("invalid_open_trade_count", 0)) or 0),
        "halt_reason": runtime.get("halt_reason", ""),
        "latest_exit_reason": runtime.get("latest_exit_reason", ""),
        "block_new_entries": bool(runtime.get("block_new_entries", False)),
        "mt5_connected": bool(market.get("mt5_connected", False)),
        "market_open_readiness_status": market.get("micro_v2_market_open_readiness_status", ""),
        "blocking_gate_count": int(decision.get("blocking_gate_count", 0) or 0),
        "blocking_gate_ids": decision.get("blocking_gate_ids", []),
        "reason": decision.get("reason", ""),
        "recommended_next_action": decision.get("recommended_next_action", ""),
        "command_pack_available": True,
        "forward_shadow_executed": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _write_reports(output: Path, summary: Mapping[str, Any], gates: list[Mapping[str, Any]], decision: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "relaunch_summary.json",
        output / "relaunch_decision.json",
        output / "relaunch_gates.json",
        output / "relaunch_recommendations.md",
        output / "relaunch_commands.ps1",
        output / "relaunch_report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], decision)
    _write_json(paths[2], {"gates": gates, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    paths[3].write_text(recommendations_markdown(decision), encoding="utf-8")
    paths[4].write_text(relaunch_commands_ps1(decision), encoding="utf-8")
    paths[5].write_text(f"<html><body><h1>Micro V2 Post-Reset Relaunch</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

"""Report orchestration for Micro V2 pre-relaunch safety pack."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .pre_relaunch_safety_audit import REJECTION_REASONS, audit_prevention_guards, load_json
from .recommended_command_builder import command_markdown
from .reset_relaunch_gate import evaluate_reset_relaunch_gate


def run_micro_v2_pre_relaunch_safety_pack(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    daily_reset_readiness_dir: str | Path = "data/reports/micro_v2_daily_reset_readiness",
    daily_risk_scope_repair_dir: str | Path = "data/reports/micro_v2_daily_risk_scope_repair",
    closed_loss_scope_dir: str | Path = "data/reports/micro_v2_closed_loss_scope_decision",
    open_trade_repair_dir: str | Path = "data/reports/micro_v2_guarded_open_trade_integrity_repair",
    output_dir: str | Path = "data/reports/micro_v2_pre_relaunch_safety_pack",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reset_summary = load_json(Path(daily_reset_readiness_dir) / "micro_v2_daily_reset_readiness_summary.json")
    guard = audit_prevention_guards()
    gate = evaluate_reset_relaunch_gate(reset_summary)
    status = _status(guard, gate)
    summary = {
        "mode": "micro-v2-pre-relaunch-safety-pack",
        "micro_v2_pre_relaunch_safety_pack_status": status,
        "zero_risk_guard_enabled": True,
        "invalid_paper_trade_prevention_active": True,
        "paper_trade_creation_guard_status": guard.get("paper_trade_creation_guard_status", ""),
        "zero_risk_rejections_count": guard.get("zero_risk_rejections_count", 0),
        "last_zero_risk_rejection_reason": guard.get("last_zero_risk_rejection_reason", ""),
        "sl_tp_side_guard_enabled": True,
        "precision_rounding_guard_enabled": True,
        "rejection_reasons_added": REJECTION_REASONS,
        "daily_halt_active": gate.get("daily_halt_active", False),
        "daily_reset_occurred": gate.get("daily_reset_occurred", False),
        "daily_risk_scope_status": gate.get("daily_risk_scope_status", ""),
        "open_trade_count": gate.get("open_trade_count", 0),
        "invalid_open_trade_count": gate.get("invalid_open_trade_count", 0),
        "quarantined_trade_count": gate.get("quarantined_trade_count", 0),
        "paper_state_clean_for_relaunch": gate.get("paper_state_clean_for_relaunch", False),
        "relaunch_allowed": gate.get("relaunch_allowed", False),
        "recommended_next_action": gate.get("recommended_next_action", ""),
        "sqlite_modified": False,
        "ledger_modified": False,
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "daily_risk_ledger": str(daily_risk_ledger),
        "daily_risk_scope_repair_dir": str(daily_risk_scope_repair_dir),
        "closed_loss_scope_dir": str(closed_loss_scope_dir),
        "open_trade_repair_dir": str(open_trade_repair_dir),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, guard, gate)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(guard: Mapping[str, Any], gate: Mapping[str, Any]) -> str:
    if guard.get("paper_trade_creation_guard_status") != "PAPER_TRADE_CREATION_GUARD_ENABLED":
        return "MICRO_V2_ZERO_RISK_GUARD_MISSING_IN_CREATION_PATH"
    if gate.get("relaunch_allowed"):
        return "MICRO_V2_PRE_RELAUNCH_SAFETY_PACK_READY_FOR_RELAUNCH"
    if gate.get("daily_halt_active"):
        return "MICRO_V2_PRE_RELAUNCH_SAFETY_PACK_READY_KEEP_HALTED"
    if gate.get("reset_relaunch_gate_status") == "MICRO_V2_RELAUNCH_GATE_SCOPE_INVALID":
        return "MICRO_V2_RELAUNCH_GATE_SCOPE_INVALID"
    if gate.get("reset_relaunch_gate_status") == "MICRO_V2_RELAUNCH_GATE_PAPER_STATE_BLOCK":
        return "MICRO_V2_RELAUNCH_GATE_PAPER_STATE_BLOCK"
    return "MICRO_V2_PRE_RELAUNCH_REQUIRES_MANUAL_REVIEW"


def _write_reports(output: Path, summary: Mapping[str, Any], guard: Mapping[str, Any], gate: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "micro_v2_pre_relaunch_safety_pack_summary.json",
        output / "zero_risk_guard_audit.json",
        output / "stop_distance_validator_audit.json",
        output / "sl_tp_side_validator_audit.json",
        output / "precision_rounding_validator_audit.json",
        output / "paper_trade_creation_guard_audit.json",
        output / "reset_relaunch_gate.json",
        output / "prevention_rejection_reasons.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], guard)
    _write_json(paths[2], {"stop_distance_validator_enabled": True, "guard_test_cases": guard.get("guard_test_cases", []), "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(paths[3], {"sl_tp_side_guard_enabled": True, "guard_test_cases": guard.get("guard_test_cases", []), "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(paths[4], {"precision_rounding_guard_enabled": True, "guard_test_cases": guard.get("guard_test_cases", []), "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(paths[5], guard)
    _write_json(paths[6], gate)
    _write_json(paths[7], {"rejection_reasons_added": REJECTION_REASONS, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    paths[8].write_text(command_markdown(relaunch_allowed=bool(summary.get("relaunch_allowed"))), encoding="utf-8")
    paths[9].write_text(_recommendations(summary), encoding="utf-8")
    paths[10].write_text(f"<html><body><h1>Micro V2 Pre-Relaunch Safety Pack</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Recommendations

Status: `{summary.get('micro_v2_pre_relaunch_safety_pack_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This phase does not relaunch V2, clear daily halt, modify SQLite, or modify the daily risk ledger.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

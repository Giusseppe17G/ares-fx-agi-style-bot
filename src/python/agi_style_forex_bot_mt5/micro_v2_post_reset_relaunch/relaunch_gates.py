"""Gate evaluation for Micro V2 post-reset relaunch."""

from __future__ import annotations

from typing import Any, Mapping


def evaluate_relaunch_gates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    sqlite_state = _mapping(context.get("sqlite_state"))
    runtime = _mapping(sqlite_state.get("runtime"))
    profile = _mapping(context.get("profile_config"))
    watcher = _mapping(context.get("reset_watcher"))
    post = _mapping(context.get("post_reset_pack"))
    pre = _mapping(context.get("pre_relaunch_safety"))
    scope = _mapping(context.get("daily_risk_scope_repair"))
    clearance = _mapping(context.get("clearance_runtime"))
    market = _mapping(context.get("market_open_readiness"))
    telemetry = _mapping(context.get("telemetry_status"))
    execution = _mapping(context.get("execution_evidence"))
    rejection = _mapping(context.get("rejection_labeling"))
    symbol = _mapping(context.get("symbol_rejection"))
    paper_risk = _mapping(context.get("paper_risk_status"))
    heartbeat = _mapping(sqlite_state.get("latest_heartbeat"))

    gates: list[dict[str, Any]] = []
    daily_reset = bool(watcher.get("daily_reset_occurred", post.get("daily_reset_occurred", False)))
    daily_halt_active = bool(watcher.get("daily_halt_active", post.get("daily_halt_active", False)))
    gates.append(_gate("daily_reset_real", daily_reset and not daily_halt_active, "daily_reset_occurred=true and daily_halt_active=false", {"daily_reset_occurred": daily_reset, "daily_halt_active": daily_halt_active}, category="reset", wait_status="MICRO_V2_RELAUNCH_WAITING_RESET"))

    scope_status = post.get("daily_risk_scope_status") or scope.get("daily_risk_scope_status_after") or scope.get("daily_risk_scope_status")
    scope_ok = bool(post.get("daily_risk_scope_verified", False) or scope_status == "DAILY_RISK_SCOPE_OK_FOR_V2") and scope_status == "DAILY_RISK_SCOPE_OK_FOR_V2"
    gates.append(_gate("daily_risk_ledger_clean", scope_ok, "DAILY_RISK_SCOPE_OK_FOR_V2", scope_status or "missing", category="risk"))

    cooldown_active = bool(paper_risk.get("cooldown_active", False))
    gates.append(_gate("cooldown_expired", not cooldown_active, "cooldown_active=false", {"cooldown_active": cooldown_active, "cooldown_until_utc": paper_risk.get("cooldown_until_utc", "")}, category="cooldown", wait_status="MICRO_V2_RELAUNCH_WAITING_COOLDOWN"))

    gates.append(_gate("clearance_not_stale", _clearance_ok(clearance), "V2 clearance runtime match ok and daily risk accepted", {"status": clearance.get("micro_v2_clearance_runtime_check_status", ""), "match": clearance.get("clearance_profile_match", False), "daily_risk_accepted": clearance.get("daily_risk_accepted", False), "approved_for_demo": clearance.get("approved_for_demo", None), "approved_for_live": clearance.get("approved_for_live", None)}, category="clearance"))

    open_count = int(sqlite_state.get("open_trade_count", post.get("open_trade_count", 0)) or 0)
    invalid_count = int(sqlite_state.get("invalid_open_trade_count", post.get("invalid_open_trade_count", 0)) or 0)
    gates.append(_gate("no_open_or_invalid_paper_trades", open_count == 0 and invalid_count == 0, "open_trade_count=0 and invalid_open_trade_count=0", {"open_trade_count": open_count, "invalid_open_trade_count": invalid_count}, category="state"))

    paper_clean = bool(post.get("paper_state_clean_for_relaunch", False)) and runtime.get("halt_reason") != "PAPER_STATE_ERROR"
    gates.append(_gate("paper_state_clean", paper_clean, "paper_state_clean_for_relaunch=true and no PAPER_STATE_ERROR", {"paper_state_clean_for_relaunch": post.get("paper_state_clean_for_relaunch", False), "halt_reason": runtime.get("halt_reason", "")}, category="state"))

    no_config_error = runtime.get("latest_exit_reason") != "CONFIG_ERROR"
    gates.append(_gate("no_active_config_error", no_config_error, "latest_exit_reason != CONFIG_ERROR", runtime.get("latest_exit_reason", ""), category="config"))

    block_new_entries = bool(runtime.get("block_new_entries", False))
    gates.append(_gate("new_entries_unblocked", not block_new_entries, "block_new_entries=false", block_new_entries, category="risk"))

    profile_ok = _profile_ok(profile)
    gates.append(_gate("profile_config_valid", profile_ok, "BALANCED_STABLE_MICRO_V2 paper-only dry-run profile", _profile_observed(profile), category="config"))

    mt5_connected = bool(market.get("mt5_connected", heartbeat.get("mt5_connected", False)))
    market_status = str(market.get("micro_v2_market_open_readiness_status", ""))
    gates.append(_gate("mt5_diagnostics_pass", mt5_connected and market_status != "MICRO_V2_MT5_DISCONNECTED", "mt5_connected=true and not disconnected", {"mt5_connected": mt5_connected, "market_status": market_status}, category="mt5"))

    fresh_or_runtime_ready = market_status in {"MICRO_V2_MARKET_OPEN_TICKS_FRESH", "MICRO_V2_READY_FOR_LIVE_MARKET_OBSERVATION", "MICRO_V2_WAITING_FOR_MARKET_OPEN", "MICRO_V2_RUNTIME_NOT_RUNNING", ""}
    gates.append(_gate("symbols_available", fresh_or_runtime_ready and not _symbol_rejection_block(symbol), "no active symbol rejection or profile universe mismatch", {"market_status": market_status, "symbol_rejection_status": symbol.get("micro_v2_symbol_rejection_status", ""), "symbol_root_cause": symbol.get("symbol_rejection_root_cause", "")}, category="symbols"))

    telemetry_clear = bool(telemetry.get("telemetry_acceptance_clear", False)) and int(telemetry.get("active_blocking_count", 0) or 0) == 0
    gates.append(_gate("timestamps_normalized", telemetry_clear, "telemetry_acceptance_clear=true and active_blocking_count=0", {"telemetry_status": telemetry.get("telemetry_status", ""), "active_blocking_count": telemetry.get("active_blocking_count", 0), "telemetry_acceptance_clear": telemetry.get("telemetry_acceptance_clear", False)}, category="evidence"))

    execution_clear = int(execution.get("blocking_findings_count", 0) or 0) == 0 and not bool(execution.get("execution_attempted_detected", False))
    gates.append(_gate("execution_evidence_clear", execution_clear, "no execution evidence blocking findings", {"execution_evidence_status": execution.get("execution_evidence_status", ""), "blocking_findings_count": execution.get("blocking_findings_count", 0), "execution_attempted_detected": execution.get("execution_attempted_detected", False)}, category="evidence"))

    evidence_ok = _no_load_errors(context) and rejection.get("_load_error") is None
    gates.append(_gate("evidence_integrity_acceptable", evidence_ok, "reports load without corruption and replay evidence is usable", _load_error_summary(context), category="evidence"))

    safety_flags_clear = not _safety_flagged(context, heartbeat)
    gates.append(_gate("safety_flags_clear", safety_flags_clear, "execution_attempted=false and order_send/order_check false everywhere", _safety_observed(context, heartbeat), category="safety"))
    return gates


def _gate(gate_id: str, passed: bool, expected: Any, observed: Any, *, category: str, wait_status: str = "") -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "category": category,
        "passed": bool(passed),
        "blocking": not bool(passed),
        "expected": expected,
        "observed": observed,
        "wait_status": wait_status,
        "reason": "passed" if passed else f"{gate_id} failed",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _clearance_ok(clearance: Mapping[str, Any]) -> bool:
    return (
        clearance.get("micro_v2_clearance_runtime_check_status") == "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK"
        and bool(clearance.get("clearance_profile_match", False))
        and bool(clearance.get("daily_risk_accepted", False))
        and clearance.get("approved_for_demo") is False
        and clearance.get("approved_for_live") is False
    )


def _profile_ok(profile: Mapping[str, Any]) -> bool:
    return (
        bool(profile.get("profile_config_exists", False))
        and profile.get("PROFILE_NAME") == "BALANCED_STABLE_MICRO_V2"
        and _true(profile.get("PAPER_ONLY"))
        and _true(profile.get("NOT_FOR_DEMO_LIVE"))
        and _true(profile.get("NOT_FOR_LIVE"))
        and _true(profile.get("APPROVED_FOR_PAPER_DRY_RUN_ONLY"))
        and _false(profile.get("APPROVED_FOR_DEMO"))
        and _false(profile.get("APPROVED_FOR_LIVE"))
    )


def _profile_observed(profile: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("profile_config_exists", "PROFILE_NAME", "PAPER_ONLY", "NOT_FOR_DEMO_LIVE", "NOT_FOR_LIVE", "APPROVED_FOR_PAPER_DRY_RUN_ONLY", "APPROVED_FOR_DEMO", "APPROVED_FOR_LIVE")
    return {key: profile.get(key, "") for key in keys}


def _symbol_rejection_block(symbol: Mapping[str, Any]) -> bool:
    status = str(symbol.get("micro_v2_symbol_rejection_status", ""))
    root = str(symbol.get("symbol_rejection_root_cause", ""))
    if root == "STALE_TICK_OR_MARKET_CLOSED_REJECTION_RECORDED_AS_SYMBOL_REJECTED":
        return False
    return status in {
        "SYMBOL_REJECTION_DUE_TO_PROFILE_UNIVERSE",
        "SYMBOL_REJECTION_DUE_TO_STABLE_GATE_UNIVERSE",
        "SYMBOL_REJECTION_DUE_TO_SYMBOL_NORMALIZATION",
        "SYMBOL_REJECTION_DUE_TO_CLI_SYMBOL_PARSE",
        "SYMBOL_REJECTION_DUE_TO_TYPE_MISMATCH",
    }


def _safety_flagged(context: Mapping[str, Any], heartbeat: Mapping[str, Any]) -> bool:
    if bool(heartbeat.get("execution_attempted", False)):
        return True
    for value in context.values():
        if isinstance(value, Mapping):
            if any(bool(value.get(key, False)) for key in ("execution_attempted", "order_send_called", "order_check_called")):
                return True
    return False


def _safety_observed(context: Mapping[str, Any], heartbeat: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "heartbeat_execution_attempted": bool(heartbeat.get("execution_attempted", False)),
        "context_execution_attempted": bool(context.get("execution_attempted", False)),
        "context_order_send_called": bool(context.get("order_send_called", False)),
        "context_order_check_called": bool(context.get("order_check_called", False)),
    }


def _no_load_errors(context: Mapping[str, Any]) -> bool:
    for value in context.values():
        if isinstance(value, Mapping) and value.get("_load_error"):
            return False
    return True


def _load_error_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value.get("_load_error") for key, value in context.items() if isinstance(value, Mapping) and value.get("_load_error")}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _false(value: Any) -> bool:
    return str(value).strip().lower() in {"0", "false", "no", "off"}

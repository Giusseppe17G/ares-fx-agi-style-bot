"""Recheck the post-reset gate without launching V2."""

from __future__ import annotations

from typing import Any, Mapping


def recheck_reset_gate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    post = inputs.get("post_reset_relaunch") if isinstance(inputs.get("post_reset_relaunch"), Mapping) else {}
    pre = inputs.get("pre_relaunch_safety") if isinstance(inputs.get("pre_relaunch_safety"), Mapping) else {}
    scope = inputs.get("daily_risk_scope_repair") if isinstance(inputs.get("daily_risk_scope_repair"), Mapping) else {}
    safety = any(bool(source.get(key, False)) for source in (post, pre, scope) for key in ("execution_attempted", "order_send_called", "order_check_called"))
    post_allowed = bool(post.get("post_reset_relaunch_allowed", False))
    daily_halt_active = bool(post.get("daily_halt_active", False))
    daily_reset = bool(post.get("daily_reset_occurred", False))
    scope_status = (
        post.get("daily_risk_scope_status")
        or scope.get("daily_risk_scope_status_after")
        or scope.get("daily_risk_scope_status")
        or ""
    )
    scope_verified = bool(post.get("daily_risk_scope_verified", False)) or scope_status == "DAILY_RISK_SCOPE_OK_FOR_V2"
    scope_ok = scope_verified and scope_status == "DAILY_RISK_SCOPE_OK_FOR_V2"
    guard_ok = bool(post.get("zero_risk_guard_verified", False) or pre.get("zero_risk_guard_enabled", False))
    paper_clean = bool(post.get("paper_state_clean_for_relaunch", False))
    ready = post_allowed and daily_reset and not daily_halt_active and scope_ok and guard_ok and paper_clean
    if safety:
        status = "MICRO_V2_RESET_WATCHER_SAFETY_BLOCKED"
    elif not scope_ok:
        status = "MICRO_V2_RESET_WATCHER_SCOPE_INVALID"
    elif not guard_ok:
        status = "MICRO_V2_RESET_WATCHER_ZERO_RISK_GUARD_MISSING"
    elif not paper_clean:
        status = "MICRO_V2_RESET_WATCHER_PAPER_STATE_BLOCK"
    elif ready:
        status = "MICRO_V2_RESET_WATCHER_READY_FOR_MANUAL_RELAUNCH"
    elif daily_halt_active and not daily_reset:
        status = "MICRO_V2_RESET_WATCHER_KEEP_WAITING"
    else:
        status = "MICRO_V2_RESET_WATCHER_KEEP_WAITING"
    return {
        "reset_gate_recheck_status": status,
        "daily_halt_active": daily_halt_active,
        "daily_reset_occurred": daily_reset,
        "post_reset_relaunch_allowed": post_allowed,
        "daily_risk_scope_verified": scope_ok,
        "zero_risk_guard_verified": guard_ok,
        "paper_state_clean_for_relaunch": paper_clean,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

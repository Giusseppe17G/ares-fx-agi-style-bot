"""Decision policy for Micro V2 post-reset relaunch."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def decide_relaunch(gates: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> dict[str, Any]:
    failed = [gate for gate in gates if not bool(gate.get("passed", False))]
    failed_ids = [str(gate.get("gate_id", "")) for gate in failed]
    categories = {str(gate.get("category", "")) for gate in failed}
    market = context.get("market_open_readiness") if isinstance(context.get("market_open_readiness"), Mapping) else {}

    hard_categories = categories - {"reset", "cooldown"}
    if not failed:
        market_status = str(market.get("micro_v2_market_open_readiness_status", ""))
        status = "MICRO_V2_RELAUNCH_SAFE_TO_OBSERVE" if market_status in {"MICRO_V2_MARKET_OPEN_TICKS_FRESH", "MICRO_V2_READY_FOR_LIVE_MARKET_OBSERVATION"} else "MICRO_V2_RELAUNCH_READY"
        reason = "All post-reset relaunch gates passed."
        action = "MANUAL_RELAUNCH_V2_PAPER_DRY_RUN_ONLY"
    elif hard_categories and not (hard_categories == {"evidence"}):
        status = "MICRO_V2_RELAUNCH_BLOCKED"
        reason = f"Blocking gates failed: {', '.join(failed_ids)}"
        action = "DO_NOT_RELAUNCH_FIX_BLOCKING_GATES"
    elif any(gate.get("wait_status") == "MICRO_V2_RELAUNCH_WAITING_RESET" for gate in failed):
        status = "MICRO_V2_RELAUNCH_WAITING_RESET"
        reason = "Daily reset has not cleared the active halt yet."
        action = "KEEP_V2_STOPPED_AND_RERUN_RESET_WATCHER_LATER"
    elif any(gate.get("wait_status") == "MICRO_V2_RELAUNCH_WAITING_COOLDOWN" for gate in failed):
        status = "MICRO_V2_RELAUNCH_WAITING_COOLDOWN"
        reason = "Cooldown is still active."
        action = "KEEP_V2_STOPPED_UNTIL_COOLDOWN_EXPIRES"
    elif "evidence" in categories and categories <= {"evidence"}:
        status = "MICRO_V2_RELAUNCH_WAITING_MANUAL_REVIEW"
        reason = "Evidence requires manual review before relaunch."
        action = "REVIEW_EVIDENCE_AND_RERUN_ORCHESTRATOR"
    else:
        status = "MICRO_V2_RELAUNCH_BLOCKED"
        reason = f"Blocking gates failed: {', '.join(failed_ids)}"
        action = "DO_NOT_RELAUNCH_FIX_BLOCKING_GATES"

    return {
        "micro_v2_relaunch_decision": status,
        "relaunch_allowed": status in {"MICRO_V2_RELAUNCH_READY", "MICRO_V2_RELAUNCH_SAFE_TO_OBSERVE"},
        "safe_to_observe": status == "MICRO_V2_RELAUNCH_SAFE_TO_OBSERVE",
        "blocking_gate_ids": failed_ids,
        "blocking_gate_count": len(failed_ids),
        "reason": reason,
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

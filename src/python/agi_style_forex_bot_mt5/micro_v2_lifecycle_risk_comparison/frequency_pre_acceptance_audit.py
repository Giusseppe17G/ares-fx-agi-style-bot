"""Trade frequency pre-acceptance audit for Micro V2."""

from __future__ import annotations

from typing import Any, Mapping


REQUIRED_CLOSED_TRADES = 10
REQUIRED_HOURS = 24.0


def audit_frequency_pre_acceptance(stable_window: Mapping[str, Any], lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    hours = _float(stable_window.get("observed_market_open_hours"), _float(stable_window.get("v2_hours_observed")))
    closed = _int(stable_window.get("paper_trades_closed"))
    open_count = int(lifecycle.get("open_trade_count", stable_window.get("paper_trades_open", 0)) or 0)
    blockers: list[str] = []
    if closed < REQUIRED_CLOSED_TRADES:
        blockers.append("NEEDS_10_CLOSED_PAPER_TRADES")
    if hours < REQUIRED_HOURS:
        blockers.append("NEEDS_24_MARKET_OPEN_HOURS")
    acceptance_ready = not blockers
    if acceptance_ready:
        action = "PREPARE_FASE_64_FINAL_ACCEPTANCE_EVIDENCE_PACK"
    elif open_count:
        action = "CONTINUE_V2_AND_WAIT_FOR_OPEN_PAPER_TRADES_TO_CLOSE"
    else:
        action = "CONTINUE_V2_UNTIL_MORE_CLOSED_PAPER_TRADES_ACCUMULATE"
    return {
        "v2_hours_observed": hours,
        "v2_market_open_hours_estimated": hours,
        "v2_paper_trades_closed": closed,
        "required_closed_trades": REQUIRED_CLOSED_TRADES,
        "required_hours": REQUIRED_HOURS,
        "acceptance_ready": acceptance_ready,
        "preliminary_acceptance_blockers": blockers,
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default

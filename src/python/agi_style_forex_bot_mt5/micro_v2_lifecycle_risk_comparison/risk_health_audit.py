"""Paper risk health audit for Micro V2."""

from __future__ import annotations

from typing import Any, Mapping


def audit_risk_health(
    *,
    lifecycle: Mapping[str, Any],
    drawdown: Mapping[str, Any],
    pnl: Mapping[str, Any],
    profile_values: Mapping[str, str],
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    open_count = int(lifecycle.get("open_trade_count", 0) or 0)
    max_open = _int(profile_values.get("MAX_OPEN_TRADES") or profile_values.get("MAX_OPEN_PAPER_TRADES"), default=1)
    max_daily = _int(profile_values.get("MAX_PAPER_TRADES_PER_DAY"), default=3)
    closed_today = _int(checkpoint.get("v2_paper_trades_closed_today") or checkpoint.get("paper_trades_closed_today"))
    invalid_state = bool(lifecycle.get("risk_distance_issues") or lifecycle.get("sl_tp_issues"))
    blocked = (
        invalid_state
        or str(drawdown.get("drawdown_health_status", "")).endswith("BLOCKED")
        or str(pnl.get("pnl_readiness_status", "")).endswith("ISSUE")
        or open_count > max_open
        or closed_today > max_daily
    )
    return {
        "risk_health_status": "MICRO_V2_RISK_HEALTH_BLOCKED" if blocked else "MICRO_V2_RISK_HEALTH_OK",
        "paper_risk_status": "PAPER_RISK_BLOCKED" if blocked else "PAPER_RISK_OK",
        "max_open_trades_used": max_open,
        "max_paper_trades_per_day_used": max_daily,
        "current_open_exposure_count": open_count,
        "exposure_limit_breached": open_count > max_open,
        "daily_trade_limit_breached": closed_today > max_daily,
        "invalid_paper_state_risk": invalid_state,
        "risk_multiplier_applied": pnl.get("risk_multiplier_applied", False),
        "pnl_scaling_correct": pnl.get("pnl_scaling_correct", True),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _int(value: Any, *, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default

"""Policy payload for manage-open-trades-only V2 resume."""

from __future__ import annotations

from typing import Any


def build_manage_open_trades_only_policy(*, enabled: bool, reason: str = "") -> dict[str, Any]:
    return {
        "paper_resume_mode": "MANAGE_OPEN_TRADES_ONLY" if enabled else "",
        "manage_open_trades_only_enabled": enabled,
        "new_entries_blocked": enabled,
        "new_paper_trades_blocked": enabled,
        "paper_exit_evaluation_allowed": enabled,
        "paper_trade_updates_allowed": enabled,
        "daily_risk_clearing_blocked_until_open_trades_zero": enabled,
        "real_trading_allowed": False,
        "demo_live_allowed": False,
        "reason": reason,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

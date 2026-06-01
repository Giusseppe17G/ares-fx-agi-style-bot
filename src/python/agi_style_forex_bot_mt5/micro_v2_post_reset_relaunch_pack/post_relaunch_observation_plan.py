"""Post-relaunch observation plan text."""

from __future__ import annotations


def observation_plan_markdown() -> str:
    return """# Micro V2 Post-Relaunch Observation Plan

- First 15 minutes: validate `status` against the V2 SQLite path.
- First cycle: confirm no `CONFIG_ERROR`.
- First hour: confirm no `PAPER_STATE_ERROR`.
- First paper trades: confirm zero-risk guard prevents `SL=entry` and `risk_distance=0`.
- Monitor `paper_trades_opened`, `paper_trades_closed`, `zero_risk_rejections_count`, `invalid_open_trade_count`, `daily_risk_status`, and `paper_state_status`.
- Safety invariants must remain: `order_send_called=false`, `order_check_called=false`, `execution_attempted=false`.
- This plan does not approve demo/live and does not replace forward acceptance.
"""

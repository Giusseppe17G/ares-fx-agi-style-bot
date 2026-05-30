"""Session and regime opportunity diagnostics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.blocker_funnel import _is_blocking_event

from .frequency_dataset import event_reason, event_session


def audit_session_opportunity(events: list[Mapping[str, Any]], paper_trades: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    session_blocks: Counter[str] = Counter()
    regime_blocks: Counter[str] = Counter()
    trade_sessions: Counter[str] = Counter()
    for event in events:
        if not _is_blocking_event(event):
            continue
        reason = event_reason(event)
        upper = reason.upper()
        if "SESSION" in upper:
            session_blocks[event_session(event)] += 1
        if "REGIME" in upper:
            payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
            regime_blocks[str(payload.get("regime") or reason)] += 1
    for trade in paper_trades:
        trade_sessions[str(trade.get("session") or "UNKNOWN")] += 1
    rows = []
    for session in sorted(set(session_blocks) | set(trade_sessions)):
        rows.append(
            {
                "session": session,
                "session_block_count": session_blocks.get(session, 0),
                "paper_trade_count": trade_sessions.get(session, 0),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows, {
        "session_block_count": sum(session_blocks.values()),
        "regime_block_count": sum(regime_blocks.values()),
        "top_regime_blocks": [{"regime_or_reason": key, "count": value} for key, value in regime_blocks.most_common(10)],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

"""Relaunch gate for Micro V2 after daily reset."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def evaluate_v2_relaunch_gate(
    dataset: Mapping[str, Any],
    *,
    safety_blocked: bool,
    halt_audit: Mapping[str, Any],
    ledger_audit: Mapping[str, Any],
) -> dict[str, Any]:
    trades = list(dataset.get("paper_trades", []))
    open_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "OPEN"]
    invalid_open = [trade for trade in open_trades if _invalid_open_trade(trade)]
    quarantined = [trade for trade in trades if "QUARANTINED" in str(trade.get("status", "")).upper()]
    paper_state_block = _paper_state_block(dataset, cutoff_utc=str(ledger_audit.get("latest_v2_ledger_created_at_utc") or ""))
    status = "MICRO_V2_DAILY_RESET_READY_FOR_RELAUNCH"
    if safety_blocked:
        status = "MICRO_V2_DAILY_RESET_SAFETY_BLOCKED"
    elif ledger_audit.get("daily_risk_scope_status") != "DAILY_RISK_SCOPE_OK_FOR_V2":
        status = "MICRO_V2_DAILY_RESET_SCOPE_INVALID"
    elif invalid_open:
        status = "MICRO_V2_DAILY_RESET_INVALID_TRADES_BLOCK"
    elif open_trades:
        status = "MICRO_V2_DAILY_RESET_OPEN_TRADES_BLOCK"
    elif paper_state_block:
        status = "MICRO_V2_DAILY_RESET_PAPER_STATE_BLOCK"
    elif halt_audit.get("daily_halt_active"):
        status = "MICRO_V2_DAILY_RESET_NOT_READY_KEEP_HALTED"
    relaunch_allowed = status == "MICRO_V2_DAILY_RESET_READY_FOR_RELAUNCH"
    return {
        "v2_relaunch_gate_status": status,
        "relaunch_allowed": relaunch_allowed,
        "open_trade_count": len(open_trades),
        "invalid_open_trade_count": len(invalid_open),
        "quarantined_trade_count": len(quarantined),
        "paper_state_clean_for_relaunch": not paper_state_block,
        "paper_state_block": paper_state_block,
        "blocking_reason": "" if relaunch_allowed else status,
        "recommended_next_action": "RELAUNCH_V2_PAPER_DRY_RUN" if relaunch_allowed else "KEEP_V2_STOPPED_AND_RERUN_RESET_READINESS_LATER",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _invalid_open_trade(trade: Mapping[str, Any]) -> bool:
    entry = _float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"))
    sl = _float(trade.get("sl_price") or trade.get("stop_loss") or trade.get("sl"))
    tp = _float(trade.get("tp_price") or trade.get("take_profit") or trade.get("tp"))
    return entry is None or sl is None or tp is None or abs(entry - sl) <= 1e-12 or abs(tp - entry) <= 1e-12


def _paper_state_block(dataset: Mapping[str, Any], *, cutoff_utc: str) -> bool:
    cutoff = _parse_ts(cutoff_utc)
    for event in dataset.get("events", []):
        event_type = str(event.get("event_type") or "").upper()
        if event_type not in {"FORWARD_SHADOW_CRITICAL_ERROR", "PAPER_STATE_ERROR"}:
            continue
        ts = _parse_ts(event.get("timestamp_utc"))
        if cutoff and ts and ts <= cutoff:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        text = " ".join(str(item) for item in (event.get("message"), payload.get("error"), payload.get("halt_reason")))
        if "PAPER_DAILY_DRAWDOWN" in text or "PAPER_DAILY_DRAWDOWN_HALT" in text:
            continue
        return True
    return False


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None

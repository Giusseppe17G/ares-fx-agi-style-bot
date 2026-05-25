"""Audit why a PAPER_DAILY_DRAWDOWN halt was triggered."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


def audit_drawdown_trigger(evidence: Mapping[str, Any], trades: list[Mapping[str, Any]], formula_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    paper_state = evidence.get("paper_state", {}) if isinstance(evidence.get("paper_state"), Mapping) else {}
    daily_risk = evidence.get("daily_risk_summary", {}) if isinstance(evidence.get("daily_risk_summary"), Mapping) else {}
    halts = list(evidence.get("halts", [])) if isinstance(evidence.get("halts"), list) else []
    daily_limit = _float(paper_state.get("daily_drawdown_limit"), -3.0)
    reported_drawdown = _float(paper_state.get("paper_drawdown") or daily_risk.get("daily_paper_drawdown"), 0.0)
    latest_clearance = safe_parse_datetime(daily_risk.get("latest_clearance_utc"), field_name="latest_clearance_utc", source="paper_pnl_audit")
    latest_halt = _latest_halt(halts)
    after_clearance_trades = [
        trade
        for trade in trades
        if latest_clearance.value is None or _after(trade.get("exit_time_utc") or trade.get("entry_time_utc"), latest_clearance.value)
    ]
    before_clearance_losses = [
        trade
        for trade in trades
        if latest_clearance.value is not None and not _after(trade.get("exit_time_utc") or trade.get("entry_time_utc"), latest_clearance.value) and _float(trade.get("reported_profit")) < 0
    ]
    after_pnl = sum(_float(trade.get("reported_profit")) for trade in after_clearance_trades)
    worst = min((_float(trade.get("reported_profit")) for trade in trades), default=0.0)
    flags = set()
    if before_clearance_losses and not after_clearance_trades and halts:
        flags.add("DRAWDOWN_HISTORY_LEAK")
    if daily_limit < 0 and abs(daily_limit) <= 5 and abs(worst) > 10:
        flags.add("DRAWDOWN_UNIT_MISMATCH")
    if daily_limit < 0 and worst <= daily_limit:
        flags.add("DRAWDOWN_TRIGGER_VALID")
    if not flags and halts:
        flags.add("DRAWDOWN_TRIGGER_UNKNOWN")
    status = "DRAWDOWN_TRIGGER_VALID" if "DRAWDOWN_TRIGGER_VALID" in flags else next(iter(flags), "DRAWDOWN_TRIGGER_UNKNOWN")
    return {
        "drawdown_trigger_status": status,
        "trigger_flags": sorted(flags),
        "daily_drawdown_limit": daily_limit,
        "reported_drawdown": reported_drawdown,
        "latest_halt_utc": latest_halt,
        "latest_clearance_utc": latest_clearance.value.isoformat() if latest_clearance.value else "",
        "after_clearance_trade_count": len(after_clearance_trades),
        "before_clearance_loss_count": len(before_clearance_losses),
        "after_clearance_reported_pnl": after_pnl,
        "worst_reported_pnl": worst,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _latest_halt(halts: list[Mapping[str, Any]]) -> str:
    values = []
    for halt in halts:
        parsed = safe_parse_datetime(halt.get("timestamp_utc"), field_name="timestamp_utc", source="paper_pnl_audit")
        if parsed.value is not None:
            values.append(parsed.value.isoformat())
    return max(values) if values else ""


def _after(value: Any, threshold) -> bool:
    parsed = safe_parse_datetime(value, field_name="trade_time_utc", source="paper_pnl_audit")
    return bool(parsed.value is not None and parsed.value > threshold)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

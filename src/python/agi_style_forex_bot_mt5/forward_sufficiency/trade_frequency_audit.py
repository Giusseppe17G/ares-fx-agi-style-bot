"""Trade frequency calculations for forward sufficiency."""

from __future__ import annotations

from typing import Any, Mapping


def audit_trade_frequency(
    *,
    hours_observed: float,
    paper_trades: list[Mapping[str, Any]],
    signals_detected: int,
    signals_rejected: int,
    required_hours: int = 24,
    required_closed_paper_trades: int = 10,
) -> dict[str, Any]:
    closed = sum(1 for trade in paper_trades if str(trade.get("status", "")).upper() == "CLOSED")
    open_trades = sum(1 for trade in paper_trades if str(trade.get("status", "")).upper() == "OPEN")
    accepted = max(signals_detected - signals_rejected, 0)
    rejection_rate = (signals_rejected / signals_detected) if signals_detected else 0.0
    avg_signals_per_hour = signals_detected / hours_observed if hours_observed > 0 else 0.0
    avg_closed_per_hour = closed / hours_observed if hours_observed > 0 else 0.0
    remaining_trades = max(required_closed_paper_trades - closed, 0)
    hours_to_trades = 0.0 if remaining_trades == 0 else (remaining_trades / avg_closed_per_hour if avg_closed_per_hour > 0 else None)
    remaining_hours = max(required_hours - hours_observed, 0.0)
    estimates = [remaining_hours]
    if hours_to_trades is not None:
        estimates.append(hours_to_trades)
    estimated_to_acceptance = max(estimates) if estimates else None
    return {
        "required_hours": required_hours,
        "required_closed_paper_trades": required_closed_paper_trades,
        "closed_paper_trades": closed,
        "open_paper_trades": open_trades,
        "signals_detected": signals_detected,
        "signals_rejected": signals_rejected,
        "signals_accepted": accepted,
        "rejection_rate": round(rejection_rate, 4),
        "avg_signals_per_hour": round(avg_signals_per_hour, 4),
        "avg_closed_trades_per_hour": round(avg_closed_per_hour, 4),
        "estimated_hours_to_10_closed_trades": None if hours_to_trades is None else round(hours_to_trades, 4),
        "estimated_hours_to_acceptance": None if estimated_to_acceptance is None else round(estimated_to_acceptance, 4),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

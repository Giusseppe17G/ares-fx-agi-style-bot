"""Preliminary base-vs-V2 comparison without acceptance decisioning."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.v2_activity_audit import audit_activity


def compare_base_vs_v2_preliminary(
    *,
    base_dataset: Mapping[str, Any],
    v2_dataset: Mapping[str, Any],
    stable_window: Mapping[str, Any],
    filter_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    base = audit_activity(base_dataset)
    v2 = audit_activity(v2_dataset)
    hours = _float(stable_window.get("observed_market_open_hours"), _float(stable_window.get("v2_hours_observed"), 0.0))
    denominator = max(hours / 24.0, 1e-9)
    v2_closed_rate = round(_int(v2.get("paper_trades_closed")) / denominator, 6)
    v2_open_rate = round(_int(v2.get("paper_trades_open")) / denominator, 6)
    base_closed = _int(base.get("paper_trades_closed"))
    v2_closed = _int(v2.get("paper_trades_closed"))
    v2_worsens_safety = _safety(v2_dataset)
    improves = v2_closed > base_closed or v2_open_rate > 0
    if v2_worsens_safety:
        status = "V2_PRELIMINARY_SAFETY_WORSE"
    elif improves:
        status = "V2_PRELIMINARY_IMPROVING_FREQUENCY"
    else:
        status = "V2_PRELIMINARY_NOT_ENOUGH_CLOSED_DATA"
    return {
        "preliminary_base_vs_v2_result": status,
        "base_signals_detected": base.get("signals_detected", 0),
        "base_signals_rejected": base.get("signals_rejected", 0),
        "base_rejection_rate": base.get("rejection_rate", 0.0),
        "base_paper_trades_open": base.get("paper_trades_open", 0),
        "base_paper_trades_closed": base.get("paper_trades_closed", 0),
        "v2_signals_detected": v2.get("signals_detected", stable_window.get("signals_detected", 0)),
        "v2_signals_rejected": v2.get("signals_rejected", stable_window.get("signals_rejected", 0)),
        "v2_rejection_rate": v2.get("rejection_rate", stable_window.get("rejection_rate", 0.0)),
        "v2_paper_trades_open": v2.get("paper_trades_open", stable_window.get("paper_trades_open", 0)),
        "v2_paper_trades_closed": v2.get("paper_trades_closed", stable_window.get("paper_trades_closed", 0)),
        "v2_closed_trade_rate_per_24h": v2_closed_rate,
        "v2_open_trade_rate_per_24h": v2_open_rate,
        "market_closed_dominance": stable_window.get("market_closed_dominance_ratio", filter_analysis.get("market_closed_dominance_ratio", 0.0)),
        "fresh_tick_coverage": stable_window.get("fresh_tick_coverage_ratio", 0.0),
        "v2_improves_frequency_preliminary": bool(improves),
        "v2_worsens_safety": bool(v2_worsens_safety),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _safety(dataset: Mapping[str, Any]) -> bool:
    for group in ("events", "heartbeats", "paper_trades"):
        for row in dataset.get(group, []):
            payload = row.get("payload", {}) if isinstance(row.get("payload"), Mapping) else {}
            if row.get("execution_attempted") or row.get("order_send_called") or row.get("order_check_called"):
                return True
            if payload.get("execution_attempted") or payload.get("order_send_called") or payload.get("order_check_called"):
                return True
    return False


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

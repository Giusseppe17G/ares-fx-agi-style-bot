"""Compare stable/base paper telemetry against Micro V2 dry-run telemetry."""

from __future__ import annotations

from typing import Any, Mapping


def compare_base_vs_v2(*, base_activity: Mapping[str, Any], base_window: Mapping[str, Any], v2_activity: Mapping[str, Any], v2_window: Mapping[str, Any]) -> dict[str, Any]:
    base_metrics = _metrics(base_activity, base_window)
    v2_metrics = _metrics(v2_activity, v2_window)
    v2_frequency_delta = round(v2_metrics["closed_trade_rate_per_24h"] - base_metrics["closed_trade_rate_per_24h"], 6)
    v2_signal_delta = round(v2_metrics["signal_detection_rate_per_24h"] - base_metrics["signal_detection_rate_per_24h"], 6)
    v2_safety_delta = int(v2_activity.get("paper_trades_open", 0) or 0) - int(base_activity.get("paper_trades_open", 0) or 0)
    return {
        "base_metrics": base_metrics,
        "v2_metrics": v2_metrics,
        "v2_frequency_delta_per_24h": v2_frequency_delta,
        "v2_signal_delta_per_24h": v2_signal_delta,
        "v2_improves_frequency": v2_frequency_delta > 0,
        "v2_worsens_safety": v2_safety_delta > 0 or float(v2_activity.get("paper_drawdown", 0.0) or 0.0) < float(base_activity.get("paper_drawdown", 0.0) or 0.0),
        "top_rejection_reasons_base": base_activity.get("rejected_by_reason", [])[:10],
        "top_rejection_reasons_v2": v2_activity.get("rejected_by_reason", [])[:10],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def comparison_metric_rows(comparison: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric, value in dict(comparison.get("base_metrics", {})).items():
        rows.append(
            {
                "metric": metric,
                "base_value": value,
                "v2_value": dict(comparison.get("v2_metrics", {})).get(metric, ""),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows


def _metrics(activity: Mapping[str, Any], window: Mapping[str, Any]) -> dict[str, Any]:
    hours = float(window.get("hours_observed", 0.0) or 0.0)
    closed = int(activity.get("paper_trades_closed", 0) or 0)
    signals = int(activity.get("signals_detected", 0) or 0)
    rejected = int(activity.get("signals_rejected", 0) or 0)
    return {
        "hours_observed": round(hours, 4),
        "paper_trades_closed": closed,
        "paper_trades_open": int(activity.get("paper_trades_open", 0) or 0),
        "signals_detected": signals,
        "signals_rejected": rejected,
        "closed_trade_rate_per_24h": round((closed / hours) * 24.0, 6) if hours > 0 else 0.0,
        "signal_detection_rate_per_24h": round((signals / hours) * 24.0, 6) if hours > 0 else 0.0,
        "rejection_rate": round(rejected / signals, 4) if signals else 0.0,
        "paper_drawdown": float(activity.get("paper_drawdown", 0.0) or 0.0),
        "paper_state_recovery_status": str(activity.get("paper_state_recovery_status", "")),
    }

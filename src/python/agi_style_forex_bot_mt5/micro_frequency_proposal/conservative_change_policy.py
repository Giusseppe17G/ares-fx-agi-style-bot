"""Conservative proposal rules for micro frequency tuning."""

from __future__ import annotations

from typing import Any, Mapping

from .profile_parameter_detector import detect_parameter_map, float_value, int_value


def propose_conservative_changes(values: dict[str, str], context: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mapping = detect_parameter_map(values)
    summary = context.get("micro_frequency_summary", {}) if isinstance(context.get("micro_frequency_summary"), Mapping) else {}
    bottlenecks = summary.get("top_frequency_bottlenecks", [])
    changes: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    bottleneck_names = {str(item.get("bottleneck", "")).upper() for item in bottlenecks if isinstance(item, Mapping)}
    if "COOLDOWN_BLOCK" in bottleneck_names and "COOLDOWN_BLOCK" in mapping:
        key = mapping["COOLDOWN_BLOCK"]
        old = int_value(values, key, 0)
        reduction = min(max(int(round(old * 0.10)), 1), 15)
        new = max(old - reduction, 1)
        if new < old:
            changes.append(_change(key, str(old), str(new), "cooldown", "Reduce loss cooldown by at most 10% or 15 minutes."))
    elif "COOLDOWN_BLOCK" in bottleneck_names:
        rejected.append(_reject("COOLDOWN_BLOCK", "No existing cooldown_after_loss parameter found."))
    if "PAPER_TRADE_LIMIT" in mapping and int(summary.get("trade_shortfall", 0) or 0) > 0:
        key = mapping["PAPER_TRADE_LIMIT"]
        old = int_value(values, key, 0)
        new = min(3, max(old, 0) + 1)
        if old < new <= 3:
            changes.append(_change(key, str(old), str(new), "paper_limit", "Allow at most one additional paper trade per day, capped at 3."))
    for bottleneck, reason in {
        "REGIME_BLOCK": "Regime filter has no explicit safe observe-mode parameter in base profile.",
        "LIQUIDITY_BLOCK": "Liquidity threshold has no explicit tunable parameter in base profile.",
        "STALE_SIGNAL_BLOCK": "Stale signal tolerance has no explicit tunable parameter in base profile.",
        "SPREAD_BLOCK": "Spread controls are critical and no explicit safe profile key was found.",
        "SCORE_THRESHOLD_BLOCK": "Score threshold has no explicit tunable parameter in base profile.",
        "SESSION_BLOCK": "Session filter has no explicit safe session parameter in base profile.",
    }.items():
        if bottleneck in bottleneck_names and bottleneck not in mapping:
            rejected.append(_reject(bottleneck, reason))
    if "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES" in values:
        rejected.append(_reject("COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", "Drawdown halt cooldown is not reduced by policy."))
    return changes, rejected


def _change(key: str, old: str, new: str, category: str, reason: str) -> dict[str, Any]:
    return {
        "key": key,
        "base_value": old,
        "proposed_value": new,
        "change_category": category,
        "reason": reason,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _reject(bottleneck: str, reason: str) -> dict[str, Any]:
    return {
        "bottleneck": bottleneck,
        "reason": reason,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

"""Recalculate paper PnL approximations and flag formula/scale problems."""

from __future__ import annotations

from typing import Any, Mapping


def audit_pnl_formulas(trades: list[Mapping[str, Any]], contracts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    from .symbol_contract_auditor import contract_for

    rows: list[dict[str, Any]] = []
    for trade in trades:
        symbol = str(trade.get("symbol") or "").upper()
        contract = contract_for(symbol, contracts)
        entry = _float(trade.get("entry_price"))
        exit_price = _float(trade.get("exit_price") or trade.get("current_price"))
        direction = str(trade.get("direction") or "").upper()
        volume = _float(trade.get("volume"), 0.0)
        reported = _float(trade.get("reported_profit"))
        point = max(_float(contract.get("point"), 0.00001), 1e-12)
        tick_size = max(_float(contract.get("tick_size"), point), 1e-12)
        tick_value = _float(contract.get("tick_value"), 1.0)
        contract_size = _float(contract.get("contract_size"), 100000.0)
        commission = _float(trade.get("commission_assumed"))
        raw_delta = exit_price - entry
        direction_delta = -raw_delta if direction == "SELL" else raw_delta
        point_delta = direction_delta / point if point else 0.0
        pip_delta = point_delta / (10.0 if int(_float(contract.get("digits"), 5)) in {3, 5} else 1.0)
        pnl_naive = direction_delta
        pnl_with_contract_size = direction_delta * contract_size * volume - commission
        pnl_with_tick_value = (direction_delta / tick_size) * tick_value * volume - commission
        micro = _float(trade.get("paper_risk_multiplier"), 1.0)
        risk_multiplier = _float(trade.get("risk_multiplier"), 1.0)
        pnl_with_micro = pnl_with_tick_value * micro
        pnl_with_risk = pnl_with_tick_value * risk_multiplier
        scaled_recorded = _float(trade.get("scaled_paper_pnl"), reported)
        flags = _flags(
            trade=trade,
            reported=reported,
            pnl_with_tick_value=pnl_with_tick_value,
            pnl_with_micro=pnl_with_micro,
            pnl_with_risk=pnl_with_risk,
            direction_delta=direction_delta,
            point_delta=point_delta,
        )
        rows.append(
            {
                "trade_id": trade.get("trade_id", ""),
                "symbol": symbol,
                "strategy_name": trade.get("strategy_name", ""),
                "direction": direction,
                "entry_price": entry,
                "exit_price": exit_price,
                "price_delta": raw_delta,
                "direction_adjusted_delta": direction_delta,
                "point_delta": point_delta,
                "pip_delta": pip_delta,
                "pnl_naive": pnl_naive,
                "pnl_with_contract_size": pnl_with_contract_size,
                "pnl_with_tick_value": pnl_with_tick_value,
                "pnl_with_risk_multiplier": pnl_with_risk,
                "pnl_with_micro_multiplier": pnl_with_micro,
                "reported_profit": reported,
                "scaled_paper_pnl": scaled_recorded,
                "paper_risk_multiplier": micro,
                "risk_multiplier": risk_multiplier,
                "multiplier_applied": bool(trade.get("multiplier_applied", False)),
                "pnl_scaling_status": trade.get("pnl_scaling_status", ""),
                "pnl_formula_version": trade.get("pnl_formula_version", ""),
                "audit_flags": ";".join(flags),
                "execution_attempted": False,
            }
        )
    return rows


def _flags(
    *,
    trade: Mapping[str, Any],
    reported: float,
    pnl_with_tick_value: float,
    pnl_with_micro: float,
    pnl_with_risk: float,
    direction_delta: float,
    point_delta: float,
) -> list[str]:
    flags: list[str] = []
    if trade.get("multiplier_applied") and trade.get("scaled_paper_pnl") is not None:
        return flags
    if reported and direction_delta and (reported > 0) != (direction_delta > 0):
        flags.append("PNL_SIGN_ERROR")
    if abs(point_delta) > 1000:
        flags.append("POINT_PIP_MISMATCH")
    micro = _float(trade.get("paper_risk_multiplier"), 1.0)
    if micro < 1.0 and _close(reported, pnl_with_tick_value) and not _close(reported, pnl_with_micro):
        flags.append("MICRO_MULTIPLIER_NOT_APPLIED")
    risk_multiplier = _float(trade.get("risk_multiplier"), 1.0)
    if risk_multiplier < 1.0 and _close(reported, pnl_with_tick_value) and not _close(reported, pnl_with_risk):
        flags.append("RISK_MULTIPLIER_NOT_APPLIED")
    if abs(reported) > max(10.0, abs(pnl_with_micro) * 5.0) and micro < 1.0:
        flags.append("PNL_SCALE_TOO_LARGE")
    if not flags and reported == 0 and trade.get("exit_time_utc"):
        flags.append("UNKNOWN_PNL_FORMULA")
    return flags


def _close(left: float, right: float, tolerance: float = 1e-6) -> bool:
    return abs(left - right) <= max(tolerance, abs(right) * 0.01)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

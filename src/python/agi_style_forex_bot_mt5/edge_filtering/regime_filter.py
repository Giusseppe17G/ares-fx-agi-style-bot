"""Regime filters for BALANCED_FILTERED profiles."""

from __future__ import annotations

from typing import Any

import pandas as pd


def filter_regimes(by_regime: pd.DataFrame, blockers: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return regime allow/block/watchlist decisions."""

    rows: list[dict[str, Any]] = []
    cost_dominates = _cost_blockers_dominate(blockers)
    if by_regime.empty:
        return pd.DataFrame(columns=["regime", "filter_decision", "filter_reason"])
    for _, row in by_regime.iterrows():
        regime = str(row.get("regime", "UNKNOWN"))
        trades = int(row.get("total_trades", 0) or 0)
        expectancy = _maybe_float(row.get("expectancy_r"))
        pf = _maybe_float(row.get("profit_factor"))
        decision = "WATCHLIST"
        reason = "insufficient or incomplete regime evidence"
        if expectancy is not None and trades >= 20 and expectancy < 0:
            decision = "BLOCK"
            reason = "negative expectancy with sufficient regime sample"
        elif "HIGH_VOLATILITY" in regime.upper() and cost_dominates:
            decision = "BLOCK"
            reason = "high volatility blocked while cost blockers dominate"
        elif expectancy is not None and pf is not None and trades >= 20 and expectancy > 0 and pf >= 1.05:
            decision = "ALLOW"
            reason = "regime has positive edge metrics"
        rows.append({**row.to_dict(), "regime": regime, "filter_decision": decision, "filter_reason": reason})
    return pd.DataFrame(rows)


def _cost_blockers_dominate(blockers: pd.DataFrame | None) -> bool:
    if blockers is None or blockers.empty or "blocking_reason" not in blockers.columns:
        return False
    total = float(blockers.get("count", pd.Series([1] * len(blockers))).sum() or 0)
    if total <= 0:
        return False
    cost = blockers[blockers["blocking_reason"].astype(str).str.contains("SPREAD|COST", case=False, regex=True)]
    return float(cost.get("count", pd.Series([1] * len(cost))).sum() or 0) / total >= 0.35


def _maybe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

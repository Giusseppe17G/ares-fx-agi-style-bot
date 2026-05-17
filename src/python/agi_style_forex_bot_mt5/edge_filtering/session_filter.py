"""Session filters for BALANCED_FILTERED profiles."""

from __future__ import annotations

from typing import Any

import pandas as pd


def filter_sessions(by_session: pd.DataFrame, blockers: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return session allow/block/watchlist decisions."""

    rows: list[dict[str, Any]] = []
    cost_dominates = _cost_blockers_dominate(blockers)
    if by_session.empty:
        return pd.DataFrame(columns=["session", "filter_decision", "filter_reason"])
    for _, row in by_session.iterrows():
        session = str(row.get("session", "UNKNOWN"))
        trades = int(row.get("total_trades", 0) or 0)
        expectancy = _maybe_float(row.get("expectancy_r"))
        pf = _maybe_float(row.get("profit_factor"))
        decision = "WATCHLIST"
        reason = "insufficient or incomplete session evidence"
        if session.upper() == "ROLLOVER" and (cost_dominates or expectancy is None or expectancy <= 0 or (pf is not None and pf < 1.10)):
            decision = "BLOCK"
            reason = "rollover blocked due to cost or negative expectancy"
        elif expectancy is not None and trades >= 20 and expectancy < 0:
            decision = "BLOCK"
            reason = "negative expectancy with sufficient session sample"
        elif expectancy is not None and pf is not None and trades >= 20 and expectancy > 0 and pf >= 1.05:
            decision = "ALLOW"
            reason = "session has positive edge metrics"
        rows.append({**row.to_dict(), "session": session, "filter_decision": decision, "filter_reason": reason})
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

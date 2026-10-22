"""Strategy pruning rules for BALANCED_FILTERED research profiles."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..edge_evaluation.significance import recorded_significance


def filter_strategies(by_strategy: pd.DataFrame) -> pd.DataFrame:
    """Classify strategies as KEEP, WATCHLIST, DISABLE_IN_BALANCED, or RESEARCH_ONLY.

    KEEP needs at least 30 trades, PF >= 1.10, positive mean R, a win rate of
    at least 35% when reported, and the strategy selector's
    ``holm_adjusted_p_value`` <= 0.05
    (docs/decisions/2026-10-22-deflated-promotion-gate.md). A row that passes
    only the metric rule, or has no usable adjusted p-value, is WATCHLIST.
    """

    rows: list[dict[str, Any]] = []
    if by_strategy.empty:
        return pd.DataFrame(columns=["strategy_name", "filter_decision", "filter_reason"])
    for _, row in by_strategy.iterrows():
        trades = int(row.get("total_trades", row.get("trades", 0)) or 0)
        expectancy = _maybe_float(row.get("expectancy_r"))
        pf = _maybe_float(row.get("profit_factor"))
        winrate = _maybe_float(row.get("winrate"))
        net_profit = _maybe_float(row.get("net_profit"))
        drawdown = _maybe_float(row.get("max_drawdown_pct"))
        if expectancy is None or pf is None:
            decision = "INSUFFICIENT_METRICS" if trades <= 0 else "WATCHLIST_COUNTS_ONLY"
            reason = "missing profit factor or expectancy"
        elif trades >= 30 and pf >= 1.10 and expectancy > 0 and (winrate is None or winrate >= 35):
            significant, not_significant = recorded_significance(row.to_dict())
            if significant:
                decision = "KEEP"
                reason = "strategy has positive edge metrics"
            else:
                decision = "WATCHLIST"
                reason = f"strategy has positive edge metrics, but {not_significant}"
        elif trades >= 20 and pf >= 0.95 and expectancy >= -0.02:
            decision = "WATCHLIST"
            reason = "strategy is near break-even"
        elif trades >= 20:
            decision = "DISABLE_IN_BALANCED"
            reason = "strategy weakens BALANCED profile"
        else:
            decision = "RESEARCH_ONLY"
            reason = "strategy sample too small"
        if net_profit is not None and net_profit < 0 and decision == "KEEP":
            decision = "WATCHLIST"
            reason = "positive R metrics but negative net profit"
        if drawdown is not None and drawdown > 12.0:
            decision = "DISABLE_IN_BALANCED"
            reason = "drawdown exceeds filter threshold"
        rows.append({**row.to_dict(), "strategy_name": row.get("strategy_name", "UNKNOWN"), "filter_decision": decision, "filter_reason": reason})
    return pd.DataFrame(rows)


def _maybe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

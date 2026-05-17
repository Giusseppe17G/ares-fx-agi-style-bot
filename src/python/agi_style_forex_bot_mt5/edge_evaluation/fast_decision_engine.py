"""Fast decision engine for research artifacts."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def decide_fast(
    *,
    global_metrics: Mapping[str, Any],
    symbol_selection: pd.DataFrame,
    strategy_selection: pd.DataFrame,
    blocker_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a conservative fast decision for research iteration."""

    total = int(global_metrics.get("total_trades", 0) or 0)
    pf = float(global_metrics.get("profit_factor", 0.0) or 0.0)
    expectancy = float(global_metrics.get("expectancy_r", 0.0) or 0.0)
    if total < 30:
        decision = "NEEDS_MORE_TRADES"
        reason = "fewer than 30 simulated trades"
    elif blocker_summary.get("cost_blockers_dominate"):
        decision = "NEEDS_BROKER_COST_FIX"
        reason = "spread/cost blockers dominate"
    elif pf < 0.95 and expectancy < 0:
        decision = "NEEDS_STRATEGY_FIX"
        reason = "global expectancy and profit factor are negative"
    elif total >= 100 and _has_keep(symbol_selection) and _has_keep(strategy_selection) and expectancy > 0 and pf > 1.05:
        decision = "FORWARD_SHADOW_CANDIDATE"
        reason = "usable sample with positive symbol and strategy edge; paper/shadow only"
    elif total < 100:
        decision = "CONTINUE_BALANCED_RESEARCH" if expectancy >= -0.02 else "NEEDS_STRATEGY_FIX"
        reason = "small sample; continue research before stronger decisions"
    else:
        decision = "TEST_ACTIVE_RESEARCH_ONLY" if expectancy >= -0.02 else "NEEDS_STRATEGY_FIX"
        reason = "edge is weak or mixed; use active only for research diagnostics"
    return {"decision": decision, "reason": reason, "execution_attempted": False}


def _has_keep(frame: pd.DataFrame) -> bool:
    return not frame.empty and "decision" in frame.columns and bool((frame["decision"] == "KEEP").any())

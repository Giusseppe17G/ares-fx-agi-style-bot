"""Strategy selection rules for fast edge review."""

from __future__ import annotations

from typing import Any

import pandas as pd


def select_strategies(by_strategy: pd.DataFrame) -> pd.DataFrame:
    """Classify strategies for the BALANCED research profile."""

    rows: list[dict[str, Any]] = []
    if by_strategy.empty:
        return pd.DataFrame(columns=["strategy_name", "decision", "reasons"])
    for _, row in by_strategy.iterrows():
        trades = int(row.get("total_trades", row.get("trades", 0)) or 0)
        expectancy = float(row.get("expectancy_r", 0.0) or 0.0)
        pf = float(row.get("profit_factor", 0.0) or 0.0)
        if trades >= 30 and expectancy > 0 and pf > 1.10:
            decision = "KEEP"
            reason = "positive edge with enough strategy trades"
        elif trades >= 20 and expectancy >= -0.02 and pf >= 0.95:
            decision = "WATCHLIST"
            reason = "strategy is close to break-even; needs more sample"
        elif trades >= 20:
            decision = "DISABLE_IN_BALANCED"
            reason = "strategy degrades BALANCED profile"
        else:
            decision = "RESEARCH_ONLY"
            reason = "strategy sample is too small"
        rows.append({**row.to_dict(), "strategy_name": row.get("strategy_name", "UNKNOWN"), "decision": decision, "reasons": reason})
    return pd.DataFrame(rows)

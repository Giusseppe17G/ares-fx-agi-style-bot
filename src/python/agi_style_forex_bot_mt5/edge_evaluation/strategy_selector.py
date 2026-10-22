"""Strategy selection rules for fast edge review."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .significance import SIGNIFICANCE_COLUMNS, is_significant, mean_r_significance, not_significant_reason


def select_strategies(by_strategy: pd.DataFrame) -> pd.DataFrame:
    """Classify strategies for the BALANCED research profile.

    KEEP needs PF > 1.10 and positive mean R on 30+ trades and a Holm-adjusted
    one-sided p-value of mean R <= 0.05 across every row of ``by_strategy``
    (docs/decisions/2026-10-22-deflated-promotion-gate.md); a row that passes
    only the first part is WATCHLIST.
    """

    rows: list[dict[str, Any]] = []
    if by_strategy.empty:
        return pd.DataFrame(columns=["strategy_name", "decision", "reasons", *SIGNIFICANCE_COLUMNS])
    significance = mean_r_significance(by_strategy)
    for (_, row), tested in zip(by_strategy.iterrows(), significance):
        trades = int(row.get("total_trades", row.get("trades", 0)) or 0)
        if str(row.get("metrics_status", "FULL_EDGE_METRICS")) == "COUNTS_ONLY":
            rows.append({**row.to_dict(), **tested, "strategy_name": row.get("strategy_name", "UNKNOWN"), "decision": "WATCHLIST_COUNTS_ONLY", "reasons": "strategy has trade count but no profit/expectancy metrics"})
            continue
        expectancy = float(row.get("expectancy_r", 0.0) or 0.0)
        pf = float(row.get("profit_factor", 0.0) or 0.0)
        if trades >= 30 and expectancy > 0 and pf > 1.10:
            if is_significant(tested):
                decision = "KEEP"
                reason = "positive edge with enough strategy trades"
            else:
                decision = "WATCHLIST"
                reason = f"positive edge with enough strategy trades, but {not_significant_reason(tested)}"
        elif trades >= 20 and expectancy >= -0.02 and pf >= 0.95:
            decision = "WATCHLIST"
            reason = "strategy is close to break-even; needs more sample"
        elif trades >= 20:
            decision = "DISABLE_IN_BALANCED"
            reason = "strategy degrades BALANCED profile"
        else:
            decision = "RESEARCH_ONLY"
            reason = "strategy sample is too small"
        rows.append({**row.to_dict(), **tested, "strategy_name": row.get("strategy_name", "UNKNOWN"), "decision": decision, "reasons": reason})
    return pd.DataFrame(rows)

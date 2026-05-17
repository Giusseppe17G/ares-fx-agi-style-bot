"""Symbol selection rules for fast edge review."""

from __future__ import annotations

from typing import Any

import pandas as pd


def select_symbols(by_symbol: pd.DataFrame) -> pd.DataFrame:
    """Classify symbols as KEEP, WATCHLIST, REDUCE, or REJECT."""

    rows: list[dict[str, Any]] = []
    if by_symbol.empty:
        return pd.DataFrame(columns=["symbol", "decision", "reasons"])
    for _, row in by_symbol.iterrows():
        trades = int(row.get("total_trades", row.get("trades", 0)) or 0)
        metrics_status = str(row.get("metrics_status", "FULL_EDGE_METRICS"))
        if metrics_status == "COUNTS_ONLY":
            rows.append({**row.to_dict(), "symbol": row.get("symbol", ""), "decision": "WATCHLIST_COUNTS_ONLY", "reasons": "symbol has trade count but no profit/expectancy metrics"})
            continue
        expectancy = float(row.get("expectancy_r", 0.0) or 0.0)
        pf = float(row.get("profit_factor", 0.0) or 0.0)
        winrate = float(row.get("winrate", 0.0) or 0.0)
        decision = "WATCHLIST"
        reasons: list[str] = []
        if trades >= 30 and expectancy > 0 and pf > 1.10 and (winrate >= 35 or expectancy > 0.05):
            decision = "KEEP"
            reasons.append("positive expectancy with sufficient symbol sample")
        elif trades >= 20 and expectancy >= -0.02 and 0.95 <= pf <= 1.10:
            decision = "WATCHLIST"
            reasons.append("near break-even symbol; needs more evidence")
        elif trades >= 20 and (expectancy < 0 or pf < 0.95):
            decision = "REDUCE"
            reasons.append("negative or weak symbol metrics")
        if expectancy < -0.10 or pf < 0.90:
            decision = "REJECT"
            reasons.append("expectancy or profit factor clearly negative")
        if trades < 20:
            decision = "WATCHLIST"
            reasons.append("insufficient symbol sample")
        rows.append({**row.to_dict(), "symbol": row.get("symbol", ""), "decision": decision, "reasons": "; ".join(reasons)})
    return pd.DataFrame(rows)

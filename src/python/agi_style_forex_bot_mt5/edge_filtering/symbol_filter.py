"""Symbol pruning rules for BALANCED_FILTERED research profiles."""

from __future__ import annotations

from typing import Any

import pandas as pd


def filter_symbols(by_symbol: pd.DataFrame) -> pd.DataFrame:
    """Classify every available symbol for filtered profile decisions."""

    rows: list[dict[str, Any]] = []
    if by_symbol.empty:
        return pd.DataFrame(columns=["symbol", "filter_decision", "filter_reason"])
    for _, row in by_symbol.iterrows():
        trades = int(row.get("total_trades", row.get("trades", 0)) or 0)
        expectancy = _maybe_float(row.get("expectancy_r"))
        pf = _maybe_float(row.get("profit_factor"))
        drawdown = _maybe_float(row.get("max_drawdown_pct"))
        decision = "WATCHLIST"
        reasons: list[str] = []
        if expectancy is None or pf is None:
            decision = "INSUFFICIENT_METRICS" if trades <= 0 else "WATCHLIST_COUNTS_ONLY"
            reasons.append("missing profit factor or expectancy")
        elif trades >= 30 and pf >= 1.10 and expectancy > 0:
            decision = "KEEP"
            reasons.append("positive expectancy and profit factor")
        elif trades >= 20 and 0.95 <= pf < 1.10 and expectancy >= -0.02:
            decision = "WATCHLIST"
            reasons.append("near break-even; keep under observation")
        elif pf < 0.95 or expectancy < 0:
            decision = "DISABLE"
            reasons.append("negative or weak symbol edge")
        if drawdown is not None and drawdown > 12.0:
            decision = "DISABLE"
            reasons.append("drawdown exceeds filter threshold")
        if trades < 20 and decision not in {"DISABLE", "INSUFFICIENT_METRICS"}:
            decision = "RESEARCH_ONLY"
            reasons.append("insufficient symbol sample")
        rows.append({**row.to_dict(), "symbol": row.get("symbol", ""), "filter_decision": decision, "filter_reason": "; ".join(reasons)})
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

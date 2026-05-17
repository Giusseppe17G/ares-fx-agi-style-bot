"""Strategy stability classification."""

from __future__ import annotations

import pandas as pd

from .symbol_stability_selector import _select_group


def select_stable_strategies(trades: pd.DataFrame, fold_count: int = 3) -> pd.DataFrame:
    frame = _select_group(trades, "strategy_name", "strategy_name", disable_label="DISABLE_IN_BALANCED", fold_count=fold_count)
    if not frame.empty:
        frame.loc[frame["decision"] == "DISABLE_FOR_NOW", "decision"] = "DISABLE_IN_BALANCED"
        frame.loc[frame["decision"] == "NEEDS_MORE_DATA", "decision"] = "RESEARCH_ONLY"
    return frame

"""Analyze strategy and data blockers."""

from __future__ import annotations

from typing import Any

import pandas as pd


def analyze_blockers(blockers: pd.DataFrame) -> pd.DataFrame:
    """Aggregate blockers and recommend conservative action."""

    if blockers.empty:
        return pd.DataFrame(columns=["blocking_reason", "count", "recommendation"])
    frame = blockers.copy()
    frame["count"] = pd.to_numeric(frame.get("count", 1), errors="coerce").fillna(1).astype(int)
    grouped = frame.groupby("blocking_reason", dropna=False)["count"].sum().reset_index().sort_values("count", ascending=False)
    grouped["recommendation"] = grouped["blocking_reason"].map(_recommendation_for_blocker)
    return grouped.reset_index(drop=True)


def blocker_summary(blockers: pd.DataFrame) -> dict[str, Any]:
    analyzed = analyze_blockers(blockers)
    if analyzed.empty:
        return {"top_blockers": [], "dominant_blocker": "", "cost_blockers_dominate": False}
    top = analyzed.to_dict("records")
    total = int(analyzed["count"].sum())
    spread = int(analyzed[analyzed["blocking_reason"].astype(str).str.contains("SPREAD|COST", case=False, regex=True)]["count"].sum())
    return {
        "top_blockers": top[:10],
        "dominant_blocker": str(top[0]["blocking_reason"]),
        "cost_blockers_dominate": bool(total and spread / total >= 0.40),
    }


def _recommendation_for_blocker(reason: Any) -> str:
    value = str(reason or "").upper()
    if "SPREAD" in value or "COST" in value:
        return "maintain strict; review broker costs"
    if "ENSEMBLE_SCORE_LOW" in value:
        return "investigate threshold if near-misses are high"
    if "SESSION" in value:
        return "review allowed sessions"
    if "REGIME" in value:
        return "review regime detector"
    if "RISK" in value or "INVALID_RR" in value:
        return "maintain strict; inspect SL/TP and RR"
    return "investigate"

"""Session and regime edge analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd


def analyze_sessions_regimes(by_session: pd.DataFrame, by_regime: pd.DataFrame) -> dict[str, Any]:
    """Return allowed/blocked session and regime recommendations."""

    session_rows = _classify_context(by_session, "session", rollover=True)
    regime_rows = _classify_context(by_regime, "regime", rollover=False)
    return {
        "sessions": session_rows,
        "regimes": regime_rows,
        "allowed_sessions": [row["name"] for row in session_rows if row["decision"] == "ALLOW"],
        "blocked_sessions": [row["name"] for row in session_rows if row["decision"] == "BLOCK"],
        "allowed_regimes": [row["name"] for row in regime_rows if row["decision"] == "ALLOW"],
        "blocked_regimes": [row["name"] for row in regime_rows if row["decision"] == "BLOCK"],
        "reduce_risk_regimes": [row["name"] for row in regime_rows if row["decision"] == "REDUCE_RISK"],
    }


def _classify_context(frame: pd.DataFrame, column: str, *, rollover: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame.empty or column not in frame.columns:
        return rows
    for _, item in frame.iterrows():
        name = str(item.get(column, "UNKNOWN") or "UNKNOWN").upper()
        trades = int(item.get("total_trades", 0) or 0)
        expectancy = float(item.get("expectancy_r", 0.0) or 0.0)
        pf = float(item.get("profit_factor", 0.0) or 0.0)
        decision = "WATCHLIST"
        reason = "insufficient context sample"
        if rollover and name == "ROLLOVER":
            decision = "BLOCK" if expectancy <= 0 or pf < 1.10 else "WATCHLIST"
            reason = "rollover is blocked by default unless clearly positive"
        elif trades >= 20 and expectancy > 0 and pf > 1.05:
            decision = "ALLOW"
            reason = "positive context metrics"
        elif trades >= 20 and expectancy < 0:
            decision = "BLOCK"
            reason = "negative context expectancy"
        elif trades >= 10:
            decision = "REDUCE_RISK"
            reason = "context sample is weak or mixed"
        rows.append({"name": name, "decision": decision, "reasons": reason, **item.to_dict()})
    return rows

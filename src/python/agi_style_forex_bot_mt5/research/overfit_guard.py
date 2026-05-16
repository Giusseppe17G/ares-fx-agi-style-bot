"""Overfit detection for research candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class OverfitAssessment:
    overfit_risk: str
    reasons: tuple[str, ...]
    recommended_status: str


def assess_overfit(
    *,
    train_metrics: Mapping[str, Any] | None = None,
    test_metrics: Mapping[str, Any] | None = None,
    trades_summary: Mapping[str, Any] | None = None,
    stress_summary: Mapping[str, Any] | None = None,
) -> OverfitAssessment:
    """Assess overfit risk from train/test, concentration and stress evidence."""

    train = train_metrics or {}
    test = test_metrics or {}
    trades = trades_summary or {}
    stress = stress_summary or {}
    reasons: list[str] = []
    severity = 0
    if _avg_r(train) > 0.15 and _avg_r(test) < 0:
        reasons.append("train positive but test negative")
        severity += 3
    if _pf(test) > 3.0 and _trades(test) < 100:
        reasons.append("profit factor exaggerated with too few trades")
        severity += 2
    if float(trades.get("top_5_profit_concentration_pct", 0.0) or 0.0) > 40.0:
        reasons.append("more than 40% of gains in top 5% trades")
        severity += 3
    if int(trades.get("profitable_days", 99) or 99) < 3:
        reasons.append("performance concentrated in fewer than 3 days")
        severity += 2
    if int(trades.get("profitable_sessions", 99) or 99) <= 1:
        reasons.append("performance concentrated in one session")
        severity += 2
    if float(stress.get("parameter_sensitivity_pct", 0.0) or 0.0) > 50.0:
        reasons.append("parameters are too sensitive")
        severity += 2
    if _trades(test) < 30:
        reasons.append("too few trades per validation window")
        severity += 2
    if str(stress.get("classification", "WATCHLIST")) == "REJECTED":
        reasons.append("stress test deteriorated strongly")
        severity += 3
    if severity >= 6:
        return OverfitAssessment("CRITICAL", tuple(reasons), "REJECTED")
    if severity >= 4:
        return OverfitAssessment("HIGH", tuple(reasons), "REJECTED")
    if severity >= 2:
        return OverfitAssessment("MEDIUM", tuple(reasons), "WATCHLIST")
    return OverfitAssessment("LOW", tuple(reasons) or ("no major overfit flags",), "APPROVED_FOR_SHADOW_OBSERVATION")


def _avg_r(metrics: Mapping[str, Any]) -> float:
    return float(metrics.get("expectancy_r", metrics.get("average_r", 0.0)) or 0.0)


def _pf(metrics: Mapping[str, Any]) -> float:
    value = metrics.get("profit_factor", 0.0)
    return 10.0 if value == "Infinity" else float(value or 0.0)


def _trades(metrics: Mapping[str, Any]) -> int:
    return int(metrics.get("trades_total", metrics.get("total_trades", metrics.get("trades_count", 0))) or 0)

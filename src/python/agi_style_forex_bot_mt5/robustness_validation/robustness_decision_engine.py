"""Decision engine for BALANCED robustness fast-track."""

from __future__ import annotations

from typing import Any, Mapping


def decide_robustness(
    *,
    profile: str,
    base_metrics: Mapping[str, Any],
    monte_carlo: Mapping[str, Any],
    stress: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    cost_sensitivity: Mapping[str, Any],
    profile_allowed_for_shadow: bool,
    not_for_demo_live: bool,
) -> dict[str, Any]:
    """Return a conservative paper/shadow-only robustness decision."""

    total = int(_number(base_metrics.get("total_trades")) or 0)
    pf = _number(base_metrics.get("profit_factor"))
    expectancy = _number(base_metrics.get("expectancy_r"))
    if total < 100 or pf is None or expectancy is None:
        return _decision("NEEDS_MORE_ROBUSTNESS_DATA", "BALANCED needs at least 100 trades with full metrics.")
    if not profile_allowed_for_shadow or not_for_demo_live or profile.upper() != "BALANCED":
        return _decision("NEEDS_MORE_ROBUSTNESS_DATA", "Profile safety flags do not allow paper-forward candidate review.")
    if str(monte_carlo.get("classification")) in {"NEEDS_MORE_ROBUSTNESS_DATA", "LIMITED_MONTE_CARLO"} or monte_carlo.get("probability_profit_positive") is None:
        return _decision("NEEDS_MORE_ROBUSTNESS_DATA", "Trade-level Monte Carlo evidence is missing.")
    if str(cost_sensitivity.get("classification")) == "NEEDS_COST_RECALIBRATION":
        return _decision("NEEDS_COST_RECALIBRATION", "Cost sensitivity destroys the edge.")
    if str(stress.get("classification")) == "STRESS_FAILED":
        if str(stress.get("most_sensitive_cost", "")).startswith("spread"):
            return _decision("NEEDS_COST_RECALIBRATION", "Stress test fails under spread/cost expansion.")
        return _decision("NEEDS_STRATEGY_REWORK", "Stress test fails under robustness scenarios.")
    if str(walk_forward.get("classification")) == "NEEDS_MORE_WALK_FORWARD_DATA":
        return _decision("NEEDS_MORE_ROBUSTNESS_DATA", "Reduced walk-forward does not have enough temporal evidence.")
    if bool(walk_forward.get("overfit_warning")) and _number(walk_forward.get("min_fold_expectancy")) is not None and float(walk_forward.get("min_fold_expectancy")) < 0:
        return _decision("NEEDS_STRATEGY_REWORK", "Walk-forward folds show negative out-of-sample behavior.")
    if pf < 1.20 or expectancy <= 0:
        return _decision("REJECT_BALANCED_ROBUSTNESS", "BALANCED base edge metrics no longer meet the robustness gate.")
    if float(monte_carlo.get("probability_profit_positive", 0.0) or 0.0) < 0.60:
        return _decision("NEEDS_MORE_ROBUSTNESS_DATA", "Monte Carlo positive-profit probability is below 60%.")
    if _number(stress.get("worst_case_profit_factor")) is not None and float(stress.get("worst_case_profit_factor")) < 1.0:
        return _decision("NEEDS_COST_RECALIBRATION", "Worst stress case profit factor falls below 1.0.")
    if float(cost_sensitivity.get("cost_fragility_score", 100.0) or 100.0) >= 80:
        return _decision("NEEDS_COST_RECALIBRATION", "Cost fragility score is extreme.")
    return _decision("PAPER_FORWARD_SHADOW_CANDIDATE", "BALANCED passed fast robustness checks for paper/shadow observation only.")


def _decision(decision: str, reason: str) -> dict[str, Any]:
    return {"robustness_decision": decision, "reason": reason, "execution_attempted": False}


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

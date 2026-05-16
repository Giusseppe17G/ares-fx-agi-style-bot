"""Rank candidate signals by portfolio-aware quality."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class SignalRanker:
    """Rank signals and attach accept/reject rank decisions."""

    def rank(self, candidates: Sequence[Mapping[str, Any]], *, top_n: int = 3) -> list[dict[str, Any]]:
        scored = []
        for candidate in candidates:
            score = self._score(candidate)
            scored.append({**dict(candidate), "ranking_score": score})
        scored.sort(key=lambda item: item["ranking_score"], reverse=True)
        ranked: list[dict[str, Any]] = []
        for index, item in enumerate(scored):
            decision = "ACCEPT_TOP_N" if index < top_n else "REJECT_LOW_RANK"
            if float(item.get("correlation", 0.0) or 0.0) >= 0.85:
                decision = "REJECT_CORRELATED"
            if bool(item.get("exposure_breach", False)):
                decision = "REJECT_EXPOSURE"
            if bool(item.get("risk_budget_exhausted", False)):
                decision = "REJECT_RISK_BUDGET"
            ranked.append({**item, "rank": index + 1, "ranking_decision": decision, "execution_attempted": False})
        return ranked

    def _score(self, candidate: Mapping[str, Any]) -> float:
        ml = float(candidate.get("ml_probability") or 0.0) * 100.0
        strategy = float(candidate.get("strategy_score") or candidate.get("score") or 0.0)
        broker = float(candidate.get("broker_readiness_score") or 50.0)
        spread_penalty = float(candidate.get("spread_percentile") or 50.0) * 0.25
        corr_penalty = abs(float(candidate.get("correlation") or 0.0)) * 25.0
        exposure_penalty = float(candidate.get("additional_exposure") or 0.0) * 5.0
        recent = float(candidate.get("recent_expectancy") or 0.0) * 10.0
        return ml * 0.35 + strategy * 0.30 + broker * 0.15 + recent - spread_penalty - corr_penalty - exposure_penalty


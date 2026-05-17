"""Conservative master decision engine."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .validation_artifacts import artifact_paths


DECISIONS = {
    "CONTINUE_FORWARD_SHADOW",
    "NEEDS_MORE_DATA",
    "NEEDS_STRATEGY_RESEARCH",
    "NEEDS_BROKER_FIX",
    "NEEDS_COST_RECALIBRATION",
    "REJECTED",
}


@dataclass(frozen=True)
class MasterDecision:
    final_decision: str
    reasons: tuple[str, ...]
    by_symbol: dict[str, Any]
    by_strategy: dict[str, Any]
    by_regime: dict[str, Any]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MasterDecisionEngine:
    """Merge quantitative and operational evidence into a fail-closed decision."""

    def decide(self, *, reports_root: str | Path, output_dir: str | Path, symbols: tuple[str, ...] = ()) -> MasterDecision:
        paths = artifact_paths(reports_root, output_dir)
        summaries = {name: _read_json(path) for name, path in paths.items() if name not in {"pipeline_summary", "stage_results", "master_decision", "master_decision_csv", "html"}}
        reasons: list[str] = []
        decision = self._decision_from_summaries(summaries, reasons)
        by_symbol = {symbol: {"decision": decision, "reasons": reasons[:]} for symbol in symbols}
        return MasterDecision(decision, tuple(reasons), by_symbol, {}, {}, False)

    def _decision_from_summaries(self, summaries: Mapping[str, Mapping[str, Any]], reasons: list[str]) -> str:
        data_quality = summaries.get("data_quality", {})
        if not data_quality or str(data_quality.get("classification") or "").upper() not in {"OK", "APPROVED_FOR_SHADOW_OBSERVATION"}:
            reasons.append("data-quality missing or not OK")
            return "NEEDS_MORE_DATA"
        costs = summaries.get("broker_cost_profile", {})
        if not costs:
            reasons.append("broker cost profile missing")
            return "NEEDS_MORE_DATA"
        backtest = summaries.get("backtest", {})
        signal_profile = str(backtest.get("signal_profile_used") or backtest.get("settings", {}).get("parameters", {}).get("SIGNAL_PROFILE", "")).upper()
        if signal_profile in {"ACTIVE", "RESEARCH_ONLY"}:
            reasons.append(f"{signal_profile} profile is NOT_FOR_DEMO_LIVE and cannot promote to forward-shadow continuation")
            return "NEEDS_STRATEGY_RESEARCH"
        if int(backtest.get("total_trades", 0) or 0) < 100:
            reasons.append("backtest has insufficient trades")
            return "NEEDS_STRATEGY_RESEARCH"
        wf = summaries.get("walk_forward", {})
        if str(wf.get("classification", "")).upper() in {"REJECTED", "NEGATIVE_OOS"}:
            reasons.append("walk-forward out-of-sample is negative")
            return "NEEDS_STRATEGY_RESEARCH"
        monte = summaries.get("monte_carlo", {})
        ruin = float(monte.get("probability_of_ruin", monte.get("risk_of_ruin", 0.0)) or 0.0)
        if ruin > 0.10 or str(monte.get("classification", "")).upper() == "REJECTED":
            reasons.append("Monte Carlo risk of ruin is high")
            return "REJECTED"
        stress = summaries.get("stress", {})
        if str(stress.get("classification", "")).upper() in {"REJECTED", "COLLAPSED"}:
            reasons.append("stress test collapsed")
            return "NEEDS_COST_RECALIBRATION"
        benchmark = summaries.get("benchmark", {})
        competitive = summaries.get("competitive_scorecard", {})
        if str(benchmark.get("classification", "")).upper() == "NEEDS_MORE_DATA":
            reasons.append("benchmark data insufficient")
            return "NEEDS_MORE_DATA"
        if str(benchmark.get("classification", "")).upper() == "REJECTED" or str(competitive.get("classification", "")).upper() in {"REJECTED", "WEAK_EDGE"}:
            reasons.append("strategy does not beat benchmarks")
            return "NEEDS_STRATEGY_RESEARCH"
        broker = summaries.get("broker_quality", {})
        readiness = summaries.get("validation_report", {})
        if str(broker.get("classification", "")).upper() in {"NOT_READY", "NEEDS_BROKER_FIX"} or str(readiness.get("classification", "")).upper() == "NEEDS_BROKER_FIX":
            reasons.append("broker readiness is not ready")
            return "NEEDS_BROKER_FIX"
        paper = summaries.get("paper_vs_backtest", {})
        if str(paper.get("classification", "")).upper() in {"BACKTEST_TOO_OPTIMISTIC", "COST_ASSUMPTION_TOO_LOW"}:
            reasons.append("paper-vs-backtest indicates optimistic or low cost assumptions")
            return "NEEDS_COST_RECALIBRATION"
        simulation = summaries.get("simulation_calibration", {})
        if str(simulation.get("classification", "")).upper() == "COST_ASSUMPTION_TOO_LOW":
            reasons.append("execution simulation cost assumptions too low")
            return "NEEDS_COST_RECALIBRATION"
        forward = summaries.get("forward_shadow", {})
        if not forward or int(forward.get("paper_trades_closed", forward.get("closed_trades", 0)) or 0) < 200:
            reasons.append("forward paper data is still accumulating")
            return "CONTINUE_FORWARD_SHADOW"
        reasons.append("all critical evidence is acceptable for continued shadow observation")
        return "CONTINUE_FORWARD_SHADOW"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

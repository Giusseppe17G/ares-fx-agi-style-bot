"""Research report writers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .candidate_registry import CandidateRegistry
from .strategy_candidate import StrategyCandidate


def write_research_reports(
    *,
    output_dir: str | Path,
    registry: CandidateRegistry,
    recommended_mix: Iterable[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> list[str]:
    """Write JSON/CSV/HTML research artifacts."""

    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    summary_json = path / "research_summary.json"
    summary_csv = path / "research_summary.csv"
    registry_json = path / "candidate_registry.json"
    mix_json = path / "recommended_strategy_mix.json"
    rejected_csv = path / "rejected_candidates.csv"
    ablation_csv = path / "ablation_results.csv"
    version_csv = path / "strategy_version_comparison.csv"
    html = path / "report.html"
    candidates = registry.list()
    summary_json.write_text(json.dumps(dict(summary), indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame([summary]).to_csv(summary_csv, index=False)
    registry.save_json(registry_json)
    mix_json.write_text(json.dumps(list(recommended_mix), indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame([item.to_dict() for item in candidates if item.status == "REJECTED"]).to_csv(rejected_csv, index=False)
    pd.DataFrame(
        [
            {"ablation": "baseline_v0_1", "classification": "REFERENCE", "execution_attempted": False},
            {"ablation": "without_market_structure", "classification": "WATCHLIST", "execution_attempted": False},
            {"ablation": "without_cost_scoring", "classification": "WATCHLIST", "execution_attempted": False},
            {"ablation": "without_session_filters", "classification": "WATCHLIST", "execution_attempted": False},
            {"ablation": "without_liquidity_filters", "classification": "WATCHLIST", "execution_attempted": False},
        ]
    ).to_csv(ablation_csv, index=False)
    pd.DataFrame(
        [
            {"strategy_version": "0.1.0", "role": "legacy_reference", "execution_attempted": False},
            {"strategy_version": "0.2.0", "role": "market_structure_upgrade", "execution_attempted": False},
        ]
    ).to_csv(version_csv, index=False)
    html.write_text(_html(summary, candidates), encoding="utf-8")
    return [str(item) for item in (summary_json, summary_csv, registry_json, mix_json, rejected_csv, ablation_csv, version_csv, html)]


def _html(summary: Mapping[str, Any], candidates: Iterable[StrategyCandidate]) -> str:
    rows = "\n".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in summary.items())
    candidate_rows = "\n".join(
        f"<tr><td>{item.symbol}</td><td>{item.strategy_name}</td><td>{item.status}</td><td>{item.metrics_summary.get('composite_score', 0)}</td></tr>"
        for item in candidates
    )
    return f"""<!doctype html>
<html><body>
<h1>Strategy Research Report</h1>
<p>Research-only. No demo or live orders are enabled.</p>
<table>{rows}</table>
<h2>Candidates</h2>
<table><tr><th>Symbol</th><th>Strategy</th><th>Status</th><th>Score</th></tr>{candidate_rows}</table>
</body></html>
"""

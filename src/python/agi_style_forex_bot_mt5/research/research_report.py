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
    html = path / "report.html"
    candidates = registry.list()
    summary_json.write_text(json.dumps(dict(summary), indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame([summary]).to_csv(summary_csv, index=False)
    registry.save_json(registry_json)
    mix_json.write_text(json.dumps(list(recommended_mix), indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame([item.to_dict() for item in candidates if item.status == "REJECTED"]).to_csv(rejected_csv, index=False)
    html.write_text(_html(summary, candidates), encoding="utf-8")
    return [str(item) for item in (summary_json, summary_csv, registry_json, mix_json, rejected_csv, html)]


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

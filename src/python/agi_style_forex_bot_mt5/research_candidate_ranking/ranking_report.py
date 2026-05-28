"""Report writer for offline research candidate ranking."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .candidate_loader import build_candidate_events, load_research_inputs
from .candidate_ranker import rank_candidates, research_recommendations


def run_research_candidate_ranking(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/research_candidate_ranking",
) -> dict[str, Any]:
    """Build an offline ranking of symbol and strategy research candidates."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_research_inputs(database=database, log_dir=log_dir, reports_root=reports_root)
    candidate_events = build_candidate_events(inputs)
    paper_trades = [dict(row) for row in inputs.get("paper_trades", [])]
    by_symbol = rank_candidates(events=candidate_events, paper_trades=paper_trades, group_key="symbol")
    by_strategy = rank_candidates(events=candidate_events, paper_trades=paper_trades, group_key="strategy_name")
    blockers = _blocker_rows(by_symbol, by_strategy)
    recs = research_recommendations(by_symbol, by_strategy)
    status = _status(by_symbol, by_strategy)
    top_score = float(by_symbol[0].get("final_candidate_score", 0.0) or 0.0) if by_symbol else 0.0
    summary = {
        "mode": "research-candidate-ranking",
        "research_candidate_status": status,
        "research_candidate_score": top_score,
        "symbols_analyzed": len([row for row in by_symbol if row.get("symbol") != "UNKNOWN"]),
        "strategies_analyzed": len([row for row in by_strategy if row.get("strategy_name") != "UNKNOWN"]),
        **recs,
        "input_event_count": len(candidate_events),
        "paper_trade_count": len(paper_trades),
        "reports_root": str(reports_root),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, by_symbol, by_strategy, blockers)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(by_symbol: list[Mapping[str, Any]], by_strategy: list[Mapping[str, Any]]) -> str:
    rows = [*by_symbol, *by_strategy]
    if not rows:
        return "DATA_INSUFFICIENT"
    classes = {str(row.get("candidate_classification")) for row in rows}
    if classes <= {"DATA_INSUFFICIENT"}:
        return "DATA_INSUFFICIENT"
    if "RESEARCH_READY" in classes:
        return "RESEARCH_READY"
    if "RISK_UNSTABLE" in classes:
        return "RISK_UNSTABLE"
    if "HIGH_REJECTION_RATE" in classes:
        return "HIGH_REJECTION_RATE"
    return "NEEDS_MORE_FORWARD_DATA"


def _blocker_rows(by_symbol: list[Mapping[str, Any]], by_strategy: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope, items, key in (("symbol", by_symbol, "symbol"), ("strategy", by_strategy, "strategy_name")):
        for item in items:
            rows.append(
                {
                    "scope": scope,
                    "name": item.get(key, ""),
                    "top_blocking_reasons": item.get("top_blocking_reasons", ""),
                    "signals_rejected": item.get("signals_rejected", 0),
                    "rejection_rate": item.get("rejection_rate", 0.0),
                    "classification": item.get("candidate_classification", ""),
                    "execution_attempted": False,
                }
            )
    return rows


def _write_reports(output: Path, summary: Mapping[str, Any], by_symbol: list[Mapping[str, Any]], by_strategy: list[Mapping[str, Any]], blockers: list[Mapping[str, Any]]) -> list[Path]:
    paths = [
        output / "candidate_ranking_summary.json",
        output / "candidate_ranking_by_symbol.csv",
        output / "candidate_ranking_by_strategy.csv",
        output / "candidate_blockers.csv",
        output / "candidate_recommendations.md",
        output / "report.html",
    ]
    paths[0].write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(paths[1], by_symbol)
    _write_csv(paths[2], by_strategy)
    _write_csv(paths[3], blockers)
    paths[4].write_text(_recommendations_markdown(summary), encoding="utf-8")
    paths[5].write_text(f"<html><body><h1>Research Candidate Ranking</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _recommendations_markdown(summary: Mapping[str, Any]) -> str:
    return f"""# Research Candidate Ranking

Status: `{summary.get('research_candidate_status')}`

Best symbols for next paper/shadow window: `{', '.join(summary.get('best_symbols_for_next_shadow_window', []))}`

Symbols to pause from research: `{', '.join(summary.get('symbols_to_pause_from_research', []))}`

Strategies to watch: `{', '.join(summary.get('strategies_to_watch', []))}`

Strategies to disable candidate: `{', '.join(summary.get('strategies_to_disable_candidate', []))}`

Recommended next research action: {summary.get('recommended_next_research_action')}

This report is offline research only. It does not authorize demo/live execution and does not bypass forward acceptance or risk gates.
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

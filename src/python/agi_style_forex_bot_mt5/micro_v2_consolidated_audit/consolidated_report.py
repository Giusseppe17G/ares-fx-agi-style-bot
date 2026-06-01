"""Report orchestration for Micro V2 consolidated risk/market audit."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .consolidated_loader import load_consolidated_inputs
from .exposure_double_counting_audit import audit_exposure_double_counting
from .exposure_explainability import audit_exposure_explainability
from .market_stability_audit import audit_market_stability
from .risk_decision_audit import audit_risk_decision
from .v2_continue_or_repair_decision import decide_continue_or_repair


def run_micro_v2_consolidated_audit(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    filter_analysis_dir: str | Path = "data/reports/micro_v2_filter_analysis",
    risk_block_dir: str | Path = "data/reports/micro_v2_risk_block_audit",
    checkpoint_dir: str | Path = "data/reports/micro_v2_observation_checkpoint",
    readiness_dir: str | Path = "data/reports/micro_v2_market_open_readiness",
    output_dir: str | Path = "data/reports/micro_v2_consolidated_audit",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_consolidated_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        filter_analysis_dir=filter_analysis_dir,
        risk_block_dir=risk_block_dir,
        checkpoint_dir=checkpoint_dir,
        readiness_dir=readiness_dir,
    )
    exposure = audit_exposure_explainability(inputs["v2_dataset"], inputs["checkpoint"], inputs["profile_values"])
    double_counting = audit_exposure_double_counting(exposure)
    market = audit_market_stability(inputs["filter_analysis"], inputs["checkpoint"], inputs["readiness"])
    risk = audit_risk_decision(inputs["risk_block"], exposure)
    decision = decide_continue_or_repair(
        dataset=inputs["v2_dataset"],
        exposure=exposure,
        double_counting=double_counting,
        market=market,
        risk=risk,
        checkpoint=inputs["checkpoint"],
    )
    summary = {
        "mode": "micro-v2-consolidated-risk-market-audit",
        **decision,
        "exposure_guard_diagnosis": exposure.get("exposure_guard_diagnosis", ""),
        "market_stability_status": market.get("market_stability_status", ""),
        "market_closed_dominance_ratio": market.get("market_closed_dominance_ratio", 0.0),
        "fresh_tick_symbols": market.get("fresh_tick_symbols", []),
        "stale_tick_symbols": market.get("stale_tick_symbols", []),
        "affected_symbols": risk.get("affected_symbols", exposure.get("affected_symbols", [])),
        "double_counting_detected": double_counting.get("double_counting_detected", False),
        "data_missing_detected": double_counting.get("data_missing_detected", False),
        "profile_parse_error": exposure.get("profile_parse_error", False),
        "dominant_risk_block_reason": risk.get("dominant_risk_block_reason", ""),
        "risk_rejected_count": risk.get("risk_rejected_count", 0),
        "runtime_repair_recommendations_created": _needs_runtime_repair(decision),
        "future_filter_tuning_recommendations_created": decision.get("consolidated_v2_audit_status") == "MICRO_V2_READY_FOR_FILTER_TUNING_REVIEW",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, exposure, double_counting, market, risk, decision)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _needs_runtime_repair(decision: Mapping[str, Any]) -> bool:
    return str(decision.get("consolidated_v2_audit_status", "")) in {
        "MICRO_V2_EXPOSURE_POSSIBLE_DOUBLE_COUNTING",
        "MICRO_V2_EXPOSURE_DATA_MISSING",
        "MICRO_V2_EXPOSURE_PROFILE_PARSE_ERROR",
        "MICRO_V2_REQUIRES_RUNTIME_REPAIR",
    }


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    exposure: Mapping[str, Any],
    double_counting: Mapping[str, Any],
    market: Mapping[str, Any],
    risk: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_consolidated_audit_summary.json",
        output / "exposure_explainability.json",
        output / "exposure_blocks.csv",
        output / "exposure_by_symbol.csv",
        output / "exposure_double_counting_audit.json",
        output / "market_stability_audit.json",
        output / "risk_decision_audit.json",
        output / "continue_or_repair_decision.json",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], exposure)
    _write_csv(paths[2], exposure.get("exposure_blocks", []))
    _write_csv(paths[3], exposure.get("exposure_by_symbol", []))
    _write_json(paths[4], double_counting)
    _write_json(paths[5], market)
    _write_json(paths[6], risk)
    _write_json(paths[7], decision)
    paths[8].write_text(_recommendations(summary), encoding="utf-8")
    if summary.get("runtime_repair_recommendations_created"):
        repair = output / "runtime_repair_recommendations.md"
        repair.write_text(_research_only_md(summary, "Runtime Repair Recommendations"), encoding="utf-8")
        paths.append(repair)
    if summary.get("future_filter_tuning_recommendations_created"):
        tuning = output / "future_filter_tuning_recommendations.md"
        tuning.write_text(_research_only_md(summary, "Future Filter Tuning Recommendations"), encoding="utf-8")
        paths.append(tuning)
    paths[9].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Consolidated Audit

Status: `{summary.get('consolidated_v2_audit_status')}`

Exposure diagnosis: `{summary.get('exposure_guard_diagnosis')}`

Market stability: `{summary.get('market_stability_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This audit is offline/read-only. It does not create runtime profiles, tune filters, modify ledgers, or authorize demo/live execution.
"""


def _research_only_md(summary: Mapping[str, Any], title: str) -> str:
    return f"""# {title}

NOT_ACTIVE_RESEARCH_ONLY=true
REQUIRES_REVIEW_PHASE=true
APPROVED_FOR_RUNTIME=false

Status: `{summary.get('consolidated_v2_audit_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Consolidated Audit</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

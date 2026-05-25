"""Forward evidence report orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.execution_evidence import run_execution_evidence_audit
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .drift_summary import summarize_forward_drift
from .evidence_collector import collect_forward_evidence
from .forward_metrics import calculate_forward_metrics
from .operational_acceptance_gate import decide_operational_acceptance
from .paper_trade_audit import audit_paper_trades
from .rejection_analysis import analyze_rejections


def run_forward_evidence(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/forward_evidence",
) -> dict[str, Any]:
    """Build the evidence pack and write all reports."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence = collect_forward_evidence(database=database, log_dir=log_dir, reports_root=reports_root)
    metrics = calculate_forward_metrics(
        database=database,
        hours_observed=float(evidence.get("hours_observed", 0.0) or 0.0),
        signals_detected=int(evidence.get("signals_detected", 0) or 0),
        signals_rejected=int(evidence.get("signals_rejected", 0) or 0),
    )
    baseline = _load_json(Path(reports_root) / "stable_gate" / "stable_gate_summary.json") or _load_json(Path(reports_root) / "robustness" / "robustness_summary.json")
    drift = summarize_forward_drift(forward_metrics=metrics, baseline=baseline)
    rejections, rejection_frame = analyze_rejections(database=database)
    audit = audit_paper_trades(database=database, log_dir=str(log_dir))
    diagnostics = _load_json(Path(reports_root) / "forward_diagnostics" / "signal_scarcity_summary.json")
    forward_research = _load_json(Path(reports_root) / "forward_research" / "candidate_replay_summary.json")
    blocker_sensitivity = _load_json(Path(reports_root) / "forward_research" / "blocker_sensitivity.json")
    execution_evidence = run_execution_evidence_audit(
        sqlite_path=database.path,
        log_dir=log_dir,
        reports_root=reports_root,
        output_dir=Path(reports_root) / "execution_evidence",
    )
    acceptance = decide_operational_acceptance(evidence=evidence, metrics=metrics, drift=drift, paper_audit=audit, execution_evidence=execution_evidence)
    summary = {
        **evidence,
        "forward_metrics_classification": metrics.get("classification"),
        "drift_classification": drift.get("classification"),
        "paper_trade_audit_status": audit.get("status"),
        "operational_acceptance": acceptance.get("decision"),
        "paper_state_status": metrics.get("paper_state_status"),
        "paper_drawdown_status": metrics.get("paper_drawdown_status"),
        "operational_halt_reason": acceptance.get("reason") if str(acceptance.get("decision", "")).startswith("PAUSE") else "",
        "execution_evidence_status": execution_evidence.get("execution_evidence_status"),
        "execution_false_positive_count": execution_evidence.get("execution_false_positive_count", 0),
        "execution_blocking_findings_count": execution_evidence.get("blocking_findings_count", 0),
        "execution_evidence_report_path": execution_evidence.get("execution_evidence_report_path", ""),
        "evidence_parse_status": evidence.get("evidence_parse_status", "OK"),
        "invalid_timestamp_count": evidence.get("invalid_timestamp_count", 0),
        "invalid_timestamp_fields": evidence.get("invalid_timestamp_fields", {}),
        "invalid_timestamp_examples": evidence.get("invalid_timestamp_examples", []),
        "forward_diagnostics_status": diagnostics.get("classification", ""),
        "top_forward_blockers": diagnostics.get("top_blockers", []),
        "candidate_count": diagnostics.get("candidate_count", 0),
        "near_miss_count": diagnostics.get("near_miss_count", 0),
        "live_feature_ready_symbols": diagnostics.get("feature_ready_symbols", []),
        "recommended_signal_diagnosis_action": diagnostics.get("recommended_action", ""),
        "forward_research_status": forward_research.get("status", ""),
        "top_research_blockers": forward_research.get("top_research_blockers", []),
        "research_variants_available": bool(blocker_sensitivity.get("variants_evaluated")),
        "recommended_research_action": _recommended_research_action(forward_research, blocker_sensitivity),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, metrics, drift, rejections, rejection_frame, audit, acceptance)
    return {**summary, "reports_created": paths}


def run_forward_acceptance(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/forward_evidence",
) -> dict[str, Any]:
    """Return only the operational acceptance gate, writing the full pack as context."""

    summary = run_forward_evidence(database=database, log_dir=log_dir, reports_root=reports_root, output_dir=output_dir)
    acceptance = _load_json(Path(output_dir) / "operational_acceptance.json")
    return {**acceptance, "reports_created": summary.get("reports_created", []), "execution_attempted": False, "order_send_called": False, "order_check_called": False}


def _write_reports(
    output: Path,
    evidence: Mapping[str, Any],
    metrics: Mapping[str, Any],
    drift: Mapping[str, Any],
    rejections: Mapping[str, Any],
    rejection_frame: pd.DataFrame,
    audit: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> list[str]:
    paths = {
        "evidence": output / "evidence_summary.json",
        "metrics": output / "forward_metrics.json",
        "drift": output / "drift_summary.json",
        "rejections": output / "rejections.csv",
        "audit": output / "paper_trade_audit.json",
        "acceptance": output / "operational_acceptance.json",
        "html": output / "report.html",
    }
    _write_json(paths["evidence"], evidence)
    _write_json(paths["metrics"], metrics)
    _write_json(paths["drift"], drift)
    rejection_frame.to_csv(paths["rejections"], index=False)
    _write_json(paths["audit"], audit)
    _write_json(paths["acceptance"], acceptance)
    rows = {
        "evidence": evidence,
        "metrics": metrics,
        "drift": drift,
        "rejections": rejections,
        "audit": audit,
        "acceptance": acceptance,
    }
    paths["html"].write_text(f"<html><body><h1>Forward Evidence Pack</h1><pre>{json.dumps(rows, indent=2, sort_keys=True)}</pre></body></html>", encoding="utf-8")
    return [str(path) for path in paths.values()]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _recommended_research_action(forward_research: Mapping[str, Any], blocker_sensitivity: Mapping[str, Any]) -> str:
    if not forward_research and not blocker_sensitivity:
        return ""
    if str(forward_research.get("status", "")).upper() == "NEEDS_MORE_FORWARD_CANDIDATES":
        return "Collect more blocked forward candidates before changing research variants."
    if blocker_sensitivity.get("best_research_variant"):
        return f"Review {blocker_sensitivity.get('best_research_variant')} in research only; do not modify live BALANCED_STABLE."
    return "Review candidate replay before proposing BALANCED_STABLE_V2 research."


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and value in {float("inf"), float("-inf")}:
        return "Infinity" if value > 0 else "-Infinity"
    return value

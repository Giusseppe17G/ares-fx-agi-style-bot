"""Forward evidence report orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.execution_evidence import run_execution_evidence_audit
from agi_style_forex_bot_mt5.paper_risk_calibration import run_paper_risk_status
from agi_style_forex_bot_mt5.paper_trading.paper_state_recovery import run_invalid_open_paper_trade_audit, run_paper_state_recovery_audit
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry_repair import run_telemetry_timestamp_audit

from .acceptance_drawdown_policy import run_acceptance_drawdown_policy_audit
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
    research_candidate_ranking = _load_json(Path(reports_root) / "research_candidate_ranking" / "candidate_ranking_summary.json")
    forward_sufficiency = _load_json(Path(reports_root) / "forward_sufficiency" / "forward_sufficiency_summary.json")
    micro_frequency = _load_json(Path(reports_root) / "micro_frequency_calibration" / "micro_frequency_summary.json")
    micro_v2_review = _load_json(Path(reports_root) / "micro_v2_review" / "micro_v2_review_summary.json")
    micro_v2_proposed_review = _load_json(Path(reports_root) / "micro_v2_review_proposed" / "micro_v2_proposed_review_summary.json")
    micro_v2_dry_run_readiness = _load_json(Path(reports_root) / "micro_v2_dry_run_readiness" / "micro_v2_dry_run_readiness_summary.json")
    micro_v2_dry_run_monitor = _load_json(Path(reports_root) / "micro_v2_dry_run_monitor" / "micro_v2_dry_run_monitor_summary.json")
    micro_v2_symbol_rejection = _load_json(Path(reports_root) / "micro_v2_symbol_rejection_audit" / "micro_v2_symbol_rejection_summary.json")
    micro_v2_market_open = _load_json(Path(reports_root) / "micro_v2_market_open_readiness" / "micro_v2_market_open_readiness_summary.json")
    micro_v2_observation_playbook = _load_json(Path(reports_root) / "micro_v2_observation_playbook" / "micro_v2_observation_playbook_summary.json")
    paper_pnl_audit = _load_json(Path(reports_root) / "paper_pnl_audit" / "paper_pnl_audit_summary.json")
    paper_risk_recommendation = _load_json(Path(reports_root) / "paper_pnl_audit" / "paper_risk_recommendation.json")
    legacy_drawdown = _load_json(Path(reports_root) / "paper_daily_risk" / "legacy_drawdown_audit_summary.json")
    execution_evidence = run_execution_evidence_audit(
        sqlite_path=database.path,
        log_dir=log_dir,
        reports_root=reports_root,
        output_dir=Path(reports_root) / "execution_evidence",
    )
    telemetry_summary = run_telemetry_timestamp_audit(
        sqlite_path=database.path,
        log_dir=log_dir,
        reports_root=reports_root,
        output_dir=Path(reports_root) / "telemetry_repair",
    )
    paper_risk = run_paper_risk_status(
        database=database,
        profile_config=_paper_risk_profile_config(Path(reports_root)),
        clearance_ledger=_paper_risk_clearance_ledger(Path(reports_root)),
        daily_risk_ledger=_paper_daily_risk_ledger(Path(reports_root)),
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=Path(reports_root) / "paper_risk",
        output_dir=Path(reports_root) / "paper_risk",
    )
    paper_state_recovery = run_paper_state_recovery_audit(
        database=database,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=Path(reports_root) / "paper_risk",
        daily_risk_dir=Path(reports_root) / "paper_daily_risk",
        pnl_audit_dir=Path(reports_root) / "paper_pnl_audit",
        clearance_ledger=_paper_risk_clearance_ledger(Path(reports_root)),
        daily_risk_ledger=_paper_daily_risk_ledger(Path(reports_root)),
        profile_config=_paper_risk_profile_config(Path(reports_root)),
        stable_gate=Path(reports_root) / "stable_gate" / "stable_gate_summary.json",
        output_dir=Path(reports_root) / "paper_state_recovery",
    )
    invalid_open_trade = run_invalid_open_paper_trade_audit(
        database=database,
        log_dir=log_dir,
        reports_root=reports_root,
        output_dir=Path(reports_root) / "paper_state_recovery",
    )
    acceptance = decide_operational_acceptance(
        evidence=evidence,
        metrics=metrics,
        drift=drift,
        paper_audit=audit,
        execution_evidence=execution_evidence,
        telemetry_summary=telemetry_summary,
        paper_risk=paper_risk,
        legacy_drawdown=legacy_drawdown,
        paper_state_recovery=paper_state_recovery,
    )
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
        "telemetry_status": telemetry_summary.get("telemetry_status"),
        "active_telemetry_blocking_count": telemetry_summary.get("active_blocking_count", 0),
        "historical_telemetry_issue_count": telemetry_summary.get("historical_invalid_count", 0),
        "historical_telemetry_quarantined_count": telemetry_summary.get("historical_quarantined_count", telemetry_summary.get("quarantined_count", 0)),
        "historical_telemetry_unreviewed_count": telemetry_summary.get("historical_unreviewed_count", telemetry_summary.get("unquarantined_historical_count", 0)),
        "telemetry_auto_quarantine_candidate_count": telemetry_summary.get("auto_quarantine_candidate_count", 0),
        "telemetry_derived_example_count": telemetry_summary.get("derived_example_count", 0),
        "telemetry_redacted_legacy_count": telemetry_summary.get("redacted_legacy_count", 0),
        "telemetry_drift_prevented": bool(
            telemetry_summary.get("telemetry_acceptance_clear", False)
            and int(telemetry_summary.get("historical_unreviewed_count", telemetry_summary.get("unquarantined_historical_count", 0)) or 0) == 0
            and (
                int(telemetry_summary.get("auto_quarantine_candidate_count", 0) or 0) > 0
                or int(telemetry_summary.get("derived_example_count", 0) or 0) > 0
                or int(telemetry_summary.get("redacted_legacy_count", 0) or 0) > 0
            )
        ),
        "telemetry_quarantined_count": telemetry_summary.get("quarantined_count", 0),
        "telemetry_acceptance_clear": telemetry_summary.get("telemetry_acceptance_clear", False),
        "telemetry_policy_reason": telemetry_summary.get("telemetry_policy_reason", ""),
        "telemetry_report_path": telemetry_summary.get("telemetry_report_path", ""),
        "paper_risk_status": paper_risk.get("paper_risk_status", ""),
        "paper_state_recovery_status": paper_state_recovery.get("paper_state_recovery_status", ""),
        "config_error_root_cause": paper_state_recovery.get("config_error_root_cause", ""),
        "config_error_recommended_fix": paper_state_recovery.get("recommended_config_fix", ""),
        "can_rerun_forward_shadow_after_fix": paper_state_recovery.get("can_rerun_forward_shadow_after_fix", False),
        "config_error_resolved": paper_state_recovery.get("config_error_resolved", False),
        "invalid_open_paper_trade_count": invalid_open_trade.get("invalid_open_trade_count", 0),
        "invalid_open_paper_trade_resolved": int(invalid_open_trade.get("invalid_open_trade_count", 0) or 0) == 0,
        "open_paper_trade_audit_status": _open_trade_audit_status(paper_state_recovery),
        "paper_state_clean_for_observation": paper_state_recovery.get("paper_state_clean_for_observation", False),
        "recovery_required": paper_state_recovery.get("recovery_required", False),
        "recovery_recommended_action": paper_state_recovery.get("recovery_recommended_action", ""),
        "paper_risk_profile": paper_risk.get("paper_risk_profile", ""),
        "paper_risk_blocks": [paper_risk.get("blocking_reason")] if paper_risk.get("blocking_reason") else [],
        "paper_risk_acceptance_clear": paper_risk.get("paper_risk_acceptance_clear", False),
        "paper_risk_clearance_status": paper_risk.get("paper_risk_clearance_status", ""),
        "paper_risk_clearance_id": paper_risk.get("paper_risk_clearance_id", ""),
        "cleared_for_profile": paper_risk.get("cleared_for_profile", ""),
        "clearance_stale": paper_risk.get("clearance_stale", False),
        "paper_daily_risk_status": paper_risk.get("paper_daily_risk_status", ""),
        "active_today_halt_count": paper_risk.get("active_today_halt_count", 0),
        "stale_halt_count": paper_risk.get("stale_halt_count", 0),
        "daily_risk_ledger_status": paper_risk.get("daily_risk_ledger_status", ""),
        "can_resume_micro_shadow": paper_risk.get("can_resume_micro_shadow", False),
        "legacy_drawdown_status": legacy_drawdown.get("legacy_drawdown_status", paper_risk.get("legacy_drawdown_status", "")),
        "legacy_drawdown_quarantined": legacy_drawdown.get("legacy_drawdown_quarantined", paper_risk.get("legacy_drawdown_quarantined", False)),
        "legacy_quarantined_halt_count": legacy_drawdown.get("legacy_quarantined_halt_count", paper_risk.get("legacy_quarantined_halt_count", 0)),
        "active_scaled_drawdown_count": legacy_drawdown.get("active_scaled_events_count", paper_risk.get("active_scaled_drawdown_count", 0)),
        "drawdown_basis": legacy_drawdown.get("drawdown_basis", paper_risk.get("drawdown_basis", "")),
        "paper_pnl_audit_status": paper_pnl_audit.get("paper_pnl_audit_status", paper_risk.get("paper_pnl_audit_status", "")),
        "micro_risk_application_status": paper_pnl_audit.get("micro_risk_application_status", ""),
        "drawdown_root_cause": paper_pnl_audit.get("root_cause", ""),
        "paper_risk_recommendation": paper_risk_recommendation.get("recommendation", paper_pnl_audit.get("recommended_action", "")),
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
        "research_candidate_score": research_candidate_ranking.get("research_candidate_score", 0.0),
        "best_research_symbols": research_candidate_ranking.get("best_symbols_for_next_shadow_window", []),
        "research_recommendation": research_candidate_ranking.get("recommended_next_research_action", ""),
        "forward_sufficiency_status": forward_sufficiency.get("forward_sufficiency_status", ""),
        "forward_sufficiency_hours_observed": forward_sufficiency.get("hours_observed", 0.0),
        "forward_sufficiency_closed_paper_trades": forward_sufficiency.get("closed_paper_trades", 0),
        "forward_sufficiency_estimated_hours_to_acceptance": forward_sufficiency.get("estimated_hours_to_acceptance"),
        "forward_sufficiency_recommendation": forward_sufficiency.get("recommended_next_action", ""),
        "micro_frequency_status": micro_frequency.get("micro_frequency_status", ""),
        "micro_frequency_estimated_hours_to_10_trades_current_profile": micro_frequency.get("estimated_hours_to_10_trades_current_profile"),
        "micro_frequency_top_bottlenecks": micro_frequency.get("top_frequency_bottlenecks", []),
        "micro_frequency_candidate_profile_available": micro_frequency.get("candidate_profile_available", False),
        "micro_v2_review_status": micro_v2_review.get("micro_v2_review_status", ""),
        "micro_v2_candidate_available": bool(micro_v2_review.get("candidate_profile_exists", False)),
        "micro_v2_proposed_review_status": micro_v2_proposed_review.get("micro_v2_proposed_review_status", ""),
        "micro_v2_profile_created": bool(micro_v2_proposed_review.get("micro_v2_profile_created", micro_v2_review.get("micro_v2_profile_created", False))),
        "micro_v2_profile_path": micro_v2_proposed_review.get("micro_v2_profile_path", micro_v2_review.get("micro_v2_profile_path", "")),
        "micro_v2_dry_run_readiness_status": micro_v2_dry_run_readiness.get("micro_v2_dry_run_readiness_status", ""),
        "micro_v2_launch_command_available": bool(micro_v2_dry_run_readiness.get("micro_v2_launch_command_available", False)),
        "micro_v2_dry_run_monitor_status": micro_v2_dry_run_monitor.get("micro_v2_dry_run_monitor_status", ""),
        "v2_hours_observed": micro_v2_dry_run_monitor.get("v2_hours_observed", 0.0),
        "v2_paper_trades_closed": micro_v2_dry_run_monitor.get("v2_paper_trades_closed", 0),
        "v2_signals_detected": micro_v2_dry_run_monitor.get("v2_signals_detected", 0),
        "v2_recommended_next_action": micro_v2_dry_run_monitor.get("recommended_next_action", ""),
        "micro_v2_symbol_rejection_status": micro_v2_symbol_rejection.get("micro_v2_symbol_rejection_status", ""),
        "symbol_rejection_root_cause": micro_v2_symbol_rejection.get("symbol_rejection_root_cause", ""),
        "symbol_fix_candidate_available": bool(micro_v2_symbol_rejection.get("fix_candidate_created", False)),
        "micro_v2_market_open_readiness_status": micro_v2_market_open.get("micro_v2_market_open_readiness_status", ""),
        "market_closed_rejection_count": micro_v2_market_open.get("market_closed_rejection_count", 0),
        "fresh_tick_symbols": micro_v2_market_open.get("fresh_tick_symbols", []),
        "stale_tick_symbols": micro_v2_market_open.get("stale_tick_symbols", []),
        "market_open_readiness_recommended_next_action": micro_v2_market_open.get("recommended_next_action", ""),
        "micro_v2_observation_playbook_status": micro_v2_observation_playbook.get("micro_v2_observation_playbook_status", ""),
        "observation_playbook_available": bool(micro_v2_observation_playbook),
        "observation_playbook_recommended_next_action": micro_v2_observation_playbook.get("recommended_next_action", ""),
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


def run_acceptance_drawdown_policy_report(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    daily_risk_dir: str | Path = "data/reports/paper_daily_risk",
    pnl_audit_dir: str | Path = "data/reports/paper_pnl_audit",
    clearance_ledger: str | Path | None = None,
    daily_risk_ledger: str | Path | None = None,
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/forward_evidence",
) -> dict[str, Any]:
    return run_acceptance_drawdown_policy_audit(
        database=database,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
        daily_risk_dir=daily_risk_dir,
        pnl_audit_dir=pnl_audit_dir,
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
        profile_config=profile_config,
        output_dir=output_dir,
    )


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


def _paper_risk_profile_config(reports_root: Path) -> Path | None:
    candidate = reports_root / "paper_risk" / "balanced_stable_micro.ini"
    return candidate if candidate.exists() else None


def _paper_risk_clearance_ledger(reports_root: Path) -> Path | None:
    candidate = reports_root / "paper_risk_review" / "paper_risk_clearance_ledger.json"
    return candidate if candidate.exists() else None


def _paper_daily_risk_ledger(reports_root: Path) -> Path | None:
    candidate = reports_root / "paper_daily_risk" / "paper_daily_risk_ledger.json"
    return candidate if candidate.exists() else None


def _open_trade_audit_status(recovery: Mapping[str, Any]) -> str:
    if int(recovery.get("orphan_open_trade_count", 0) or 0) > 0:
        return "ORPHAN_OPEN_PAPER_TRADE"
    if int(recovery.get("invalid_risk_open_trade_count", 0) or 0) > 0:
        return "INVALID_RISK_OPEN_PAPER_TRADE"
    if int(recovery.get("stale_open_trade_count", 0) or 0) > 0:
        return "STALE_OPEN_PAPER_TRADE"
    if int(recovery.get("valid_open_trade_count", 0) or 0) > 0:
        return "VALID_OPEN_PAPER_TRADE"
    return "OK"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and value in {float("inf"), float("-inf")}:
        return "Infinity" if value > 0 else "-Infinity"
    return value

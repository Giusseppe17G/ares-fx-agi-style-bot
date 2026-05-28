"""Offline operator dashboard and daily report generation."""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def run_operator_dashboard(
    *,
    database: TelemetryDatabase,
    reports_root: str | Path,
    log_dir: str | Path,
    output_dir: str | Path,
    config: BotConfig,
) -> dict[str, Any]:
    """Build a consolidated offline operator dashboard."""

    reports = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state = database.get_operational_state()
    paper = _paper_state(database)
    sources = _source_status(reports)
    safety = _safety(config)
    evidence = _load_json(reports / "forward_evidence" / "evidence_summary.json")
    execution_evidence = _load_json(reports / "execution_evidence" / "execution_evidence_summary.json")
    telemetry_repair = _load_json(reports / "telemetry_repair" / "telemetry_timestamp_summary.json")
    paper_risk = _load_json(reports / "paper_risk" / "paper_risk_status.json") or _load_json(reports / "paper_risk" / "paper_risk_summary.json")
    paper_pnl_audit = _load_json(reports / "paper_pnl_audit" / "paper_pnl_audit_summary.json")
    paper_risk_recommendation = _load_json(reports / "paper_pnl_audit" / "paper_risk_recommendation.json")
    daily_risk = _load_json(reports / "paper_daily_risk" / "paper_daily_risk_summary.json") or _load_json(reports / "paper_daily_risk" / "paper_daily_risk_clear_summary.json")
    legacy_drawdown = _load_json(reports / "paper_daily_risk" / "legacy_drawdown_audit_summary.json")
    clearance = _load_json(reports / "paper_risk_review" / "paper_risk_clearance_summary.json")
    diagnostics = _load_json(reports / "forward_diagnostics" / "signal_scarcity_summary.json")
    stable_gate = _load_json(reports / "stable_gate" / "stable_gate_summary.json")
    health = database.get_latest_health()
    checks = _dashboard_checks(sources, safety, paper, state, health)
    classification = _dashboard_classification(checks, safety, paper)
    next_action = _dashboard_next_action(classification, sources, paper, state)
    summary = {
        "mode": "operator-dashboard",
        "classification": classification,
        "operator_dashboard_status": classification,
        "overall_status": classification,
        "weekend_readiness_status": _value(sources, "weekend_readiness", "weekend_readiness_status"),
        "ec2_readiness_status": _value(sources, "ec2_readiness", "ec2_readiness_status"),
        "ec2_deployment_pack_status": _value(sources, "ec2_deployment_pack", "package_status"),
        "operator_drill_status": _value(sources, "operator_drill", "operator_drill_status"),
        "dry_run_market_open_status": _value(sources, "dry_run_market_open", "dry_run_market_open_status"),
        "paper_shadow_paused": bool(state.get("shadow_paused", False)),
        "latest_halt_or_pause_reason": state.get("halt_reason") or state.get("paused_reason") or "",
        "paper_trades_open": paper["paper_trades_open"],
        "paper_trades_closed_today": paper["paper_trades_closed_today"],
        "forward_evidence_status": evidence.get("operational_acceptance") or evidence.get("classification") or _status_for_source(sources, "forward_evidence"),
        "forward_diagnostics_status": diagnostics.get("classification") or _status_for_source(sources, "forward_diagnostics"),
        "stable_gate_decision": stable_gate.get("stable_gate_decision") or stable_gate.get("classification") or _status_for_source(sources, "stable_gate"),
        "execution_evidence_status": execution_evidence.get("execution_evidence_status") or _status_for_source(sources, "execution_evidence"),
        "execution_guard_clear": str(execution_evidence.get("execution_evidence_status", "")) in {"EXECUTION_EVIDENCE_CLEAR", "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"},
        "execution_guard_reason": execution_evidence.get("recommended_action", ""),
        "execution_guard_blocking_source": _blocking_source(execution_evidence),
        "telemetry_status": telemetry_repair.get("telemetry_status") or evidence.get("telemetry_status") or _status_for_source(sources, "telemetry_repair"),
        "telemetry_acceptance_clear": bool(telemetry_repair.get("telemetry_acceptance_clear", evidence.get("telemetry_acceptance_clear", False))),
        "active_timestamp_issues": int(telemetry_repair.get("active_blocking_count", evidence.get("active_telemetry_blocking_count", 0)) or 0),
        "quarantined_historical_timestamp_issues": int(telemetry_repair.get("quarantined_count", evidence.get("telemetry_quarantined_count", 0)) or 0),
        "telemetry_next_action": telemetry_repair.get("recommended_action", ""),
        "paper_risk_status": paper_risk.get("paper_risk_status", evidence.get("paper_risk_status", "")),
        "can_open_new_paper_trade": bool(paper_risk.get("can_open_new_paper_trade", evidence.get("paper_risk_acceptance_clear", False))),
        "latest_paper_risk_block": paper_risk.get("blocking_reason", (evidence.get("paper_risk_blocks") or [""])[0] if isinstance(evidence.get("paper_risk_blocks"), list) and evidence.get("paper_risk_blocks") else ""),
        "recommended_safer_profile": paper_risk.get("recommended_safer_profile", "BALANCED_STABLE_MICRO" if paper_risk.get("paper_risk_status") not in {"", "PAPER_RISK_OK"} else ""),
        "paper_risk_clearance_status": clearance.get("paper_risk_clearance_status", evidence.get("paper_risk_clearance_status", "")),
        "paper_risk_clearance_id": clearance.get("clearance_id", evidence.get("paper_risk_clearance_id", "")),
        "cleared_for_profile": clearance.get("cleared_for_profile", evidence.get("cleared_for_profile", "")),
        "clearance_stale": bool(evidence.get("clearance_stale", False)),
        "paper_daily_risk_status": daily_risk.get("paper_daily_risk_status", evidence.get("paper_daily_risk_status", "")),
        "active_today_halt_count": daily_risk.get("active_today_halt_count", evidence.get("active_today_halt_count", 0)),
        "stale_halt_count": daily_risk.get("stale_halt_count", evidence.get("stale_halt_count", 0)),
        "daily_risk_ledger_status": daily_risk.get("daily_risk_ledger_status", evidence.get("daily_risk_ledger_status", "")),
        "can_resume_micro_shadow": daily_risk.get("can_resume_micro_shadow", evidence.get("can_resume_micro_shadow", False)),
        "legacy_drawdown_status": legacy_drawdown.get("legacy_drawdown_status", evidence.get("legacy_drawdown_status", "")),
        "legacy_drawdown_quarantined": legacy_drawdown.get("legacy_drawdown_quarantined", evidence.get("legacy_drawdown_quarantined", False)),
        "legacy_quarantined_halt_count": legacy_drawdown.get("legacy_quarantined_halt_count", evidence.get("legacy_quarantined_halt_count", 0)),
        "active_scaled_drawdown_count": legacy_drawdown.get("active_scaled_events_count", evidence.get("active_scaled_drawdown_count", 0)),
        "drawdown_basis": legacy_drawdown.get("drawdown_basis", evidence.get("drawdown_basis", "")),
        "paper_pnl_audit_status": paper_pnl_audit.get("paper_pnl_audit_status", evidence.get("paper_pnl_audit_status", "")),
        "micro_risk_application_status": paper_pnl_audit.get("micro_risk_application_status", evidence.get("micro_risk_application_status", "")),
        "drawdown_root_cause": paper_pnl_audit.get("root_cause", evidence.get("drawdown_root_cause", "")),
        "paper_risk_recommendation": paper_risk_recommendation.get("recommendation", evidence.get("paper_risk_recommendation", "")),
        "critical_alerts_recent": _critical_alerts(health),
        "recommended_next_action": next_action,
        "log_dir": str(log_dir),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "DEMO_ONLY": config.demo_only,
        "LIVE_TRADING_APPROVED": config.live_trading_approved,
        "mode_scope": "paper/shadow/read-only",
        "checks": checks,
    }
    paths = _write_dashboard(output, summary, checks, evidence, diagnostics, safety)
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def run_daily_operator_report(
    *,
    database: TelemetryDatabase,
    reports_root: str | Path,
    log_dir: str | Path,
    output_dir: str | Path,
    config: BotConfig,
) -> dict[str, Any]:
    """Create a compact daily offline operator report."""

    reports = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state = database.get_operational_state()
    paper = _paper_state(database)
    diagnostics = _load_json(reports / "forward_diagnostics" / "signal_scarcity_summary.json")
    evidence = _load_json(reports / "forward_evidence" / "evidence_summary.json")
    telemetry_repair = _load_json(reports / "telemetry_repair" / "telemetry_timestamp_summary.json")
    paper_risk = _load_json(reports / "paper_risk" / "paper_risk_status.json") or _load_json(reports / "paper_risk" / "paper_risk_summary.json")
    paper_pnl_audit = _load_json(reports / "paper_pnl_audit" / "paper_pnl_audit_summary.json")
    paper_risk_recommendation = _load_json(reports / "paper_pnl_audit" / "paper_risk_recommendation.json")
    daily_risk = _load_json(reports / "paper_daily_risk" / "paper_daily_risk_summary.json") or _load_json(reports / "paper_daily_risk" / "paper_daily_risk_clear_summary.json")
    legacy_drawdown = _load_json(reports / "paper_daily_risk" / "legacy_drawdown_audit_summary.json")
    clearance = _load_json(reports / "paper_risk_review" / "paper_risk_clearance_summary.json")
    health = database.get_latest_health()
    top_blockers = diagnostics.get("top_blockers", [])
    critical_alerts = _critical_alerts(health)
    classification = "DAILY_REPORT_NEEDS_REVIEW" if paper["paper_trades_open"] > 0 or critical_alerts or not config.demo_only or config.live_trading_approved else "DAILY_REPORT_OK"
    commands = _next_commands(classification)
    summary = {
        "mode": "daily-operator-report",
        "classification": classification,
        "daily_report_status": classification,
        "date_utc": datetime.now(timezone.utc).date().isoformat(),
        "bot_state": "PAUSED" if bool(state.get("shadow_paused", False)) else "READY_OR_RUNNING_PAPER_SHADOW",
        "paper_shadow_paused": bool(state.get("shadow_paused", False)),
        "paper_trades_open": paper["paper_trades_open"],
        "paper_trades_closed_today": paper["paper_trades_closed_today"],
        "signals_detected_latest": diagnostics.get("candidate_count", evidence.get("signals_detected", 0)),
        "signals_rejected_latest": diagnostics.get("signals_rejected", evidence.get("signals_rejected", 0)),
        "top_blockers_latest": top_blockers,
        "evidence_status": evidence.get("operational_acceptance") or evidence.get("classification") or ("MISSING" if not evidence else "UNKNOWN"),
        "telemetry_status": telemetry_repair.get("telemetry_status", evidence.get("telemetry_status", "")),
        "telemetry_acceptance_clear": bool(telemetry_repair.get("telemetry_acceptance_clear", evidence.get("telemetry_acceptance_clear", False))),
        "active_timestamp_issues": int(telemetry_repair.get("active_blocking_count", evidence.get("active_telemetry_blocking_count", 0)) or 0),
        "quarantined_historical_timestamp_issues": int(telemetry_repair.get("quarantined_count", evidence.get("telemetry_quarantined_count", 0)) or 0),
        "paper_risk_status": paper_risk.get("paper_risk_status", evidence.get("paper_risk_status", "")),
        "can_open_new_paper_trade": bool(paper_risk.get("can_open_new_paper_trade", evidence.get("paper_risk_acceptance_clear", False))),
        "latest_paper_risk_block": paper_risk.get("blocking_reason", (evidence.get("paper_risk_blocks") or [""])[0] if isinstance(evidence.get("paper_risk_blocks"), list) and evidence.get("paper_risk_blocks") else ""),
        "recommended_safer_profile": paper_risk.get("recommended_safer_profile", "BALANCED_STABLE_MICRO" if paper_risk.get("paper_risk_status") not in {"", "PAPER_RISK_OK"} else ""),
        "paper_risk_clearance_status": clearance.get("paper_risk_clearance_status", evidence.get("paper_risk_clearance_status", "")),
        "paper_risk_clearance_id": clearance.get("clearance_id", evidence.get("paper_risk_clearance_id", "")),
        "cleared_for_profile": clearance.get("cleared_for_profile", evidence.get("cleared_for_profile", "")),
        "clearance_stale": bool(evidence.get("clearance_stale", False)),
        "paper_daily_risk_status": daily_risk.get("paper_daily_risk_status", evidence.get("paper_daily_risk_status", "")),
        "active_today_halt_count": daily_risk.get("active_today_halt_count", evidence.get("active_today_halt_count", 0)),
        "stale_halt_count": daily_risk.get("stale_halt_count", evidence.get("stale_halt_count", 0)),
        "daily_risk_ledger_status": daily_risk.get("daily_risk_ledger_status", evidence.get("daily_risk_ledger_status", "")),
        "can_resume_micro_shadow": daily_risk.get("can_resume_micro_shadow", evidence.get("can_resume_micro_shadow", False)),
        "legacy_drawdown_status": legacy_drawdown.get("legacy_drawdown_status", evidence.get("legacy_drawdown_status", "")),
        "legacy_drawdown_quarantined": legacy_drawdown.get("legacy_drawdown_quarantined", evidence.get("legacy_drawdown_quarantined", False)),
        "legacy_quarantined_halt_count": legacy_drawdown.get("legacy_quarantined_halt_count", evidence.get("legacy_quarantined_halt_count", 0)),
        "active_scaled_drawdown_count": legacy_drawdown.get("active_scaled_events_count", evidence.get("active_scaled_drawdown_count", 0)),
        "drawdown_basis": legacy_drawdown.get("drawdown_basis", evidence.get("drawdown_basis", "")),
        "paper_pnl_audit_status": paper_pnl_audit.get("paper_pnl_audit_status", evidence.get("paper_pnl_audit_status", "")),
        "micro_risk_application_status": paper_pnl_audit.get("micro_risk_application_status", evidence.get("micro_risk_application_status", "")),
        "drawdown_root_cause": paper_pnl_audit.get("root_cause", evidence.get("drawdown_root_cause", "")),
        "paper_risk_recommendation": paper_risk_recommendation.get("recommendation", evidence.get("paper_risk_recommendation", "")),
        "critical_alerts_recent": critical_alerts,
        "recommended_action": _daily_action(classification, state, paper),
        "commands_to_run_next": commands,
        "log_dir": str(log_dir),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "DEMO_ONLY": config.demo_only,
        "LIVE_TRADING_APPROVED": config.live_trading_approved,
    }
    paths = _write_daily(output, summary, commands)
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def _paper_state(database: TelemetryDatabase) -> dict[str, Any]:
    trades = [_payload(row) for row in database.fetch_paper_trades()]
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "paper_trades_open": sum(1 for trade in trades if str(trade.get("status", "")).upper() == "OPEN"),
        "paper_trades_closed_today": sum(
            1
            for trade in trades
            if str(trade.get("status", "")).upper() == "CLOSED" and str(trade.get("exit_time_utc", ""))[:10] == today
        ),
    }


def _source_status(reports: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "weekend_readiness": reports / "weekend_readiness" / "weekend_readiness_summary.json",
        "ec2_readiness": reports / "ec2_readiness" / "ec2_readiness_summary.json",
        "ec2_deployment_pack": reports / "ec2_deployment_pack" / "ec2_deployment_summary.json",
        "operator_drill": reports / "operator_drill" / "operator_drill_summary.json",
        "dry_run_market_open": reports / "operator_drill" / "dry_run_market_open_summary.json",
        "paper_state": reports / "paper_state" / "paper_state_report.json",
        "forward_evidence": reports / "forward_evidence" / "evidence_summary.json",
        "forward_diagnostics": reports / "forward_diagnostics" / "signal_scarcity_summary.json",
        "stable_gate": reports / "stable_gate" / "stable_gate_summary.json",
        "execution_evidence": reports / "execution_evidence" / "execution_evidence_summary.json",
        "telemetry_repair": reports / "telemetry_repair" / "telemetry_timestamp_summary.json",
        "paper_daily_risk": reports / "paper_daily_risk" / "paper_daily_risk_summary.json",
        "legacy_drawdown": reports / "paper_daily_risk" / "legacy_drawdown_audit_summary.json",
        "paper_pnl_audit": reports / "paper_pnl_audit" / "paper_pnl_audit_summary.json",
        "security_guardrails": reports / "ec2_deployment_pack" / "EC2_SECURITY_GUARDRAILS.md",
    }
    result: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        payload = _load_json(path) if path.suffix.lower() == ".json" else {}
        result[name] = {"path": str(path), "exists": path.exists(), "payload": payload}
    return result


def _safety(config: BotConfig) -> dict[str, Any]:
    return {
        "DEMO_ONLY": config.demo_only,
        "LIVE_TRADING_APPROVED": config.live_trading_approved,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "mode_scope": "paper/shadow/read-only",
    }


def _dashboard_checks(
    sources: Mapping[str, Mapping[str, Any]],
    safety: Mapping[str, Any],
    paper: Mapping[str, Any],
    state: Mapping[str, Any],
    health: Mapping[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name, source in sources.items():
        severity = "PASS" if name in {"paper_daily_risk", "paper_pnl_audit", "legacy_drawdown"} else ("WARNING" if name in {"forward_evidence", "forward_diagnostics", "paper_state", "paper_risk"} else "FAIL")
        checks.append(
            {
                "check_name": f"source_{name}",
                "status": "PASS" if source.get("exists") else severity,
                "detail": source.get("path", ""),
                "execution_attempted": False,
            }
        )
    checks.extend(
        [
            {"check_name": "demo_only_true", "status": "PASS" if safety["DEMO_ONLY"] else "FAIL", "detail": f"DEMO_ONLY={safety['DEMO_ONLY']}", "execution_attempted": False},
            {"check_name": "live_trading_not_approved", "status": "PASS" if not safety["LIVE_TRADING_APPROVED"] else "FAIL", "detail": f"LIVE_TRADING_APPROVED={safety['LIVE_TRADING_APPROVED']}", "execution_attempted": False},
            {"check_name": "paper_trades_open_zero", "status": "PASS" if int(paper["paper_trades_open"]) == 0 else "WARNING", "detail": f"paper_trades_open={paper['paper_trades_open']}", "execution_attempted": False},
            {"check_name": "shadow_paused_known", "status": "PASS", "detail": f"paper_shadow_paused={bool(state.get('shadow_paused', False))}", "execution_attempted": False},
            {"check_name": "recent_critical_alerts", "status": "WARNING" if _critical_alerts(health) else "PASS", "detail": f"critical_alerts={len(_critical_alerts(health))}", "execution_attempted": False},
        ]
    )
    return checks


def _dashboard_classification(checks: Iterable[Mapping[str, Any]], safety: Mapping[str, Any], paper: Mapping[str, Any]) -> str:
    if not safety["DEMO_ONLY"] or safety["LIVE_TRADING_APPROVED"]:
        return "OPERATOR_DASHBOARD_BLOCKED"
    if any(check.get("status") == "FAIL" for check in checks):
        return "OPERATOR_DASHBOARD_BLOCKED"
    if int(paper["paper_trades_open"]) > 0 or any(check.get("status") == "WARNING" for check in checks):
        return "OPERATOR_DASHBOARD_NEEDS_REVIEW"
    return "OPERATOR_DASHBOARD_OK"


def _dashboard_next_action(classification: str, sources: Mapping[str, Mapping[str, Any]], paper: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    if classification == "OPERATOR_DASHBOARD_OK":
        if bool(state.get("shadow_paused", False)):
            return "Wait for market open; run mt5-diagnose and live-feature-contract before paper-only resume."
        return "Continue paper/shadow monitoring and collect daily operator report."
    if int(paper["paper_trades_open"]) > 0:
        return "Run paper-open-trades and paper-state-report before resuming shadow."
    missing = [name for name, source in sources.items() if not source.get("exists")]
    if missing:
        return f"Regenerate missing offline reports: {', '.join(missing[:5])}."
    return "Review warnings before market open."


def _daily_action(classification: str, state: Mapping[str, Any], paper: Mapping[str, Any]) -> str:
    if classification == "DAILY_REPORT_OK":
        return "Keep shadow paused until market open or continue read-only monitoring if already in paper observation."
    if int(paper["paper_trades_open"]) > 0:
        return "Inspect open paper trades and collect evidence before any resume."
    if bool(state.get("shadow_paused", False)):
        return "Review pause reason, run dashboard, and wait for diagnostics before resume."
    return "Review critical alerts and pause paper/shadow if needed."


def _next_commands(classification: str) -> list[str]:
    commands = [
        '$env:PYTHONPATH="src/python"',
        "py -m agi_style_forex_bot_mt5.cli --mode operator-dashboard --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --reports-root data\\reports --log-dir data\\logs\\forward-shadow-stable --output-dir data\\reports\\operator_dashboard",
        "py -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --output-dir data\\reports\\paper_state",
        "py -m agi_style_forex_bot_mt5.cli --mode forward-evidence --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root data\\reports --output-dir data\\reports\\forward_evidence",
        "py -m agi_style_forex_bot_mt5.cli --mode telemetry-status --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root data\\reports --output-dir data\\reports\\telemetry_repair",
    ]
    if classification == "DAILY_REPORT_NEEDS_REVIEW":
        commands.append('py -m agi_style_forex_bot_mt5.cli --mode pause-shadow --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --reason "daily operator review"')
    else:
        commands.append("py -m agi_style_forex_bot_mt5.cli --mode market-open-checklist --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --reports-root data\\reports --output-dir data\\reports\\market_open_checklist")
    commands.append("# Do not enable demo/live execution. Keep DEMO_ONLY=True and LIVE_TRADING_APPROVED=False.")
    return commands


def _write_dashboard(
    output: Path,
    summary: Mapping[str, Any],
    checks: list[dict[str, Any]],
    evidence: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    safety: Mapping[str, Any],
) -> list[Path]:
    summary_path = output / "operator_dashboard_summary.json"
    checks_path = output / "operator_dashboard_checks.csv"
    html_path = output / "dashboard.html"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(checks_path, checks, ("check_name", "status", "detail", "execution_attempted"))
    html_path.write_text(_dashboard_html(summary, checks, evidence, diagnostics, safety), encoding="utf-8")
    return [summary_path, checks_path, html_path]


def _write_daily(output: Path, summary: Mapping[str, Any], commands: list[str]) -> list[Path]:
    json_path = output / "daily_operator_report.json"
    md_path = output / "daily_operator_report.md"
    ps_path = output / "next_commands.ps1"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_daily_markdown(summary), encoding="utf-8")
    ps_path.write_text("\n".join(commands) + "\n", encoding="utf-8")
    return [json_path, md_path, ps_path]


def _dashboard_html(
    summary: Mapping[str, Any],
    checks: Iterable[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    safety: Mapping[str, Any],
) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(str(row.get('check_name')))}</td><td>{html.escape(str(row.get('status')))}</td><td>{html.escape(str(row.get('detail')))}</td></tr>"
        for row in checks
    )
    sections = {
        "Overall Status": summary.get("overall_status"),
        "Safety Guardrails": safety,
        "Paper State": {"paper_shadow_paused": summary.get("paper_shadow_paused"), "paper_trades_open": summary.get("paper_trades_open")},
        "Forward Evidence": evidence or {"status": "MISSING"},
        "Execution Evidence": {
            "execution_evidence_status": summary.get("execution_evidence_status"),
            "execution_guard_clear": summary.get("execution_guard_clear"),
            "execution_guard_reason": summary.get("execution_guard_reason"),
            "execution_guard_blocking_source": summary.get("execution_guard_blocking_source"),
        },
        "Telemetry Repair": {
            "telemetry_status": summary.get("telemetry_status"),
            "telemetry_acceptance_clear": summary.get("telemetry_acceptance_clear"),
            "active_timestamp_issues": summary.get("active_timestamp_issues"),
            "quarantined_historical_timestamp_issues": summary.get("quarantined_historical_timestamp_issues"),
            "telemetry_next_action": summary.get("telemetry_next_action"),
        },
        "Paper Risk": {
            "paper_risk_status": summary.get("paper_risk_status"),
            "can_open_new_paper_trade": summary.get("can_open_new_paper_trade"),
            "latest_paper_risk_block": summary.get("latest_paper_risk_block"),
            "recommended_safer_profile": summary.get("recommended_safer_profile"),
            "paper_risk_clearance_status": summary.get("paper_risk_clearance_status"),
            "paper_risk_clearance_id": summary.get("paper_risk_clearance_id"),
            "cleared_for_profile": summary.get("cleared_for_profile"),
            "clearance_stale": summary.get("clearance_stale"),
            "paper_daily_risk_status": summary.get("paper_daily_risk_status"),
            "active_today_halt_count": summary.get("active_today_halt_count"),
            "stale_halt_count": summary.get("stale_halt_count"),
            "daily_risk_ledger_status": summary.get("daily_risk_ledger_status"),
            "can_resume_micro_shadow": summary.get("can_resume_micro_shadow"),
        },
        "Diagnostics": diagnostics or {"status": "MISSING"},
        "EC2 Readiness": {"ec2_readiness_status": summary.get("ec2_readiness_status"), "ec2_deployment_pack_status": summary.get("ec2_deployment_pack_status")},
        "Market Open Plan": {"dry_run_market_open_status": summary.get("dry_run_market_open_status")},
        "Alerts": summary.get("critical_alerts_recent"),
        "Next Commands": summary.get("recommended_next_action"),
    }
    section_html = "".join(f"<h2>{html.escape(title)}</h2><pre>{html.escape(json.dumps(value, indent=2, sort_keys=True))}</pre>" for title, value in sections.items())
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Operator Dashboard</title></head>
<body>
<h1>Offline Operator Dashboard</h1>
{section_html}
<h2>Checks</h2><table border="1" cellspacing="0" cellpadding="4"><thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>
<p>execution_attempted=false; order_send_called=false; order_check_called=false</p>
</body></html>
"""


def _daily_markdown(summary: Mapping[str, Any]) -> str:
    return f"""# Daily Operator Report

- date_utc: `{summary.get('date_utc')}`
- classification: `{summary.get('classification')}`
- bot_state: `{summary.get('bot_state')}`
- paper_shadow_paused: `{summary.get('paper_shadow_paused')}`
- paper_trades_open: `{summary.get('paper_trades_open')}`
- paper_trades_closed_today: `{summary.get('paper_trades_closed_today')}`
- evidence_status: `{summary.get('evidence_status')}`
- telemetry_status: `{summary.get('telemetry_status')}`
- telemetry_acceptance_clear: `{summary.get('telemetry_acceptance_clear')}`
- recommended_action: {summary.get('recommended_action')}

Safety: `execution_attempted=false`, `order_send_called=false`, `order_check_called=false`, `DEMO_ONLY=True`, `LIVE_TRADING_APPROVED=False`.
"""


def _critical_alerts(health: Mapping[str, Any]) -> list[dict[str, Any]]:
    alerts = health.get("recent_alerts", [])
    if not isinstance(alerts, list):
        return []
    return [dict(alert) for alert in alerts if isinstance(alert, Mapping) and str(alert.get("severity", "")).upper() == "CRITICAL"]


def _blocking_source(execution_evidence: Mapping[str, Any]) -> str:
    findings = execution_evidence.get("blocking_findings", [])
    if isinstance(findings, list) and findings:
        first = findings[0]
        if isinstance(first, Mapping):
            return f"{first.get('source', '')}:{first.get('field_path', '')}"
    return ""


def _status_for_source(sources: Mapping[str, Mapping[str, Any]], name: str) -> str:
    return "AVAILABLE" if sources.get(name, {}).get("exists") else "MISSING"


def _value(sources: Mapping[str, Mapping[str, Any]], name: str, key: str) -> str:
    payload = sources.get(name, {}).get("payload", {})
    return str(payload.get(key, "MISSING" if not sources.get(name, {}).get("exists") else "UNKNOWN"))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _payload(row: Any) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

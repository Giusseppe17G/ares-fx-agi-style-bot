"""Report orchestration for paper risk manual review and clearance."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .clearance_ledger import append_clearance, clearance_is_stale, latest_clearance, load_clearance_ledger
from .drawdown_halt_loader import load_drawdown_halt_context
from .manual_review_gate import decide_manual_review
from .profile_matching import effective_requested_profile, normalize_profile_name


def run_paper_risk_review(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    output_dir: str | Path = "data/reports/paper_risk_review",
) -> dict[str, Any]:
    """Write paper risk manual review reports."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    context = load_drawdown_halt_context(database=database, log_dir=log_dir, reports_root=reports_root, paper_risk_dir=paper_risk_dir)
    decision = decide_manual_review(context)
    summary = {
        "mode": "paper-risk-review",
        **decision,
        "latest_halt_utc": context.get("latest_halt_utc", ""),
        "paper_trades_open": context.get("paper_trades_open", 0),
        "paper_trades_closed": context.get("paper_trades_closed", 0),
        "daily_paper_drawdown": context.get("daily_paper_drawdown", 0.0),
        "worst_paper_pnl": context.get("worst_paper_pnl", 0.0),
        "paper_state_clean": context.get("paper_state_clean", False),
        "execution_evidence_clear": context.get("execution_evidence_clear", False),
        "telemetry_clear": context.get("telemetry_clear", False),
        "micro_profile_exists": context.get("micro_profile_exists", False),
        "stable_gate_exists": context.get("stable_gate_exists", False),
        "stable_gate_ready": context.get("stable_gate_ready", False),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_review_reports(output, summary, context)
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def run_paper_risk_clearance(
    *,
    database: TelemetryDatabase,
    reason: str,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    output_dir: str | Path = "data/reports/paper_risk_review",
) -> dict[str, Any]:
    """Grant a ledger-only clearance if all manual review gates pass."""

    if not str(reason or "").strip():
        return _clearance_denied("PAPER_RISK_CLEARANCE_DENIED_NO_REASON", "paper-risk-clearance requires --reason")
    review = run_paper_risk_review(database=database, log_dir=log_dir, reports_root=reports_root, paper_risk_dir=paper_risk_dir, output_dir=output_dir)
    mapping = {
        "PAPER_RISK_REVIEW_BLOCKED_OPEN_TRADES": "PAPER_RISK_CLEARANCE_DENIED_OPEN_TRADES",
        "PAPER_RISK_REVIEW_BLOCKED_EXECUTION_EVIDENCE": "PAPER_RISK_CLEARANCE_DENIED_EXECUTION_EVIDENCE",
        "PAPER_RISK_REVIEW_BLOCKED_TELEMETRY": "PAPER_RISK_CLEARANCE_DENIED_TELEMETRY",
        "PAPER_RISK_REVIEW_BLOCKED_NO_MICRO_PROFILE": "PAPER_RISK_CLEARANCE_DENIED_NO_MICRO_PROFILE",
        "PAPER_RISK_REVIEW_REQUIRED": "PAPER_RISK_CLEARANCE_DENIED_REVIEW_REQUIRED",
    }
    if review.get("classification") != "PAPER_RISK_REVIEW_READY_FOR_CLEARANCE":
        return _clearance_denied(mapping.get(str(review.get("classification")), "PAPER_RISK_CLEARANCE_DENIED_REVIEW_REQUIRED"), str(review.get("reason", "")), review)
    entry = append_clearance(output_dir=output_dir, reason=reason, latest_halt_utc=str(review.get("latest_halt_utc", "")))
    summary = {
        "mode": "paper-risk-clearance",
        "classification": "PAPER_RISK_CLEARANCE_GRANTED",
        "paper_risk_clearance_status": "PAPER_RISK_CLEARANCE_GRANTED",
        "clearance_id": entry["clearance_id"],
        "ledger_path": entry["ledger_path"],
        "cleared_for_profile": entry.get("cleared_for_profile", "BALANCED_STABLE_MICRO"),
        "canonical_cleared_for_profile": entry.get("canonical_cleared_for_profile", "BALANCED_STABLE_MICRO"),
        "cleared_for_paper_shadow": True,
        "not_for_demo_live": True,
        "reason": reason,
        "latest_halt_utc": review.get("latest_halt_utc", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = Path(output_dir) / "paper_risk_clearance_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path), entry["ledger_path"]]
    return summary


def run_paper_risk_clearance_check(
    *,
    profile: str = "",
    profile_config: str | Path | None = None,
    clearance_ledger: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_risk_review",
) -> dict[str, Any]:
    """Check whether a paper risk clearance ledger matches a requested profile."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    requested = effective_requested_profile(profile, profile_config)
    ledger = load_clearance_ledger(clearance_ledger)
    clearance = latest_clearance(ledger)
    cleared = normalize_profile_name(clearance.get("canonical_cleared_for_profile") or clearance.get("cleared_for_profile"))
    requested_canonical = str(requested.get("requested_profile_canonical", ""))
    latest_halt = str(clearance.get("latest_halt_utc_at_clearance") or clearance.get("latest_halt_utc") or "")
    stale = clearance_is_stale(clearance, latest_halt) if clearance else True
    mismatch_reason = ""
    if not clearance:
        mismatch_reason = "PAPER_RISK_CLEARANCE_REQUIRED"
    elif requested_canonical != "BALANCED_STABLE_MICRO":
        mismatch_reason = "REQUESTED_PROFILE_NOT_MICRO"
    elif cleared != requested_canonical:
        mismatch_reason = "PAPER_RISK_CLEARANCE_PROFILE_MISMATCH"
    elif stale:
        mismatch_reason = "PAPER_RISK_CLEARANCE_STALE"
    summary = {
        "mode": "paper-risk-clearance-check",
        "clearance_match": bool(clearance) and not stale and not mismatch_reason,
        "requested_profile": requested.get("requested_profile", ""),
        "requested_profile_canonical": requested_canonical,
        "cleared_for_profile": clearance.get("cleared_for_profile", "") if clearance else "",
        "cleared_for_profile_canonical": cleared,
        "clearance_stale": stale,
        "mismatch_reason": mismatch_reason,
        "profile_config_profile": requested.get("profile_config_profile", ""),
        "profile_config_profile_canonical": requested.get("profile_config_profile_canonical", ""),
        "profile_warnings": requested.get("profile_warnings", []),
        "clearance_id": clearance.get("clearance_id", "") if clearance else "",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_risk_clearance_check.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def _write_review_reports(output: Path, summary: Mapping[str, Any], context: Mapping[str, Any]) -> list[Path]:
    summary_path = output / "paper_risk_review_summary.json"
    events_path = output / "drawdown_halt_events.csv"
    requirements_path = output / "review_requirements.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(events_path, list(context.get("halt_events", [])))
    _write_csv(requirements_path, _requirements(summary))
    html_path.write_text(_html(summary), encoding="utf-8")
    return [summary_path, events_path, requirements_path, html_path]


def _clearance_denied(classification: str, reason: str, review: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "mode": "paper-risk-clearance",
        "classification": classification,
        "paper_risk_clearance_status": classification,
        "reason": reason,
        "review": dict(review or {}),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _requirements(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"requirement": "open_paper_trades_zero", "passed": int(summary.get("paper_trades_open", 0) or 0) == 0},
        {"requirement": "execution_evidence_clear", "passed": bool(summary.get("execution_evidence_clear", False))},
        {"requirement": "telemetry_clear", "passed": bool(summary.get("telemetry_clear", False))},
        {"requirement": "micro_profile_exists", "passed": bool(summary.get("micro_profile_exists", False))},
        {"requirement": "stable_gate_ready", "passed": bool(summary.get("stable_gate_ready", False))},
    ]


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    keys = sorted({key for row in rows for key in row.keys()} | {"execution_attempted"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key == "execution_attempted" else "") for key in keys})


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Paper Risk Manual Review</h1><pre>{html.escape(json.dumps(summary, indent=2, sort_keys=True))}</pre></body></html>"

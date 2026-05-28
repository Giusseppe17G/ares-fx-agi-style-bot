"""Forward acceptance drawdown policy aligned with legacy quarantine."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.paper_daily_risk_state import run_paper_legacy_drawdown_audit
from agi_style_forex_bot_mt5.paper_risk_calibration import run_paper_risk_status
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def evaluate_acceptance_drawdown_policy(
    *,
    metrics: Mapping[str, Any],
    evidence: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    paper_risk: Mapping[str, Any] | None = None,
    legacy_drawdown: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return whether drawdown evidence should block forward acceptance."""

    evidence = evidence or {}
    telemetry_summary = telemetry_summary or {}
    paper_risk = paper_risk or {}
    legacy_drawdown = legacy_drawdown or {}
    legacy_status = str(legacy_drawdown.get("legacy_drawdown_status") or paper_risk.get("legacy_drawdown_status") or "")
    legacy_quarantined = bool(legacy_drawdown.get("legacy_drawdown_quarantined", paper_risk.get("legacy_drawdown_quarantined", False)))
    active_scaled = int(legacy_drawdown.get("active_scaled_events_count", paper_risk.get("active_scaled_drawdown_count", 0)) or 0)
    paper_risk_status = str(paper_risk.get("paper_risk_status") or "")
    blocking_reason = str(paper_risk.get("blocking_reason") or "")
    telemetry_clear = bool(telemetry_summary.get("telemetry_acceptance_clear", False))
    drawdown_status = str(metrics.get("paper_drawdown_status") or "")
    open_trades = int(evidence.get("open_paper_trades", paper_risk.get("current_open_paper_trades", 0)) or 0)
    max_open = int(paper_risk.get("max_open_paper_trades", 10) or 10)

    active_scaled_block = active_scaled > 0 or legacy_status == "ACTIVE_SCALED_DRAWDOWN_BLOCK"
    if active_scaled_block:
        return _policy(
            "ACTIVE_SCALED_DRAWDOWN_BLOCK",
            True,
            "Active scaled paper drawdown halt exists after the ledger.",
            metrics,
            paper_risk,
            legacy_drawdown,
            telemetry_clear,
            open_trades,
        )
    if "PAPER_DRAWDOWN_HALT" in blocking_reason and not legacy_quarantined:
        return _policy(
            "ACTIVE_DRAWDOWN_HALT_BLOCK",
            True,
            "Paper risk reports an active drawdown halt that is not quarantined legacy evidence.",
            metrics,
            paper_risk,
            legacy_drawdown,
            telemetry_clear,
            open_trades,
        )
    legacy_not_blocking = (
        drawdown_status == "PAPER_DAILY_DRAWDOWN"
        and telemetry_clear
        and legacy_status == "LEGACY_DRAWDOWN_QUARANTINED"
        and legacy_quarantined
        and active_scaled == 0
        and (paper_risk_status == "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW" or "PAPER_DRAWDOWN_HALT" not in blocking_reason)
        and open_trades <= max_open
    )
    if legacy_not_blocking:
        return _policy(
            "LEGACY_DRAWDOWN_NOT_BLOCKING",
            False,
            "Paper drawdown halt is legacy/quarantined; no active scaled drawdown event is present.",
            metrics,
            paper_risk,
            legacy_drawdown,
            telemetry_clear,
            open_trades,
        )
    if drawdown_status == "PAPER_DAILY_DRAWDOWN":
        return _policy(
            "ACTIVE_DRAWDOWN_HALT_BLOCK",
            True,
            "Paper daily drawdown halt is active.",
            metrics,
            paper_risk,
            legacy_drawdown,
            telemetry_clear,
            open_trades,
        )
    return _policy(
        "DRAWDOWN_POLICY_CLEAR",
        False,
        "No active paper drawdown halt blocks forward acceptance.",
        metrics,
        paper_risk,
        legacy_drawdown,
        telemetry_clear,
        open_trades,
    )


def run_acceptance_drawdown_policy_audit(
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
    """Write an auditable acceptance drawdown policy report."""

    from .evidence_collector import collect_forward_evidence
    from .forward_metrics import calculate_forward_metrics

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence = collect_forward_evidence(database=database, log_dir=log_dir, reports_root=reports_root)
    metrics = calculate_forward_metrics(
        database=database,
        hours_observed=float(evidence.get("hours_observed", 0.0) or 0.0),
        signals_detected=int(evidence.get("signals_detected", 0) or 0),
        signals_rejected=int(evidence.get("signals_rejected", 0) or 0),
    )
    legacy = run_paper_legacy_drawdown_audit(
        database=database,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
        pnl_audit_dir=pnl_audit_dir,
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
        profile_config=profile_config,
        output_dir=daily_risk_dir,
    )
    paper_risk = run_paper_risk_status(
        database=database,
        profile_config=profile_config,
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
        output_dir=paper_risk_dir,
    )
    policy = evaluate_acceptance_drawdown_policy(
        metrics=metrics,
        evidence=evidence,
        telemetry_summary={"telemetry_acceptance_clear": True},
        paper_risk=paper_risk,
        legacy_drawdown=legacy,
    )
    summary = {
        "mode": "acceptance-drawdown-policy-audit",
        "acceptance_drawdown_policy_status": policy.get("acceptance_drawdown_policy_status"),
        "legacy_drawdown_quarantined": policy.get("legacy_drawdown_quarantined", False),
        "active_scaled_drawdown_count": policy.get("active_scaled_drawdown_count", 0),
        "acceptance_drawdown_blocking": policy.get("acceptance_drawdown_blocking", False),
        "acceptance_blocking_reason": policy.get("acceptance_blocking_reason", ""),
        "recommended_action": "Run forward-acceptance again." if not policy.get("acceptance_drawdown_blocking") else "Keep forward-shadow paused and review active scaled drawdown.",
        **{key: value for key, value in policy.items() if key not in {"mode", "execution_attempted", "order_send_called", "order_check_called"}},
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    _write_policy_reports(output, summary)
    return summary


def _policy(
    status: str,
    blocking: bool,
    reason: str,
    metrics: Mapping[str, Any],
    paper_risk: Mapping[str, Any],
    legacy_drawdown: Mapping[str, Any],
    telemetry_clear: bool,
    open_trades: int,
) -> dict[str, Any]:
    return {
        "acceptance_drawdown_policy_status": status,
        "paper_daily_risk_status": paper_risk.get("paper_daily_risk_status", ""),
        "legacy_drawdown_status": legacy_drawdown.get("legacy_drawdown_status", paper_risk.get("legacy_drawdown_status", "")),
        "legacy_drawdown_quarantined": bool(legacy_drawdown.get("legacy_drawdown_quarantined", paper_risk.get("legacy_drawdown_quarantined", False))),
        "active_scaled_drawdown_count": int(legacy_drawdown.get("active_scaled_events_count", paper_risk.get("active_scaled_drawdown_count", 0)) or 0),
        "drawdown_basis": legacy_drawdown.get("drawdown_basis", paper_risk.get("drawdown_basis", "")),
        "daily_risk_ledger_status": paper_risk.get("daily_risk_ledger_status", ""),
        "paper_risk_status": paper_risk.get("paper_risk_status", ""),
        "paper_drawdown_status": metrics.get("paper_drawdown_status", ""),
        "telemetry_acceptance_clear": telemetry_clear,
        "paper_trades_open": open_trades,
        "acceptance_drawdown_blocking": blocking,
        "acceptance_blocking_reason": reason if blocking else "",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _write_policy_reports(output: Path, summary: Mapping[str, Any]) -> None:
    (output / "acceptance_drawdown_policy_summary.json").write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    rows = [summary]
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with (output / "acceptance_drawdown_policy_events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    (output / "acceptance_drawdown_policy_report.html").write_text(
        f"<html><body><h1>Acceptance Drawdown Policy</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>",
        encoding="utf-8",
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

"""Classify legacy/unscaled paper drawdown halts without deleting evidence."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.paper_risk_review.clearance_ledger import latest_clearance, load_clearance_ledger
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime

from .daily_risk_ledger import latest_daily_risk_clearance, load_daily_risk_ledger
from .drawdown_state_loader import load_drawdown_state


ACTIVE = "ACTIVE_SCALED_CURRENT_EVENT"
LEGACY_BEFORE_FIX = "LEGACY_UNSCALED_BEFORE_PNL_FIX"
LEGACY_BEFORE_LEDGER = "LEGACY_BEFORE_DAILY_RISK_LEDGER"
LEGACY_BEFORE_CLEARANCE = "LEGACY_BEFORE_CLEARANCE"
INVALID_LEGACY = "INVALID_TIMESTAMP_LEGACY"
UNKNOWN = "UNKNOWN_REVIEW_REQUIRED"
QUARANTINED = "LEGACY_DRAWDOWN_QUARANTINED"


def classify_legacy_drawdown_events(
    *,
    halt_events: list[Mapping[str, Any]],
    clearance_ledger: str | Path | None = None,
    daily_risk_ledger: str | Path | None = None,
    pnl_audit_dir: str | Path | None = None,
    profile_clearance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify halts relative to post-fix cutoff and scaled PnL readiness."""

    profile_clearance_payload = dict(profile_clearance or latest_clearance(load_clearance_ledger(clearance_ledger)))
    daily_clearance = latest_daily_risk_clearance(load_daily_risk_ledger(daily_risk_ledger))
    pnl_dir = Path(pnl_audit_dir) if pnl_audit_dir else Path("data/reports/paper_pnl_audit")
    scaling = _load_json(pnl_dir / "paper_pnl_scaling_check.json")
    audit = _load_json(pnl_dir / "paper_pnl_audit_summary.json")
    scaling_status = str(scaling.get("paper_pnl_scaling_status") or "").upper()
    scaling_ready = scaling_status in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"} or bool(audit.get("current_engine_multiplier_ready", False))
    cutoff = _max_dt(
        profile_clearance_payload.get("created_at_utc"),
        daily_clearance.get("created_at_utc"),
        audit.get("post_fix_utc"),
        scaling.get("created_at_utc"),
    )
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(halt_events):
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else event
        parsed = safe_parse_datetime(event.get("timestamp_utc") or payload.get("timestamp_utc"), field_name="timestamp_utc", source=str(event.get("source", "legacy_drawdown")))
        classification = UNKNOWN
        reason = ""
        if parsed.value is None:
            classification = INVALID_LEGACY
            reason = "timestamp invalid or redacted"
        elif cutoff is not None and parsed.value <= cutoff:
            classification = LEGACY_BEFORE_LEDGER if daily_clearance else LEGACY_BEFORE_CLEARANCE
            reason = "halt is at or before post-fix clearance cutoff"
        elif _is_legacy_event(event, payload) and scaling_ready:
            classification = LEGACY_BEFORE_FIX
            reason = "halt/event lacks scaled paper PnL basis"
        elif scaling_ready and _is_scaled_event(event, payload):
            classification = ACTIVE
            reason = "halt is after cutoff and uses scaled paper PnL basis"
        elif not scaling_ready and parsed.value is not None and cutoff is not None and parsed.value > cutoff:
            classification = ACTIVE
            reason = "scaling is not ready, so post-cutoff halt remains active"
        elif scaling_ready:
            classification = UNKNOWN
            reason = "post-cutoff halt lacks scaled/legacy markers"
        row = {
            "event_index": index,
            "source": event.get("source", ""),
            "halt_code": event.get("halt_code") or payload.get("alert_code") or payload.get("event_type") or payload.get("halt_reason") or "",
            "timestamp_utc": parsed.value.isoformat() if parsed.value else str(event.get("timestamp_utc") or payload.get("timestamp_utc") or ""),
            "classification": classification,
            "reason": reason,
            "drawdown_basis": payload.get("drawdown_basis") or payload.get("basis") or "",
            "scaled_drawdown": payload.get("scaled_drawdown", payload.get("scaled_paper_pnl", "")),
            "raw_drawdown": payload.get("raw_drawdown", payload.get("raw_pnl", "")),
            "execution_attempted": False,
        }
        rows.append(row)
    active = [row for row in rows if row["classification"] == ACTIVE]
    legacy = [row for row in rows if row["classification"] in {LEGACY_BEFORE_FIX, LEGACY_BEFORE_LEDGER, LEGACY_BEFORE_CLEARANCE, INVALID_LEGACY}]
    unknown = [row for row in rows if row["classification"] == UNKNOWN]
    invalid = [row for row in rows if row["classification"] == INVALID_LEGACY]
    legacy_quarantined = bool(legacy and not active and not unknown and scaling_ready and daily_clearance)
    status = "NO_DRAWDOWN_EVENTS"
    if active:
        status = "ACTIVE_SCALED_DRAWDOWN_BLOCK"
    elif unknown:
        status = "LEGACY_DRAWDOWN_REVIEW_REQUIRED"
    elif legacy_quarantined:
        status = QUARANTINED
    elif rows:
        status = "LEGACY_DRAWDOWN_AUDIT_INCONCLUSIVE"
    return {
        "legacy_drawdown_status": status,
        "events": rows,
        "legacy_events_count": len(legacy),
        "legacy_quarantined_halt_count": len(legacy) if legacy_quarantined else 0,
        "active_scaled_events_count": len(active),
        "invalid_timestamp_halt_count": len(invalid),
        "unknown_review_required_count": len(unknown),
        "legacy_drawdown_quarantined": legacy_quarantined,
        "can_resume_micro_shadow": legacy_quarantined or status == "NO_DRAWDOWN_EVENTS",
        "drawdown_basis": "SCALED_PAPER_PNL_ONLY",
        "cutoff_utc": cutoff.isoformat() if cutoff else "",
        "paper_pnl_scaling_status": scaling_status,
        "current_engine_multiplier_ready": scaling_ready,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def run_paper_legacy_drawdown_audit(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    pnl_audit_dir: str | Path = "data/reports/paper_pnl_audit",
    clearance_ledger: str | Path | None = None,
    daily_risk_ledger: str | Path | None = None,
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_daily_risk",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state = load_drawdown_state(database=database, log_dir=log_dir, reports_root=reports_root, paper_risk_dir=paper_risk_dir, clearance_ledger=clearance_ledger, profile_config=profile_config)
    classified = classify_legacy_drawdown_events(
        halt_events=list(state.get("halt_events", [])),
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
        pnl_audit_dir=pnl_audit_dir,
        profile_clearance=state.get("profile_clearance", {}),
    )
    summary = {
        "mode": "paper-legacy-drawdown-audit",
        **{key: value for key, value in classified.items() if key != "events"},
        "recommended_action": _recommended_action(classified),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, list(classified.get("events", [])))
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def _is_legacy_event(event: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    basis = str(payload.get("drawdown_basis") or event.get("drawdown_basis") or "").upper()
    if basis in {"LEGACY_UNSCALED_PNL", "RAW_PNL", "UNSCALED_PNL"}:
        return True
    if payload.get("legacy_unscaled_events") is True or payload.get("legacy_unscaled_trade_count", 0):
        return True
    if not basis and not _is_scaled_event(event, payload):
        return True
    return False


def _is_scaled_event(event: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    basis = str(payload.get("drawdown_basis") or event.get("drawdown_basis") or "").upper()
    if basis in {"SCALED_PAPER_PNL", "SCALED_PAPER_PNL_ONLY"}:
        return True
    return any(key in payload for key in ("scaled_drawdown", "scaled_paper_pnl")) or any(key in event for key in ("scaled_drawdown", "scaled_paper_pnl"))


def _max_dt(*values: Any):
    parsed = [safe_parse_datetime(value, field_name="cutoff", source="legacy_drawdown").value for value in values if value]
    parsed = [value for value in parsed if value is not None]
    return max(parsed) if parsed else None


def _recommended_action(summary: Mapping[str, Any]) -> str:
    if summary.get("legacy_drawdown_status") == QUARANTINED:
        return "Resume BALANCED_STABLE_MICRO only with clearance, daily risk ledger, and paper PnL scaling active."
    if summary.get("legacy_drawdown_status") == "ACTIVE_SCALED_DRAWDOWN_BLOCK":
        return "Keep BALANCED_STABLE_MICRO blocked; a scaled drawdown halt exists after the ledger."
    if summary.get("legacy_drawdown_status") == "NO_DRAWDOWN_EVENTS":
        return "No drawdown halt evidence found; continue normal paper risk checks."
    return "Review legacy drawdown evidence before resuming micro shadow."


def _write_reports(output: Path, summary: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> list[Path]:
    summary_path = output / "legacy_drawdown_audit_summary.json"
    legacy_path = output / "legacy_drawdown_events.csv"
    active_path = output / "active_scaled_drawdown_events.csv"
    html_path = output / "legacy_drawdown_report.html"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(legacy_path, [row for row in rows if str(row.get("classification", "")).startswith("LEGACY") or str(row.get("classification")) == INVALID_LEGACY])
    _write_csv(active_path, [row for row in rows if row.get("classification") == ACTIVE])
    html_path.write_text(f"<html><body><h1>Legacy Drawdown Audit</h1><pre>{html.escape(json.dumps(summary, indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return [summary_path, legacy_path, active_path, html_path]


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    keys = sorted({key for row in rows for key in row.keys()} | {"execution_attempted"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key == "execution_attempted" else "") for key in keys})


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

"""Load paper drawdown halt context without mutating evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


HALT_CODES = {"PAPER_DAILY_DRAWDOWN", "PAPER_DAILY_DRAWDOWN_HALT", "PAPER_SHADOW_HALTED"}


def load_drawdown_halt_context(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
) -> dict[str, Any]:
    """Return the current manual-review context for paper drawdown halts."""

    reports = Path(reports_root)
    paper_risk = Path(paper_risk_dir)
    paper_state = _load_json(reports / "paper_state" / "paper_state_report.json")
    risk_summary = _load_json(paper_risk / "paper_risk_summary.json")
    evidence = _load_json(reports / "forward_evidence" / "evidence_summary.json")
    execution = _load_json(reports / "execution_evidence" / "execution_evidence_summary.json")
    telemetry = _load_json(reports / "telemetry_repair" / "telemetry_timestamp_summary.json")
    trades = [_payload(row) for row in database.fetch_paper_trades()]
    open_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "OPEN"]
    closed_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"]
    halt_events = _load_halt_events(database=database, log_dir=Path(log_dir), risk_summary=risk_summary)
    latest = _latest_halt(halt_events)
    stable_gate = _load_json(reports / "stable_gate" / "stable_gate_summary.json")
    micro_profile = paper_risk / "balanced_stable_micro.ini"
    return {
        "latest_halt": latest,
        "latest_halt_utc": latest.get("timestamp_utc", ""),
        "halt_events": halt_events,
        "paper_trades_open": len(open_trades),
        "paper_trades_closed": len(closed_trades),
        "daily_paper_drawdown": paper_state.get("paper_drawdown", risk_summary.get("max_paper_drawdown", 0.0)),
        "worst_paper_pnl": risk_summary.get("worst_paper_pnl", 0.0),
        "symbols_causing_drawdown": risk_summary.get("symbols_causing_drawdown", []),
        "strategies_causing_drawdown": risk_summary.get("strategies_causing_drawdown", []),
        "paper_state_clean": len(open_trades) == 0 and int(paper_state.get("paper_trades_open", 0) or 0) == 0,
        "execution_evidence_clear": _execution_clear(execution),
        "execution_evidence_status": execution.get("execution_evidence_status", ""),
        "telemetry_clear": _telemetry_clear(telemetry),
        "telemetry_status": telemetry.get("telemetry_status", ""),
        "micro_profile_exists": micro_profile.exists(),
        "micro_profile_path": str(micro_profile),
        "stable_gate_exists": (reports / "stable_gate" / "stable_gate_summary.json").exists(),
        "stable_gate_ready": stable_gate.get("stable_gate_decision") == "PAPER_SHADOW_READY" and stable_gate.get("paper_shadow_ready") is True,
        "forward_evidence_status": evidence.get("operational_acceptance", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _load_halt_events(*, database: TelemetryDatabase, log_dir: Path, risk_summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in database.fetch_all("alerts"):
        payload = _payload(row)
        code = str(payload.get("alert_code") or row["alert_code"] or "").upper()
        if code in HALT_CODES:
            events.append(_halt_row("sqlite_alert", code, payload.get("timestamp_utc") or row["timestamp_utc"], payload))
    state = database.get_operational_state()
    paused_reason = str(state.get("paused_reason") or state.get("halt_reason") or "").upper()
    if paused_reason in HALT_CODES:
        events.append(_halt_row("operational_state", paused_reason, state.get("paused_at_utc") or state.get("updated_at_utc"), state))
    if log_dir.exists():
        for path in log_dir.glob("*.jsonl"):
            for item in _read_jsonl(path):
                code = str(item.get("alert_code") or item.get("event_type") or item.get("halt_reason") or "").upper()
                payload = item.get("payload")
                if isinstance(payload, Mapping):
                    code = str(payload.get("alert_code") or payload.get("event_type") or payload.get("halt_reason") or code).upper()
                if code in HALT_CODES:
                    events.append(_halt_row(str(path), code, item.get("timestamp_utc") or (payload or {}).get("timestamp_utc") if isinstance(payload, Mapping) else "", item))
    for item in risk_summary.get("drawdown_events", []) if isinstance(risk_summary.get("drawdown_events"), list) else []:
        code = str(item.get("alert_code") or item.get("event_type") or item.get("halt_reason") or "").upper()
        if code in HALT_CODES:
            events.append(_halt_row("paper_risk_summary", code, item.get("timestamp_utc"), item))
    return sorted(events, key=lambda row: row.get("timestamp_utc") or "")


def _latest_halt(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    dated = [event for event in events if event.get("timestamp_utc")]
    return dict(dated[-1] if dated else (events[-1] if events else {}))


def _halt_row(source: str, code: str, timestamp: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    parsed = safe_parse_datetime(timestamp, field_name="timestamp_utc", source=source)
    return {
        "source": source,
        "halt_code": code,
        "timestamp_utc": parsed.value.isoformat() if parsed.value is not None else str(timestamp or ""),
        "timestamp_parse_status": parsed.status,
        "payload": dict(payload),
        "execution_attempted": False,
    }


def _execution_clear(summary: Mapping[str, Any]) -> bool:
    status = str(summary.get("execution_evidence_status", "")).upper()
    return status in {"EXECUTION_EVIDENCE_CLEAR", "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"} and int(summary.get("blocking_findings_count", 0) or 0) == 0


def _telemetry_clear(summary: Mapping[str, Any]) -> bool:
    status = str(summary.get("telemetry_status", "")).upper()
    return bool(summary.get("telemetry_acceptance_clear", False)) or status in {"TELEMETRY_CLEAN", "TELEMETRY_HISTORICAL_QUARANTINED"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    except (OSError, json.JSONDecodeError):
        pass
    return rows


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        try:
            return dict(row)
        except Exception:
            return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

"""CLI status and health helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.observability.metrics_collector import MetricsCollector
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def build_status(database: TelemetryDatabase) -> dict[str, Any]:
    metrics = MetricsCollector(database).collect()
    state = database.get_operational_state()
    latest = database.get_latest_health()
    return {
        "mode": "status",
        "shadow_paused": bool(state.get("shadow_paused", False)),
        "paper_shadow_paused": bool(state.get("shadow_paused", False)),
        "halt_reason": state.get("halt_reason") or state.get("paused_reason") or "",
        "daily_drawdown_status": "PAPER_DAILY_DRAWDOWN" if float(metrics.get("drawdown_paper", 0.0) or 0.0) <= -3.0 else "OK",
        "evidence_parse_status": _load_evidence_parse_status(),
        "all_symbols_rejected_count": 1 if int(metrics.get("symbols_seen", 0) or 0) > 0 and int(metrics.get("symbols_rejected", 0) or 0) >= int(metrics.get("symbols_seen", 0) or 0) else 0,
        "symbol_rejection_error_count": sum(1 for reason in metrics.get("rejected_signals_by_reason", {}) if "arg must be" in str(reason)),
        "latest_exit_reason": state.get("latest_exit_reason", ""),
        "next_recommended_command": _next_command(state, metrics),
        "last_heartbeat_utc": latest.get("last_heartbeat_utc"),
        "metrics": metrics,
        "execution_attempted": False,
    }


def build_health_status(database: TelemetryDatabase, *, log_dir: str | Path | None = None) -> dict[str, Any]:
    latest = database.get_latest_health()
    log_status = "UNKNOWN"
    if log_dir is not None:
        log_status = "OK" if any(Path(log_dir).rglob("*.jsonl")) else "WARNING"
    return {
        "mode": "health",
        "status": "OK" if latest.get("last_heartbeat_utc") else "WARNING",
        "latest_health": latest,
        "paper_shadow_paused": bool(database.get_operational_state().get("shadow_paused", False)),
        "halt_reason": database.get_operational_state().get("halt_reason") or database.get_operational_state().get("paused_reason") or "",
        "evidence_parse_status": _load_evidence_parse_status(),
        "sqlite_status": "OK",
        "jsonl_status": log_status,
        "execution_attempted": False,
    }


def _load_evidence_parse_status() -> str:
    path = Path("data/reports/forward_evidence/evidence_summary.json")
    if not path.exists():
        return ""
    try:
        import json

        return str(json.loads(path.read_text(encoding="utf-8")).get("evidence_parse_status", ""))
    except Exception:
        return "UNKNOWN"


def _next_command(state: dict[str, Any], metrics: dict[str, Any]) -> str:
    if bool(state.get("shadow_paused", False)) or float(metrics.get("drawdown_paper", 0.0) or 0.0) <= -3.0:
        return "py -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --output-dir data\\reports\\paper_state"
    return ""

"""Stable forward-shadow reporting and health helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .forward_stable_drift_detector import detect_stable_forward_drift
from .paper_performance import group_metrics, paper_metrics


def write_stable_shadow_daily_report(
    *,
    database: TelemetryDatabase,
    report_dir: str | Path = "data/reports/forward_shadow_stable/daily",
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write BALANCED_STABLE daily paper-shadow reports from SQLite."""

    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = [_payload(row) for row in database.fetch_paper_trades()]
    stable_rows = [row for row in rows if _is_stable(row)]
    frame = pd.DataFrame(stable_rows)
    metrics = paper_metrics(stable_rows)
    drift = detect_stable_forward_drift(forward=metrics, baseline=dict(baseline or _load_json(Path("data/reports/robustness/robustness_summary.json"))))
    paths = {
        "summary": output / "daily_summary.json",
        "trades": output / "trades.csv",
        "open": output / "open_trades.csv",
        "closed": output / "closed_trades.csv",
        "by_symbol": output / "by_symbol.csv",
        "by_strategy": output / "by_strategy.csv",
        "by_session": output / "by_session.csv",
        "by_regime": output / "by_regime.csv",
        "drift": output / "drift.json",
        "html": output / "report.html",
    }
    summary = {
        "mode": "stable-daily-summary",
        "profile": "BALANCED_STABLE",
        **metrics,
        "stable_drift_status": drift.get("classification"),
        "execution_attempted": False,
    }
    _write_json(paths["summary"], summary)
    _write_json(paths["drift"], drift)
    frame.to_csv(paths["trades"], index=False)
    _filter_status(frame, "OPEN").to_csv(paths["open"], index=False)
    _filter_status(frame, "CLOSED").to_csv(paths["closed"], index=False)
    group_metrics(stable_rows, "symbol").to_csv(paths["by_symbol"], index=False)
    group_metrics(stable_rows, "strategy_name").to_csv(paths["by_strategy"], index=False)
    group_metrics(stable_rows, "session").to_csv(paths["by_session"], index=False)
    group_metrics(stable_rows, "regime").to_csv(paths["by_regime"], index=False)
    paths["html"].write_text(f"<html><body><h1>BALANCED_STABLE Daily Summary</h1><pre>{json.dumps(summary, indent=2)}</pre></body></html>", encoding="utf-8")
    return {**summary, "drift": drift, "reports_created": [str(path) for path in paths.values()]}


def build_stable_health(
    *,
    database: TelemetryDatabase,
    stable_gate_path: str | Path = "data/reports/stable_gate/stable_gate_summary.json",
) -> dict[str, Any]:
    """Return a read-only stable forward-shadow health summary."""

    gate = _load_json(Path(stable_gate_path))
    health = database.get_latest_health()
    trades = [_payload(row) for row in database.fetch_paper_trades()]
    stable_rows = [row for row in trades if _is_stable(row)]
    metrics = paper_metrics(stable_rows)
    drift = _load_json(Path("data/reports/forward_shadow_stable/daily/drift.json"))
    drift_status = str(drift.get("classification") or drift.get("stable_drift_status") or "NEEDS_MORE_DATA")
    status = "OK"
    blockers: list[str] = []
    if not Path(database.path).exists():
        status = "FAILED"
        blockers.append("SQLITE_MISSING")
    if gate.get("stable_gate_decision") != "PAPER_SHADOW_READY" or gate.get("paper_shadow_ready") is not True:
        status = "FAILED"
        blockers.append("STABLE_GATE_NOT_READY")
    if not health.get("last_heartbeat_utc"):
        status = "WARNING" if status == "OK" else status
        blockers.append("NO_HEARTBEAT")
    if bool(health.get("shadow_paused", False)):
        status = "WARNING" if status == "OK" else status
        blockers.append("STABLE_SHADOW_PAUSED")
    if drift_status in {"CRITICAL_DRIFT", "PAUSE_STABLE_SHADOW"}:
        status = "CRITICAL"
        blockers.append("STABLE_DRIFT_CRITICAL")
    return {
        "mode": "stable-health",
        "status": status,
        "sqlite_exists": Path(database.path).exists(),
        "last_heartbeat_utc": health.get("last_heartbeat_utc"),
        "mt5_connected": bool(health.get("mt5_connected", False)),
        "stable_gate_confirmed": gate.get("stable_gate_decision") == "PAPER_SHADOW_READY",
        "paper_shadow_ready": gate.get("paper_shadow_ready") is True,
        "stable_shadow_paused": bool(health.get("shadow_paused", False)),
        "stable_open_paper_trades": metrics.get("open_trades", 0),
        "stable_closed_paper_trades_today": metrics.get("closed_trades", 0),
        "stable_drift_status": drift_status,
        "blockers": blockers,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _is_stable(row: Mapping[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    return str(metadata.get("profile") or metadata.get("signal_profile_used") or row.get("profile") or "").upper() == "BALANCED_STABLE"


def _filter_status(frame: pd.DataFrame, status: str) -> pd.DataFrame:
    if frame.empty or "status" not in frame.columns:
        return pd.DataFrame()
    return frame[frame["status"].astype(str).str.upper() == status].copy()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

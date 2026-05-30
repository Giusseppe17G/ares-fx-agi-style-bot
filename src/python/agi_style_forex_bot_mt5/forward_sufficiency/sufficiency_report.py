"""Forward data sufficiency audit report orchestration."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .blocker_funnel import build_blocker_funnel
from .observation_window import calculate_observation_window
from .profile_throttle_audit import audit_profile_throttle
from .rejection_funnel import REJECTION_EVENTS, build_rejection_funnel
from .symbol_activity_audit import audit_symbol_activity
from .trade_frequency_audit import audit_trade_frequency


SIGNAL_EVENTS = {
    "SIGNAL_DETECTED",
    "SIGNAL_ACCEPTED",
    "SIGNAL_REJECTED",
    "RISK_REJECTED",
    "SYMBOL_REJECTED",
    "STALE_TICK_REJECTION",
    "MARKET_CLOSED_REJECTION",
    "FUTURE_SIGNAL_REJECTION",
    "INVALID_MARKET_SNAPSHOT_REJECTION",
    "STRATEGY_BLOCKED_BY_CONTEXT",
    "FORWARD_CANDIDATE_EVALUATED",
    "FORWARD_CANDIDATE_BLOCKED",
    "FORWARD_NEAR_MISS",
    "PAPER_TRADE_OPENED",
}


def run_forward_sufficiency_audit(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/forward_sufficiency",
) -> dict[str, Any]:
    """Build offline diagnostics for forward observation sufficiency."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    events = _load_events(database)
    heartbeats = _load_heartbeats(database)
    paper_trades = _load_paper_trades(database)
    window = calculate_observation_window([*events, *heartbeats, *paper_trades])
    signals_detected = _signals_detected(events, paper_trades)
    signals_rejected = sum(1 for event in events if str(event.get("event_type", "")) in REJECTION_EVENTS)
    trade_frequency = audit_trade_frequency(
        hours_observed=float(window.get("hours_observed", 0.0) or 0.0),
        paper_trades=paper_trades,
        signals_detected=signals_detected,
        signals_rejected=signals_rejected,
    )
    rejection_rows, rejection_summary = build_rejection_funnel(events)
    blocker_rows, blocker_summary = build_blocker_funnel(events)
    symbol_rows, symbol_summary = audit_symbol_activity(events, paper_trades)
    throttle = audit_profile_throttle(events)
    status, action = _classify(window, trade_frequency, throttle, rejection_summary)
    summary = {
        "mode": "forward-sufficiency-audit",
        "forward_sufficiency_status": status,
        **window,
        **trade_frequency,
        **symbol_summary,
        "top_rejection_reasons": rejection_summary.get("top_rejection_reasons", []),
        "top_blocking_reasons": blocker_summary.get("top_blocking_reasons", []),
        **throttle,
        "recommended_next_action": action,
        "reports_root": str(reports_root),
        "log_dir": str(log_dir),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, window, trade_frequency, rejection_rows, blocker_rows, symbol_rows, throttle)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _load_events(database: TelemetryDatabase) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in database.fetch_all("events"):
        payload = _loads(row["payload_json"])
        rows.append(
            {
                "source": "sqlite:events",
                "event_type": row["event_type"],
                "symbol": row["symbol"],
                "timestamp_utc": row["timestamp_utc"],
                "severity": row["severity"],
                "message": row["message"],
                "payload": payload,
            }
        )
    return rows


def _load_heartbeats(database: TelemetryDatabase) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in database.fetch_all("heartbeats"):
        payload = _loads(row["payload_json"])
        rows.append(
            {
                "source": "sqlite:heartbeats",
                "event_type": "HEARTBEAT",
                "timestamp_utc": row["timestamp_utc"],
                "symbol": "",
                "payload": payload,
            }
        )
    return rows


def _load_paper_trades(database: TelemetryDatabase) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for row in database.fetch_paper_trades():
        payload = _loads(row["payload_json"])
        trades.append(
            {
                **payload,
                "source": "sqlite:paper_trades",
                "paper_trade_id": payload.get("paper_trade_id") or row["paper_trade_id"],
                "symbol": payload.get("symbol") or row["symbol"],
                "status": payload.get("status") or row["status"],
                "opened_at_utc": payload.get("entry_time_utc") or row["opened_at_utc"],
                "closed_at_utc": payload.get("exit_time_utc") or row["closed_at_utc"],
            }
        )
    return trades


def _signals_detected(events: list[Mapping[str, Any]], paper_trades: list[Mapping[str, Any]]) -> int:
    count = 0
    for event in events:
        event_type = str(event.get("event_type", ""))
        if event_type in SIGNAL_EVENTS or event_type in REJECTION_EVENTS:
            count += 1
    return max(count, len(paper_trades))


def _classify(
    window: Mapping[str, Any],
    frequency: Mapping[str, Any],
    throttle: Mapping[str, Any],
    rejection_summary: Mapping[str, Any],
) -> tuple[str, str]:
    hours = float(window.get("hours_observed", 0.0) or 0.0)
    closed = int(frequency.get("closed_paper_trades", 0) or 0)
    signals = int(frequency.get("signals_detected", 0) or 0)
    rejection_rate = float(frequency.get("rejection_rate", 0.0) or 0.0)
    estimated = frequency.get("estimated_hours_to_acceptance")
    data_quality = int(throttle.get("data_quality_block_count", 0) or 0)
    risk_blocks = int(throttle.get("paper_risk_block_count", 0) or 0) + int(throttle.get("cooldown_block_count", 0) or 0)
    session_blocks = int(throttle.get("session_block_count", 0) or 0)
    if hours <= 0 and signals == 0 and closed == 0:
        return "INSUFFICIENT_FORWARD_DATA", "KEEP_RUNNING_FORWARD_SHADOW"
    if data_quality > 0 and data_quality >= max(2, signals // 2):
        return "DATA_QUALITY_LIMITING", "REVIEW_DATA_QUALITY_FEEDS"
    if risk_blocks > 0 and risk_blocks >= max(2, signals // 2):
        return "RISK_GATES_LIMITING", "DO_NOT_CHANGE_RUNTIME_YET"
    if session_blocks > 0 and session_blocks >= max(2, signals // 2):
        return "SESSION_LIMITING", "REVIEW_SESSION_WINDOWS_OFFLINE"
    if signals >= 5 and rejection_rate >= 0.8:
        return "FILTERS_TOO_RESTRICTIVE", _filter_action(rejection_summary)
    if hours < 24 and closed >= 10:
        return "NEEDS_MORE_TIME_ONLY", "WAIT_FOR_24H"
    if hours >= 24 and closed < 10:
        return "NEEDS_MORE_TRADES_ONLY", "WAIT_FOR_MORE_CLOSED_TRADES"
    if hours >= 4 and closed == 0:
        return "LOW_TRADE_FREQUENCY", "REVIEW_FILTER_STRICTNESS_OFFLINE"
    if estimated is not None and float(estimated) > 48:
        return "LOW_TRADE_FREQUENCY", "REVIEW_FILTER_STRICTNESS_OFFLINE"
    if hours >= 24 and closed >= 10:
        return "SUFFICIENCY_ON_TRACK", "KEEP_RUNNING_FORWARD_SHADOW"
    return "SUFFICIENCY_ON_TRACK", "KEEP_RUNNING_FORWARD_SHADOW"


def _filter_action(rejection_summary: Mapping[str, Any]) -> str:
    reasons = json.dumps(rejection_summary.get("top_rejection_reasons", [])).upper()
    if "SPREAD" in reasons or "COST" in reasons:
        return "REVIEW_DATA_QUALITY_FEEDS"
    if "SESSION" in reasons:
        return "REVIEW_SESSION_WINDOWS_OFFLINE"
    if "SCORE" in reasons or "ENSEMBLE" in reasons:
        return "REVIEW_SIGNAL_SCORE_THRESHOLDS_OFFLINE"
    return "REVIEW_FILTER_STRICTNESS_OFFLINE"


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    window: Mapping[str, Any],
    trade_frequency: Mapping[str, Any],
    rejection_rows: list[Mapping[str, Any]],
    blocker_rows: list[Mapping[str, Any]],
    symbol_rows: list[Mapping[str, Any]],
    throttle: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "forward_sufficiency_summary.json",
        output / "observation_window.json",
        output / "trade_frequency_audit.json",
        output / "rejection_funnel.csv",
        output / "blocker_funnel.csv",
        output / "symbol_activity.csv",
        output / "profile_throttle_audit.json",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], window)
    _write_json(paths[2], trade_frequency)
    _write_csv(paths[3], rejection_rows)
    _write_csv(paths[4], blocker_rows)
    _write_csv(paths[5], symbol_rows)
    _write_json(paths[6], throttle)
    paths[7].write_text(_recommendations_markdown(summary), encoding="utf-8")
    paths[8].write_text(
        f"<html><body><h1>Forward Sufficiency Audit</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>",
        encoding="utf-8",
    )
    return paths


def _recommendations_markdown(summary: Mapping[str, Any]) -> str:
    return f"""# Forward Sufficiency Audit

Status: `{summary.get('forward_sufficiency_status')}`

Hours observed: `{summary.get('hours_observed')}` of `{summary.get('required_hours')}`

Closed paper trades: `{summary.get('closed_paper_trades')}` of `{summary.get('required_closed_paper_trades')}`

Estimated hours to acceptance: `{summary.get('estimated_hours_to_acceptance')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This report is offline/read-only. It does not authorize demo/live execution, does not pause or resume forward-shadow, and does not bypass forward-acceptance gates.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

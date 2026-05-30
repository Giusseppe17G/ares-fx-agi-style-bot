"""Report orchestration for Micro V2 market-open fresh tick readiness."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .fresh_tick_audit import audit_fresh_ticks
from .market_closed_audit import audit_market_closed
from .market_tick_loader import load_market_open_inputs
from .mt5_connection_audit import audit_mt5_connection
from .v2_runtime_state_audit import audit_v2_runtime_state


def run_micro_v2_market_open_readiness(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    rejection_labeling_dir: str | Path = "data/reports/rejection_labeling_audit",
    monitor_dir: str | Path = "data/reports/micro_v2_dry_run_monitor",
    output_dir: str | Path = "data/reports/micro_v2_market_open_readiness",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_market_open_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        rejection_labeling_dir=rejection_labeling_dir,
        monitor_dir=monitor_dir,
    )
    dataset = inputs["dataset"]
    tick_rows, tick_summary = audit_fresh_ticks(dataset)
    closed = audit_market_closed(dataset, inputs["rejection_labeling"])
    mt5 = audit_mt5_connection(dataset)
    runtime = audit_v2_runtime_state(dataset, inputs["monitor"])
    status, action = _classify(runtime, mt5, tick_summary, closed)
    summary = {
        "mode": "micro-v2-market-open-readiness",
        "micro_v2_market_open_readiness_status": status,
        "last_heartbeat_utc": runtime.get("last_heartbeat_utc"),
        "v2_runtime_active": runtime.get("v2_runtime_active", False),
        "mt5_connected": mt5.get("mt5_connected", False),
        "symbols_configured": _configured_symbols(inputs["profile"], tick_summary),
        "signals_detected": runtime.get("signals_detected", 0),
        "signals_rejected": runtime.get("signals_rejected", 0),
        "paper_trades_open": runtime.get("paper_trades_open", 0),
        "paper_trades_closed": runtime.get("paper_trades_closed", 0),
        "fresh_tick_symbols": tick_summary.get("fresh_tick_symbols", []),
        "stale_tick_symbols": tick_summary.get("stale_tick_symbols", []),
        "market_closed_symbols": tick_summary.get("market_closed_symbols", []),
        "market_closed_rejection_count": closed.get("market_closed_rejection_count", 0),
        "stale_tick_rejection_count": closed.get("stale_tick_rejection_count", 0),
        "future_signal_rejection_count": closed.get("future_signal_rejection_count", 0),
        "invalid_market_snapshot_rejection_count": closed.get("invalid_market_snapshot_rejection_count", 0),
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, tick_rows, tick_summary, closed, mt5, runtime)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _classify(runtime: Mapping[str, Any], mt5: Mapping[str, Any], ticks: Mapping[str, Any], closed: Mapping[str, Any]) -> tuple[str, str]:
    if runtime.get("execution_attempted_detected") or runtime.get("order_send_detected") or runtime.get("order_check_detected"):
        return "MICRO_V2_SAFETY_BLOCKED", "STOP_AND_REVIEW_EXECUTION_SAFETY_EVIDENCE"
    if not runtime.get("heartbeat_recent", False):
        return "MICRO_V2_RUNTIME_NOT_RUNNING", "VERIFY_V2_DRY_RUN_TERMINAL_AND_HEARTBEAT"
    if not mt5.get("mt5_connected", False):
        return "MICRO_V2_MT5_DISCONNECTED", "RESTORE_MT5_CONNECTION_FOR_PAPER_OBSERVATION"
    if ticks.get("fresh_tick_symbols"):
        return "MICRO_V2_MARKET_OPEN_TICKS_FRESH", "CONTINUE_V2_PAPER_OBSERVATION"
    if int(closed.get("market_closed_rejection_count", 0) or 0) > 0 and closed.get("market_closed_rejection_dominant", False):
        return "MICRO_V2_WAITING_FOR_MARKET_OPEN", "WAIT_FOR_MARKET_OPEN_AND_FRESH_TICKS"
    if int(closed.get("stale_tick_rejection_count", 0) or 0) > 0 or ticks.get("stale_tick_symbols"):
        return "MICRO_V2_MARKET_OPEN_BUT_TICKS_STALE", "KEEP_V2_RUNNING_AND_RECHECK_TICK_FRESHNESS"
    return "MICRO_V2_REQUIRES_MANUAL_REVIEW", "REVIEW_V2_MARKET_DATA_AND_REJECTION_LABELING"


def _configured_symbols(profile: Mapping[str, Any], ticks: Mapping[str, Any]) -> list[str]:
    for key in ("ALLOWED_SYMBOLS", "SYMBOLS", "SYMBOL_UNIVERSE", "ENABLED_SYMBOLS"):
        raw = str(profile.get(key, "")).strip()
        if raw:
            return [item.strip().upper() for item in raw.split(",") if item.strip()]
    return sorted(set(ticks.get("symbols_with_tick_evidence", [])))


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    tick_rows: list[Mapping[str, Any]],
    tick_summary: Mapping[str, Any],
    closed: Mapping[str, Any],
    mt5: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_market_open_readiness_summary.json",
        output / "fresh_tick_audit.json",
        output / "market_closed_audit.json",
        output / "mt5_connection_audit.json",
        output / "v2_runtime_state.json",
        output / "symbol_tick_freshness.csv",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], tick_summary)
    _write_json(paths[2], closed)
    _write_json(paths[3], mt5)
    _write_json(paths[4], runtime)
    _write_csv(paths[5], tick_rows)
    paths[6].write_text(_recommendations(summary), encoding="utf-8")
    paths[7].write_text(f"<html><body><h1>Micro V2 Market Open Readiness</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Market Open Readiness

Status: `{summary.get('micro_v2_market_open_readiness_status')}`

MT5 connected: `{summary.get('mt5_connected')}`

V2 runtime active: `{summary.get('v2_runtime_active')}`

Fresh tick symbols: `{', '.join(summary.get('fresh_tick_symbols', []))}`

Recommended next action: `{summary.get('recommended_next_action')}`

This audit is offline/read-only. It does not execute trades, pause/resume shadow, or authorize demo/live execution.
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


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

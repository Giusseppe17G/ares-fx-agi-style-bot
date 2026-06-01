"""Report orchestration for Micro V2 invalid trade forensics."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .invalid_trade_identifier import identify_invalid_open_trades
from .invalid_trade_loader import load_invalid_trade_inputs
from .repair_plan_builder import build_repair_plan
from .risk_distance_forensics import analyze_risk_distance
from .root_cause_classifier import classify_root_cause
from .sl_tp_forensics import analyze_sl_tp


def run_micro_v2_invalid_trade_forensics(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    lifecycle_dir: str | Path = "data/reports/micro_v2_lifecycle_risk_comparison",
    stable_window_dir: str | Path = "data/reports/micro_v2_stable_market_window",
    checkpoint_dir: str | Path = "data/reports/micro_v2_observation_checkpoint",
    output_dir: str | Path = "data/reports/micro_v2_invalid_trade_forensics",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_invalid_trade_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        lifecycle_dir=lifecycle_dir,
        stable_window_dir=stable_window_dir,
        checkpoint_dir=checkpoint_dir,
    )
    invalid = identify_invalid_open_trades(inputs)
    risk = analyze_risk_distance(invalid["invalid_open_trades"])
    sl_tp = analyze_sl_tp(invalid["invalid_open_trades"])
    root = classify_root_cause(invalid["invalid_open_trades"], risk, sl_tp, inputs)
    repair = build_repair_plan(root, invalid)
    status = _status(inputs, invalid, root, repair)
    summary = {
        "mode": "micro-v2-invalid-trade-forensics",
        "invalid_trade_forensics_status": status,
        "invalid_trade_count": invalid.get("invalid_open_trade_count", 0),
        "invalid_trade_ids": invalid.get("invalid_trade_ids", []),
        "affected_symbols": invalid.get("affected_symbols", []),
        "root_cause": root.get("root_cause", ""),
        "root_cause_deterministic": root.get("root_cause_deterministic", False),
        "repair_plan_available": repair.get("repair_plan_available", False),
        "repair_action_recommended": repair.get("repair_action_recommended", ""),
        "repair_plan_applied": False,
        "recommended_next_action": _next_action(status, repair),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, invalid, root, risk, sl_tp, repair)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _status(inputs: Mapping[str, Any], invalid: Mapping[str, Any], root: Mapping[str, Any], repair: Mapping[str, Any]) -> str:
    if _safety(inputs.get("v2_dataset", {})):
        return "MICRO_V2_INVALID_TRADE_SAFETY_BLOCKED"
    if invalid.get("invalid_open_trade_count", 0) == 0:
        return "MICRO_V2_INVALID_TRADE_NO_INVALID_TRADES_FOUND"
    if _data_missing(invalid.get("invalid_open_trades", [])):
        return "MICRO_V2_INVALID_TRADE_DATA_MISSING"
    if root.get("root_cause") == "UNKNOWN_REQUIRES_MANUAL_REVIEW":
        return "MICRO_V2_INVALID_TRADE_REQUIRES_MANUAL_REVIEW"
    if repair.get("repair_plan_available"):
        return "MICRO_V2_INVALID_TRADE_REPAIR_PLAN_READY"
    return "MICRO_V2_INVALID_TRADE_ROOT_CAUSE_IDENTIFIED"


def _data_missing(trades: list[Mapping[str, Any]]) -> bool:
    for trade in trades:
        if not trade.get("trade_id") and not trade.get("paper_trade_id"):
            return True
        if not trade.get("symbol"):
            return True
        if trade.get("entry_price") in {None, ""}:
            return True
    return False


def _safety(dataset: Mapping[str, Any]) -> bool:
    for group in ("events", "heartbeats", "paper_trades"):
        for row in dataset.get(group, []):
            payload = row.get("payload", {}) if isinstance(row.get("payload"), Mapping) else {}
            if row.get("execution_attempted") or row.get("order_send_called") or row.get("order_check_called"):
                return True
            if payload.get("execution_attempted") or payload.get("order_send_called") or payload.get("order_check_called"):
                return True
    return False


def _next_action(status: str, repair: Mapping[str, Any]) -> str:
    if status == "MICRO_V2_INVALID_TRADE_REPAIR_PLAN_READY":
        return "PREPARE_FASE_65_GUARDED_PAPER_STATE_REPAIR"
    if status == "MICRO_V2_INVALID_TRADE_REQUIRES_MANUAL_REVIEW":
        return "DO_NOT_MODIFY_SQLITE_REVIEW_INVALID_OPEN_TRADES_CSV"
    if status == "MICRO_V2_INVALID_TRADE_NO_INVALID_TRADES_FOUND":
        return "RERUN_MICRO_V2_LIFECYCLE_RISK_COMPARISON"
    if status == "MICRO_V2_INVALID_TRADE_SAFETY_BLOCKED":
        return "STOP_AND_REVIEW_EXECUTION_SAFETY_EVIDENCE"
    return str(repair.get("repair_action_recommended") or "REVIEW_INVALID_TRADE_FORENSICS")


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    invalid: Mapping[str, Any],
    root: Mapping[str, Any],
    risk: Mapping[str, Any],
    sl_tp: Mapping[str, Any],
    repair: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_invalid_trade_forensics_summary.json",
        output / "invalid_open_trades.csv",
        output / "invalid_trade_root_cause.json",
        output / "risk_distance_forensics.json",
        output / "sl_tp_forensics.json",
        output / "repair_plan.json",
        output / "repair_plan.md",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], invalid.get("invalid_open_trades", []))
    _write_json(paths[2], root)
    _write_json(paths[3], risk)
    _write_json(paths[4], sl_tp)
    _write_json(paths[5], repair)
    paths[6].write_text(_repair_plan_md(repair), encoding="utf-8")
    paths[7].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[8].write_text(_recommendations(summary), encoding="utf-8")
    paths[9].write_text(_html(summary), encoding="utf-8")
    return paths


def _repair_plan_md(repair: Mapping[str, Any]) -> str:
    return f"""# Guarded Repair Plan

Action: `{repair.get('repair_action_recommended')}`

NOT_APPLIED=true
PAPER_ONLY=true
REQUIRES_BACKUP=true
REQUIRES_RUNTIME_STOP=true
REQUIRES_EXPLICIT_NEXT_PHASE=true
APPROVED_FOR_RUNTIME=false
APPROVED_FOR_DEMO=false
APPROVED_FOR_LIVE=false
"""


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    return f"""# Recommended Commands

Status: `{summary.get('invalid_trade_forensics_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

Do not modify SQLite in this phase. Any repair requires a later explicit guarded paper-state repair phase.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Invalid Trade Forensics

Root cause: `{summary.get('root_cause')}`

Repair plan available: `{summary.get('repair_plan_available')}`

Repair plan applied: `false`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Invalid Trade Forensics</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


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

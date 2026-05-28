"""Root-cause audit for forward-shadow CONFIG_ERROR states."""

from __future__ import annotations

import configparser
import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

ROOT_CAUSE_FIXES = {
    "MISSING_PROFILE_CONFIG": ("RERUN_WITH_CORRECT_ARGS", "Pass --profile-config data\\reports\\paper_risk\\balanced_stable_micro.ini."),
    "MISSING_STABLE_GATE": ("RERUN_WITH_CORRECT_ARGS", "Pass --stable-gate data\\reports\\stable_gate\\stable_gate_summary.json."),
    "MISSING_CLEARANCE_LEDGER": ("REGENERATE_CLEARANCE_LEDGER", "Run paper-risk-clearance after manual review, then rerun forward-shadow with --paper-risk-clearance/--clearance-ledger."),
    "MISSING_DAILY_RISK_LEDGER": ("REGENERATE_DAILY_RISK_LEDGER", "Run paper-daily-risk-clear, then rerun forward-shadow with --daily-risk-ledger."),
    "INVALID_PROFILE_CONFIG_SCHEMA": ("REBUILD_PROFILE_CONFIG", "Rebuild balanced_stable_micro.ini from build-paper-risk-profile."),
    "INVALID_STABLE_GATE_SCHEMA": ("REBUILD_STABLE_GATE", "Rerun stable-robustness-gate and verify paper_shadow_ready=true."),
    "INVALID_CLEARANCE_LEDGER_SCHEMA": ("REGENERATE_CLEARANCE_LEDGER", "Regenerate the paper risk clearance ledger."),
    "INVALID_DAILY_RISK_LEDGER_SCHEMA": ("REGENERATE_DAILY_RISK_LEDGER", "Regenerate the daily paper risk ledger."),
    "PROFILE_MISMATCH": ("RERUN_WITH_CORRECT_ARGS", "Use BALANCED_STABLE_MICRO with data\\reports\\paper_risk\\balanced_stable_micro.ini."),
    "STABLE_GATE_NOT_ACCEPTED": ("REBUILD_STABLE_GATE", "Rerun stable-robustness-gate; stable_gate_decision must be PAPER_SHADOW_READY."),
    "PAPER_RISK_NOT_ACCEPTED": ("REGENERATE_CLEARANCE_LEDGER", "Create a valid paper-risk-clearance for BALANCED_STABLE_MICRO."),
    "DAILY_RISK_LEDGER_NOT_ACCEPTED": ("REGENERATE_DAILY_RISK_LEDGER", "Create a valid paper-daily-risk-clear ledger for BALANCED_STABLE_MICRO."),
    "MISSING_REQUIRED_FORWARD_SHADOW_ARG": ("RERUN_WITH_CORRECT_ARGS", "Rerun forward-shadow with profile-config, stable-gate, paper-risk-clearance and daily-risk-ledger."),
    "INVALID_SYMBOLS_ARG": ("RERUN_WITH_CORRECT_ARGS", "Use a comma-separated --symbols list such as EURUSD,GBPUSD,USDJPY."),
    "INVALID_SIGNAL_PROFILE": ("RERUN_WITH_CORRECT_ARGS", "Use --signal-profile BALANCED_STABLE_MICRO for the micro paper/shadow run."),
    "CONFIG_PARSE_EXCEPTION": ("FIX_SCHEMA", "Repair the config file that raised the parser exception."),
    "RUNTIME_CONFIG_PATH_ERROR": ("RERUN_WITH_CORRECT_ARGS", "Fix the runtime path shown in source_file_or_log."),
    "FORWARD_SHADOW_CONFIG_EXCEPTION": ("MANUAL_REVIEW_REQUIRED", "Inspect the exact forward-shadow exception and repair the paper state/config source before rerun."),
    "RESOLVED_INVALID_OPEN_PAPER_TRADE": ("RERUN_WITH_CORRECT_ARGS", "Invalid open paper trade was closed in paper-only recovery; rerun forward-shadow only with the required micro ledgers and gates."),
    "UNKNOWN_CONFIG_ERROR": ("MANUAL_REVIEW_REQUIRED", "No specific config root cause was found; inspect recent forward-shadow logs manually."),
}


def run_config_error_root_cause_audit(
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
    stable_gate: str | Path | None = None,
    output_dir: str | Path = "data/reports/config_error_recovery",
) -> dict[str, Any]:
    """Diagnose the exact source of a forward-shadow CONFIG_ERROR without mutation."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state = database.get_operational_state()
    input_rows = _input_path_rows(
        profile_config=profile_config,
        stable_gate=stable_gate,
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
        paper_risk_dir=paper_risk_dir,
        daily_risk_dir=daily_risk_dir,
        pnl_audit_dir=pnl_audit_dir,
        reports_root=reports_root,
    )
    parser_rows = _parser_audit_rows(
        profile_config=profile_config,
        stable_gate=stable_gate,
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
    )
    event_rows = _collect_config_events(database=database, log_dir=log_dir, state=state)
    last_errors = [row for row in event_rows if row.get("severity") in {"ERROR", "CRITICAL"} or row.get("event_type") in {"FORWARD_SHADOW_CRITICAL_ERROR"} or row.get("error")]
    root, evidence, source = _select_root_cause(
        state=state,
        input_rows=input_rows,
        parser_rows=parser_rows,
        event_rows=event_rows,
        open_trades=[_payload(row) for row in database.fetch_open_paper_trades()],
    )
    fix_action, recommended_fix = ROOT_CAUSE_FIXES.get(root, ROOT_CAUSE_FIXES["UNKNOWN_CONFIG_ERROR"])
    summary = {
        "mode": "config-error-root-cause-audit",
        "config_error_detected": _config_error_detected(state),
        "primary_root_cause": root,
        "config_error_root_cause": root,
        "config_error_evidence": evidence,
        "source_file_or_log": source,
        "recommended_fix_action": fix_action,
        "recommended_fix": recommended_fix,
        "can_rerun_forward_shadow_after_fix": root in {"RESOLVED_INVALID_OPEN_PAPER_TRADE"} or root not in {"UNKNOWN_CONFIG_ERROR", "FORWARD_SHADOW_CONFIG_EXCEPTION"},
        "latest_exit_reason": state.get("latest_exit_reason", ""),
        "halt_reason": state.get("halt_reason") or state.get("paused_reason") or "",
        "latest_forward_shadow_error": state.get("latest_forward_shadow_error", ""),
        "input_path_count": len(input_rows),
        "config_event_count": len(event_rows),
        "forward_shadow_last_error_count": len(last_errors),
        "reports_root": str(reports_root),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_audit_reports(output, summary, event_rows, input_rows, parser_rows, last_errors)
    return {**summary, "reports_created": [str(path) for path in paths]}


def run_config_error_fix_plan(
    *,
    audit_dir: str | Path = "data/reports/config_error_recovery",
    output_dir: str | Path = "data/reports/config_error_recovery",
) -> dict[str, Any]:
    """Write an operator fix plan from the latest root-cause audit."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    audit = _load_json(Path(audit_dir) / "config_error_root_cause_summary.json")
    root = str(audit.get("config_error_root_cause") or audit.get("primary_root_cause") or "UNKNOWN_CONFIG_ERROR")
    action, fix = ROOT_CAUSE_FIXES.get(root, ROOT_CAUSE_FIXES["UNKNOWN_CONFIG_ERROR"])
    md = output / "CONFIG_ERROR_FIX_PLAN.md"
    ps1 = output / "config_fix_commands.ps1"
    md.write_text(_fix_plan_markdown(audit, action, fix), encoding="utf-8")
    ps1.write_text(_fix_plan_commands(action), encoding="utf-8")
    return {
        "mode": "config-error-fix-plan",
        "config_error_root_cause": root,
        "recommended_fix_action": action,
        "recommended_fix": fix,
        "reports_created": [str(md), str(ps1)],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _select_root_cause(
    *,
    state: Mapping[str, Any],
    input_rows: list[dict[str, Any]],
    parser_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    open_trades: list[Mapping[str, Any]],
) -> tuple[str, str, str]:
    invalid_risk = _open_trade_invalid_risk(open_trades)
    if not _config_error_detected(state):
        if state.get("invalid_open_paper_trade_resolved") and not invalid_risk:
            return "RESOLVED_INVALID_OPEN_PAPER_TRADE", "Previous invalid open paper trade was closed with paper-only recovery and no invalid open paper trade remains.", "sqlite:operational_state"
        return "UNKNOWN_CONFIG_ERROR", "No active CONFIG_ERROR/PAPER_STATE_ERROR was found in operational state.", "operational_state"
    for cause in ("MISSING_PROFILE_CONFIG", "MISSING_STABLE_GATE", "MISSING_CLEARANCE_LEDGER", "MISSING_DAILY_RISK_LEDGER"):
        row = _find(input_rows, "root_cause", cause)
        if row:
            return cause, str(row.get("detail", "")), str(row.get("path", ""))
    for cause in ("INVALID_PROFILE_CONFIG_SCHEMA", "INVALID_STABLE_GATE_SCHEMA", "INVALID_CLEARANCE_LEDGER_SCHEMA", "INVALID_DAILY_RISK_LEDGER_SCHEMA"):
        row = _find(parser_rows, "root_cause", cause)
        if row:
            return cause, str(row.get("detail", "")), str(row.get("source", ""))
    for cause in ("PROFILE_MISMATCH", "STABLE_GATE_NOT_ACCEPTED", "PAPER_RISK_NOT_ACCEPTED", "DAILY_RISK_LEDGER_NOT_ACCEPTED"):
        row = _find(parser_rows, "root_cause", cause)
        if row:
            return cause, str(row.get("detail", "")), str(row.get("source", ""))
    text = " ".join([str(state.get("latest_forward_shadow_error", "")), *[str(row.get("message", "")) + " " + str(row.get("error", "")) for row in event_rows[-50:]]]).lower()
    if "required" in text and ("argument" in text or "--" in text):
        return "MISSING_REQUIRED_FORWARD_SHADOW_ARG", text[:500], "forward-shadow logs/state"
    if "symbols" in text and ("invalid" in text or "empty" in text):
        return "INVALID_SYMBOLS_ARG", text[:500], "forward-shadow logs/state"
    if "signal_profile" in text and ("invalid" in text or "must be" in text):
        return "INVALID_SIGNAL_PROFILE", text[:500], "forward-shadow logs/state"
    if "parse" in text and "config" in text:
        return "CONFIG_PARSE_EXCEPTION", text[:500], "forward-shadow logs/state"
    if "no such file" in text or "path" in text and "not found" in text:
        return "RUNTIME_CONFIG_PATH_ERROR", text[:500], "forward-shadow logs/state"
    if invalid_risk:
        return "FORWARD_SHADOW_CONFIG_EXCEPTION", invalid_risk, "sqlite:paper_trades"
    latest_error = str(state.get("latest_forward_shadow_error") or "")
    if latest_error:
        return "FORWARD_SHADOW_CONFIG_EXCEPTION", latest_error, "sqlite:operational_state.latest_forward_shadow_error"
    row = next((item for item in reversed(event_rows) if item.get("event_type") == "FORWARD_SHADOW_CRITICAL_ERROR"), None)
    if row:
        return "FORWARD_SHADOW_CONFIG_EXCEPTION", str(row.get("message") or row.get("error") or row.get("payload_json", "")), str(row.get("source", ""))
    return "UNKNOWN_CONFIG_ERROR", "No path, schema, profile or forward-shadow exception evidence was specific enough.", "operational_state/logs"


def _input_path_rows(**paths: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root_map = {
        "profile_config": "MISSING_PROFILE_CONFIG",
        "stable_gate": "MISSING_STABLE_GATE",
        "clearance_ledger": "MISSING_CLEARANCE_LEDGER",
        "daily_risk_ledger": "MISSING_DAILY_RISK_LEDGER",
    }
    for name, value in paths.items():
        path = Path(value) if value is not None else None
        exists = bool(path and path.exists())
        is_file = bool(path and path.is_file())
        is_dir = bool(path and path.is_dir())
        root = root_map.get(name, "") if not exists else ""
        rows.append(
            {
                "input_name": name,
                "path": str(path or ""),
                "exists": exists,
                "is_file": is_file,
                "is_dir": is_dir,
                "schema_status": "MISSING" if root else "PRESENT",
                "root_cause": root,
                "detail": f"{name} is missing" if root else f"{name} exists",
                "execution_attempted": False,
            }
        )
    return rows


def _parser_audit_rows(
    *,
    profile_config: str | Path | None,
    stable_gate: str | Path | None,
    clearance_ledger: str | Path | None,
    daily_risk_ledger: str | Path | None,
) -> list[dict[str, Any]]:
    rows = []
    if profile_config and Path(profile_config).exists():
        rows.append(_audit_profile_config(Path(profile_config)))
    if stable_gate and Path(stable_gate).exists():
        rows.append(_audit_stable_gate(Path(stable_gate)))
    if clearance_ledger and Path(clearance_ledger).exists():
        rows.append(_audit_clearance_ledger(Path(clearance_ledger)))
    if daily_risk_ledger and Path(daily_risk_ledger).exists():
        rows.append(_audit_daily_risk_ledger(Path(daily_risk_ledger)))
    return rows


def _audit_profile_config(path: Path) -> dict[str, Any]:
    try:
        values = _parse_profile_config(path)
    except Exception as exc:
        return _parser_row("profile_config", path, "INVALID", "INVALID_PROFILE_CONFIG_SCHEMA", str(exc))
    profile = _canonical_profile(values.get("SIGNAL_PROFILE") or values.get("signal_profile") or values.get("PROFILE") or values.get("profile") or values.get("RISK_PROFILE_USED") or values.get("risk_profile_used"))
    if not profile:
        return _parser_row("profile_config", path, "INVALID", "INVALID_PROFILE_CONFIG_SCHEMA", "Profile config has no SIGNAL_PROFILE/profile value.")
    if profile != "BALANCED_STABLE_MICRO":
        return _parser_row("profile_config", path, "INVALID", "PROFILE_MISMATCH", f"profile={profile}, expected BALANCED_STABLE_MICRO")
    missing = [key for key in ("PAPER_ONLY", "NOT_FOR_DEMO_LIVE", "PAPER_RISK_MULTIPLIER") if key not in {k.upper(): v for k, v in values.items()}]
    if missing:
        return _parser_row("profile_config", path, "INVALID", "INVALID_PROFILE_CONFIG_SCHEMA", f"Missing required keys: {','.join(missing)}")
    return _parser_row("profile_config", path, "OK", "", "BALANCED_STABLE_MICRO profile config parsed.")


def _audit_stable_gate(path: Path) -> dict[str, Any]:
    payload, error = _load_json_with_error(path)
    if error or not isinstance(payload, dict):
        return _parser_row("stable_gate", path, "INVALID", "INVALID_STABLE_GATE_SCHEMA", error or "stable gate is not a JSON object")
    if not (payload.get("stable_gate_decision") == "PAPER_SHADOW_READY" or payload.get("classification") == "PAPER_SHADOW_READY" or bool(payload.get("paper_shadow_ready", False))):
        return _parser_row("stable_gate", path, "INVALID", "STABLE_GATE_NOT_ACCEPTED", "stable gate is not PAPER_SHADOW_READY")
    return _parser_row("stable_gate", path, "OK", "", "stable gate accepted.")


def _audit_clearance_ledger(path: Path) -> dict[str, Any]:
    payload, error = _load_json_with_error(path)
    if error or not isinstance(payload, dict):
        return _parser_row("clearance_ledger", path, "INVALID", "INVALID_CLEARANCE_LEDGER_SCHEMA", error or "clearance ledger is not a JSON object")
    clearances = payload.get("clearances")
    if not isinstance(clearances, list):
        return _parser_row("clearance_ledger", path, "INVALID", "INVALID_CLEARANCE_LEDGER_SCHEMA", "clearances must be a list")
    latest = _latest_mapping(clearances)
    if not latest or _canonical_profile(latest.get("canonical_cleared_for_profile") or latest.get("cleared_for_profile")) != "BALANCED_STABLE_MICRO" or not latest.get("cleared_for_paper_shadow", False):
        return _parser_row("clearance_ledger", path, "INVALID", "PAPER_RISK_NOT_ACCEPTED", "latest clearance is not valid for BALANCED_STABLE_MICRO paper/shadow")
    return _parser_row("clearance_ledger", path, "OK", "", "paper risk clearance accepted.")


def _audit_daily_risk_ledger(path: Path) -> dict[str, Any]:
    payload, error = _load_json_with_error(path)
    if error or not isinstance(payload, dict):
        return _parser_row("daily_risk_ledger", path, "INVALID", "INVALID_DAILY_RISK_LEDGER_SCHEMA", error or "daily risk ledger is not a JSON object")
    clearances = payload.get("daily_risk_clearances")
    if not isinstance(clearances, list):
        return _parser_row("daily_risk_ledger", path, "INVALID", "INVALID_DAILY_RISK_LEDGER_SCHEMA", "daily_risk_clearances must be a list")
    latest = _latest_mapping(clearances)
    if not latest or _canonical_profile(latest.get("canonical_cleared_for_profile") or latest.get("cleared_for_profile")) != "BALANCED_STABLE_MICRO" or not latest.get("cleared_for_paper_shadow", False):
        return _parser_row("daily_risk_ledger", path, "INVALID", "DAILY_RISK_LEDGER_NOT_ACCEPTED", "latest daily risk clearance is not valid for BALANCED_STABLE_MICRO")
    return _parser_row("daily_risk_ledger", path, "OK", "", "daily risk ledger accepted.")


def _collect_config_events(*, database: TelemetryDatabase, log_dir: str | Path, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if state.get("latest_exit_reason") or state.get("latest_forward_shadow_error"):
        rows.append(
            {
                "source": "sqlite:operational_state",
                "timestamp_utc": state.get("last_heartbeat_utc") or state.get("paused_at_utc") or "",
                "event_type": "OPERATIONAL_STATE",
                "severity": "ERROR" if state.get("latest_exit_reason") == "CONFIG_ERROR" else "INFO",
                "message": state.get("latest_exit_reason", ""),
                "error": state.get("latest_forward_shadow_error", ""),
                "execution_attempted": False,
            }
        )
    try:
        db_rows = database.fetch_all("events")[-1000:]
    except Exception:
        db_rows = []
    for row in db_rows:
        item = _row_to_event(row, "sqlite:events")
        if _looks_config_related(item):
            rows.append(item)
    rows.extend(_scan_jsonl_logs(Path(log_dir)))
    return rows[-300:]


def _scan_jsonl_logs(log_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not log_dir.exists():
        return rows
    files = sorted(log_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime)[-6:]
    for path in files:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if not any(token in line for token in ("CONFIG_ERROR", "PAPER_STATE_ERROR", "FORWARD_SHADOW_CRITICAL_ERROR", "invalid risk distance", "profile-config", "stable-gate", "clearance")):
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        payload = {"message": line.strip()}
                    item = _event_payload(payload, f"{path}:{line_no}")
                    if _looks_config_related(item):
                        rows.append(item)
        except OSError:
            continue
    return rows[-200:]


def _row_to_event(row: Any, source: str) -> dict[str, Any]:
    try:
        payload = {key: row[key] for key in row.keys()}
    except Exception:
        payload = {}
    return _event_payload(payload, source)


def _event_payload(payload: Mapping[str, Any], source: str) -> dict[str, Any]:
    nested = _loads(payload.get("payload_json"))
    return {
        "source": source,
        "timestamp_utc": payload.get("timestamp_utc") or nested.get("timestamp_utc", ""),
        "event_type": payload.get("event_type") or nested.get("event_type", ""),
        "severity": str(payload.get("severity") or nested.get("severity") or "").upper(),
        "message": payload.get("message") or nested.get("message") or nested.get("reason", ""),
        "error": nested.get("error") or nested.get("latest_forward_shadow_error") or "",
        "payload_json": payload.get("payload_json") or json.dumps(_jsonable(nested), sort_keys=True),
        "execution_attempted": False,
    }


def _looks_config_related(row: Mapping[str, Any]) -> bool:
    text = json.dumps(_jsonable(row), sort_keys=True).lower()
    return any(token in text for token in ("config_error", "config", "paper_state_error", "forward_shadow_critical_error", "invalid risk distance", "profile", "stable_gate", "clearance"))


def _open_trade_invalid_risk(open_trades: Iterable[Mapping[str, Any]]) -> str:
    for trade in open_trades:
        try:
            entry = float(trade.get("entry_price"))
            sl = float(trade.get("sl_price"))
        except Exception:
            continue
        if abs(entry - sl) <= 0:
            return f"Open paper trade {trade.get('paper_trade_id', '')} has invalid risk distance: entry_price={entry}, sl_price={sl}."
    return ""


def _write_audit_reports(
    output: Path,
    summary: Mapping[str, Any],
    event_rows: list[Mapping[str, Any]],
    input_rows: list[Mapping[str, Any]],
    parser_rows: list[Mapping[str, Any]],
    last_errors: list[Mapping[str, Any]],
) -> list[Path]:
    paths = {
        "summary": output / "config_error_root_cause_summary.json",
        "events": output / "config_error_events.csv",
        "paths": output / "config_input_paths.csv",
        "parser": output / "config_parser_audit.csv",
        "last_errors": output / "forward_shadow_last_errors.csv",
        "html": output / "report.html",
    }
    paths["summary"].write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(paths["events"], event_rows)
    _write_csv(paths["paths"], input_rows)
    _write_csv(paths["parser"], parser_rows)
    _write_csv(paths["last_errors"], last_errors)
    paths["html"].write_text(f"<html><body><h1>Config Error Root Cause</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return list(paths.values())


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key == "execution_attempted" else "") for key in fieldnames})


def _fix_plan_markdown(audit: Mapping[str, Any], action: str, fix: str) -> str:
    return f"""# Config Error Fix Plan

Recommended action: `{action}`

- root_cause: `{audit.get('config_error_root_cause', '')}`
- evidence: `{audit.get('config_error_evidence', '')}`
- source: `{audit.get('source_file_or_log', '')}`
- fix: `{fix}`
- execution_attempted=false
- order_send_called=false
- order_check_called=false

This plan is offline/paper-shadow only. It does not modify SQLite, logs, evidence or trades.
"""


def _fix_plan_commands(action: str) -> str:
    lines = ['$ErrorActionPreference = "Stop"', 'Set-Location (Split-Path -Parent $PSScriptRoot)', '$env:PYTHONPATH = "src/python"', ""]
    if action == "REBUILD_PROFILE_CONFIG":
        lines.append("py -m agi_style_forex_bot_mt5.cli --mode build-paper-risk-profile --base-profile BALANCED_STABLE --risk-audit-dir data\\reports\\paper_risk --output-dir data\\reports\\paper_risk")
    elif action == "REBUILD_STABLE_GATE":
        lines.append("py -m agi_style_forex_bot_mt5.cli --mode stable-robustness-gate --runs-root data\\runs --robustness-dir data\\reports\\robustness_stable --stability-dir data\\reports\\stability_repair --profile BALANCED_STABLE --output-dir data\\reports\\stable_gate")
    elif action == "REGENERATE_CLEARANCE_LEDGER":
        lines.append('py -m agi_style_forex_bot_mt5.cli --mode paper-risk-review --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root data\\reports --paper-risk-dir data\\reports\\paper_risk --output-dir data\\reports\\paper_risk_review')
    elif action == "REGENERATE_DAILY_RISK_LEDGER":
        lines.append('py -m agi_style_forex_bot_mt5.cli --mode paper-daily-risk-audit --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root data\\reports --paper-risk-dir data\\reports\\paper_risk --clearance-ledger data\\reports\\paper_risk_review\\paper_risk_clearance_ledger.json --output-dir data\\reports\\paper_daily_risk')
    else:
        lines.append("py -m agi_style_forex_bot_mt5.cli --mode config-error-root-cause-audit --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root data\\reports --paper-risk-dir data\\reports\\paper_risk --daily-risk-dir data\\reports\\paper_daily_risk --pnl-audit-dir data\\reports\\paper_pnl_audit --clearance-ledger data\\reports\\paper_risk_review\\paper_risk_clearance_ledger.json --daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json --profile-config data\\reports\\paper_risk\\balanced_stable_micro.ini --stable-gate data\\reports\\stable_gate\\stable_gate_summary.json --output-dir data\\reports\\config_error_recovery")
    return "\n".join(lines) + "\n"


def _parser_row(component: str, source: Path, status: str, root_cause: str, detail: str) -> dict[str, Any]:
    return {"component": component, "source": str(source), "parser_status": status, "root_cause": root_cause, "detail": detail, "execution_attempted": False}


def _parse_profile_config(path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(strict=False)
    text = path.read_text(encoding="utf-8")
    parser.read_string(text if text.lstrip().startswith("[") else "[profile]\n" + text)
    section = parser["profile"] if parser.has_section("profile") else parser.defaults()
    return {str(key).upper(): str(value) for key, value in section.items()}


def _latest_mapping(items: list[Any]) -> Mapping[str, Any]:
    mappings = [item for item in items if isinstance(item, Mapping)]
    if not mappings:
        return {}
    return sorted(mappings, key=lambda item: str(item.get("created_at_utc") or item.get("updated_at_utc") or ""))[-1]


def _find(rows: list[Mapping[str, Any]], key: str, value: str) -> Mapping[str, Any]:
    return next((row for row in rows if row.get(key) == value), {})


def _config_error_detected(state: Mapping[str, Any]) -> bool:
    return state.get("latest_exit_reason") == "CONFIG_ERROR" or state.get("halt_reason") == "PAPER_STATE_ERROR"


def _canonical_profile(value: Any) -> str:
    return str(value or "").strip().replace(" ", "_").replace("-", "_").upper()


def _load_json(path: Path) -> dict[str, Any]:
    payload, _ = _load_json_with_error(path)
    return payload if isinstance(payload, dict) else {}


def _load_json_with_error(path: Path) -> tuple[Any, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:
        return {}, str(exc)


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {"message": value}


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value

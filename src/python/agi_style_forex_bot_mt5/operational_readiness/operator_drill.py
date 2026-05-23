"""Offline operator drill and dry-run market-open validation."""

from __future__ import annotations

import csv
import html
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


EC2_SCRIPTS = (
    "ec2_operator_handoff.ps1",
    "ec2_market_open_runbook.ps1",
    "ec2_safe_stop_shadow.ps1",
    "ec2_collect_evidence.ps1",
    "ec2_backup_and_health.ps1",
)


def run_operator_drill(*, reports_root: str | Path, output_dir: str | Path, config: BotConfig) -> dict[str, Any]:
    """Simulate the operator market-open runbook without touching MT5."""

    reports = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    steps = _operator_steps(reports, config)
    scenarios = _failure_scenarios()
    commands_review = _commands_review(reports)
    classification = "OPERATOR_DRILL_PASSED" if all(step["status"] in {"PASS", "SIMULATED"} for step in steps) else "OPERATOR_DRILL_NEEDS_REVIEW"
    summary = {
        "mode": "operator-drill",
        "classification": classification,
        "operator_drill_status": classification,
        "steps_passed": sum(1 for step in steps if step["status"] == "PASS"),
        "steps_simulated": sum(1 for step in steps if step["status"] == "SIMULATED"),
        "steps_failed": sum(1 for step in steps if step["status"] == "FAIL"),
        "failure_scenarios": len(scenarios),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "recommended_next_action": "Use this drill for operator training only; wait for market open before running live MT5 diagnostics or paper shadow.",
    }
    paths = _write_operator_reports(output, summary, steps, scenarios, commands_review)
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def run_dry_run_market_open(
    *,
    sqlite_path: str | Path,
    reports_root: str | Path,
    output_dir: str | Path,
    config: BotConfig,
) -> dict[str, Any]:
    """Validate market-open prerequisites offline without connecting to MT5."""

    reports = Path(reports_root)
    sqlite = Path(sqlite_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    _check(checks, "market_open_commands_exist", (reports / "market_open_checklist" / "commands.ps1").exists(), str(reports / "market_open_checklist" / "commands.ps1"))
    _check(checks, "ec2_commands_exist", (reports / "ec2_deployment_pack" / "EC2_COMMANDS.ps1").exists(), str(reports / "ec2_deployment_pack" / "EC2_COMMANDS.ps1"))
    _check(checks, "stable_gate_exists", (reports / "stable_gate" / "stable_gate_summary.json").exists(), str(reports / "stable_gate" / "stable_gate_summary.json"))
    _check(checks, "profile_config_exists", (reports / "stability_repair" / "balanced_stable.ini").exists(), str(reports / "stability_repair" / "balanced_stable.ini"))
    for script in EC2_SCRIPTS:
        _check(checks, f"script_{script}", (Path("scripts") / script).exists(), str(Path("scripts") / script))

    state: dict[str, Any] = {}
    open_trades = 0
    if not sqlite.exists():
        _row(checks, "sqlite_exists", "FAIL", f"SQLite file not found: {sqlite}")
    else:
        try:
            with sqlite3.connect(sqlite) as conn:
                conn.execute("SELECT 1").fetchone()
            _row(checks, "sqlite_opens", "PASS", f"SQLite opens: {sqlite}")
            database = TelemetryDatabase(sqlite)
            try:
                open_trades = len(database.fetch_open_paper_trades())
                state = database.get_operational_state()
            finally:
                database.close()
            _row(checks, "paper_trades_open_zero", "PASS" if open_trades == 0 else "FAIL", f"paper_trades_open={open_trades}")
            _row(checks, "shadow_paused", "PASS" if bool(state.get("shadow_paused")) else "FAIL", f"paper_shadow_paused={bool(state.get('shadow_paused'))}")
        except Exception as exc:
            _row(checks, "sqlite_opens", "FAIL", f"SQLite open/read failed: {exc}")

    _row(checks, "demo_only_true", "PASS" if config.demo_only else "FAIL", f"DEMO_ONLY={config.demo_only}")
    _row(checks, "live_trading_not_approved", "PASS" if not config.live_trading_approved else "FAIL", f"LIVE_TRADING_APPROVED={config.live_trading_approved}")
    _row(checks, "no_order_send_or_check_would_run", "PASS", "Dry run does not instantiate MT5 or forward-shadow execution.")

    classification = "DRY_RUN_MARKET_OPEN_READY" if all(check["status"] == "PASS" for check in checks) else "DRY_RUN_MARKET_OPEN_BLOCKED"
    summary = {
        "mode": "dry-run-market-open",
        "classification": classification,
        "dry_run_market_open_status": classification,
        "paper_trades_open": open_trades,
        "paper_shadow_paused": bool(state.get("shadow_paused", False)),
        "checks_passed": sum(1 for check in checks if check["status"] == "PASS"),
        "checks_failed": sum(1 for check in checks if check["status"] == "FAIL"),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "recommended_next_action": _dry_run_next_action(classification),
        "checks": checks,
    }
    path = output / "dry_run_market_open_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def _operator_steps(reports: Path, config: BotConfig) -> list[dict[str, Any]]:
    weekend = _load_json(reports / "weekend_readiness" / "weekend_readiness_summary.json")
    ec2_pack = _load_json(reports / "ec2_deployment_pack" / "ec2_deployment_summary.json")
    return [
        _step("pre_check_weekend_readiness", weekend.get("weekend_readiness_status") == "WEEKEND_SAFE", weekend.get("weekend_readiness_status", "missing")),
        _step("validate_ec2_deployment_pack", ec2_pack.get("package_status") == "EC2_DEPLOYMENT_PACK_READY", ec2_pack.get("package_status", "missing")),
        _step("validate_market_open_checklist", (reports / "market_open_checklist" / "commands.ps1").exists(), str(reports / "market_open_checklist" / "commands.ps1")),
        _step("validate_stable_gate", (reports / "stable_gate" / "stable_gate_summary.json").exists(), str(reports / "stable_gate" / "stable_gate_summary.json")),
        _step("validate_paper_state_clean", bool(weekend.get("paper_clean_state", False)) and int(weekend.get("paper_trades_open", 99)) == 0, f"paper_clean_state={weekend.get('paper_clean_state')}"),
        _step("confirm_safety_flags", config.demo_only and not config.live_trading_approved, f"DEMO_ONLY={config.demo_only}; LIVE_TRADING_APPROVED={config.live_trading_approved}"),
        {"step_name": "simulate_market_open_commands", "status": "SIMULATED", "detail": "mt5-diagnose, live-feature-contract, resume-shadow and forward-shadow commands reviewed only", "execution_attempted": False},
        {"step_name": "simulate_failure_scenarios", "status": "SIMULATED", "detail": "Six failure scenarios mapped to safe operator action", "execution_attempted": False},
    ]


def _failure_scenarios() -> list[dict[str, Any]]:
    return [
        {"scenario": "MT5_DISCONNECTED", "simulated_signal": "mt5_connected=false", "recommended_action": "Reconnect RDP/MT5 demo account and rerun mt5-diagnose.", "execution_attempted": False},
        {"scenario": "ALL_SYMBOLS_REJECTED", "simulated_signal": "symbols_rejected == symbols_seen", "recommended_action": "Run mt5-diagnose, live-feature-contract and forward-signal-diagnose; keep shadow paused if rejection persists.", "execution_attempted": False},
        {"scenario": "FEATURE_PIPELINE_NOT_READY", "simulated_signal": "feature_ready_symbols=[]", "recommended_action": "Run live-feature-contract and repair schema/features before any resume.", "execution_attempted": False},
        {"scenario": "PAPER_DAILY_DRAWDOWN", "simulated_signal": "alert severity CRITICAL", "recommended_action": "pause-shadow, paper-state-report, collect evidence, review before resume.", "execution_attempted": False},
        {"scenario": "FORWARD_EVIDENCE_PARTIAL_INVALID_TIMESTAMPS", "simulated_signal": "evidence_parse_status=PARTIAL_INVALID_TIMESTAMPS", "recommended_action": "Keep evidence, inspect invalid timestamp examples, rerun forward-evidence after parser repair.", "execution_attempted": False},
        {"scenario": "SHADOW_MANUALLY_PAUSED", "simulated_signal": "paper_shadow_paused=true", "recommended_action": "Do not restart automatically; resume-shadow only after diagnostics and operator approval.", "execution_attempted": False},
    ]


def _commands_review(reports: Path) -> str:
    command_path = reports / "market_open_checklist" / "commands.ps1"
    commands = command_path.read_text(encoding="utf-8", errors="ignore") if command_path.exists() else "# commands.ps1 missing"
    return "\n".join(
        [
            "# Market Open Commands Review",
            "",
            "This is an offline review. Do not run forward-shadow while the market is closed.",
            "",
            "```powershell",
            commands.strip(),
            "```",
            "",
            "Safety: execution_attempted=false; order_send_called=false; order_check_called=false.",
            "",
        ]
    )


def _write_operator_reports(output: Path, summary: Mapping[str, Any], steps: list[dict[str, Any]], scenarios: list[dict[str, Any]], commands_review: str) -> list[Path]:
    summary_path = output / "operator_drill_summary.json"
    steps_path = output / "operator_steps.csv"
    scenarios_path = output / "failure_scenarios.csv"
    commands_path = output / "market_open_commands_review.md"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps({**dict(summary), "operator_steps": steps}, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(steps_path, steps, ("step_name", "status", "detail", "execution_attempted"))
    _write_csv(scenarios_path, scenarios, ("scenario", "simulated_signal", "recommended_action", "execution_attempted"))
    commands_path.write_text(commands_review, encoding="utf-8")
    html_path.write_text(_html(summary, steps, scenarios), encoding="utf-8")
    return [summary_path, steps_path, scenarios_path, commands_path, html_path]


def _step(name: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"step_name": name, "status": "PASS" if passed else "FAIL", "detail": str(detail), "execution_attempted": False}


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    _row(checks, name, "PASS" if passed else "FAIL", detail)


def _row(checks: list[dict[str, Any]], name: str, status: str, detail: str) -> None:
    checks.append({"check_name": name, "status": status, "detail": detail, "execution_attempted": False})


def _dry_run_next_action(classification: str) -> str:
    if classification == "DRY_RUN_MARKET_OPEN_READY":
        return "Wait for market open, then run mt5-diagnose and live-feature-contract before any paper-only resume."
    return "Keep shadow paused and repair failed dry-run checks before market open."


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _html(summary: Mapping[str, Any], steps: Iterable[Mapping[str, Any]], scenarios: Iterable[Mapping[str, Any]]) -> str:
    step_rows = "".join(f"<tr><td>{html.escape(str(row.get('step_name')))}</td><td>{html.escape(str(row.get('status')))}</td><td>{html.escape(str(row.get('detail')))}</td></tr>" for row in steps)
    scenario_rows = "".join(f"<tr><td>{html.escape(str(row.get('scenario')))}</td><td>{html.escape(str(row.get('recommended_action')))}</td></tr>" for row in scenarios)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Operator Drill</title></head>
<body>
<h1>Operator Drill</h1>
<p>Status: <strong>{html.escape(str(summary.get('classification')))}</strong></p>
<p>execution_attempted=false; order_send_called=false; order_check_called=false</p>
<h2>Steps</h2><table border="1"><tbody>{step_rows}</tbody></table>
<h2>Failure Scenarios</h2><table border="1"><tbody>{scenario_rows}</tbody></table>
</body></html>
"""

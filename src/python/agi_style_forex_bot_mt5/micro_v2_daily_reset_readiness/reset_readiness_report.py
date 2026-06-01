"""Report orchestration for Micro V2 daily reset readiness."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .daily_halt_status_audit import audit_daily_halt_status
from .ledger_date_audit import audit_ledger_date
from .reset_readiness_loader import load_reset_readiness_inputs, safety_flags
from .v2_relaunch_gate import evaluate_v2_relaunch_gate


RELAUNCH_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY "
    "--signal-profile BALANCED_STABLE_MICRO_V2 --profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--stable-gate data\\reports\\stable_gate\\stable_gate_summary.json "
    "--paper-risk-clearance data\\reports\\micro_v2_clearance\\paper_risk_clearance_v2_ledger.json "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --log-dir data\\logs\\forward-shadow-v2-dryrun --cycle-seconds 30"
)


def run_micro_v2_daily_reset_readiness(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    daily_risk_scope_repair_dir: str | Path = "data/reports/micro_v2_daily_risk_scope_repair",
    closed_loss_scope_dir: str | Path = "data/reports/micro_v2_closed_loss_scope_decision",
    output_dir: str | Path = "data/reports/micro_v2_daily_reset_readiness",
    current_utc: datetime | None = None,
) -> dict[str, Any]:
    now = current_utc or datetime.now(timezone.utc)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_reset_readiness_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        daily_risk_ledger=daily_risk_ledger,
        daily_risk_scope_repair_dir=daily_risk_scope_repair_dir,
        closed_loss_scope_dir=closed_loss_scope_dir,
    )
    halt = audit_daily_halt_status(inputs["dataset"], current_utc=now)
    ledger = audit_ledger_date(inputs, current_utc=now)
    gate = evaluate_v2_relaunch_gate(
        inputs["dataset"],
        safety_blocked=safety_flags(inputs["dataset"]),
        halt_audit=halt,
        ledger_audit=ledger,
    )
    summary = {
        "mode": "micro-v2-daily-reset-readiness",
        "micro_v2_daily_reset_readiness_status": gate["v2_relaunch_gate_status"],
        "daily_halt_active": bool(halt.get("daily_halt_active", False)),
        "daily_reset_occurred": bool(halt.get("daily_reset_occurred", False)),
        "daily_risk_scope_status": ledger.get("daily_risk_scope_status", ""),
        "current_operational_day": halt.get("current_operational_day", ""),
        "latest_halt_operational_day": halt.get("latest_halt_operational_day", ""),
        "open_trade_count": gate.get("open_trade_count", 0),
        "invalid_open_trade_count": gate.get("invalid_open_trade_count", 0),
        "quarantined_trade_count": gate.get("quarantined_trade_count", 0),
        "paper_state_clean_for_relaunch": bool(gate.get("paper_state_clean_for_relaunch", False)),
        "relaunch_allowed": bool(gate.get("relaunch_allowed", False)),
        "recommended_next_action": gate.get("recommended_next_action", ""),
        "relaunch_command": RELAUNCH_COMMAND if gate.get("relaunch_allowed") else "",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, halt, ledger, gate)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _write_reports(output: Path, summary: Mapping[str, Any], halt: Mapping[str, Any], ledger: Mapping[str, Any], gate: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "micro_v2_daily_reset_readiness_summary.json",
        output / "daily_halt_status_audit.json",
        output / "ledger_date_audit.json",
        output / "v2_relaunch_gate.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], halt)
    _write_json(paths[2], ledger)
    _write_json(paths[3], gate)
    paths[4].write_text(_commands(summary), encoding="utf-8")
    paths[5].write_text(_recommendations(summary), encoding="utf-8")
    paths[6].write_text(f"<html><body><h1>Micro V2 Daily Reset Readiness</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _commands(summary: Mapping[str, Any]) -> str:
    if summary.get("relaunch_allowed"):
        return f"""# Micro V2 Relaunch Command

Daily reset readiness is green. Operator may relaunch V2 paper dry-run with:

```powershell
{RELAUNCH_COMMAND}
```
"""
    return """# Micro V2 Daily Reset Readiness

KEEP_V2_STOPPED_AND_RERUN_RESET_READINESS_LATER.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Recommendations

Status: `{summary.get('micro_v2_daily_reset_readiness_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This phase is read-only and does not clear the daily halt manually.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

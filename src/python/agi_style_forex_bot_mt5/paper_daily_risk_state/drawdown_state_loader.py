"""Load paper drawdown state for daily risk classification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.paper_risk_review import validate_micro_resume_clearance
from agi_style_forex_bot_mt5.paper_risk_review.clearance_ledger import latest_clearance, load_clearance_ledger
from agi_style_forex_bot_mt5.paper_risk_review.drawdown_halt_loader import load_drawdown_halt_context
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def load_drawdown_state(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    clearance_ledger: str | Path | None = None,
    profile_config: str | Path | None = None,
    profile: str = "BALANCED_STABLE_MICRO",
) -> dict[str, Any]:
    context = load_drawdown_halt_context(database=database, log_dir=log_dir, reports_root=reports_root, paper_risk_dir=paper_risk_dir)
    ledger = load_clearance_ledger(clearance_ledger)
    clearance = latest_clearance(ledger)
    validation = validate_micro_resume_clearance(
        database=database,
        clearance_ledger=clearance_ledger,
        profile=profile,
        profile_config=profile_config,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
    )
    trades = [_payload(row) for row in database.fetch_paper_trades()]
    return {
        "context": context,
        "halt_events": list(context.get("halt_events", [])),
        "profile_clearance": clearance,
        "profile_clearance_validation": validation,
        "trades": trades,
        "paper_trades_open": context.get("paper_trades_open", 0),
        "execution_evidence_clear": context.get("execution_evidence_clear", False),
        "telemetry_clear": context.get("telemetry_clear", False),
        "stable_gate_ready": context.get("stable_gate_ready", False),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _payload(row: Any) -> dict[str, Any]:
    try:
        if "payload_json" in row.keys():
            return json.loads(row["payload_json"])
    except Exception:
        pass
    try:
        return dict(row)
    except Exception:
        return {}

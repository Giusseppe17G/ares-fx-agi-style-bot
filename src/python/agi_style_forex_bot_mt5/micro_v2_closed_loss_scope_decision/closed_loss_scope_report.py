"""Report orchestration for Micro V2 closed loss scope decision."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .closed_loss_loader import load_closed_loss_scope_inputs, safety_flags
from .closed_trade_attribution_audit import audit_closed_trade_attribution
from .daily_drawdown_legitimacy_audit import audit_daily_drawdown_legitimacy
from .daily_risk_scope_audit import audit_daily_risk_scope
from .next_action_decision import decide_next_action
from .quarantined_trade_exclusion_audit import audit_quarantined_trade_exclusion


def run_micro_v2_closed_loss_scope_decision(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    daily_risk_ledger: str | Path | None = "data/reports/paper_daily_risk/paper_daily_risk_ledger.json",
    drawdown_recovery_dir: str | Path = "data/reports/micro_v2_daily_drawdown_state_recovery_after_open_trade_repair",
    open_trade_repair_dir: str | Path = "data/reports/micro_v2_guarded_open_trade_integrity_repair",
    schema_repair_dir: str | Path = "data/reports/micro_v2_papertrade_schema_repair",
    output_dir: str | Path = "data/reports/micro_v2_closed_loss_scope_decision",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_closed_loss_scope_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        daily_risk_ledger=daily_risk_ledger,
        drawdown_recovery_dir=drawdown_recovery_dir,
        open_trade_repair_dir=open_trade_repair_dir,
        schema_repair_dir=schema_repair_dir,
    )
    dataset = inputs["dataset"]
    attribution = audit_closed_trade_attribution(dataset)
    quarantine = audit_quarantined_trade_exclusion(dataset)
    legitimacy = audit_daily_drawdown_legitimacy(attribution, quarantine, dataset)
    scope = audit_daily_risk_scope(inputs.get("daily_risk_ledger_payload", {}), closed_scaled_pnl_total=float(attribution.get("closed_scaled_pnl_total", 0.0) or 0.0))
    decision = decide_next_action(
        safety_blocked=safety_flags(dataset),
        attribution=attribution,
        quarantine=quarantine,
        legitimacy=legitimacy,
        scope=scope,
    )
    summary = {
        "mode": "micro-v2-closed-loss-scope-decision",
        "micro_v2_closed_loss_scope_decision_status": decision["micro_v2_closed_loss_scope_decision_status"],
        "closed_loss_legitimate": bool(legitimacy.get("closed_loss_legitimate", False)),
        "closed_trade_count": attribution.get("closed_trade_count", 0),
        "closed_scaled_pnl_total": attribution.get("closed_scaled_pnl_total", 0.0),
        "quarantined_contamination_detected": bool(quarantine.get("quarantined_contamination_detected", False)),
        "quarantined_trade_count": quarantine.get("quarantined_trade_count", 0),
        "pnl_integrity_status": attribution.get("pnl_integrity_status", ""),
        "daily_risk_scope_status": scope.get("daily_risk_scope_status", ""),
        "next_allowed_action": decision.get("next_allowed_action", ""),
        "recommended_next_action": decision.get("recommended_next_action", ""),
        "daily_halt_should_remain": bool(legitimacy.get("keep_daily_halt", False)),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, attribution, quarantine, legitimacy, scope, decision)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _write_reports(output: Path, summary: Mapping[str, Any], attribution: Mapping[str, Any], quarantine: Mapping[str, Any], legitimacy: Mapping[str, Any], scope: Mapping[str, Any], decision: Mapping[str, Any]) -> list[Path]:
    paths = [
        output / "micro_v2_closed_loss_scope_decision_summary.json",
        output / "closed_trades_attribution.csv",
        output / "closed_trade_attribution_audit.json",
        output / "quarantined_trade_exclusion_audit.json",
        output / "daily_drawdown_legitimacy_audit.json",
        output / "daily_risk_scope_audit.json",
        output / "next_action_decision.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_closed_csv(paths[1], attribution.get("closed_trade_rows", []))
    _write_json(paths[2], attribution)
    _write_json(paths[3], quarantine)
    _write_json(paths[4], legitimacy)
    _write_json(paths[5], scope)
    _write_json(paths[6], decision)
    paths[7].write_text(_commands(summary), encoding="utf-8")
    paths[8].write_text(_recommendations(summary), encoding="utf-8")
    paths[9].write_text(f"<html><body><h1>Micro V2 Closed Loss Scope Decision</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _commands(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Closed Loss Scope Decision

Status: `{summary.get('micro_v2_closed_loss_scope_decision_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Closed Loss Scope Recommendations

Closed loss legitimate: `{summary.get('closed_loss_legitimate')}`

Daily risk scope status: `{summary.get('daily_risk_scope_status')}`
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_closed_csv(path: Path, rows: Any) -> None:
    fields = [
        "trade_id",
        "symbol",
        "side",
        "entry_price",
        "close_price",
        "sl_price",
        "tp_price",
        "opened_at",
        "closed_at",
        "close_reason",
        "raw_pnl",
        "scaled_pnl",
        "risk_distance",
        "reward_distance",
        "counted_in_daily_drawdown",
        "was_quarantined",
        "invalid_close",
        "normal_paper_exit",
        "came_from_manage_open_trades_only",
        "pnl_integrity_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows or []:
            writer.writerow({field: row.get(field, "") for field in fields})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

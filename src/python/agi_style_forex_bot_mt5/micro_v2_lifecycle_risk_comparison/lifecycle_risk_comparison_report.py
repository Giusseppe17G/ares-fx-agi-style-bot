"""Report orchestration for Micro V2 lifecycle/risk comparison."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .base_vs_v2_preliminary_comparison import compare_base_vs_v2_preliminary
from .drawdown_health_audit import audit_drawdown_health
from .exit_readiness_audit import audit_exit_readiness
from .frequency_pre_acceptance_audit import audit_frequency_pre_acceptance
from .lifecycle_loader import load_lifecycle_inputs
from .open_trade_lifecycle_audit import audit_open_trade_lifecycle
from .pnl_readiness_audit import audit_pnl_readiness
from .risk_health_audit import audit_risk_health


def run_micro_v2_lifecycle_risk_comparison(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    stable_window_dir: str | Path = "data/reports/micro_v2_stable_market_window",
    checkpoint_dir: str | Path = "data/reports/micro_v2_observation_checkpoint",
    filter_analysis_dir: str | Path = "data/reports/micro_v2_filter_analysis",
    consolidated_dir: str | Path = "data/reports/micro_v2_consolidated_audit",
    output_dir: str | Path = "data/reports/micro_v2_lifecycle_risk_comparison",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_lifecycle_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        stable_window_dir=stable_window_dir,
        checkpoint_dir=checkpoint_dir,
        filter_analysis_dir=filter_analysis_dir,
        consolidated_dir=consolidated_dir,
    )
    stale_symbols = list(inputs["stable_window"].get("stale_tick_symbols") or inputs["consolidated"].get("stale_tick_symbols") or [])
    lifecycle = audit_open_trade_lifecycle(inputs["v2_dataset"], profile_config=str(v2_profile_config), stale_symbols=stale_symbols)
    exit_readiness = audit_exit_readiness(lifecycle)
    pnl = audit_pnl_readiness(lifecycle, inputs["profile_values"])
    drawdown = audit_drawdown_health(inputs["v2_dataset"], inputs["consolidated"], inputs["stable_window"])
    risk = audit_risk_health(
        lifecycle=lifecycle,
        drawdown=drawdown,
        pnl=pnl,
        profile_values=inputs["profile_values"],
        checkpoint=inputs["checkpoint"],
    )
    comparison = compare_base_vs_v2_preliminary(
        base_dataset=inputs["base_dataset"],
        v2_dataset=inputs["v2_dataset"],
        stable_window=inputs["stable_window"],
        filter_analysis=inputs["filter_analysis"],
    )
    pre_acceptance = audit_frequency_pre_acceptance(inputs["stable_window"], lifecycle)
    status = _decide_status(inputs["v2_dataset"], lifecycle, pnl, drawdown, risk, pre_acceptance, comparison)
    blockers = _acceptance_blockers(lifecycle, pnl, drawdown, risk, pre_acceptance)
    summary = {
        "mode": "micro-v2-lifecycle-risk-comparison",
        "micro_v2_lifecycle_risk_comparison_status": status,
        "open_trade_count": lifecycle.get("open_trade_count", 0),
        "closed_trade_count": pre_acceptance.get("v2_paper_trades_closed", 0),
        "invalid_open_trade_count": lifecycle.get("invalid_open_trade_count", 0),
        "risk_distance_issues": lifecycle.get("risk_distance_issues", 0),
        "sl_tp_issues": lifecycle.get("sl_tp_issues", 0),
        "pnl_issues": pnl.get("pnl_issues", 0),
        "risk_health_status": risk.get("risk_health_status", ""),
        "drawdown_health_status": drawdown.get("drawdown_health_status", ""),
        "preliminary_base_vs_v2_result": comparison.get("preliminary_base_vs_v2_result", ""),
        "acceptance_ready": pre_acceptance.get("acceptance_ready", False),
        "acceptance_blockers": blockers,
        "recommended_next_action": _recommended_next_action(status, pre_acceptance),
        "v2_hours_observed": pre_acceptance.get("v2_hours_observed", 0.0),
        "v2_market_open_hours_estimated": pre_acceptance.get("v2_market_open_hours_estimated", 0.0),
        "open_latent_pnl_total": pnl.get("open_latent_pnl_total", 0.0),
        "scaled_latent_pnl_total": pnl.get("scaled_latent_pnl_total", 0.0),
        "raw_latent_pnl_total": pnl.get("raw_latent_pnl_total", 0.0),
        "active_scaled_drawdown_count": drawdown.get("active_scaled_drawdown_count", 0),
        "daily_halt_active": drawdown.get("daily_halt_active", False),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, lifecycle, exit_readiness, pnl, drawdown, risk, comparison, pre_acceptance, blockers)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _decide_status(
    dataset: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    pnl: Mapping[str, Any],
    drawdown: Mapping[str, Any],
    risk: Mapping[str, Any],
    pre_acceptance: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> str:
    if _safety(dataset):
        return "MICRO_V2_SAFETY_BLOCKED"
    if lifecycle.get("risk_distance_issues", 0):
        return "MICRO_V2_OPEN_TRADES_INVALID_RISK_DISTANCE"
    if lifecycle.get("sl_tp_issues", 0):
        return "MICRO_V2_OPEN_TRADES_INVALID_SL_TP"
    if pnl.get("pnl_issues", 0):
        return "MICRO_V2_OPEN_TRADES_PNL_ISSUE"
    if str(drawdown.get("drawdown_health_status", "")).endswith("BLOCKED") or str(risk.get("risk_health_status", "")).endswith("BLOCKED"):
        return "MICRO_V2_RISK_HEALTH_BLOCKED"
    if pre_acceptance.get("acceptance_ready"):
        return "MICRO_V2_READY_FOR_FINAL_ACCEPTANCE_EVIDENCE_PACK"
    if lifecycle.get("open_trade_count", 0) and pre_acceptance.get("v2_paper_trades_closed", 0) < 10:
        return "MICRO_V2_OPEN_TRADES_HEALTHY_COLLECTING_EXITS"
    if str(comparison.get("preliminary_base_vs_v2_result", "")).endswith("IMPROVING_FREQUENCY"):
        return "MICRO_V2_PRELIMINARY_OUTPERFORMING_STABLE"
    if pre_acceptance.get("v2_paper_trades_closed", 0) < 10:
        return "MICRO_V2_ACCEPTANCE_NOT_READY_NEEDS_CLOSED_TRADES"
    return "MICRO_V2_REQUIRES_MANUAL_REVIEW"


def _acceptance_blockers(
    lifecycle: Mapping[str, Any],
    pnl: Mapping[str, Any],
    drawdown: Mapping[str, Any],
    risk: Mapping[str, Any],
    pre_acceptance: Mapping[str, Any],
) -> list[str]:
    blockers = list(pre_acceptance.get("preliminary_acceptance_blockers", []))
    if lifecycle.get("risk_distance_issues", 0):
        blockers.append("OPEN_TRADE_INVALID_RISK_DISTANCE")
    if lifecycle.get("sl_tp_issues", 0):
        blockers.append("OPEN_TRADE_INVALID_SL_TP")
    if pnl.get("pnl_issues", 0):
        blockers.append("OPEN_TRADE_PNL_ISSUE")
    if drawdown.get("active_scaled_drawdown_count", 0) or drawdown.get("daily_halt_active"):
        blockers.append("ACTIVE_DRAWDOWN_OR_DAILY_HALT")
    if str(risk.get("risk_health_status", "")).endswith("BLOCKED"):
        blockers.append("PAPER_RISK_HEALTH_BLOCKED")
    return sorted(set(blockers))


def _recommended_next_action(status: str, pre_acceptance: Mapping[str, Any]) -> str:
    if status == "MICRO_V2_OPEN_TRADES_HEALTHY_COLLECTING_EXITS":
        return "CONTINUE_V2_PAPER_OBSERVATION_AND_WAIT_FOR_OPEN_TRADES_TO_EXIT"
    if status == "MICRO_V2_OPEN_TRADES_INVALID_RISK_DISTANCE":
        return "PREPARE_INVALID_OPEN_TRADE_RISK_DISTANCE_REPAIR_PHASE"
    if status == "MICRO_V2_OPEN_TRADES_INVALID_SL_TP":
        return "PREPARE_INVALID_SL_TP_REPAIR_PHASE"
    if status == "MICRO_V2_OPEN_TRADES_PNL_ISSUE":
        return "PREPARE_PAPER_PNL_REPAIR_PHASE"
    if status == "MICRO_V2_RISK_HEALTH_BLOCKED":
        return "KEEP_V2_BLOCKED_AND_REVIEW_RISK_HEALTH"
    if status == "MICRO_V2_READY_FOR_FINAL_ACCEPTANCE_EVIDENCE_PACK":
        return "PREPARE_FASE_64_FINAL_ACCEPTANCE_EVIDENCE_PACK"
    if status == "MICRO_V2_SAFETY_BLOCKED":
        return "STOP_AND_REVIEW_SAFETY_EVIDENCE"
    return str(pre_acceptance.get("recommended_next_action", "CONTINUE_V2_OBSERVATION"))


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    exit_readiness: Mapping[str, Any],
    pnl: Mapping[str, Any],
    drawdown: Mapping[str, Any],
    risk: Mapping[str, Any],
    comparison: Mapping[str, Any],
    pre_acceptance: Mapping[str, Any],
    blockers: list[str],
) -> list[Path]:
    paths = [
        output / "micro_v2_lifecycle_risk_comparison_summary.json",
        output / "open_trades.csv",
        output / "open_trade_lifecycle_audit.json",
        output / "exit_readiness_audit.json",
        output / "pnl_readiness_audit.json",
        output / "drawdown_health_audit.json",
        output / "risk_health_audit.json",
        output / "base_vs_v2_preliminary_comparison.json",
        output / "frequency_pre_acceptance_audit.json",
        output / "acceptance_blockers.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], lifecycle.get("open_trades", []))
    _write_json(paths[2], lifecycle)
    _write_json(paths[3], exit_readiness)
    _write_json(paths[4], pnl)
    _write_json(paths[5], drawdown)
    _write_json(paths[6], risk)
    _write_json(paths[7], comparison)
    _write_json(paths[8], pre_acceptance)
    _write_json(paths[9], {"acceptance_blockers": blockers, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    paths[10].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[11].write_text(_recommendations(summary), encoding="utf-8")
    paths[12].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    status = str(summary.get("micro_v2_lifecycle_risk_comparison_status", ""))
    lines = [
        "# Micro V2 Lifecycle/Risk Recommended Commands",
        "",
        f"Status: `{status}`",
        "",
        f"Recommended next action: `{summary.get('recommended_next_action')}`",
        "",
    ]
    if status == "MICRO_V2_OPEN_TRADES_HEALTHY_COLLECTING_EXITS":
        lines.append("Keep V2 running in paper/shadow and wait for paper exits before final acceptance evidence.")
    elif status == "MICRO_V2_OPEN_TRADES_INVALID_RISK_DISTANCE":
        lines.append("Prepare a repair phase for invalid open paper trade risk distance. Do not close or modify trades from this pack.")
    elif status == "MICRO_V2_OPEN_TRADES_PNL_ISSUE":
        lines.append("Prepare a paper PnL repair phase before new clearance or acceptance.")
    elif status == "MICRO_V2_READY_FOR_FINAL_ACCEPTANCE_EVIDENCE_PACK":
        lines.append("Prepare FASE 64 Final Acceptance Evidence Pack.")
    elif status == "MICRO_V2_SAFETY_BLOCKED":
        lines.append("Use stop/rollback checklist and review execution evidence immediately.")
    else:
        lines.append("Continue offline review using generated JSON/CSV evidence.")
    lines.append("")
    lines.append("This pack is offline/read-only and does not approve demo/live execution.")
    return "\n".join(lines) + "\n"


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Lifecycle, Risk/PnL & Preliminary Comparison

Status: `{summary.get('micro_v2_lifecycle_risk_comparison_status')}`

Open trades: `{summary.get('open_trade_count')}`

Closed trades: `{summary.get('closed_trade_count')}`

Acceptance ready: `{summary.get('acceptance_ready')}`

Recommended next action: `{summary.get('recommended_next_action')}`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Lifecycle/Risk Comparison</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _safety(dataset: Mapping[str, Any]) -> bool:
    for group in ("events", "heartbeats", "paper_trades"):
        for row in dataset.get(group, []):
            payload = row.get("payload", {}) if isinstance(row.get("payload"), Mapping) else {}
            if row.get("execution_attempted") or row.get("order_send_called") or row.get("order_check_called"):
                return True
            if payload.get("execution_attempted") or payload.get("order_send_called") or payload.get("order_check_called"):
                return True
    return False


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

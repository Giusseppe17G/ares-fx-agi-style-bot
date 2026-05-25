"""Reports and CLI helpers for paper risk calibration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.paper_risk_review.profile_matching import effective_requested_profile, read_profile_config_profile
from agi_style_forex_bot_mt5.paper_daily_risk_state import validate_micro_daily_risk

from .paper_acceptance_guard import paper_risk_acceptance_clear
from .paper_drawdown_analyzer import analyze_paper_drawdown
from .paper_trade_limit_policy import evaluate_paper_trade_limits
from .safe_profile_builder import build_safe_paper_profile


def run_paper_risk_audit(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/paper_risk",
) -> dict[str, Any]:
    """Analyze paper risk and write audit artifacts."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary = analyze_paper_drawdown(database=database, log_dir=log_dir, reports_root=reports_root)
    drawdown_events = list(summary.pop("drawdown_events", []))
    trade_rows = list(summary.pop("trade_rows", []))
    paths = {
        "summary": output / "paper_risk_summary.json",
        "drawdown": output / "paper_drawdown_events.csv",
        "trade_risk": output / "paper_trade_risk.csv",
        "html": output / "report.html",
    }
    _write_json(paths["summary"], summary)
    pd.DataFrame(drawdown_events).to_csv(paths["drawdown"], index=False)
    pd.DataFrame(_trade_risk_rows(trade_rows)).to_csv(paths["trade_risk"], index=False)
    paths["html"].write_text(f"<html><body><h1>Paper Risk Audit</h1><pre>{json.dumps(summary, indent=2, sort_keys=True)}</pre></body></html>", encoding="utf-8")
    return {**summary, "reports_created": [str(path) for path in paths.values()]}


def build_paper_risk_profile(
    *,
    base_profile: str = "BALANCED_STABLE",
    risk_audit_dir: str | Path = "data/reports/paper_risk",
    output_dir: str | Path = "data/reports/paper_risk",
) -> dict[str, Any]:
    """Build BALANCED_STABLE_MICRO profile artifacts."""

    return build_safe_paper_profile(base_profile=base_profile, risk_audit_dir=risk_audit_dir, output_dir=output_dir)


def run_paper_risk_status(
    *,
    database: TelemetryDatabase,
    profile_config: str | Path | None = None,
    clearance_ledger: str | Path | None = None,
    daily_risk_ledger: str | Path | None = None,
    profile_name: str = "",
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    output_dir: str | Path = "data/reports/paper_risk",
) -> dict[str, Any]:
    """Write and return the current paper risk gate state."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    status = evaluate_paper_trade_limits(database=database, profile_config=profile_config)
    profile_info = _effective_status_profile(profile_name, profile_config)
    clearance = _clearance_status(
        database=database,
        clearance_ledger=clearance_ledger,
        profile_name=str(profile_info.get("requested_profile_canonical", "")),
        profile_config=profile_config,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
    )
    if status.get("blocking_reason") == "PAPER_DRAWDOWN_HALT_BLOCK" and clearance.get("accepted"):
        daily_risk = _daily_risk_status(
            database=database,
            clearance_ledger=clearance_ledger,
            daily_risk_ledger=daily_risk_ledger,
            profile_config=profile_config,
            log_dir=log_dir,
            reports_root=reports_root,
            paper_risk_dir=paper_risk_dir,
        )
        if daily_risk.get("accepted"):
            status.update(
                {
                    "paper_risk_status": "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW",
                    "daily_drawdown_status": "CLEARED_STALE_HALT",
                    "can_open_new_paper_trade": True,
                    "blocking_reason": "",
                    "manual_review_required": False,
                    "cleared_profile": clearance.get("cleared_profile", "BALANCED_STABLE_MICRO"),
                    "paper_risk_clearance_status": clearance.get("paper_risk_clearance_status", "PAPER_RISK_CLEARANCE_ACCEPTED"),
                }
            )
        else:
            status["paper_daily_risk_status"] = daily_risk.get("paper_daily_risk_status", "")
            status["daily_risk_ledger_status"] = daily_risk.get("daily_risk_ledger_status", "")
            status["paper_daily_risk_blocking_reason"] = daily_risk.get("blocking_reason", "")
    else:
        daily_risk = {}
    pnl_audit = _paper_pnl_audit_status(Path(reports_root))
    summary = {
        "mode": "paper-risk-status",
        **profile_info,
        **status,
        "paper_risk_clearance_status": clearance.get("paper_risk_clearance_status", ""),
        "paper_risk_clearance_id": clearance.get("paper_risk_clearance_id", ""),
        "cleared_for_profile": clearance.get("cleared_for_profile", ""),
        "clearance_stale": clearance.get("paper_risk_clearance_status") == "PAPER_RISK_CLEARANCE_STALE",
        "paper_daily_risk_status": daily_risk.get("paper_daily_risk_status", status.get("paper_daily_risk_status", "")),
        "daily_risk_ledger_status": daily_risk.get("daily_risk_ledger_status", status.get("daily_risk_ledger_status", "")),
        "active_today_halt_count": daily_risk.get("active_today_halt_count", 0),
        "stale_halt_count": daily_risk.get("stale_halt_count", 0),
        "can_resume_micro_shadow": daily_risk.get("can_resume_micro_shadow", False),
        "paper_pnl_audit_status": pnl_audit.get("paper_pnl_audit_status", ""),
        "root_cause": pnl_audit.get("root_cause", ""),
        "paper_pnl_recommended_action": pnl_audit.get("recommended_action", ""),
        "block_new_clearance": _blocks_new_clearance(pnl_audit),
        "paper_risk_acceptance_clear": paper_risk_acceptance_clear(status),
        "recommended_action": _recommended_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_risk_status.json"
    _write_json(path, summary)
    summary["reports_created"] = [str(path)]
    return summary


def _clearance_status(
    *,
    database: TelemetryDatabase,
    clearance_ledger: str | Path | None,
    profile_name: str,
    profile_config: str | Path | None,
    log_dir: str | Path,
    reports_root: str | Path,
    paper_risk_dir: str | Path,
) -> dict[str, Any]:
    if not clearance_ledger:
        return {}
    try:
        from agi_style_forex_bot_mt5.paper_risk_review import validate_micro_resume_clearance

        return validate_micro_resume_clearance(
            database=database,
            clearance_ledger=clearance_ledger,
            profile=profile_name,
            profile_config=profile_config,
            log_dir=log_dir,
            reports_root=reports_root,
            paper_risk_dir=paper_risk_dir,
        )
    except Exception as exc:
        return {"accepted": False, "paper_risk_clearance_status": "PAPER_RISK_CLEARANCE_ERROR", "reason": str(exc)}


def _daily_risk_status(
    *,
    database: TelemetryDatabase,
    clearance_ledger: str | Path | None,
    daily_risk_ledger: str | Path | None,
    profile_config: str | Path | None,
    log_dir: str | Path,
    reports_root: str | Path,
    paper_risk_dir: str | Path,
) -> dict[str, Any]:
    try:
        return validate_micro_daily_risk(
            database=database,
            clearance_ledger=clearance_ledger,
            daily_risk_ledger=daily_risk_ledger,
            profile_config=profile_config,
            log_dir=log_dir,
            reports_root=reports_root,
            paper_risk_dir=paper_risk_dir,
        )
    except Exception as exc:
        return {"accepted": False, "paper_daily_risk_status": "PAPER_DAILY_RISK_ERROR", "blocking_reason": str(exc)}


def _effective_status_profile(profile_name: str, profile_config: str | Path | None) -> dict[str, Any]:
    explicit = str(profile_name or "").strip()
    config_profile = read_profile_config_profile(profile_config)
    if explicit and explicit.upper() != "BALANCED":
        return effective_requested_profile(explicit, profile_config)
    if config_profile.get("canonical_profile") == "BALANCED_STABLE_MICRO":
        return effective_requested_profile("", profile_config)
    return effective_requested_profile(explicit, profile_config)


def _trade_risk_rows(trades: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "paper_trade_id": trade.get("paper_trade_id"),
            "symbol": trade.get("symbol"),
            "strategy_name": trade.get("strategy_name"),
            "status": trade.get("status"),
            "profit": trade.get("profit", 0.0),
            "r_multiple": trade.get("r_multiple", 0.0),
            "risk_pct": trade.get("risk_pct", 0.0),
            "entry_time_utc": trade.get("entry_time_utc"),
            "exit_time_utc": trade.get("exit_time_utc"),
            "execution_attempted": False,
        }
        for trade in trades
    ]


def _recommended_action(status: Mapping[str, Any]) -> str:
    reason = str(status.get("blocking_reason", "")).upper()
    if reason == "PAPER_MAX_OPEN_TRADES_BLOCK":
        return "Wait for the existing paper trade to close or inspect paper-open-trades before resuming."
    if reason == "PAPER_DAILY_TRADE_LIMIT_BLOCK":
        return "Stop opening new paper entries for today; continue observation tomorrow."
    if reason in {"PAPER_COOLDOWN_BLOCK", "PAPER_DRAWDOWN_HALT_BLOCK"}:
        return "Keep paper shadow paused until cooldown/manual review completes."
    return "Paper risk gate is clear for paper-only observation."


def _paper_pnl_audit_status(reports_root: Path) -> dict[str, Any]:
    path = reports_root / "paper_pnl_audit" / "paper_pnl_audit_summary.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _blocks_new_clearance(pnl_audit: Mapping[str, Any]) -> bool:
    status = str(pnl_audit.get("paper_pnl_audit_status", "")).upper()
    return status in {
        "PAPER_PNL_SCALING_BUG",
        "MICRO_RISK_NOT_APPLIED",
        "VALID_MICRO_DRAWDOWN_HALT",
        "PAPER_PNL_AUDIT_INCONCLUSIVE",
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

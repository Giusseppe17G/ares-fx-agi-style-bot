"""Validate BALANCED_STABLE_MICRO manual clearance before paper resume."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .clearance_ledger import clearance_is_stale, latest_clearance, load_clearance_ledger
from .drawdown_halt_loader import load_drawdown_halt_context
from .profile_matching import effective_requested_profile, normalize_profile_name


def validate_micro_resume_clearance(
    *,
    database: TelemetryDatabase,
    clearance_ledger: str | Path | None,
    profile: str = "BALANCED_STABLE_MICRO",
    profile_config: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
) -> dict[str, Any]:
    """Return whether the ledger clears the latest halt for the requested profile."""

    requested = effective_requested_profile(profile, profile_config)
    requested_canonical = str(requested.get("requested_profile_canonical", ""))
    if requested_canonical != "BALANCED_STABLE_MICRO":
        return _result(False, "PAPER_RISK_CLEARANCE_PROFILE_MISMATCH", "Clearance is only valid for BALANCED_STABLE_MICRO.", requested=requested)
    if not clearance_ledger or not Path(clearance_ledger).exists():
        return _result(False, "PAPER_RISK_CLEARANCE_REQUIRED", "BALANCED_STABLE_MICRO requires --paper-risk-clearance.", requested=requested)
    ledger = load_clearance_ledger(clearance_ledger)
    clearance = latest_clearance(ledger)
    if not clearance:
        return _result(False, "PAPER_RISK_CLEARANCE_REQUIRED", "Clearance ledger has no entries.", requested=requested)
    cleared_canonical = normalize_profile_name(clearance.get("canonical_cleared_for_profile") or clearance.get("cleared_for_profile"))
    if cleared_canonical != requested_canonical:
        return _result(False, "PAPER_RISK_CLEARANCE_PROFILE_MISMATCH", "Clearance profile does not match requested paper risk profile.", clearance, requested=requested, cleared_canonical=cleared_canonical)
    context = load_drawdown_halt_context(database=database, log_dir=log_dir, reports_root=reports_root, paper_risk_dir=paper_risk_dir)
    latest_halt = str(context.get("latest_halt_utc") or "")
    if clearance_is_stale(clearance, latest_halt):
        return _result(False, "PAPER_RISK_CLEARANCE_STALE", "A newer paper drawdown halt exists after the clearance.", clearance, latest_halt, requested=requested, cleared_canonical=cleared_canonical)
    return {
        **_result(True, "PAPER_RISK_CLEARANCE_ACCEPTED", "Manual clearance is valid for BALANCED_STABLE_MICRO paper/shadow only.", clearance, latest_halt, requested=requested, cleared_canonical=cleared_canonical),
        "paper_risk_clearance_id": clearance.get("clearance_id", ""),
        "cleared_for_profile": cleared_canonical,
        "cleared_profile": cleared_canonical,
        "cleared_for_paper_shadow": True,
        "not_for_demo_live": True,
    }


def _result(
    accepted: bool,
    status: str,
    reason: str,
    clearance: dict[str, Any] | None = None,
    latest_halt_utc: str = "",
    *,
    requested: dict[str, Any] | None = None,
    cleared_canonical: str = "",
) -> dict[str, Any]:
    requested = requested or {}
    return {
        "accepted": accepted,
        "paper_risk_clearance_status": status,
        "classification": status,
        "reason": reason,
        "clearance": clearance or {},
        "requested_profile": requested.get("requested_profile", ""),
        "requested_profile_canonical": requested.get("requested_profile_canonical", ""),
        "profile_config_profile": requested.get("profile_config_profile", ""),
        "profile_config_profile_canonical": requested.get("profile_config_profile_canonical", ""),
        "profile_warnings": requested.get("profile_warnings", []),
        "cleared_for_profile_canonical": cleared_canonical,
        "latest_halt_utc": latest_halt_utc,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }

from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_evidence.operational_acceptance_gate import decide_operational_acceptance
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_legacy_drawdown_quarantined_does_not_block_acceptance() -> None:
    decision = _decision(
        metrics={"paper_drawdown_status": "PAPER_DAILY_DRAWDOWN", "closed_trades": 0},
        legacy={"legacy_drawdown_status": "LEGACY_DRAWDOWN_QUARANTINED", "legacy_drawdown_quarantined": True, "active_scaled_events_count": 0, "drawdown_basis": "SCALED_PAPER_PNL_ONLY"},
        paper_risk={"paper_risk_status": "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW", "current_open_paper_trades": 0, "max_open_paper_trades": 1},
    )

    assert decision["decision"] == "NEEDS_MORE_FORWARD_DATA"
    assert decision["acceptance_drawdown_blocking"] is False
    assert decision["legacy_drawdown_quarantined"] is True
    assert decision["active_scaled_drawdown_count"] == 0


def test_active_scaled_drawdown_blocks_acceptance() -> None:
    decision = _decision(
        metrics={"paper_drawdown_status": "PAPER_DAILY_DRAWDOWN", "closed_trades": 0},
        legacy={"legacy_drawdown_status": "ACTIVE_SCALED_DRAWDOWN_BLOCK", "legacy_drawdown_quarantined": False, "active_scaled_events_count": 1, "drawdown_basis": "SCALED_PAPER_PNL_ONLY"},
        paper_risk={"paper_risk_status": "PAPER_RISK_BLOCKED", "blocking_reason": "PAPER_DRAWDOWN_HALT_BLOCK"},
    )

    assert decision["decision"] == "PAUSE_FORWARD_SHADOW"
    assert decision["acceptance_drawdown_blocking"] is True
    assert decision["active_scaled_drawdown_count"] == 1


def test_telemetry_clear_legacy_drawdown_enough_data_continues() -> None:
    decision = _decision(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 100, "hours_observed": 30, "open_paper_trades": 0},
        metrics={"paper_drawdown_status": "PAPER_DAILY_DRAWDOWN", "closed_trades": 12},
        drift={"classification": "NO_DRIFT"},
        legacy={"legacy_drawdown_status": "LEGACY_DRAWDOWN_QUARANTINED", "legacy_drawdown_quarantined": True, "active_scaled_events_count": 0, "drawdown_basis": "SCALED_PAPER_PNL_ONLY"},
        paper_risk={"paper_risk_status": "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW", "current_open_paper_trades": 0, "max_open_paper_trades": 1},
    )

    assert decision["decision"] == "CONTINUE_FORWARD_SHADOW"
    assert decision["acceptance_drawdown_blocking"] is False


def test_legacy_drawdown_not_blocking_even_if_non_drawdown_paper_risk_block() -> None:
    decision = _decision(
        metrics={"paper_drawdown_status": "PAPER_DAILY_DRAWDOWN", "closed_trades": 0},
        legacy={"legacy_drawdown_status": "LEGACY_DRAWDOWN_QUARANTINED", "legacy_drawdown_quarantined": True, "active_scaled_events_count": 0, "drawdown_basis": "SCALED_PAPER_PNL_ONLY"},
        paper_risk={"paper_risk_status": "PAPER_RISK_BLOCKED", "blocking_reason": "PAPER_COOLDOWN_BLOCK", "current_open_paper_trades": 0, "max_open_paper_trades": 1},
    )

    assert decision["decision"] == "NEEDS_MORE_FORWARD_DATA"
    assert decision["acceptance_drawdown_blocking"] is False
    assert decision["paper_risk_status"] == "PAPER_RISK_BLOCKED"


def test_acceptance_drawdown_policy_audit_cli(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "forward.sqlite3"
    db = TelemetryDatabase(sqlite)
    db.close()
    reports = tmp_path / "reports"
    _write_report_context(reports)

    assert cli.main([
        "--mode",
        "acceptance-drawdown-policy-audit",
        "--sqlite",
        str(sqlite),
        "--log-dir",
        str(tmp_path / "logs"),
        "--reports-root",
        str(reports),
        "--paper-risk-dir",
        str(reports / "paper_risk"),
        "--daily-risk-dir",
        str(reports / "paper_daily_risk"),
        "--pnl-audit-dir",
        str(reports / "paper_pnl_audit"),
        "--clearance-ledger",
        str(reports / "paper_risk_review" / "paper_risk_clearance_ledger.json"),
        "--daily-risk-ledger",
        str(reports / "paper_daily_risk" / "paper_daily_risk_ledger.json"),
        "--profile-config",
        str(reports / "paper_risk" / "balanced_stable_micro.ini"),
        "--output-dir",
        str(reports / "forward_evidence"),
    ]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert (reports / "forward_evidence" / "acceptance_drawdown_policy_summary.json").exists()


def _decision(
    *,
    evidence: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
    drift: dict[str, object] | None = None,
    legacy: dict[str, object] | None = None,
    paper_risk: dict[str, object] | None = None,
) -> dict[str, object]:
    return decide_operational_acceptance(
        evidence=evidence or {"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1, "open_paper_trades": 0},
        metrics=metrics or {"paper_drawdown_status": "OK", "closed_trades": 0},
        drift=drift or {"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_HISTORICAL_QUARANTINED", "telemetry_acceptance_clear": True, "active_blocking_count": 0, "historical_unreviewed_count": 0},
        paper_risk=paper_risk or {},
        legacy_drawdown=legacy or {},
    )


def _write_report_context(root: Path) -> None:
    for name in ("paper_risk", "paper_risk_review", "paper_daily_risk", "paper_pnl_audit", "stable_gate", "execution_evidence", "telemetry_repair"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "paper_risk" / "balanced_stable_micro.ini").write_text("profile=BALANCED_STABLE_MICRO\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\nPAPER_RISK_MULTIPLIER=0.1\n", encoding="utf-8")
    (root / "paper_pnl_audit" / "paper_pnl_scaling_check.json").write_text(json.dumps({"paper_pnl_scaling_status": "PAPER_PNL_SCALING_FIXED", "multiplier_application_ready": True, "created_at_utc": "2026-05-26T00:00:00+00:00"}), encoding="utf-8")
    (root / "paper_pnl_audit" / "paper_pnl_audit_summary.json").write_text(json.dumps({"current_engine_multiplier_ready": True, "post_fix_utc": "2026-05-26T00:00:00+00:00"}), encoding="utf-8")
    (root / "paper_risk_review" / "paper_risk_clearance_ledger.json").write_text(json.dumps({"clearances": [{"clearance_id": "c1", "created_at_utc": "2026-05-26T00:00:00+00:00", "cleared_for_profile": "BALANCED_STABLE_MICRO", "canonical_cleared_for_profile": "BALANCED_STABLE_MICRO"}]}), encoding="utf-8")
    (root / "paper_daily_risk" / "paper_daily_risk_ledger.json").write_text(json.dumps({"clearances": [{"clearance_id": "d1", "created_at_utc": "2026-05-26T00:01:00+00:00", "cleared_for_profile": "BALANCED_STABLE_MICRO"}]}), encoding="utf-8")

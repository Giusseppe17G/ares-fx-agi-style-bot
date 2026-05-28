from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.paper_trading.config_error_root_cause import run_config_error_root_cause_audit
from agi_style_forex_bot_mt5.paper_trading.paper_state_recovery import run_paper_state_recovery_audit
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_missing_profile_config_detected(tmp_path: Path) -> None:
    db = _db_with_config_error(tmp_path)
    try:
        summary = run_config_error_root_cause_audit(
            database=db,
            profile_config=tmp_path / "missing.ini",
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "out",
        )
    finally:
        db.close()

    assert summary["config_error_root_cause"] == "MISSING_PROFILE_CONFIG"
    assert summary["execution_attempted"] is False


def test_missing_stable_gate_detected(tmp_path: Path) -> None:
    db = _db_with_config_error(tmp_path)
    try:
        summary = run_config_error_root_cause_audit(
            database=db,
            log_dir=tmp_path / "logs",
            profile_config=_profile(tmp_path),
            stable_gate=tmp_path / "missing_stable.json",
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "out",
        )
    finally:
        db.close()

    assert summary["config_error_root_cause"] == "MISSING_STABLE_GATE"


def test_invalid_schema_detected(tmp_path: Path) -> None:
    db = _db_with_config_error(tmp_path)
    invalid_profile = _file(tmp_path / "bad.ini", "SIGNAL_PROFILE=BALANCED_STABLE_MICRO\nPAPER_ONLY=true\n")
    try:
        summary = run_config_error_root_cause_audit(
            database=db,
            profile_config=invalid_profile,
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "out",
        )
    finally:
        db.close()

    assert summary["config_error_root_cause"] == "INVALID_PROFILE_CONFIG_SCHEMA"


def test_profile_mismatch_detected(tmp_path: Path) -> None:
    db = _db_with_config_error(tmp_path)
    wrong = _file(tmp_path / "wrong.ini", "SIGNAL_PROFILE=BALANCED_STABLE\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\nPAPER_RISK_MULTIPLIER=0.1\n")
    try:
        summary = run_config_error_root_cause_audit(
            database=db,
            profile_config=wrong,
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "out",
        )
    finally:
        db.close()

    assert summary["config_error_root_cause"] == "PROFILE_MISMATCH"


def test_forward_shadow_exception_detected_from_open_trade_risk_distance(tmp_path: Path) -> None:
    db = _db_with_config_error(tmp_path, latest_error="paper trade has invalid risk distance")
    try:
        db.insert_paper_trade(_trade("t1", entry=1.1, sl=1.1))
        summary = run_config_error_root_cause_audit(
            database=db,
            profile_config=_profile(tmp_path),
            log_dir=tmp_path / "logs",
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "out",
        )
        open_rows = db.fetch_open_paper_trades()
    finally:
        db.close()

    assert summary["config_error_root_cause"] == "FORWARD_SHADOW_CONFIG_EXCEPTION"
    assert "invalid risk distance" in summary["config_error_evidence"]
    assert len(open_rows) == 1


def test_unknown_config_error_only_without_evidence(tmp_path: Path) -> None:
    db = _db_with_config_error(tmp_path, latest_error="")
    try:
        summary = run_config_error_root_cause_audit(
            database=db,
            log_dir=tmp_path / "logs",
            profile_config=_profile(tmp_path),
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "out",
        )
    finally:
        db.close()

    assert summary["config_error_root_cause"] == "UNKNOWN_CONFIG_ERROR"


def test_paper_state_recovery_uses_root_cause_audit(tmp_path: Path) -> None:
    db = _db_with_config_error(tmp_path, latest_error="paper trade has invalid risk distance")
    try:
        db.insert_paper_trade(_trade("t1", entry=1.1, sl=1.1))
        run_config_error_root_cause_audit(
            database=db,
            reports_root=tmp_path,
            profile_config=_profile(tmp_path),
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "config_error_recovery",
        )
        recovery = run_paper_state_recovery_audit(
            database=db,
            reports_root=tmp_path,
            profile_config=_profile(tmp_path),
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_clearance(tmp_path),
            daily_risk_ledger=_daily_ledger(tmp_path),
            output_dir=tmp_path / "recovery",
        )
    finally:
        db.close()

    assert recovery["config_error_root_cause"] == "FORWARD_SHADOW_CONFIG_EXCEPTION"
    assert recovery["open_trade_audit_status"] == "INVALID_RISK_OPEN_PAPER_TRADE"
    assert recovery["requires_paper_only_close"] is False


def test_cli_config_error_modes(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    db = TelemetryDatabase(sqlite)
    try:
        db.update_operational_state({"latest_exit_reason": "CONFIG_ERROR", "halt_reason": "PAPER_STATE_ERROR", "latest_forward_shadow_error": "paper trade has invalid risk distance"})
    finally:
        db.close()
    out = tmp_path / "out"
    args = [
        "--sqlite",
        str(sqlite),
        "--profile-config",
        str(_profile(tmp_path)),
        "--stable-gate",
        str(_stable_gate(tmp_path)),
        "--clearance-ledger",
        str(_clearance(tmp_path)),
        "--daily-risk-ledger",
        str(_daily_ledger(tmp_path)),
        "--output-dir",
        str(out),
    ]
    assert cli.main(["--mode", "config-error-root-cause-audit", *args]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["config_error_root_cause"] == "FORWARD_SHADOW_CONFIG_EXCEPTION"
    assert cli.main(["--mode", "config-error-fix-plan", "--output-dir", str(out)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["execution_attempted"] is False
    assert (out / "CONFIG_ERROR_FIX_PLAN.md").exists()


def _db_with_config_error(tmp_path: Path, latest_error: str = "config error") -> TelemetryDatabase:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    db.update_operational_state({"latest_exit_reason": "CONFIG_ERROR", "halt_reason": "PAPER_STATE_ERROR", "latest_forward_shadow_error": latest_error})
    return db


def _trade(trade_id: str, *, entry: float = 1.1, sl: float = 1.09) -> dict[str, object]:
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig-{trade_id}",
        "idempotency_key": f"idem-{trade_id}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": datetime.now(timezone.utc).isoformat(),
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": 1.12,
        "lot": 0.01,
        "risk_pct": 0.1,
        "risk_amount": 1.0,
        "strategy_name": "test_strategy",
        "strategy_version": "1",
        "regime": "RANGE",
        "session": "LONDON",
        "score": 70,
        "reasons": [],
        "status": "OPEN",
        "scaled_paper_pnl": 0.0,
    }


def _profile(tmp_path: Path) -> Path:
    return _file(tmp_path / "balanced_stable_micro.ini", "SIGNAL_PROFILE=BALANCED_STABLE_MICRO\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\nPAPER_RISK_MULTIPLIER=0.1\n")


def _stable_gate(tmp_path: Path) -> Path:
    return _file(tmp_path / "stable_gate.json", {"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True})


def _clearance(tmp_path: Path) -> Path:
    return _file(
        tmp_path / "clearance.json",
        {
            "clearances": [
                {
                    "created_at_utc": "2026-05-25T07:06:17+00:00",
                    "cleared_for_profile": "BALANCED_STABLE_MICRO",
                    "canonical_cleared_for_profile": "BALANCED_STABLE_MICRO",
                    "cleared_for_paper_shadow": True,
                }
            ]
        },
    )


def _daily_ledger(tmp_path: Path) -> Path:
    return _file(
        tmp_path / "daily.json",
        {
            "daily_risk_clearances": [
                {
                    "created_at_utc": "2026-05-25T07:06:23+00:00",
                    "cleared_for_profile": "BALANCED_STABLE_MICRO",
                    "canonical_cleared_for_profile": "BALANCED_STABLE_MICRO",
                    "cleared_for_paper_shadow": True,
                }
            ]
        },
    )


def _file(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path

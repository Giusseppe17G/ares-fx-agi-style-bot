from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.paper_risk_calibration import (
    build_paper_risk_profile,
    evaluate_paper_trade_limits,
    run_paper_risk_audit,
)
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _trade(
    trade_id: str,
    *,
    status: str = "OPEN",
    opened: datetime | None = None,
    closed: datetime | None = None,
    profit: float = 0.0,
) -> dict[str, object]:
    opened = opened or datetime.now(timezone.utc)
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig_{trade_id}",
        "idempotency_key": f"paper:{trade_id}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": opened.isoformat(),
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
        "lot": 0.01,
        "risk_pct": 0.05,
        "risk_amount": 1.0,
        "strategy_name": "strategy_ensemble",
        "strategy_version": "test",
        "regime": "RANGE",
        "session": "LONDON",
        "score": 60.0,
        "reasons": (),
        "status": status,
        "profit": profit,
        "r_multiple": profit,
        "exit_time_utc": closed.isoformat() if closed else None,
        "metadata": {"profile": "BALANCED_STABLE_MICRO"},
    }


def _micro_ini(path: Path, **overrides: object) -> Path:
    values: dict[str, object] = {
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO",
        "PROFILE_TYPE": "PAPER_SHADOW_ONLY",
        "PAPER_ONLY": "true",
        "STABILITY_FILTERS_APPLIED": "true",
        "PAPER_RISK_MULTIPLIER": "0.10",
        "MAX_OPEN_PAPER_TRADES": "1",
        "MAX_PAPER_TRADES_PER_DAY": "2",
        "COOLDOWN_AFTER_LOSS_MINUTES": "120",
        "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES": "1440",
        "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT": "true",
        "MANUAL_RESUME_REQUIRED": "true",
    }
    values.update(overrides)
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path


def test_paper_risk_audit_detects_daily_drawdown_halt(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_paper_trade(_trade("ptr_loss", status="CLOSED", closed=datetime.now(timezone.utc), profit=-50.0))
        db.insert_alert({"alert_code": "PAPER_DAILY_DRAWDOWN", "severity": "CRITICAL", "deduplication_key": "dd"})
        summary = run_paper_risk_audit(database=db, log_dir=tmp_path / "logs", reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
        assert summary["daily_drawdown_events"] == 1
        assert summary["classification"] in {"PAPER_PROFILE_NEEDS_MICRO_RISK", "PAPER_RISK_TOO_HIGH"}
        assert (tmp_path / "out" / "paper_risk_summary.json").exists()
    finally:
        db.close()


def test_build_paper_risk_profile_creates_micro_ini(tmp_path: Path) -> None:
    (tmp_path / "audit").mkdir()
    (tmp_path / "audit" / "paper_risk_summary.json").write_text(json.dumps({"classification": "PAPER_PROFILE_NEEDS_MICRO_RISK"}), encoding="utf-8")
    summary = build_paper_risk_profile(base_profile="BALANCED_STABLE", risk_audit_dir=tmp_path / "audit", output_dir=tmp_path / "out")
    ini = Path(summary["profile_config"])
    assert ini.exists()
    text = ini.read_text(encoding="utf-8")
    assert "SIGNAL_PROFILE=BALANCED_STABLE_MICRO" in text
    assert "NOT_FOR_DEMO_LIVE=true" in text
    assert "PAPER_ONLY=true" in text


def test_balanced_stable_micro_valid_only_paper_shadow(tmp_path: Path) -> None:
    profile_config = _micro_ini(tmp_path / "balanced_stable_micro.ini")
    cfg = BotConfig(
        signal_profile="BALANCED_STABLE_MICRO",
        profile_config=str(profile_config),
        profile_type="PAPER_SHADOW_ONLY",
        paper_only=True,
        max_open_paper_trades=1,
        paper_risk_multiplier=0.1,
    )
    cfg.validate_safety()
    try:
        BotConfig(signal_profile="BALANCED_STABLE_MICRO").validate_safety()
        raise AssertionError("MICRO profile without config should fail")
    except ValueError as exc:
        assert "MICRO_PROFILE_CONFIG_REQUIRED" in str(exc)


def test_policy_blocks_max_open_trades(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile_config = _micro_ini(tmp_path / "micro.ini")
    try:
        db.insert_paper_trade(_trade("ptr_open"))
        status = evaluate_paper_trade_limits(database=db, profile_config=profile_config)
        assert status["can_open_new_paper_trade"] is False
        assert status["blocking_reason"] == "PAPER_MAX_OPEN_TRADES_BLOCK"
    finally:
        db.close()


def test_policy_blocks_daily_trade_limit(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile_config = _micro_ini(tmp_path / "micro.ini", MAX_OPEN_PAPER_TRADES="5", MAX_PAPER_TRADES_PER_DAY="2")
    now = datetime.now(timezone.utc)
    try:
        db.insert_paper_trade(_trade("ptr_1", status="CLOSED", opened=now, closed=now, profit=1.0))
        db.insert_paper_trade(_trade("ptr_2", status="CLOSED", opened=now, closed=now, profit=1.0))
        status = evaluate_paper_trade_limits(database=db, profile_config=profile_config, now=now)
        assert status["blocking_reason"] == "PAPER_DAILY_TRADE_LIMIT_BLOCK"
    finally:
        db.close()


def test_policy_blocks_cooldown_and_no_auto_resume_after_halt(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile_config = _micro_ini(tmp_path / "micro.ini", MAX_OPEN_PAPER_TRADES="5")
    now = datetime.now(timezone.utc)
    try:
        db.insert_paper_trade(_trade("ptr_loss", status="CLOSED", opened=now - timedelta(minutes=30), closed=now - timedelta(minutes=10), profit=-1.0))
        status = evaluate_paper_trade_limits(database=db, profile_config=profile_config, now=now)
        assert status["blocking_reason"] == "PAPER_COOLDOWN_BLOCK"
        db.set_shadow_paused(True, reason="PAPER_DAILY_DRAWDOWN_HALT", paused_by="test")
        status = evaluate_paper_trade_limits(database=db, profile_config=profile_config, now=now + timedelta(hours=3))
        assert status["blocking_reason"] == "PAPER_DRAWDOWN_HALT_BLOCK"
    finally:
        db.close()


def test_forward_shadow_guard_blocks_with_micro_profile(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile_config = _micro_ini(tmp_path / "micro.ini")
    try:
        db.insert_paper_trade(_trade("ptr_open"))
        cfg = BotConfig(
            signal_profile="BALANCED_STABLE_MICRO",
            profile_config=str(profile_config),
            profile_type="PAPER_SHADOW_ONLY",
            paper_only=True,
            max_open_paper_trades=1,
            paper_risk_multiplier=0.1,
        )
        bot = ForwardShadowBot(config=cfg, symbols=("EURUSD",), audit_logger=JsonlAuditLogger(tmp_path / "logs"), database=db, max_cycles=0)
        status = bot._paper_risk_guard()
        assert status["blocking_reason"] == "PAPER_MAX_OPEN_TRADES_BLOCK"
    finally:
        db.close()


def test_forward_evidence_includes_paper_risk_status(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "paper.sqlite3"
    db = TelemetryDatabase(db_path)
    try:
        reports = tmp_path / "reports"
        (reports / "stable_gate").mkdir(parents=True)
        (reports / "stable_gate" / "stable_gate_summary.json").write_text('{"stable_gate_decision":"PAPER_SHADOW_READY","paper_shadow_ready":true,"execution_attempted":false}', encoding="utf-8")
    finally:
        db.close()
    assert cli.main(["--mode", "forward-evidence", "--sqlite", str(db_path), "--log-dir", str(tmp_path / "logs"), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "evidence")]) == 0
    assert '"paper_risk_status"' in capsys.readouterr().out


def test_paper_risk_cli_modes_do_not_attempt_execution(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "paper.sqlite3"
    TelemetryDatabase(db_path).close()
    assert cli.main(["--mode", "paper-risk-audit", "--sqlite", str(db_path), "--log-dir", str(tmp_path / "logs"), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "risk")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "build-paper-risk-profile", "--risk-audit-dir", str(tmp_path / "risk"), "--output-dir", str(tmp_path / "risk")]) == 0
    assert '"profile": "BALANCED_STABLE_MICRO"' in capsys.readouterr().out
    assert cli.main(["--mode", "paper-risk-status", "--sqlite", str(db_path), "--profile-config", str(tmp_path / "risk" / "balanced_stable_micro.ini"), "--output-dir", str(tmp_path / "risk")]) == 0
    out = capsys.readouterr().out
    assert '"order_send_called": false' in out
    assert '"order_check_called": false' in out

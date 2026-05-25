from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState
from agi_style_forex_bot_mt5.paper_pnl_audit import run_paper_pnl_audit, run_paper_pnl_scaling_check, run_paper_risk_post_fix_gate
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.paper_trading.paper_performance import paper_metrics
from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import calculate_scaled_paper_pnl
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _micro_ini(path: Path, include_multiplier: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "SIGNAL_PROFILE=BALANCED_STABLE_MICRO",
        "PROFILE_TYPE=PAPER_SHADOW_ONLY",
        "PAPER_ONLY=true",
        "NOT_FOR_DEMO_LIVE=true",
        "MAX_OPEN_PAPER_TRADES=1",
        "MAX_PAPER_TRADES_PER_DAY=2",
    ]
    if include_multiplier:
        lines.extend(["PAPER_RISK_MULTIPLIER=0.1", "paper_risk_multiplier=0.1"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _closed_trade(trade_id: str, *, raw: float = -100.0, scaled: float = -10.0, multiplier_applied: bool = True) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig_{trade_id}",
        "idempotency_key": f"paper:{trade_id}",
        "symbol": "EURUSD",
        "status": "CLOSED",
        "entry_time_utc": now,
        "exit_time_utc": now,
        "entry_price": 1.1000,
        "exit_price": 1.0990,
        "sl_price": 1.0990,
        "tp_price": 1.1020,
        "direction": "BUY",
        "lot": 1.0,
        "profit": scaled,
        "raw_pnl": raw,
        "scaled_paper_pnl": scaled,
        "paper_risk_multiplier": 0.1,
        "risk_multiplier": 1.0,
        "multiplier_applied": multiplier_applied,
        "pnl_formula_version": "paper_pnl_scaled_v1",
        "pnl_scaling_status": "SCALED_PAPER_PNL",
        "r_multiple": scaled / 100.0,
        "strategy_name": "trend_pullback",
        "metadata": {"profile": "BALANCED_STABLE_MICRO", "paper_risk_multiplier": 0.1, "multiplier_applied": multiplier_applied},
    }


def test_paper_pnl_engine_applies_multiplier_and_preserves_raw(tmp_path: Path) -> None:
    config = _micro_ini(tmp_path / "balanced_stable_micro.ini")
    result = calculate_scaled_paper_pnl(
        {"symbol": "EURUSD", "direction": "BUY", "entry_price": 1.1000, "exit_price": 1.0990, "lot": 1.0},
        profile_config=config,
        symbol_contract={"tick_size": 0.00001, "tick_value": 1.0, "point": 0.00001},
    )
    assert round(result["raw_pnl"], 6) == -100.0
    assert round(result["scaled_paper_pnl"], 6) == -10.0
    assert result["paper_risk_multiplier"] == 0.1
    assert result["multiplier_applied"] is True


def test_scaled_paper_pnl_is_used_for_drawdown() -> None:
    metrics = paper_metrics([_closed_trade("scaled_loss", raw=-100.0, scaled=-10.0)])
    assert metrics["raw_drawdown_shadow"] == -100.0
    assert metrics["scaled_drawdown_shadow"] == -10.0
    assert metrics["daily_drawdown_shadow"] == -10.0
    assert metrics["drawdown_basis"] == "SCALED_PAPER_PNL"


def test_legacy_unscaled_events_do_not_mark_current_engine_unfixed(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports = tmp_path / "reports"
    paper_risk = reports / "paper_risk"
    daily = reports / "paper_daily_risk"
    paper_risk.mkdir(parents=True)
    daily.mkdir(parents=True)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini")
    try:
        legacy = dict(_closed_trade("legacy", raw=-100.0, scaled=-100.0, multiplier_applied=False))
        legacy.pop("raw_pnl", None)
        legacy.pop("scaled_paper_pnl", None)
        legacy.pop("multiplier_applied", None)
        db.insert_paper_trade(legacy)
        summary = run_paper_pnl_audit(database=db, reports_root=reports, paper_risk_dir=paper_risk, daily_risk_dir=daily, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_audit_status"] == "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"
        assert summary["current_engine_multiplier_ready"] is True
        assert summary["legacy_unscaled_events"] is True
    finally:
        db.close()


def test_paper_pnl_scaling_check_detects_config_and_legacy(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    config = _micro_ini(tmp_path / "balanced_stable_micro.ini")
    try:
        db.insert_paper_trade(_closed_trade("scaled"))
        summary = run_paper_pnl_scaling_check(database=db, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_scaling_status"] == "PAPER_PNL_SCALING_FIXED"
        assert summary["profile_multiplier"] == 0.1
        assert summary["multiplier_application_ready"] is True
    finally:
        db.close()


def test_paper_risk_post_fix_gate_ready_when_scaling_fixed(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    audit_dir = reports / "paper_pnl_audit"
    execution_dir = reports / "execution_evidence"
    telemetry_dir = reports / "telemetry_repair"
    audit_dir.mkdir(parents=True)
    execution_dir.mkdir(parents=True)
    telemetry_dir.mkdir(parents=True)
    audit_dir.joinpath("paper_pnl_scaling_check.json").write_text(json.dumps({"paper_pnl_scaling_status": "PAPER_PNL_SCALING_FIXED", "legacy_unscaled_trade_count": 0, "scaled_trade_count": 1}), encoding="utf-8")
    audit_dir.joinpath("paper_pnl_audit_summary.json").write_text(json.dumps({"paper_pnl_audit_status": "PAPER_PNL_SCALING_FIXED"}), encoding="utf-8")
    execution_dir.joinpath("execution_evidence_summary.json").write_text(json.dumps({"blocking_findings_count": 0}), encoding="utf-8")
    telemetry_dir.joinpath("telemetry_timestamp_summary.json").write_text(json.dumps({"active_blocking_count": 0}), encoding="utf-8")
    summary = run_paper_risk_post_fix_gate(reports_root=reports, output_dir=audit_dir)
    assert summary["decision"] == "READY_FOR_NEW_MICRO_CLEARANCE"


def test_forward_shadow_micro_fails_if_multiplier_missing(tmp_path: Path, capsys) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    db.close()
    config = _micro_ini(tmp_path / "balanced_stable_micro.ini", include_multiplier=False)
    stable_gate = tmp_path / "stable_gate.json"
    stable_gate.write_text(json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True, "execution_attempted": False}), encoding="utf-8")
    assert (
        cli.main(
            [
                "--mode",
                "forward-shadow",
                "--sqlite",
                str(tmp_path / "paper.sqlite3"),
                "--signal-profile",
                "BALANCED_STABLE_MICRO",
                "--profile-config",
                str(config),
                "--stable-gate",
                str(stable_gate),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "PAPER_PNL_SCALING_CONFIG_MISSING" in out
    assert '"execution_attempted": false' in out


def test_forward_shadow_micro_registers_scaling_active(tmp_path: Path, monkeypatch) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    config_path = _micro_ini(tmp_path / "balanced_stable_micro.ini")
    bot_config = BotConfig(signal_profile="BALANCED_STABLE_MICRO", profile_config=str(config_path), profile_type="PAPER_SHADOW_ONLY", paper_only=True, paper_risk_multiplier=0.1, max_open_paper_trades=1, max_paper_trades_per_day=2)
    bot = ForwardShadowBot(
        config=bot_config,
        symbols=["EURUSD"],
        audit_logger=JsonlAuditLogger(tmp_path / "logs"),
        database=db,
        max_cycles=0,
        stable_gate_confirmed=True,
        stable_gate_decision="PAPER_SHADOW_READY",
    )
    monkeypatch.setattr(bot, "_connect", lambda: True)
    monkeypatch.setattr(bot, "_read_account", lambda: AccountState(login=1, trade_mode="DEMO", balance=1000, equity=1000, margin_free=1000, is_demo=True, trade_allowed=False))
    try:
        summary = bot.run()
        events = [json.loads(row["payload_json"]) for row in db.fetch_all("events")]
        assert any(event.get("event_type") == "PAPER_PNL_SCALING_ACTIVE" or event.get("paper_risk_multiplier") == 0.1 for event in events)
        assert summary.execution_attempted is False
        assert summary.order_send_called is False
        assert summary.order_check_called is False
    finally:
        db.close()

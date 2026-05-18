from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import SignalAction
from agi_style_forex_bot_mt5.observability import HeartbeatWriter
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot, PaperTrade, build_stable_health, detect_stable_forward_drift
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter


def test_forward_shadow_balanced_stable_blocks_without_gate(tmp_path: Path, capsys) -> None:
    ini = _stable_ini(tmp_path)

    code = cli.main(
        [
            "--mode",
            "forward-shadow",
            "--sqlite",
            str(tmp_path / "stable.sqlite3"),
            "--signal-profile",
            "BALANCED_STABLE",
            "--profile-config",
            str(ini),
            "--stable-gate",
            str(tmp_path / "missing_gate.json"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["classification"] == "STABLE_GATE_REQUIRED"
    assert payload["execution_attempted"] is False
    assert payload["order_send_called"] is False
    assert payload["order_check_called"] is False


def test_forward_shadow_balanced_stable_accepts_paper_ready_gate(tmp_path: Path, monkeypatch, capsys) -> None:
    ini = _stable_ini(tmp_path)
    gate = _stable_gate(tmp_path)

    class FakeBot:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run(self):
            return SimpleNamespace(
                mode="forward-shadow",
                mt5_connected=False,
                cycles_completed=0,
                open_trades=0,
                paper_trades_opened=0,
                paper_trades_closed=0,
                heartbeat_written=False,
                alerts_emitted=0,
                telegram_commands_processed=0,
                shadow_paused=False,
                execution_attempted=False,
                signal_profile_used=self.kwargs["config"].signal_profile,
                stable_gate_confirmed=self.kwargs["stable_gate_confirmed"],
                order_send_called=False,
                order_check_called=False,
            )

    monkeypatch.setattr(cli, "ForwardShadowBot", FakeBot)
    code = cli.main(
        [
            "--mode",
            "forward-shadow",
            "--sqlite",
            str(tmp_path / "stable.sqlite3"),
            "--signal-profile",
            "BALANCED_STABLE",
            "--profile-config",
            str(ini),
            "--stable-gate",
            str(gate),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["signal_profile_used"] == "BALANCED_STABLE"
    assert payload["stable_gate_confirmed"] is True
    assert payload["execution_attempted"] is False


def test_paper_trade_metadata_contains_stable_profile_hash(tmp_path: Path) -> None:
    ini = _stable_ini(tmp_path)
    db = TelemetryDatabase(tmp_path / "stable.sqlite3")
    try:
        bot = ForwardShadowBot(
            config=BotConfig(signal_profile="BALANCED_STABLE", profile_config=str(ini), stability_filters_applied=True, profile_type="RESEARCH_BACKTEST_ONLY", requires_robustness_rerun=True),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            max_cycles=0,
            cycle_seconds=0,
            stable_gate_confirmed=True,
            stable_gate_decision="PAPER_SHADOW_READY",
        )
        trade = _paper_trade()
        db.insert_paper_trade(trade.to_dict())
        decorated = bot._decorate_stable_trade(
            trade,
            SimpleNamespace(score=74, metadata={"setup_score": 70, "component_scores": {"cost_fit": 80}}),
            {"session": "LONDON", "regime": "TREND_UP"},
        )

        assert decorated.metadata["profile"] == "BALANCED_STABLE"
        assert decorated.metadata["stable_profile_hash"]
        assert decorated.metadata["stable_gate_decision"] == "PAPER_SHADOW_READY"
    finally:
        db.close()


def test_stable_drift_detector_detects_critical_drift() -> None:
    drift = detect_stable_forward_drift(
        forward={"closed_trades": 40, "winrate": 10, "expectancy_r": -0.2, "profit_factor": 0.6, "rejection_rate": 80, "symbol_negative_count": 2},
        baseline={"winrate": 42, "expectancy_r": 0.37, "profit_factor": 1.62, "rejection_rate": 10},
    )

    assert drift["classification"] in {"CRITICAL_DRIFT", "PAUSE_STABLE_SHADOW"}
    assert drift["execution_attempted"] is False


def test_pause_resume_stable_shadow_is_paper_only(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "telegram.sqlite3")
    try:
        center = TelegramCommandCenter(database=db, allowed_chat_id="123")
        paused = center.process_update({"message": {"chat": {"id": "123"}, "text": "/pause_stable_shadow test"}})
        resumed = center.process_update({"message": {"chat": {"id": "123"}, "text": "/resume_stable_shadow"}})

        assert paused.execution_attempted is False
        assert resumed.execution_attempted is False
        assert db.get_shadow_paused() is False
    finally:
        db.close()


def test_stable_health_reports_ok_with_heartbeat(tmp_path: Path) -> None:
    gate = _stable_gate(tmp_path)
    db = TelemetryDatabase(tmp_path / "stable.sqlite3")
    try:
        HeartbeatWriter(db).write({"mt5_connected": True, "mode": "forward-shadow", "stable_gate_confirmed": True})
        health = build_stable_health(database=db, stable_gate_path=gate)

        assert health["stable_gate_confirmed"] is True
        assert health["paper_shadow_ready"] is True
        assert health["execution_attempted"] is False
    finally:
        db.close()


def test_stable_scripts_include_profile_and_gate() -> None:
    run_script = Path("scripts/run_forward_shadow_balanced_stable.ps1").read_text(encoding="utf-8")
    status_script = Path("scripts/status_forward_shadow_stable.ps1").read_text(encoding="utf-8")
    daily_script = Path("scripts/daily_summary_stable.ps1").read_text(encoding="utf-8")

    assert "BALANCED_STABLE" in run_script
    assert "--stable-gate" in run_script
    assert "forward-shadow-stable.sqlite3" in run_script
    assert "stable-health" in status_script
    assert "stable-daily-summary" in daily_script


def _stable_ini(tmp_path: Path) -> Path:
    path = tmp_path / "balanced_stable.ini"
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE",
                "PROFILE_TYPE=RESEARCH_BACKTEST_ONLY",
                "NOT_FOR_DEMO_LIVE=true",
                "REQUIRES_ROBUSTNESS_RERUN=true",
                "APPLY_STABILITY_FILTERS=true",
                "DISABLED_SYMBOLS=GBPUSD",
                "DISABLED_STRATEGIES=mean_reversion",
                "BLOCKED_SESSIONS=ROLLOVER",
                "BLOCKED_REGIMES=HIGH_VOLATILITY",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _stable_gate(tmp_path: Path) -> Path:
    path = tmp_path / "stable_gate_summary.json"
    path.write_text(json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True, "execution_attempted": False}), encoding="utf-8")
    return path


def _paper_trade() -> PaperTrade:
    return PaperTrade(
        paper_trade_id="ptr_stable",
        signal_id="sig_stable",
        idempotency_key="paper_trade:sig_stable:EURUSD:BUY",
        symbol="EURUSD",
        broker_symbol="EURUSD",
        direction="BUY",
        entry_time_utc="2024-01-01T00:00:00+00:00",
        entry_price=1.1,
        sl_price=1.09,
        tp_price=1.12,
        lot=0.01,
        risk_pct=0.5,
        risk_amount=50,
        strategy_name="trend_pullback",
        strategy_version="0.1.0",
        regime="TREND_UP",
        session="LONDON",
        score=74,
        reasons=("test",),
    )

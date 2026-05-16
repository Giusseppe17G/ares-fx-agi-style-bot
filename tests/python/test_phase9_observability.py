from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.observability import AlertRuleEngine, DailySummary, HeartbeatWriter
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _db(tmp_path: Path) -> TelemetryDatabase:
    return TelemetryDatabase(tmp_path / "obs.sqlite3")


def test_heartbeat_persists(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        heartbeat = HeartbeatWriter(db).write(
            {
                "mt5_connected": True,
                "symbols_seen": 2,
                "symbols_rejected": 0,
                "open_paper_trades": 1,
                "closed_paper_trades_today": 0,
            }
        )
        assert heartbeat["execution_attempted"] is False
        assert db.count_rows("heartbeats") == 1
        assert db.get_latest_health()["mt5_connected"] is True
    finally:
        db.close()


def test_alert_rule_detects_mt5_disconnected_and_deduplicates(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        engine = AlertRuleEngine(db, dedup_window_seconds=3600)
        alerts = engine.evaluate({"mt5_connected": False, "symbols_seen": 0, "drawdown_paper": 0, "sqlite_status": "OK", "jsonl_status": "OK"})
        assert alerts[0].alert_code == "MT5_DISCONNECTED"
        assert engine.persist(alerts) == 1
        assert engine.persist(alerts) == 0
        assert db.count_rows("alerts") == 1
    finally:
        db.close()


def test_operational_state_pauses_and_resumes_shadow(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        db.set_shadow_paused(True, reason="maintenance", paused_by="test")
        assert db.get_shadow_paused() is True
        db.set_shadow_paused(False, reason="", paused_by="test")
        assert db.get_shadow_paused() is False
    finally:
        db.close()


def test_telegram_commands_status_pause_resume_and_unauthorized(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        center = TelegramCommandCenter(database=db, allowed_chat_id="123")
        unauthorized = center.process_update({"message": {"chat": {"id": "999"}, "text": "/status"}})
        assert unauthorized.status == "UNAUTHORIZED"
        pause = center.process_update({"message": {"chat": {"id": "123"}, "text": "/pause_shadow maintenance"}})
        assert pause.accepted is True
        assert db.get_shadow_paused() is True
        status = center.process_update({"message": {"chat": {"id": "123"}, "text": "/status"}})
        assert status.accepted is True
        resume = center.process_update({"message": {"chat": {"id": "123"}, "text": "/resume_shadow"}})
        assert resume.accepted is True
        assert db.get_shadow_paused() is False
        assert db.count_rows("telegram_commands") == 4
        assert db.fetch_all("events")[-1]["event_type"] == "TELEGRAM_COMMAND_PROCESSED"
    finally:
        db.close()


def test_daily_summary_generates_json(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        summary = DailySummary(db, tmp_path / "daily").generate()
        assert summary["execution_attempted"] is False
        assert Path(summary["reports_created"][0]).exists()
        assert db.count_rows("daily_summaries") == 1
    finally:
        db.close()


def test_forward_shadow_respects_paused_state_and_writes_heartbeat(tmp_path: Path) -> None:
    class FakeMT5:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def initialize(self):
            self.calls.append("initialize")
            return True

        def account_info(self):
            return SimpleNamespace(
                login=100,
                trade_mode=0,
                balance=10000.0,
                equity=10000.0,
                margin_free=9000.0,
                currency="USD",
                trade_allowed=True,
            )

        def symbol_info(self, symbol):
            self.calls.append("symbol_info")
            return None

        def order_send(self, request):
            self.calls.append("order_send")
            raise AssertionError("order_send must not be called")

    db = _db(tmp_path)
    try:
        db.set_shadow_paused(True, reason="test", paused_by="test")
        fake = FakeMT5()
        bot = ForwardShadowBot(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            mt5_client=fake,
            max_cycles=1,
            cycle_seconds=0,
            report_dir=str(tmp_path / "reports"),
        )
        summary = bot.run()
        assert summary.shadow_paused is True
        assert summary.heartbeat_written is True
        assert summary.execution_attempted is False
        assert "order_send" not in fake.calls
        assert db.count_rows("heartbeats") == 1
    finally:
        db.close()


def test_cli_status_health_daily_summary(tmp_path: Path, capsys) -> None:
    sqlite_path = tmp_path / "cli.sqlite3"
    db = TelemetryDatabase(sqlite_path)
    try:
        HeartbeatWriter(db).write({"mt5_connected": True})
    finally:
        db.close()

    assert cli.main(["--mode", "status", "--sqlite", str(sqlite_path)]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "health", "--sqlite", str(sqlite_path), "--log-dir", str(tmp_path / "logs")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "daily-summary", "--sqlite", str(sqlite_path), "--report-dir", str(tmp_path / "daily")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out


def test_forward_shadow_scripts_exist() -> None:
    assert Path("scripts/run_forward_shadow.ps1").exists()
    assert Path("scripts/watchdog_forward_shadow.ps1").exists()
    assert Path("scripts/status.ps1").exists()


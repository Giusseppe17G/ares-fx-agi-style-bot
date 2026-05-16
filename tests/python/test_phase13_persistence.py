from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import SignalAction, StrategySignal, utc_now
from agi_style_forex_bot_mt5.ml.ml_filter import MLFilterDecision
from agi_style_forex_bot_mt5.persistence import (
    RecoveryManager,
    check_db_health,
    compact_jsonl_logs,
    create_backup,
    flush_telegram_outbox,
    replay_audit,
    run_db_migrations,
    validate_event_integrity,
)
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _paper_trade(index: int = 1, *, status: str = "OPEN") -> dict[str, object]:
    now = utc_now().isoformat()
    return {
        "paper_trade_id": f"ptr_{index}",
        "signal_id": f"sig_{index}",
        "idempotency_key": f"paper:{index}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": now,
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
        "lot": 0.1,
        "risk_pct": 0.5,
        "risk_amount": 10,
        "strategy_name": "strategy_ensemble",
        "strategy_version": "0.1",
        "regime": "TREND_UP",
        "session": "LONDON",
        "score": 80,
        "reasons": ("test",),
        "status": status,
        "exit_time_utc": now if status == "CLOSED" else None,
        "exit_price": 1.12 if status == "CLOSED" else None,
        "exit_reason": "TP" if status == "CLOSED" else None,
        "profit": 10 if status == "CLOSED" else 0,
        "r_multiple": 1 if status == "CLOSED" else 0,
    }


def test_migrations_idempotent_and_db_health_detects_missing_table(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "telemetry.sqlite3"
    first = run_db_migrations(sqlite_path=sqlite_path, backup_dir=tmp_path / "backups")
    second = run_db_migrations(sqlite_path=sqlite_path, backup_dir=tmp_path / "backups")
    assert first["execution_attempted"] is False
    assert second["status"] == "OK"

    broken = tmp_path / "broken.sqlite3"
    conn = sqlite3.connect(broken)
    conn.execute("CREATE TABLE events(id INTEGER)")
    conn.commit()
    conn.close()
    health = check_db_health(sqlite_path=broken, report_dir=tmp_path / "reports")
    assert health["status"] == "CRITICAL"
    assert any("missing table" in item for item in health["errors"])


def test_backup_creates_file_and_skips_env(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "telemetry.sqlite3"
    db = TelemetryDatabase(sqlite_path)
    db.close()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "events-test.jsonl").write_text('{"ok":true}\n', encoding="utf-8")
    (log_dir / ".env").write_text("SECRET=1", encoding="utf-8")

    report = create_backup(sqlite_path=sqlite_path, log_dir=log_dir, backup_dir=tmp_path / "backups")

    assert report["backup_files"]
    assert all(".env" not in path for path in report["backup_files"])
    assert report["execution_attempted"] is False


def test_audit_replay_reconstructs_paper_trade(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "replay.sqlite3")
    try:
        trade = _paper_trade(status="CLOSED")
        db.insert_paper_trade(trade)
        db.insert_paper_trade_event(str(trade["paper_trade_id"]), "PAPER_TRADE_OPENED", trade)
        db.insert_paper_trade_event(str(trade["paper_trade_id"]), "PAPER_TRADE_CLOSED", trade)
        report = replay_audit(database=db, output_dir=tmp_path / "reports")
        assert report["paper_trades_closed"] == 1
        assert report["equity_curve"][0]["equity"] == 10
        assert report["execution_attempted"] is False
    finally:
        db.close()


def test_event_integrity_detects_duplicates_and_heartbeat_gap(tmp_path: Path) -> None:
    duplicate = validate_event_integrity(
        events=[
            {"idempotency_key": "same", "timestamp_utc": utc_now().isoformat()},
            {"idempotency_key": "same", "timestamp_utc": utc_now().isoformat()},
        ]
    )
    assert duplicate["issues"][0]["code"] == "DUPLICATE_IDEMPOTENCY_KEY"

    db = TelemetryDatabase(tmp_path / "gap.sqlite3")
    try:
        start = utc_now()
        db.insert_heartbeat({"heartbeat_id": "h1", "timestamp_utc": start.isoformat(), "mode": "forward-shadow", "mt5_connected": True, "execution_attempted": False})
        db.insert_heartbeat({"heartbeat_id": "h2", "timestamp_utc": (start + timedelta(minutes=10)).isoformat(), "mode": "forward-shadow", "mt5_connected": True, "execution_attempted": False})
        gap = validate_event_integrity(database=db, heartbeat_gap_seconds=60)
        assert gap["event_gap_count"] == 1
    finally:
        db.close()


def test_telegram_outbox_flush_does_not_duplicate(tmp_path: Path) -> None:
    class Response:
        status_code = 200
        text = "OK"

    calls = []

    def sender(url, payload, timeout):
        calls.append(payload)
        return Response()

    db = TelemetryDatabase(tmp_path / "outbox.sqlite3")
    try:
        db.enqueue_telegram_message(event_id="evt", idempotency_key="tg:1", message="hello", chat_id_redacted="123", payload={})
        first = flush_telegram_outbox(database=db, bot_token="token", chat_id="123", sender=sender)
        second = flush_telegram_outbox(database=db, bot_token="token", chat_id="123", sender=sender)
        assert first["delivered"] == 1
        assert second["attempted"] == 0
        assert len(calls) == 1
    finally:
        db.close()


def test_jsonl_compactor_rotates_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    path = log_dir / "events-test.jsonl"
    path.write_text("x" * 2048, encoding="utf-8")
    report = compact_jsonl_logs(log_dir=log_dir, backup_dir=tmp_path / "backups", max_file_mb=0.0001)
    assert report["rotated_files"]
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_recovery_manager_loads_open_trades(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "recovery.sqlite3")
    try:
        db.insert_paper_trade(_paper_trade())
        manager = RecoveryManager(database=db, audit_logger=JsonlAuditLogger(tmp_path / "logs"), run_id="test")
        report = manager.recover()
        assert report["status"] == "OK"
        assert report["open_paper_trades"] == 1
        assert any(row["event_type"] == "RECOVERY_COMPLETED" for row in db.fetch_all("events"))
    finally:
        db.close()


def test_forward_shadow_calls_recovery_manager(monkeypatch, tmp_path: Path) -> None:
    import agi_style_forex_bot_mt5.paper_trading.forward_shadow_bot as fsb

    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO = 0

        def initialize(self):
            return True

        def account_info(self):
            return SimpleNamespace(login=1, trade_mode=0, balance=10000, equity=10000, margin_free=9000, currency="USD", trade_allowed=True)

        def symbol_info(self, symbol):
            return SimpleNamespace(name=symbol, visible=True, trade_mode=1, digits=5, point=0.00001, trade_tick_value=1, trade_tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, trade_stops_level=10, trade_freeze_level=5)

        def symbol_info_tick(self, symbol):
            now = int(utc_now().timestamp())
            return SimpleNamespace(bid=1.1000, ask=1.1001, time=now, time_msc=now * 1000)

        def last_error(self):
            return (0, "")

        def order_send(self, request):
            raise AssertionError("order_send must not be called")

    monkeypatch.setattr(fsb.MT5DataOnlyBot, "_read_timeframes", lambda self, *args, **kwargs: {"M5": object()})
    monkeypatch.setattr(fsb.MT5DataOnlyBot, "_features_from_bars", lambda self, *args, **kwargs: {"regime": "TREND_UP", "session": "LONDON", "atr": 0.001})
    monkeypatch.setattr(fsb, "evaluate_ensemble", lambda *_args, **_kwargs: StrategySignal(SignalAction.NONE, 0, ("none",), "strategy_ensemble", {}))
    monkeypatch.setattr(fsb.MLFilter, "load_latest_model", staticmethod(lambda: SimpleNamespace(approve_or_reject=lambda signal, features: MLFilterDecision("ML_DISABLED", None, None, None, None, None, 0.58, ("no model",)))))
    db = TelemetryDatabase(tmp_path / "fwd.sqlite3")
    try:
        bot = fsb.ForwardShadowBot(config=BotConfig(), symbols=("EURUSD",), audit_logger=JsonlAuditLogger(tmp_path / "logs"), database=db, mt5_client=FakeMT5(), max_cycles=1, cycle_seconds=0)
        summary = bot.run()
        assert summary.execution_attempted is False
        assert any(row["event_type"] == "RECOVERY_COMPLETED" for row in db.fetch_all("events"))
    finally:
        db.close()


def test_cli_persistence_modes_and_telegram_commands(tmp_path: Path, capsys) -> None:
    sqlite_path = tmp_path / "cli.sqlite3"
    assert cli.main(["--mode", "db-migrate", "--sqlite", str(sqlite_path), "--backup-dir", str(tmp_path / "backups")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "db-health", "--sqlite", str(sqlite_path), "--report-dir", str(tmp_path / "reports")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "backup", "--sqlite", str(sqlite_path), "--log-dir", str(tmp_path / "logs"), "--backup-dir", str(tmp_path / "backups")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "audit-replay", "--sqlite", str(sqlite_path), "--report-dir", str(tmp_path / "reports")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "telegram-outbox-flush", "--sqlite", str(sqlite_path)]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "compact-logs", "--log-dir", str(tmp_path / "logs"), "--backup-dir", str(tmp_path / "backups")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

    from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter

    db = TelemetryDatabase(tmp_path / "tg.sqlite3")
    try:
        center = TelegramCommandCenter(database=db, allowed_chat_id="123")
        assert center.process_update({"message": {"chat": {"id": "123"}, "text": "/db"}}).accepted is True
        backup = center.process_update({"message": {"chat": {"id": "123"}, "text": "/backup"}})
        assert backup.accepted is True
        assert "execution_attempted" in backup.response_text
    finally:
        db.close()


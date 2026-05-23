from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.forward_evidence import run_forward_acceptance, run_forward_evidence
from agi_style_forex_bot_mt5.observability.metrics_collector import MetricsCollector
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.paper_trading.paper_state import close_all_paper_trades
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry.logger_setup import redact_text
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


def _trade(status: str = "OPEN", trade_id: str = "ptr_test") -> dict[str, object]:
    return {
        "paper_trade_id": trade_id,
        "signal_id": "sig",
        "idempotency_key": f"paper:{trade_id}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": "2026-05-18T09:30:00+00:00",
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
        "lot": 0.01,
        "risk_pct": 0.5,
        "risk_amount": 10.0,
        "strategy_name": "strategy_ensemble",
        "strategy_version": "test",
        "regime": "RANGE",
        "session": "LONDON",
        "score": 60.0,
        "reasons": (),
        "status": status,
        "profit": -50.0 if status == "CLOSED" else 0.0,
        "r_multiple": -1.0 if status == "CLOSED" else 0.0,
        "exit_time_utc": "2026-18T09:34:43.[REDACTED:900]+00:00" if status == "CLOSED" else None,
        "metadata": {},
    }


def test_safe_parse_datetime_parse_iso_and_redacted() -> None:
    good = safe_parse_datetime("2026-05-18T09:34:43.900+00:00")
    bad = safe_parse_datetime("2026-18T09:34:43.[REDACTED:900]+00:00")
    assert good.value is not None
    assert bad.value is None
    assert bad.warning == "DATETIME_REDACTED_OR_INVALID"


def test_sanitizer_does_not_alter_iso_timestamp() -> None:
    value = "timestamp=2026-05-18T09:34:43.900+00:00"
    assert redact_text(value) == value


def test_forward_evidence_and_acceptance_do_not_crash_with_corrupt_timestamp(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "events-2026-05-18.jsonl").write_text(
        json.dumps({"event_type": "FORWARD_SHADOW_CYCLE", "timestamp_utc": "2026-18T09:34:43.[REDACTED:900]+00:00", "payload_json": "{}"}) + "\n",
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    (reports / "stable_gate").mkdir(parents=True)
    (reports / "stable_gate" / "stable_gate_summary.json").write_text('{"stable_gate_decision":"PAPER_SHADOW_READY","paper_shadow_ready":true}', encoding="utf-8")
    try:
        summary = run_forward_evidence(database=db, log_dir=log_dir, reports_root=reports, output_dir=tmp_path / "evidence")
        acceptance = run_forward_acceptance(database=db, log_dir=log_dir, reports_root=reports, output_dir=tmp_path / "evidence2")
        assert summary["evidence_parse_status"] == "PARTIAL_INVALID_TIMESTAMPS"
        assert summary["invalid_timestamp_count"] == 1
        assert acceptance["execution_attempted"] is False
    finally:
        db.close()


def test_paper_open_trades_cli_and_close_all_dry_run(tmp_path: Path, capsys) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_paper_trade(_trade("OPEN"))
    finally:
        db.close()
    assert cli.main(["--mode", "paper-open-trades", "--sqlite", str(tmp_path / "paper.sqlite3"), "--output-dir", str(tmp_path / "out")]) == 0
    assert '"open_paper_trades": 1' in capsys.readouterr().out
    assert cli.main(["--mode", "paper-close-all", "--sqlite", str(tmp_path / "paper.sqlite3"), "--output-dir", str(tmp_path / "out"), "--reason", "dry"]) == 0
    out = capsys.readouterr().out
    assert '"dry_run": true' in out
    db2 = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        assert len(db2.fetch_open_paper_trades()) == 1
    finally:
        db2.close()


def test_paper_close_all_confirm_closes_only_paper(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_paper_trade(_trade("OPEN"))
        summary = close_all_paper_trades(database=db, reason="test", output_dir=tmp_path / "out", confirm_paper_only=True)
        assert summary["paper_trades_closed"] == 1
        assert len(db.fetch_open_paper_trades()) == 0
        assert db.count_rows("paper_trade_events") == 1
    finally:
        db.close()


def test_pause_resume_shadow_persist_state(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "paper.sqlite3"
    assert cli.main(["--mode", "pause-shadow", "--sqlite", str(db_path), "--reason", "PAPER_DAILY_DRAWDOWN review"]) == 0
    assert '"paper_shadow_paused": true' in capsys.readouterr().out
    assert cli.main(["--mode", "resume-shadow", "--sqlite", str(db_path), "--reason", "reviewed"]) == 0
    assert '"paper_shadow_paused": false' in capsys.readouterr().out


class FailingMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def initialize(self):
        return True

    def account_info(self):
        return None


def test_forward_shadow_returns_exit_reason_with_zero_cycles(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "shadow.sqlite3")
    try:
        bot = ForwardShadowBot(config=BotConfig(), symbols=("EURUSD",), audit_logger=JsonlAuditLogger(tmp_path / "logs"), database=db, mt5_client=FailingMT5(), max_cycles=1, cycle_seconds=0)
        summary = bot.run()
        assert summary.cycles_completed == 0
        assert summary.exit_reason == "CONFIG_ERROR"
        assert summary.halt_reason == "ACCOUNT_INFO_UNAVAILABLE"
        assert summary.execution_attempted is False
    finally:
        db.close()


def test_all_symbols_rejected_aggregation_handles_symbol_list(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "metrics.sqlite3")
    try:
        # Empty database should not trigger pandas scalar/list errors.
        metrics = MetricsCollector(db).collect()
        assert metrics["execution_attempted"] is False
    finally:
        db.close()

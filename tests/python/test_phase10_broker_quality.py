from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.backtesting.validation_report import build_master_validation_report
from agi_style_forex_bot_mt5.broker_quality import (
    BrokerQualityProbe,
    analyze_spreads,
    analyze_tick_freshness,
    build_readiness_report,
    score_symbol_readiness,
)
from agi_style_forex_bot_mt5.broker_quality.latency_monitor import measure_latency_ms
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __init__(self, *, spread_points: float = 10.0, empty_rates: bool = False) -> None:
        self.calls: list[str] = []
        self.spread_points = spread_points
        self.empty_rates = empty_rates

    def initialize(self):
        self.calls.append("initialize")
        return True

    def account_info(self):
        self.calls.append("account_info")
        return SimpleNamespace(login=1, trade_mode=0, balance=10000, equity=10000, margin_free=9000, trade_allowed=True)

    def symbol_info(self, symbol):
        self.calls.append("symbol_info")
        point = 0.00001
        return SimpleNamespace(
            name=symbol,
            visible=True,
            trade_mode=1,
            digits=5,
            point=point,
            trade_tick_value=1.0,
            trade_tick_size=point,
            trade_contract_size=100000,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_stops_level=10,
            trade_freeze_level=5,
            filling_mode=1,
        )

    def symbol_info_tick(self, symbol):
        self.calls.append("symbol_info_tick")
        bid = 1.10000
        ask = bid + self.spread_points * 0.00001
        now = int(datetime.now(timezone.utc).timestamp())
        return SimpleNamespace(bid=bid, ask=ask, time=now, time_msc=now * 1000)

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.calls.append("copy_rates_from_pos")
        if self.empty_rates:
            return []
        return [{"time": i, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 10} for i in range(20)]

    def last_error(self):
        return (0, "")

    def order_send(self, request):
        self.calls.append("order_send")
        raise AssertionError("order_send must not be called")


def test_broker_quality_probe_read_only_and_execution_false(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "bq.sqlite3")
    fake = FakeMT5()
    try:
        probe = BrokerQualityProbe(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            mt5_client=fake,
        )
        summary = probe.run()
        assert summary["execution_attempted"] is False
        assert summary["order_send_called"] is False
        assert "order_send" not in fake.calls
        assert summary["symbols_checked"] == 1
        assert db.count_rows("broker_quality") == 1
    finally:
        db.close()


def test_spread_and_tick_analyzers() -> None:
    spreads = analyze_spreads([{"spread_points": value} for value in [1, 2, 3, 4, 100]], max_spread_points=10)
    freshness = analyze_tick_freshness([{"tick_age_seconds": value} for value in [1, 2, 3, 20, 30]], max_tick_age_seconds=5)
    assert spreads["p95"] > 4
    assert spreads["p99"] > spreads["p95"]
    assert spreads["blocked_by_p95"] is True
    assert freshness["staleness_recurrent"] is True


def test_latency_monitor_measures_mock_call() -> None:
    value, latency, error = measure_latency_ms(lambda: "ok")
    assert value == "ok"
    assert latency >= 0
    assert error == ""


def test_readiness_score_classifications() -> None:
    base = {
        "symbol_visible": True,
        "trade_allowed": True,
        "spread_points": 100,
        "tick_age_seconds": 1,
        "rates_available_m5": True,
        "rates_available_m15": True,
        "rates_available_h1": True,
        "stops_level_points": 10,
        "freeze_level_points": 5,
        "volume_min": 0.01,
        "volume_step": 0.01,
    }
    _score, status, reasons = score_symbol_readiness(base, max_spread_points=25)
    assert status == "NOT_READY"
    assert "spread above configured max" in reasons
    incomplete = {**base, "spread_points": 10, "rates_available_h1": False}
    _score, status, _reasons = score_symbol_readiness(incomplete, max_spread_points=25)
    assert status in {"WATCHLIST", "NOT_READY"}


def test_reports_and_cli_modes(monkeypatch, tmp_path: Path, capsys) -> None:
    sqlite_path = tmp_path / "bq.sqlite3"

    def fake_bq(**_kwargs):
        return {
            "mode": "broker-quality",
            "symbols_checked": 1,
            "ready": 0,
            "watchlist": 0,
            "not_ready": 1,
            "execution_attempted": False,
            "order_send_called": False,
            "reports_created": [],
        }

    monkeypatch.setattr(cli, "run_broker_quality", fake_bq)
    assert cli.main(["--mode", "broker-quality", "--sqlite", str(sqlite_path), "--report-dir", str(tmp_path / "broker_quality")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

    reports_root = tmp_path / "reports"
    (reports_root / "broker_quality").mkdir(parents=True)
    (reports_root / "broker_quality" / "summary.json").write_text(
        '{"mode":"broker-quality","symbols":[{"canonical_symbol":"EURUSD","status":"NOT_READY","readiness_score":10,"reasons":["spread"]}]}',
        encoding="utf-8",
    )
    db = TelemetryDatabase(sqlite_path)
    try:
        readiness = build_readiness_report(reports_root=reports_root, output_dir=tmp_path / "readiness", database=db)
        assert readiness["execution_attempted"] is False
        assert readiness["classification"] == "NEEDS_BROKER_FIX"
    finally:
        db.close()
    assert cli.main(["--mode", "readiness-report", "--sqlite", str(sqlite_path), "--reports-root", str(reports_root), "--output-dir", str(tmp_path / "ready_cli")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out


def test_telegram_broker_and_readiness_commands(monkeypatch, tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "tg.sqlite3")
    try:
        import agi_style_forex_bot_mt5.telegram_command_center as tcc

        monkeypatch.setattr(
            tcc,
            "build_readiness_report",
            lambda **_kwargs: {"mode": "readiness-report", "classification": "NEEDS_MORE_DATA", "execution_attempted": False},
        )
        center = TelegramCommandCenter(database=db, allowed_chat_id="123")
        assert center.process_update({"message": {"chat": {"id": "123"}, "text": "/broker"}}).accepted is True
        result = center.process_update({"message": {"chat": {"id": "123"}, "text": "/readiness"}})
        assert result.accepted is True
        assert "execution_attempted" in result.response_text
    finally:
        db.close()


def test_validation_report_includes_broker_readiness(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    (root / "data_quality").mkdir(parents=True)
    (root / "broker_quality").mkdir(parents=True)
    (root / "readiness").mkdir(parents=True)
    (root / "data_quality" / "summary.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "broker_quality" / "summary.json").write_text('{"classification":"NOT_READY"}', encoding="utf-8")
    (root / "readiness" / "execution_readiness_report.json").write_text('{"classification":"NEEDS_BROKER_FIX"}', encoding="utf-8")
    report = build_master_validation_report(reports_root=root, output_dir=tmp_path / "validation")
    assert "broker_quality" in report["summaries"]
    assert "readiness" in report["summaries"]
    assert report["execution_attempted"] is False
    assert report["classification"] == "NEEDS_BROKER_FIX"


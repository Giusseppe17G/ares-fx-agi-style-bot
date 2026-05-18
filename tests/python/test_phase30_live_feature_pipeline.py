from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import MarketSnapshot, utc_now
from agi_style_forex_bot_mt5.data_pipeline.live_data_contract import build_live_feature_contract_report, normalize_ohlcv_contract
from agi_style_forex_bot_mt5.forward_diagnostics.forward_diagnostics_report import run_forward_signal_diagnose
from agi_style_forex_bot_mt5.forward_diagnostics.live_feature_probe import probe_live_features
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DataOnlyBot
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _rates(count: int = 260, *, duplicate: bool = False, bad_ohlc: bool = False) -> list[dict[str, object]]:
    now = int(utc_now().timestamp())
    price = 1.1000
    rows: list[dict[str, object]] = []
    for idx in range(count):
        price += 0.00003
        ts = now - (count - idx) * 300
        if duplicate and idx == count - 1:
            ts = int(rows[-1]["time"])
        rows.append(
            {
                "time": ts,
                "open": "bad" if bad_ohlc and idx == 0 else f"{price:.5f}",
                "high": f"{price + 0.0001:.5f}",
                "low": f"{price - 0.0001:.5f}",
                "close": f"{price + 0.00002:.5f}",
                "tick_volume": "1000",
                "spread": "10",
            }
        )
    return rows


class LiveMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    SYMBOL_TRADE_MODE_DISABLED = 0
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __init__(self, *, rates: list[dict[str, object]] | None = None) -> None:
        self.rates = rates if rates is not None else _rates(1100)
        self.calls: list[str] = []

    def initialize(self):
        self.calls.append("initialize")
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(login=100, trade_mode=0, trade_allowed=True, balance=10000, equity=10000, margin_free=9000, currency="USD")

    def symbol_info(self, symbol: str):
        return SimpleNamespace(name=symbol, visible=True, trade_mode=1, filling_mode=0, digits=5, point=0.00001, trade_tick_value=1, trade_tick_size=0.00001, trade_contract_size=100000, volume_min=0.01, volume_max=100, volume_step=0.01, trade_stops_level=10, trade_freeze_level=5)

    def symbol_info_tick(self, symbol: str):
        now = int(utc_now().timestamp())
        return SimpleNamespace(bid=1.1000, ask=1.1001, time=now, time_msc=now * 1000)

    def copy_rates_from_pos(self, symbol: str, timeframe, start_pos: int, count: int):
        self.calls.append(f"copy_rates_from_pos:{timeframe}:{count}")
        return self.rates[-count:]

    def copy_rates_range(self, symbol: str, timeframe, date_from, date_to):
        return self.rates

    def symbols_get(self, group: str = "*"):
        return (SimpleNamespace(name="EURUSD"),)

    def last_error(self):
        return (0, "")

    def order_send(self, request):
        self.calls.append("order_send")
        raise AssertionError("order_send must not be called")

    def order_check(self, request):
        self.calls.append("order_check")
        raise AssertionError("order_check must not be called")


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(symbol="EURUSD", timeframe="M5", timestamp_utc=datetime.now(timezone.utc), bid=1.1, ask=1.1001, spread_points=10, digits=5, point=0.00001, tick_value=1, tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, stops_level_points=10, freeze_level_points=5)


def test_live_data_contract_converts_mt5_rates_to_canonical_schema() -> None:
    result = normalize_ohlcv_contract(_rates(220), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=200)
    assert result.diagnostics["status"] == "OK"
    assert {"timestamp_utc", "time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"}.issubset(result.frame.columns)
    assert str(result.frame["timestamp_utc"].dtype).startswith("datetime64")
    assert result.frame["open"].dtype.kind == "f"
    assert result.frame["real_volume"].iloc[-1] == 0


def test_live_data_contract_reports_missing_required_columns() -> None:
    rows = _rates(220)
    for row in rows:
        row.pop("high")
    result = normalize_ohlcv_contract(rows, source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=200)
    assert result.diagnostics["status"] == "LIVE_MISSING_REQUIRED_COLUMNS"
    assert "high" in result.diagnostics["missing_columns"]


def test_live_data_contract_reports_numeric_cast_failed() -> None:
    result = normalize_ohlcv_contract(_rates(220, bad_ohlc=True), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=200)
    assert result.diagnostics["status"] == "LIVE_NUMERIC_CAST_FAILED"


def test_live_data_contract_reports_duplicate_timestamps_but_keeps_schema() -> None:
    result = normalize_ohlcv_contract(_rates(220, duplicate=True), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=200)
    assert result.diagnostics["status"] == "OK"
    assert "LIVE_DUPLICATE_TIMESTAMPS" in result.diagnostics["blockers"]
    assert result.diagnostics["duplicate_timestamps"] == 1


def test_live_feature_probe_generates_features_from_contract() -> None:
    rows, features = probe_live_features(config=BotConfig(), runtime_payloads={"EURUSD": {"snapshot": _snapshot(), "rates": {"M5": _rates(260)}}})
    assert rows[0]["features_generated"] is True
    assert "FEATURE_BUILD_FAILED" not in rows[0].get("blockers", ())
    assert "EURUSD" in features


def test_live_feature_probe_uses_specific_contract_error() -> None:
    rows, features = probe_live_features(config=BotConfig(), runtime_payloads={"EURUSD": {"snapshot": _snapshot(), "rates": {"M5": _rates(20)}}})
    assert features == {}
    assert rows[0]["feature_build_error_type"] == "LIVE_INSUFFICIENT_ROWS_FOR_FEATURES"
    assert "FEATURE_BUILD_FAILED" not in rows[0]["blockers"]


def test_live_feature_contract_report_generates_outputs(tmp_path: Path) -> None:
    summary = build_live_feature_contract_report(config=BotConfig(), symbols=("EURUSD",), output_dir=tmp_path, mt5_client=LiveMT5())
    assert summary["mode"] == "live-feature-contract"
    assert summary["execution_attempted"] is False
    assert (tmp_path / "live_feature_contract_summary.json").exists()
    assert (tmp_path / "live_feature_contract_by_symbol.csv").exists()


def test_cli_accepts_live_feature_contract(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_report(**_kwargs):
        return {"mode": "live-feature-contract", "execution_attempted": False, "order_send_called": False, "order_check_called": False}

    monkeypatch.setattr(cli, "build_live_feature_contract_report", fake_report)
    code = cli.main(["--mode", "live-feature-contract", "--symbols", "EURUSD", "--output-dir", str(tmp_path)])
    assert code == 0
    assert '"mode": "live-feature-contract"' in capsys.readouterr().out


def test_forward_shadow_audits_specific_feature_failure(tmp_path: Path, monkeypatch) -> None:
    def failing_features(self, *_args, **_kwargs):
        raise ValueError("LIVE_MISSING_REQUIRED_COLUMNS: high")

    monkeypatch.setattr(MT5DataOnlyBot, "_features_from_bars", failing_features)
    db = TelemetryDatabase(tmp_path / "shadow.sqlite3")
    try:
        bot = ForwardShadowBot(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            mt5_client=LiveMT5(),
            cycle_seconds=0,
            max_cycles=1,
            report_dir=str(tmp_path / "reports"),
        )
        summary = bot.run()
        assert summary.execution_attempted is False
        events = db.fetch_all("events")
        assert any(event["event_type"] == "FORWARD_FEATURE_BUILD_FAILED" for event in events)
        payloads = [json.loads(event["payload_json"]) for event in events if event["event_type"] == "FORWARD_FEATURE_BUILD_FAILED"]
        assert payloads[0]["feature_build_error_type"] == "LIVE_MISSING_REQUIRED_COLUMNS"
        assert "order_send" not in bot.mt5_client.calls
        assert "order_check" not in bot.mt5_client.calls
    finally:
        db.close()


def test_forward_signal_diagnose_reports_feature_ready_symbols(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "diag.sqlite3")
    client = LiveMT5()
    try:
        summary = run_forward_signal_diagnose(
            config=BotConfig(signal_profile="BALANCED"),
            symbols=("EURUSD",),
            database=db,
            log_dir=tmp_path / "logs",
            reports_root=tmp_path / "reports",
            output_dir=tmp_path / "out",
            mt5_client=client,
        )
        assert "EURUSD" in summary["feature_ready_symbols"]
        assert summary["execution_attempted"] is False
        assert (tmp_path / "out" / "live_feature_contract_summary.json").exists()
        assert "order_send" not in client.calls
        assert "order_check" not in client.calls
    finally:
        db.close()

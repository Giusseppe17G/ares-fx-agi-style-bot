from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli as _cli  # noqa: F401 - mirrors CLI import order used by integration tests.
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import utc_now
from agi_style_forex_bot_mt5.execution import MT5Connector, normalize_tick_time
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DiagnoseBot
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _rates(count: int = 260) -> list[dict[str, float]]:
    now = int(utc_now().timestamp())
    rows: list[dict[str, float]] = []
    price = 1.1000
    for index in range(count):
        price += 0.00003
        rows.append(
            {
                "time": now - (count - index) * 300,
                "open": price - 0.00002,
                "high": price + 0.00008,
                "low": price - 0.00008,
                "close": price,
                "tick_volume": 1000 + index,
                "spread": 10,
            }
        )
    return rows


class OffsetMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    SYMBOL_TRADE_MODE_DISABLED = 0
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __init__(self, *, offset_seconds: int = 10800, bid: float = 1.1000, ask: float = 1.1001) -> None:
        self.offset_seconds = offset_seconds
        self.bid = bid
        self.ask = ask
        self.calls: list[str] = []

    def initialize(self) -> bool:
        self.calls.append("initialize")
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    def account_info(self):
        self.calls.append("account_info")
        return SimpleNamespace(
            login=12345678,
            server="Demo-Server",
            company="Demo-Broker",
            trade_mode=0,
            trade_allowed=True,
            balance=10000.0,
            equity=10000.0,
            margin=0.0,
            margin_free=9000.0,
            currency="USD",
            leverage=100,
        )

    def symbol_info(self, symbol: str):
        self.calls.append("symbol_info")
        return SimpleNamespace(
            name=symbol,
            visible=True,
            trade_mode=1,
            filling_mode=0,
            digits=5,
            point=0.00001,
            trade_tick_value=1.0,
            trade_tick_size=0.00001,
            trade_contract_size=100000,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_stops_level=10,
            trade_freeze_level=5,
        )

    def symbol_select(self, symbol: str, enabled: bool) -> bool:
        self.calls.append("symbol_select")
        return True

    def symbol_info_tick(self, symbol: str):
        self.calls.append("symbol_info_tick")
        timestamp = int(utc_now().timestamp()) + self.offset_seconds
        return SimpleNamespace(bid=self.bid, ask=self.ask, time=timestamp, time_msc=timestamp * 1000)

    def copy_rates_from_pos(self, symbol: str, timeframe, start_pos: int, count: int):
        self.calls.append(f"copy_rates_from_pos:{timeframe}")
        return _rates(count)

    def symbols_get(self, group: str = "*"):
        return (SimpleNamespace(name="EURUSD"),)

    def positions_get(self, symbol: str | None = None):
        return ()

    def last_error(self):
        return (0, "")

    def order_send(self, request: dict):
        self.calls.append("order_send")
        raise AssertionError("order_send must not be called")

    def order_check(self, request: dict):
        self.calls.append("order_check")
        raise AssertionError("order_check must not be called")


def test_tick_plus_three_hours_normalizes_to_fresh() -> None:
    now = datetime(2026, 5, 18, 4, 10, 49, tzinfo=timezone.utc)
    raw = int((now + timedelta(hours=3, seconds=2)).timestamp())
    diagnostic = normalize_tick_time(raw, raw * 1000, now, config=BotConfig())
    assert diagnostic["timestamp_normalized"] is True
    assert diagnostic["broker_time_offset_seconds"] == 10800
    assert diagnostic["tick_time_status"] == "NORMALIZED_FRESH"


def test_tick_plus_two_and_plus_one_hours_normalize_to_fresh() -> None:
    now = datetime(2026, 5, 18, 4, 10, 49, tzinfo=timezone.utc)
    for hours, offset in ((2, 7200), (1, 3600)):
        raw = int((now + timedelta(hours=hours)).timestamp())
        diagnostic = normalize_tick_time(raw, raw * 1000, now, config=BotConfig())
        assert diagnostic["broker_time_offset_seconds"] == offset
        assert diagnostic["tick_time_status"] == "NORMALIZED_FRESH"


def test_tick_plus_ten_hours_rejects_future_too_far() -> None:
    now = datetime(2026, 5, 18, 4, 10, 49, tzinfo=timezone.utc)
    raw = int((now + timedelta(hours=10)).timestamp())
    diagnostic = normalize_tick_time(raw, raw * 1000, now, config=BotConfig())
    assert diagnostic["tick_time_status"] == "FUTURE_TOO_FAR"
    assert diagnostic["reject_code"] == "MARKET_DATA_INVALID"


def test_old_tick_remains_stale_and_is_not_normalized() -> None:
    now = datetime(2026, 5, 18, 4, 10, 49, tzinfo=timezone.utc)
    raw = int((now - timedelta(hours=3)).timestamp())
    diagnostic = normalize_tick_time(raw, raw * 1000, now, config=BotConfig())
    assert diagnostic["timestamp_normalized"] is False
    assert diagnostic["tick_time_status"] == "STALE"


def test_tick_without_time_msc_uses_time_fallback() -> None:
    now = datetime(2026, 5, 18, 4, 10, 49, tzinfo=timezone.utc)
    raw = int((now + timedelta(hours=3)).timestamp())
    diagnostic = normalize_tick_time(raw, None, now, config=BotConfig())
    assert diagnostic["selected_tick_time_source"] == "time"
    assert diagnostic["tick_time_status"] == "NORMALIZED_FRESH"


def test_invalid_bid_ask_still_rejected_after_time_normalization(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = OffsetMT5(offset_seconds=10800, bid=0.0, ask=0.0)
    connector = MT5Connector(config=BotConfig(), mt5_client=client)
    check, snapshot = connector.ensure_symbol_snapshot("EURUSD")
    assert snapshot is None
    assert check.accepted is False
    assert check.code == "MARKET_DATA_INVALID"
    assert "order_send" not in client.calls
    assert "order_check" not in client.calls


def test_normalize_tick_time_does_not_depend_on_local_timezone(monkeypatch) -> None:
    now = datetime(2026, 5, 18, 4, 10, 49, tzinfo=timezone.utc)
    raw = int((now + timedelta(hours=3)).timestamp())
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    first = normalize_tick_time(raw, raw * 1000, now, config=BotConfig())
    monkeypatch.setenv("TZ", "America/Lima")
    second = normalize_tick_time(raw, raw * 1000, now, config=BotConfig())
    assert first["normalized_tick_utc"] == second["normalized_tick_utc"]
    assert first["broker_time_offset_seconds"] == second["broker_time_offset_seconds"]


def test_mt5_diagnose_normalized_tick_is_not_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db = TelemetryDatabase(tmp_path / "diag.sqlite3")
    try:
        bot = MT5DiagnoseBot(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            mt5_client=OffsetMT5(offset_seconds=10800),
        )
        summary = bot.run()
        diagnostic = summary.diagnostics[0]
        assert summary.symbols_rejected == 0
        assert diagnostic["timestamp_normalized"] is True
        assert diagnostic["broker_time_offset_seconds"] == 10800
        assert diagnostic["tick_time_status"] == "NORMALIZED_FRESH"
        assert diagnostic["status"] == "PASSED"
        assert diagnostic["reject_code"] is None
    finally:
        db.close()


def test_forward_shadow_audits_normalized_tick(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        bot = ForwardShadowBot(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            mt5_client=OffsetMT5(offset_seconds=10800),
            max_cycles=1,
            cycle_seconds=0,
            report_dir=str(tmp_path / "reports"),
        )
        summary = bot.run()
        events = [row["event_type"] for row in db.fetch_all("events")]
        assert summary.execution_attempted is False
        assert "TICK_TIME_NORMALIZED" in events
    finally:
        db.close()


def test_broker_time_offset_file_is_written_without_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = OffsetMT5(offset_seconds=10800)
    connector = MT5Connector(config=BotConfig(), mt5_client=client)
    check, snapshot = connector.ensure_symbol_snapshot("EURUSD")
    assert check.accepted is True
    assert snapshot is not None
    payload = (tmp_path / "data/runtime/broker_time_offset.json").read_text(encoding="utf-8")
    assert "12345678" not in payload
    assert "12***78" in payload
    assert "order_send" not in client.calls
    assert "order_check" not in client.calls

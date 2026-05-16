from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.bot import AuditUnavailableError
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import RiskDecision, utc_now
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DataOnlyBot
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelegramNotifier, TelemetryDatabase


def _rates(count: int = 260) -> list[dict[str, float]]:
    now = int(utc_now().timestamp())
    rows: list[dict[str, float]] = []
    price = 1.0800
    for i in range(count):
        price += 0.00008
        if i == count - 1:
            price -= 0.00020
        open_ = price - 0.00004
        close = price
        high = max(open_, close) + 0.00012
        low = min(open_, close) - 0.00012
        rows.append(
            {
                "time": now - (count - i) * 300,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": 1000 + i,
                "spread": 10,
            }
        )
    return rows


@dataclass
class MockMT5DataClient:
    initialize_ok: bool = True
    account_missing: bool = False
    symbol_missing: bool = False
    stale_tick: bool = False
    empty_rates: bool = False
    trade_mode: int = 0

    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    SYMBOL_TRADE_MODE_DISABLED = 0
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __post_init__(self) -> None:
        self.calls: list[str] = []

    def initialize(self) -> bool:
        self.calls.append("initialize")
        return self.initialize_ok

    def last_error(self):
        return (1, "mock error")

    def account_info(self):
        self.calls.append("account_info")
        if self.account_missing:
            return None
        return SimpleNamespace(
            login=123456,
            server="Demo-Server",
            trade_mode=self.trade_mode,
            trade_allowed=True,
            balance=10_000.0,
            equity=10_000.0,
            margin=0.0,
            margin_free=9_000.0,
            currency="USD",
            leverage=100,
        )

    def symbol_info(self, symbol: str):
        self.calls.append("symbol_info")
        if self.symbol_missing:
            return None
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
        timestamp = int(utc_now().timestamp()) - (999 if self.stale_tick else 0)
        return SimpleNamespace(
            bid=1.10000,
            ask=1.10010,
            time=timestamp,
            time_msc=timestamp * 1000,
        )

    def copy_rates_from_pos(self, symbol: str, timeframe, start_pos: int, count: int):
        self.calls.append(f"copy_rates_from_pos:{timeframe}")
        return [] if self.empty_rates else _rates(count)

    def positions_get(self, symbol: str | None = None):
        self.calls.append("positions_get")
        return ()

    def order_send(self, request: dict):
        self.calls.append("order_send")
        raise AssertionError("order_send must not be called in mt5-data mode")


class RejectingRiskEngine:
    def evaluate(self, *, signal, snapshot, account, state) -> RiskDecision:
        return RiskDecision(
            signal_id=signal.signal_id,
            accepted=False,
            reject_code="HIGH_SPREAD",
            reject_reason="spread too high",
            checks={"spread": {"status": "failed"}},
        )


def _bot(tmp_path: Path, mt5_client, **kwargs) -> tuple[MT5DataOnlyBot, TelemetryDatabase]:
    db = TelemetryDatabase(tmp_path / "telemetry.sqlite3")
    bot = MT5DataOnlyBot(
        config=BotConfig(),
        symbols=("EURUSD",),
        audit_logger=JsonlAuditLogger(tmp_path / "logs"),
        database=db,
        mt5_client=mt5_client,
        **kwargs,
    )
    return bot, db


def test_cli_accepts_mt5_data_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    class FakeMT5DataOnlyBot:
        def __init__(self, **kwargs) -> None:
            pass

        def run(self):
            return SimpleNamespace(
                mode="mt5-data",
                mt5_connected=False,
                symbols_seen=0,
                symbols_rejected=0,
                signals_detected=0,
                signals_rejected=0,
                risk_rejected=0,
                shadow_orders_created=0,
                execution_attempted=False,
            )

    monkeypatch.setattr(cli, "MT5DataOnlyBot", FakeMT5DataOnlyBot)
    code = cli.main(["--mode", "mt5-data", "--sqlite", str(tmp_path / "t.sqlite3")])
    assert code == 0
    assert '"mode": "mt5-data"' in capsys.readouterr().out


def test_mt5_data_never_calls_order_send_and_creates_shadow_order(tmp_path: Path) -> None:
    client = MockMT5DataClient()
    bot, db = _bot(tmp_path, client)
    try:
        summary = bot.run()
        assert summary.execution_attempted is False
        assert summary.mt5_connected is True
        assert summary.shadow_orders_created == 1
        assert db.count_rows("orders") == 1
        assert "order_send" not in client.calls
    finally:
        db.close()


def test_initialize_failure_fails_closed(tmp_path: Path) -> None:
    client = MockMT5DataClient(initialize_ok=False)
    bot, db = _bot(tmp_path, client)
    try:
        summary = bot.run()
        assert summary.mt5_connected is False
        assert summary.execution_attempted is False
        assert summary.shadow_orders_created == 0
        assert "order_send" not in client.calls
    finally:
        db.close()


def test_missing_account_info_fails_closed(tmp_path: Path) -> None:
    client = MockMT5DataClient(account_missing=True)
    bot, db = _bot(tmp_path, client)
    try:
        summary = bot.run()
        assert summary.mt5_connected is True
        assert summary.symbols_seen == 0
        assert summary.execution_attempted is False
        assert "order_send" not in client.calls
    finally:
        db.close()


def test_symbol_info_missing_rejects_symbol(tmp_path: Path) -> None:
    client = MockMT5DataClient(symbol_missing=True)
    bot, db = _bot(tmp_path, client)
    try:
        summary = bot.run()
        assert summary.symbols_seen == 1
        assert summary.symbols_rejected == 1
        assert summary.shadow_orders_created == 0
        assert "order_send" not in client.calls
    finally:
        db.close()


def test_stale_tick_rejects_symbol(tmp_path: Path) -> None:
    client = MockMT5DataClient(stale_tick=True)
    bot, db = _bot(tmp_path, client)
    try:
        summary = bot.run()
        assert summary.symbols_rejected == 1
        assert summary.shadow_orders_created == 0
    finally:
        db.close()


def test_empty_market_data_rejects_symbol(tmp_path: Path) -> None:
    client = MockMT5DataClient(empty_rates=True)
    bot, db = _bot(tmp_path, client)
    try:
        summary = bot.run()
        assert summary.symbols_rejected == 1
        assert summary.signals_detected == 0
        assert summary.shadow_orders_created == 0
    finally:
        db.close()


def test_risk_rejected_creates_no_shadow_order(tmp_path: Path) -> None:
    client = MockMT5DataClient()
    bot, db = _bot(tmp_path, client, risk_engine=RejectingRiskEngine())
    try:
        summary = bot.run()
        assert summary.risk_rejected == 1
        assert summary.shadow_orders_created == 0
        assert db.count_rows("orders") == 0
    finally:
        db.close()


def test_missing_audit_sink_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(AuditUnavailableError):
        MT5DataOnlyBot(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=None,
            mt5_client=MockMT5DataClient(),
        )


def test_telegram_failure_does_not_break_mt5_data_loop(tmp_path: Path) -> None:
    def failing_sender(_url: str, _payload: object, _timeout: float):
        raise requests.Timeout("telegram timeout token 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    client = MockMT5DataClient()
    db = TelemetryDatabase(tmp_path / "telemetry.sqlite3")
    try:
        bot = MT5DataOnlyBot(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            mt5_client=client,
            telegram_notifier=TelegramNotifier(
                database=db,
                enabled=True,
                bot_token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                chat_id="123456789",
                sender=failing_sender,
            ),
        )
        summary = bot.run()
        assert summary.execution_attempted is False
        assert summary.shadow_orders_created == 1
        assert any(row["status"] == "FAILED" for row in db.fetch_all("telegram_outbox"))
    finally:
        db.close()


def test_real_account_read_only_stops_before_symbols(tmp_path: Path) -> None:
    client = MockMT5DataClient(trade_mode=MockMT5DataClient.ACCOUNT_TRADE_MODE_REAL)
    bot, db = _bot(tmp_path, client)
    try:
        summary = bot.run()
        assert summary.mt5_connected is True
        assert summary.symbols_seen == 0
        assert summary.execution_attempted is False
        assert "order_send" not in client.calls
    finally:
        db.close()

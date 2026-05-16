from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import (
    Direction,
    EntryType,
    PositionState,
    RiskDecision,
    TradeSignal,
    utc_now,
)
from agi_style_forex_bot_mt5.execution import (
    ExecutionEngine,
    MT5Connector,
    RETCODE_DONE,
    RETCODE_PRICE_CHANGED,
    TradeManager,
    is_market_probably_closed,
)


@dataclass
class FakeMT5:
    trade_mode: int = 0
    account_trade_allowed: bool = True
    terminal_connected: bool = True
    terminal_trade_allowed: bool = True
    spread_points: float = 10
    tick_age_seconds: int = 0
    stops_level: int = 10
    freeze_level: int = 5
    filling_mode: int = 0
    order_check_retcode: int = RETCODE_DONE
    send_retcodes: tuple[int, ...] = (RETCODE_DONE,)
    margin_mode: int = 1

    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    ACCOUNT_MARGIN_MODE_RETAIL_NETTING = 0
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 1
    ACCOUNT_MARGIN_MODE_EXCHANGE = 2
    SYMBOL_TRADE_MODE_DISABLED = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5
    ORDER_TIME_GTC = 0
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1

    def __post_init__(self) -> None:
        self.calls: list[str] = []
        self._send_index = 0

    def terminal_info(self):
        return SimpleNamespace(
            connected=self.terminal_connected,
            trade_allowed=self.terminal_trade_allowed,
        )

    def account_info(self):
        return SimpleNamespace(
            login=123456,
            trade_mode=self.trade_mode,
            trade_allowed=self.account_trade_allowed,
            margin_mode=self.margin_mode,
        )

    def symbol_info(self, symbol: str):
        point = 0.00001
        bid = 1.10000
        ask = bid + self.spread_points * point
        return SimpleNamespace(
            name=symbol,
            visible=True,
            trade_mode=1,
            filling_mode=self.filling_mode,
            digits=5,
            point=point,
            trade_tick_value=1.0,
            trade_tick_size=point,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_stops_level=self.stops_level,
            trade_freeze_level=self.freeze_level,
            _bid=bid,
            _ask=ask,
        )

    def symbol_select(self, symbol: str, enabled: bool) -> bool:
        self.calls.append("symbol_select")
        return True

    def symbol_info_tick(self, symbol: str):
        info = self.symbol_info(symbol)
        timestamp = utc_now().timestamp() - self.tick_age_seconds
        return SimpleNamespace(
            bid=info._bid,
            ask=info._ask,
            time=int(timestamp),
            time_msc=int(timestamp * 1000),
        )

    def order_check(self, request: dict):
        self.calls.append("order_check")
        return SimpleNamespace(retcode=self.order_check_retcode, comment="checked")

    def order_send(self, request: dict):
        self.calls.append("order_send")
        retcode = self.send_retcodes[min(self._send_index, len(self.send_retcodes) - 1)]
        self._send_index += 1
        return SimpleNamespace(
            retcode=retcode,
            price=request["price"] + 0.00002,
            volume=request["volume"],
            order=777,
            deal=888,
            position=999,
            request_id=42,
            comment="sent",
        )

    def positions_get(self, symbol: str):
        return ()

    def last_error(self):
        return (0, "")


def _signal() -> TradeSignal:
    return TradeSignal(
        signal_id="sig_exec_1",
        created_at_utc=utc_now(),
        symbol="EURUSD",
        timeframe="M5",
        direction=Direction.BUY,
        entry_type=EntryType.MARKET,
        sl_price=1.09800,
        tp_price=1.10200,
        confidence=0.8,
    )


def _risk() -> RiskDecision:
    return RiskDecision(
        signal_id="sig_exec_1",
        accepted=True,
        approved_lot=0.01,
        risk_amount_account_currency=10.0,
        open_risk_pct_after_trade=0.1,
    )


def _engine(fake: FakeMT5) -> ExecutionEngine:
    cfg = BotConfig()
    connector = MT5Connector(config=cfg, mt5_client=fake)
    return ExecutionEngine(config=cfg, connector=connector)


def test_successful_execution_runs_order_check_before_order_send() -> None:
    fake = FakeMT5()
    result = _engine(fake).execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is True
    assert result.filled is True
    assert result.retcode == RETCODE_DONE
    assert fake.calls == ["order_check", "order_send"]


def test_demo_only_blocks_real_account_before_order_send() -> None:
    fake = FakeMT5(trade_mode=FakeMT5.ACCOUNT_TRADE_MODE_REAL)
    result = _engine(fake).execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is False
    assert result.retcode_description == "DEMO_ONLY_REAL_ACCOUNT"
    assert "order_send" not in fake.calls


def test_live_account_blocked_when_live_trading_not_approved() -> None:
    fake = FakeMT5(trade_mode=FakeMT5.ACCOUNT_TRADE_MODE_REAL)
    cfg = BotConfig(demo_only=False, live_trading_approved=False)
    connector = MT5Connector(config=cfg, mt5_client=fake)
    engine = ExecutionEngine(config=cfg, connector=connector)

    result = engine.execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is False
    assert result.retcode_description == "LIVE_TRADING_NOT_APPROVED"
    assert "order_send" not in fake.calls


def test_audit_must_be_confirmed_before_request_construction() -> None:
    fake = FakeMT5()
    result = _engine(fake).execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=False,
        magic_number=20260515,
    )

    assert result.sent is False
    assert result.retcode_description == "AUDIT_NOT_CONFIRMED"
    assert fake.calls == []


def test_stale_tick_is_rejected() -> None:
    fake = FakeMT5(tick_age_seconds=30)
    result = _engine(fake).execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is False
    expected = "MARKET_CLOSED_OR_NO_TICKS" if is_market_probably_closed(utc_now(), "EURUSD") else "MARKET_DATA_INVALID"
    assert result.retcode_description == expected
    assert "order_send" not in fake.calls


def test_high_spread_is_rejected_at_execution_gate() -> None:
    fake = FakeMT5(spread_points=40)
    result = _engine(fake).execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is False
    assert result.retcode_description == "HIGH_SPREAD"
    assert "order_send" not in fake.calls


def test_invalid_stops_are_rejected_before_order_check() -> None:
    fake = FakeMT5(stops_level=500)
    result = _engine(fake).execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is False
    assert result.retcode_description == "EXECUTION_CONSTRAINT"
    assert fake.calls == []


def test_retries_only_recoverable_retcodes_with_same_signal_id() -> None:
    fake = FakeMT5(send_retcodes=(RETCODE_PRICE_CHANGED, RETCODE_DONE))
    engine = _engine(fake)
    result = engine.execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.filled is True
    assert result.signal_id == "sig_exec_1"
    assert fake.calls == ["order_check", "order_send", "order_check", "order_send"]
    assert engine.broker_quality.report().recoverable_rejects == 1


def test_duplicate_signal_is_blocked() -> None:
    fake = FakeMT5()
    engine = _engine(fake)
    first = engine.execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )
    second = engine.execute(
        signal=_signal(),
        risk_decision=_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert first.filled is True
    assert second.sent is False
    assert second.retcode_description == "DUPLICATE_SIGNAL"


def test_trade_manager_break_even_and_trailing_rules() -> None:
    manager = TradeManager()
    position = PositionState(
        ticket=1,
        symbol="EURUSD",
        direction=Direction.BUY,
        volume=0.01,
        entry_price=1.10000,
        sl_price=1.09900,
        tp_price=1.10200,
        magic_number=20260515,
    )

    break_even = manager.evaluate_stop(
        position=position,
        bid=1.10070,
        ask=1.10080,
        point=0.00001,
    )
    trailing = manager.evaluate_stop(
        position=position,
        bid=1.10090,
        ask=1.10100,
        point=0.00001,
    )

    assert break_even.should_modify is True
    assert break_even.reason == "BREAK_EVEN"
    assert break_even.new_sl_price == position.entry_price
    assert trailing.should_modify is True
    assert trailing.reason == "TRAILING_STOP"
    assert trailing.new_sl_price is not None
    assert trailing.new_sl_price > position.entry_price

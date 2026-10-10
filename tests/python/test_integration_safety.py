from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import requests

from agi_style_forex_bot_mt5.bot import ShadowDemoBot
from agi_style_forex_bot_mt5.cli import build_sample_features, build_sample_snapshot
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import (
    AccountState,
    Direction,
    EntryType,
    Environment,
    Event,
    RiskDecision,
    Severity,
    TradeSignal,
    utc_now,
)
from agi_style_forex_bot_mt5.execution import ExecutionEngine, MT5Connector, RETCODE_DONE
from agi_style_forex_bot_mt5.risk import RiskEngine, RiskRuntimeState
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelegramNotifier


@dataclass
class MockMT5:
    trade_mode: int = 0
    spread_points: float = 10.0

    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 1
    SYMBOL_TRADE_MODE_DISABLED = 0
    ORDER_FILLING_FOK = 0
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0

    def __post_init__(self) -> None:
        self.calls: list[str] = []

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(
            login=123456,
            trade_mode=self.trade_mode,
            trade_allowed=True,
            margin_mode=self.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
        )

    def symbol_info(self, symbol: str):
        point = 0.00001
        bid = 1.10000
        ask = bid + self.spread_points * point
        return SimpleNamespace(
            name=symbol,
            visible=True,
            trade_mode=1,
            filling_mode=self.ORDER_FILLING_FOK,
            digits=5,
            point=point,
            trade_tick_value=1.0,
            trade_tick_size=point,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_stops_level=10,
            trade_freeze_level=5,
            _bid=bid,
            _ask=ask,
        )

    def symbol_select(self, symbol: str, enabled: bool) -> bool:
        self.calls.append("symbol_select")
        return True

    def symbol_info_tick(self, symbol: str):
        info = self.symbol_info(symbol)
        # Stamped 1 s back: the connector reads its clock before polling, and a later stamp reads as a future tick.
        timestamp = utc_now().timestamp() - 1
        return SimpleNamespace(
            bid=info._bid,
            ask=info._ask,
            time=int(timestamp),
            time_msc=int(timestamp * 1000),
        )

    def order_check(self, request: dict):
        self.calls.append("order_check")
        return SimpleNamespace(retcode=RETCODE_DONE, comment="checked")

    def order_send(self, request: dict):
        self.calls.append("order_send")
        return SimpleNamespace(
            retcode=RETCODE_DONE,
            price=request["price"],
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


def _demo_account() -> AccountState:
    return AccountState(
        login=123,
        trade_mode="DEMO",
        balance=10_000,
        equity=10_000,
        margin_free=9_000,
        is_demo=True,
        trade_allowed=True,
    )


def _real_account() -> AccountState:
    return AccountState(
        login=123,
        trade_mode="REAL",
        balance=10_000,
        equity=10_000,
        margin_free=9_000,
        is_demo=False,
        trade_allowed=True,
    )


def _signal(*, signal_id: str = "sig_integration", tp_price: float = 1.10200) -> TradeSignal:
    return TradeSignal(
        signal_id=signal_id,
        created_at_utc=utc_now(),
        symbol="EURUSD",
        timeframe="M5",
        direction=Direction.BUY,
        entry_type=EntryType.MARKET,
        sl_price=1.09800,
        tp_price=tp_price,
        risk_pct=0.5,
        confidence=0.8,
        strategy_name="integration-test",
    )


def _accepted_risk(signal_id: str = "sig_integration") -> RiskDecision:
    return RiskDecision(
        signal_id=signal_id,
        accepted=True,
        approved_lot=0.01,
        risk_amount_account_currency=10.0,
        open_risk_pct_after_trade=0.1,
    )


def _engine(fake: MockMT5, config: BotConfig | None = None) -> ExecutionEngine:
    cfg = config or BotConfig()
    connector = MT5Connector(config=cfg, mt5_client=fake)
    return ExecutionEngine(config=cfg, connector=connector)


def test_shadow_loop_audits_signal_risk_decision_and_skips_execution(tmp_path: Path) -> None:
    bot = ShadowDemoBot(
        config=BotConfig(),
        audit_logger=JsonlAuditLogger(tmp_path),
        run_id="run_integration_shadow",
    )

    result = bot.run_once(
        snapshot=build_sample_snapshot(),
        features=build_sample_features(),
        account=_demo_account(),
    )

    assert result.execution_attempted is False
    records = [
        json.loads(line)
        for path in tmp_path.glob("events-*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    event_types = [record["event_type"] for record in records]
    assert "SIGNAL_GENERATED" in event_types
    assert "TRADE_SIGNAL_CREATED" in event_types
    assert any(event_type in {"SIGNAL_ACCEPTED", "SIGNAL_REJECTED"} for event_type in event_types)
    assert "EXECUTION_SKIPPED" in event_types
    assert all(record["message"] for record in records)


def test_demo_only_real_account_is_rejected_and_audited_before_execution(tmp_path: Path) -> None:
    bot = ShadowDemoBot(
        config=BotConfig(),
        audit_logger=JsonlAuditLogger(tmp_path),
        run_id="run_integration_real_block",
    )

    result = bot.run_once(
        snapshot=build_sample_snapshot(),
        features=build_sample_features(),
        account=_real_account(),
    )

    assert result.execution_attempted is False
    assert result.risk_accepted is False
    assert result.risk_reject_code == "DEMO_ONLY_REAL_ACCOUNT"
    lines = "\n".join(
        path.read_text(encoding="utf-8") for path in tmp_path.glob("events-*.jsonl")
    )
    assert "DEMO_ONLY_REAL_ACCOUNT" in lines


def test_live_trading_not_approved_blocks_mocked_mt5_order_send() -> None:
    fake = MockMT5(trade_mode=MockMT5.ACCOUNT_TRADE_MODE_REAL)
    cfg = BotConfig(demo_only=False, live_trading_approved=False)

    result = _engine(fake, cfg).execute(
        signal=_signal(),
        risk_decision=_accepted_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is False
    assert result.retcode_description == "SHADOW_MODE_BLOCKED"
    assert "order_send" not in fake.calls


def test_no_order_without_tp_at_risk_or_execution_gate() -> None:
    snapshot = build_sample_snapshot()
    signal_without_tp = _signal(tp_price=0.0)
    risk_decision = RiskEngine().evaluate(
        signal=signal_without_tp,
        snapshot=snapshot,
        account=_demo_account(),
        state=RiskRuntimeState(daily_equity_reference=10_000, audit_confirmed=True),
    )
    assert risk_decision.accepted is False
    assert risk_decision.reject_code == "MISSING_TP"

    fake = MockMT5()
    execution_result = _engine(fake).execute(
        signal=signal_without_tp,
        risk_decision=_accepted_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )
    assert execution_result.sent is False
    assert "order_check" not in fake.calls
    assert "order_send" not in fake.calls


def test_telegram_failure_result_does_not_raise() -> None:
    def failing_sender(_url: str, _payload: object, _timeout: float) -> requests.Response:
        raise requests.Timeout("network timeout for token 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    event = Event.create(
        run_id="run_integration_telegram",
        environment=Environment.DEMO,
        severity=Severity.WARNING,
        module="risk",
        event_type="SIGNAL_REJECTED",
        message="blocked by safety gate",
        correlation_id="sig_integration",
        signal_id="sig_integration",
        symbol="EURUSD",
    )
    notifier = TelegramNotifier(
        enabled=True,
        bot_token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        chat_id="123456789",
        sender=failing_sender,
    )

    result = notifier.notify_event(event)

    assert result.sent is False
    assert result.status == "FAILED"
    assert result.error is not None
    assert "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in result.error


def test_accepted_risk_alone_cannot_enable_broker_execution() -> None:
    fake = MockMT5()

    result = _engine(fake).execute(
        signal=_signal(),
        risk_decision=_accepted_risk(),
        audit_confirmed=True,
        magic_number=20260515,
    )

    assert result.sent is False
    assert result.filled is False
    assert result.retcode_description == "SHADOW_MODE_BLOCKED"
    assert fake.calls == []

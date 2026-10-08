"""The supported Python adapter cannot construct, check or send broker orders."""

import pytest

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import Direction, EntryType, ExecutionRequest, RiskDecision, TradeSignal, utc_now
from agi_style_forex_bot_mt5.execution import ExecutionEngine, MT5Connector


class UntouchableClient:
    def __getattr__(self, name):
        raise AssertionError(f"release lock must run before touching client attribute {name}")


def request():
    # Even malformed protections must be blocked before the adapter/client path.
    return ExecutionRequest("release-lock", "EURUSD", Direction.BUY, EntryType.MARKET,
        1, 0, 0, 10, 101, "fixture")


@pytest.mark.parametrize("shadow,code", ((True, "SHADOW_MODE_BLOCKED"), (False, "EXECUTION_NOT_RELEASED")))
@pytest.mark.parametrize("demo_only,live_approved", ((True, False), (False, False), (False, True), (True, True)))
@pytest.mark.parametrize("audit", (True, False))
def test_flags_audit_and_claimed_promotion_cannot_grant_execution(shadow, code, demo_only, live_approved, audit):
    config = BotConfig(shadow_mode=shadow, demo_only=demo_only, live_trading_approved=live_approved,
        allowed_account_logins=(101,))
    connector = MT5Connector(config=config, mt5_client=UntouchableClient())
    engine = ExecutionEngine(config=config, connector=connector, max_retries=100)
    signal = TradeSignal("release-lock", utc_now(), "EURUSD", "M5", Direction.BUY, EntryType.MARKET,
        1.099, 1.102, metadata={"promotion_gate": {"approved": True, "effective_mode": "demo"}})
    risk = RiskDecision("release-lock", True, approved_lot=1, risk_amount_account_currency=1)
    for _ in range(2):
        result = engine.execute(signal=signal, risk_decision=risk, audit_confirmed=audit, magic_number=101)
        assert not result.sent and not result.filled and result.retcode_description == code
    with pytest.raises(ValueError, match=code):
        connector.build_trade_request(request(), None, 0)
    check = connector.order_check({"action": "arbitrary"})
    assert not check.accepted and check.code == code
    sent = connector.order_send(execution_request=request(), trade_request={"action": "arbitrary"}, filling_mode_name="FOK")
    assert not sent.sent and not sent.filled and sent.retcode_description == code


def test_mismatched_engine_and_connector_config_cannot_unlock_either_sink():
    connector = MT5Connector(config=BotConfig(shadow_mode=False), mt5_client=UntouchableClient())
    engine = ExecutionEngine(config=BotConfig(), connector=connector)
    signal = TradeSignal("release-lock", utc_now(), "EURUSD", "M5", Direction.BUY, EntryType.MARKET, 1.09, 1.11)
    result = engine.execute(signal=signal, risk_decision=RiskDecision("release-lock", True), audit_confirmed=True, magic_number=1)
    assert result.retcode_description == "SHADOW_MODE_BLOCKED"
    assert connector.order_check({}).code == "EXECUTION_NOT_RELEASED"

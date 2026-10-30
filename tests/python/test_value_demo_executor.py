"""Demo-only execution of the forward value book against a fake MT5 client (no terminal, no network)."""
from dataclasses import replace
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5.config import BotConfig, load_config
from agi_style_forex_bot_mt5.execution.release_policy import demo_release_gate, execution_block_reason
from agi_style_forex_bot_mt5.execution.value_demo_executor import MAGIC, DemoJournal, ValueDemoExecutor
from agi_style_forex_bot_mt5.research.daily_fx.forward_telegram import demo_messages
from agi_style_forex_bot_mt5.research.daily_fx.forward_trades import PaperTrade

LOGIN = 12345678
CONFIG = BotConfig(demo_execution_enabled=True, allowed_account_logins=(LOGIN,))


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, trade_mode=0, algo=True, equity=10_000.0):
        self.account = SimpleNamespace(login=LOGIN, trade_mode=trade_mode, equity=equity, balance=equity,
                                       trade_allowed=True, trade_expert=True)
        self.terminal = SimpleNamespace(trade_allowed=algo)
        self.ticks = {"EURUSD": (1.10000, 1.10010), "USDJPY": (150.000, 150.012)}
        self.positions: dict[int, SimpleNamespace] = {}
        self.sent: list[dict] = []
        self.next_ticket = 1000
        self.retcode = 10009

    def account_info(self):
        return self.account

    def terminal_info(self):
        return self.terminal

    def last_error(self):
        return (0, "ok")

    def symbol_select(self, symbol, enable):
        return True

    def symbol_info(self, symbol):
        jpy = symbol.endswith("JPY")
        return SimpleNamespace(point=0.001 if jpy else 0.00001, digits=3 if jpy else 5,
                               trade_tick_value=0.0066 if jpy else 1.0, trade_tick_size=0.001 if jpy else 0.00001,
                               volume_min=0.01, volume_max=100.0, volume_step=0.01, trade_stops_level=10,
                               trade_freeze_level=0, filling_mode=2, trade_mode=4)

    def symbol_info_tick(self, symbol):
        bid, ask = self.ticks.get(symbol, (1.00000, 1.00010))
        return SimpleNamespace(bid=bid, ask=ask)

    def positions_get(self):
        return tuple(self.positions.values())

    def order_send(self, request):
        self.sent.append(dict(request))
        if self.retcode not in (10008, 10009):
            return SimpleNamespace(retcode=self.retcode, order=0, deal=0, comment="rejected")
        if request["action"] == 6:
            position = self.positions[request["position"]]
            position.sl, position.tp = request["sl"], request["tp"]
            return SimpleNamespace(retcode=10009, order=0, deal=0, comment="done")
        if "position" in request:
            del self.positions[request["position"]]
            return SimpleNamespace(retcode=10009, order=request["position"], deal=1, comment="done")
        self.next_ticket += 1
        self.positions[self.next_ticket] = SimpleNamespace(
            ticket=self.next_ticket, symbol=request["symbol"], type=request["type"], volume=request["volume"],
            price_open=request["price"], sl=request["sl"], tp=request["tp"], magic=request["magic"], profit=0.0)
        return SimpleNamespace(retcode=10009, order=self.next_ticket, deal=1, comment="done")


def trade(trade_id="EURUSD-2026-10-26", symbol="EURUSD", side="BUY", sl=1.08000, tp=1.16000, risk=0.5, **extra):
    return PaperTrade(trade_id=trade_id, currency=symbol[:3], symbol=symbol, side=side, opened_on="2026-10-26",
                      open_price=1.1, stop_loss=sl, take_profit=tp, risk_percent=risk, opened_before_start=False,
                      current_stop_loss=sl, current_take_profit=tp, current_risk_percent=risk, **extra)


def executor(tmp_path, client, config=CONFIG):
    return ValueDemoExecutor(config, client, DemoJournal(tmp_path / "demo"))


# --- release policy -------------------------------------------------------------------------------------------


def test_the_generic_execution_lock_is_unchanged():
    assert execution_block_reason(BotConfig(shadow_mode=False))[0] == "EXECUTION_NOT_RELEASED"


@pytest.mark.parametrize("client, config, code", [
    (FakeMT5(trade_mode=2), CONFIG, "REAL_ACCOUNT_BLOCKED"),
    (FakeMT5(trade_mode=1), CONFIG, "REAL_ACCOUNT_BLOCKED"),
    (FakeMT5(), BotConfig(allowed_account_logins=(LOGIN,)), "DEMO_EXECUTION_DISABLED"),
    (FakeMT5(), BotConfig(demo_execution_enabled=True), "ACCOUNT_NOT_WHITELISTED"),
    (FakeMT5(algo=False), CONFIG, "ALGO_TRADING_DISABLED"),
    (FakeMT5(), replace(CONFIG, demo_only=False), "CONFIG_UNSAFE"),
    (FakeMT5(), replace(CONFIG, live_trading_approved=True), "CONFIG_UNSAFE"),
])
def test_the_gate_opens_only_on_a_whitelisted_demo_account(client, config, code):
    allowed, got, _ = demo_release_gate(config, client.account_info(), client.terminal_info())
    assert not allowed and got == code


def test_a_real_account_never_receives_an_order(tmp_path):
    client = FakeMT5(trade_mode=2)
    run = executor(tmp_path, client).run([trade()])
    assert not run.released and run.code == "REAL_ACCOUNT_BLOCKED" and client.sent == []


def test_the_config_file_keeps_execution_off_unless_asked(tmp_path):
    path = tmp_path / "bot.ini"
    path.write_text("MT5_SERVER_TIME=NY_CLOSE\n")
    assert load_config(path).demo_execution_enabled is False
    path.write_text(f"DEMO_EXECUTION_ENABLED=True\nALLOWED_ACCOUNT_LOGINS={LOGIN}\n")
    config = load_config(path)
    assert config.demo_execution_enabled is True and config.allowed_account_logins == (LOGIN,)


# --- orders ----------------------------------------------------------------------------------------------------


def test_each_order_carries_its_stop_and_target_and_the_risk_sized_lot(tmp_path):
    client = FakeMT5()
    run = executor(tmp_path, client).run([trade()])
    assert run.released and len(run.opened) == 1 and client.sent[0]["magic"] == MAGIC
    order = client.sent[0]
    assert order["sl"] == 1.08 and order["tp"] == 1.16 and order["type"] == 0 and order["price"] == 1.1001
    # Capital 10,000 x 0.5% = 50; risk per lot = (1.1001 - 1.08) / 0.00001 x 1.0 = 2,010 -> 0.0248 -> 0.02 lots.
    assert order["volume"] == 0.02 and run.opened[0]["risk_amount"] <= 50.0
    journal = (tmp_path / "demo" / "demo_journal.jsonl").read_text().splitlines()
    assert [json.loads(line)["event"] for line in journal] == ["REQUEST", "RESULT"]


def test_a_rerun_never_opens_the_same_trade_twice_and_a_broker_close_is_final(tmp_path):
    client = FakeMT5()
    executor(tmp_path, client).run([trade()])
    assert executor(tmp_path, client).run([trade()]).opened == [] and len(client.sent) == 1
    client.positions.clear()  # the stop loss or the take-profit was hit on the broker
    run = executor(tmp_path, client).run([trade()])
    assert run.opened == [] and run.closed[0]["by"] == "broker (SL/TP)" and len(client.sent) == 1


def test_a_paper_close_closes_the_demo_position_and_a_re_anchor_moves_its_levels(tmp_path):
    client = FakeMT5()
    executor(tmp_path, client).run([trade()])
    moved = trade(sl=1.07000, tp=1.17000)
    run = executor(tmp_path, client).run([moved])
    assert run.modified and client.sent[-1]["action"] == 6 and client.sent[-1]["sl"] == 1.07
    closed = trade()
    closed.closed_on = "2026-11-20"
    run = executor(tmp_path, client).run([closed])
    assert run.closed[0]["by"] == "rebalanceo" and client.positions == {}
    assert client.sent[-1]["type"] == 1 and "position" in client.sent[-1]


def test_unsafe_orders_are_skipped(tmp_path):
    client = FakeMT5()
    run = executor(tmp_path, client).run([trade(sl=1.10005, tp=1.16)])  # price already at the stop
    assert run.skipped[0]["reason"].startswith("LEVELS_INVALID") and client.sent == []
    client.ticks["EURUSD"] = (1.10000, 1.10300)  # 30-pip spread against a 200-pip stop
    run = executor(tmp_path / "b", client).run([trade()])
    assert run.skipped[0]["reason"] == "SPREAD_TOO_WIDE"
    client = FakeMT5()
    client.account.equity = 9_400.0  # floating loss 6% of balance
    assert executor(tmp_path / "c", client).run([trade()]).skipped[0]["reason"] == "FLOATING_DRAWDOWN_LIMIT"


def test_open_risk_and_open_trades_stay_within_the_limits(tmp_path):
    client = FakeMT5()
    many = [trade(trade_id=f"T{n}", risk=0.5) for n in range(12)]
    run = executor(tmp_path, client).run(many)
    assert len(run.opened) <= 10 and len(client.positions) <= 10
    reasons = {item["reason"] for item in run.skipped}
    assert reasons <= {"MAX_OPEN_TRADES", "MAX_OPEN_RISK"}
    total = sum(item["risk_amount"] for item in run.opened)
    assert total <= 0.05 * 10_000.0 + 1e-9


def test_a_rejected_order_is_reported_and_not_recorded_as_open(tmp_path):
    client = FakeMT5()
    client.retcode = 10019  # not enough money
    run = executor(tmp_path, client).run([trade()])
    assert run.failed and "10019" in run.failed[0]["reason"] and run.opened == []
    assert json.loads((tmp_path / "demo" / "demo_state.json").read_text())["trades"] == {}


def test_jpy_pairs_and_lot_sizing_take_milliseconds(tmp_path):
    client = FakeMT5()
    started = time.perf_counter()
    run = executor(tmp_path, client).run([trade(trade_id="USDJPY-2026-10-26", symbol="USDJPY", side="SELL",
                                                sl=153.000, tp=141.000)])
    elapsed = time.perf_counter() - started
    assert run.opened and client.sent[0]["type"] == 1 and client.sent[0]["sl"] == 153.0
    assert run.opened[0]["risk_amount"] <= 50.0 and elapsed < 0.5


def test_messages_describe_each_demo_order(tmp_path):
    client = FakeMT5()
    run = executor(tmp_path, client).run([trade(), trade(trade_id="X", sl=1.10005)])
    texts = [message.text for message in demo_messages(run, "2026-10-30")]
    assert any("ABIERTA COMPRA EURUSD" in text and "Stop loss 1.08" in text for text in texts)
    assert any("en espera" in text for text in texts) and all("Cuenta demo" in text for text in texts)
    blocked = executor(tmp_path / "r", FakeMT5(trade_mode=2)).run([trade()])
    assert "REAL_ACCOUNT_BLOCKED" in demo_messages(blocked, "2026-10-30")[0].text


def test_positions_opened_by_hand_count_toward_the_open_risk_limit(tmp_path):
    client = FakeMT5()
    client.positions[1] = SimpleNamespace(ticket=1, symbol="EURUSD", type=0, volume=0.24, price_open=1.1,
                                          sl=1.08, tp=1.2, magic=0, profit=0.0)  # about 4.8% at risk, by hand
    assert executor(tmp_path, client).run([trade()]).skipped[0]["reason"] == "MAX_OPEN_RISK"
    client.positions[1].sl = 0.0  # a manual position without a stop: its risk cannot be measured
    assert executor(tmp_path / "b", client).run([trade()]).skipped[0]["reason"] == "MAX_OPEN_RISK"

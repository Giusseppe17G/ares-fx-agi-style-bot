"""Independent run-loop safety review with real decisions and fake MT5 data."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.price_grid import is_price_on_tick_grid
from agi_style_forex_bot_mt5.backtesting.stateful_replay import ClosedBarInput, ReplayEvidence, StatefulReplayEvent
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DataOnlyBot
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.paper_trading.live_decision_evidence import LiveDecisionEvidence
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

from test_stateful_replay import replay_case
from test_shared_strategy_features import _bars, _snapshot


def review_event(count):
    bars = _bars(count)
    # A nondegenerate spread history avoids float representation noise at the
    # percentile boundary while preserving actual feature/strategy decisions.
    bars["spread_points"] = [4. if i % 2 else 6. for i in range(len(bars))]
    quote = _snapshot(bars, count - 1)
    bid = round(quote.bid, 5)
    quote = replace(quote, bid=bid, ask=round(bid + .00005, 5))
    return StatefulReplayEvent(f"review-{count}", quote.timestamp_utc, {"EURUSD": quote},
        (ClosedBarInput("EURUSD", "M5", bars),),
        {"EURUSD": ReplayEvidence(quote.timestamp_utc, 85., 0.)})


@pytest.fixture
def review_case(replay_case):
    return {**replay_case, "event": review_event(220)}


class LifecycleClient:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2

    def __init__(self, event):
        self.event = event
        self.connected = True
        self.trade_mode = 0
        self.account_reads = 0
        self.terminal_reads = 0

    def initialize(self):
        return True

    def shutdown(self):
        pass

    def terminal_info(self):
        self.terminal_reads += 1
        return SimpleNamespace(connected=self.connected, trade_allowed=True)

    def account_info(self):
        self.account_reads += 1
        return SimpleNamespace(login=7, trade_mode=self.trade_mode, balance=10000.,
            equity=10000., margin_free=10000., currency="USD", trade_allowed=True)

    def symbol_info(self, symbol):
        quote = self.event.quotes["EURUSD"]
        return SimpleNamespace(name=symbol, visible=True, trade_mode=1, digits=quote.digits,
            point=quote.point, trade_tick_value=quote.tick_value, trade_tick_size=quote.tick_size,
            volume_min=quote.volume_min, volume_max=quote.volume_max, volume_step=quote.volume_step,
            trade_stops_level=quote.stops_level_points, trade_freeze_level=quote.freeze_level_points)

    def symbol_info_tick(self, symbol):
        quote = self.event.quotes["EURUSD"]
        return SimpleNamespace(bid=quote.bid, ask=quote.ask,
            time=int(quote.timestamp_utc.timestamp()), time_msc=int(quote.timestamp_utc.timestamp() * 1000))

    def last_error(self):
        return (0, "")

    def order_check(self, *_args, **_kwargs):
        raise AssertionError("read-only review must never reach broker order_check")

    def order_send(self, *_args, **_kwargs):
        raise AssertionError("read-only review must never reach broker order_send")


def forward_bot(case, tmp_path, monkeypatch, *, symbols=("EURUSD",), cycles=1):
    import agi_style_forex_bot_mt5.execution.mt5_connector as connector_module

    client = LifecycleClient(case["event"])
    clock = FrozenClock(client.event.timestamp_utc)
    # Only the data acquisition seam is supplied. Features, ensemble, complete
    # decision pipeline, risk state, fill, manager, recovery and audit are real.
    monkeypatch.setattr(connector_module, "utc_now", clock.now_utc)
    monkeypatch.setattr(MT5DataOnlyBot, "_read_timeframes",
        lambda self, *_args: {"M5": client.event.decisions[0].bars})
    database = TelemetryDatabase(tmp_path / "forward.sqlite3")
    bot = ForwardShadowBot(config=case["config"], symbols=symbols, database=database,
        audit_logger=JsonlAuditLogger(tmp_path / "events"), mt5_client=client,
        cycle_seconds=0, max_cycles=cycles, report_dir=str(tmp_path / "reports"), clock=clock,
        ml_filter=case["model_filter"],
        decision_evidence_provider=lambda snapshot, features, positions:
            {"observed_at_utc": clock.now_utc(), "broker_readiness_score": 85., "correlation": 0.})
    bot.manager.fill_model = replace(case["fill_model"], clock=clock)
    return bot, database, client, clock


def test_review_positive_control_real_run_opens_two_distinct_symbols(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch, symbols=("EURUSD", "GBPUSD"))
    try:
        summary = bot.run()
        assert summary.paper_trades_opened == 2
        assert database.count_rows("paper_trades") == 2
    finally:
        database.close()


@pytest.mark.parametrize("failed_sink", ("jsonl_opened", "paper_event_opened"))
def test_run_stops_later_symbols_after_first_fill_audit_failure(review_case, tmp_path, monkeypatch, failed_sink):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch, symbols=("EURUSD", "GBPUSD"))
    fired = []
    if failed_sink == "jsonl_opened":
        original = bot.audit_logger.append_event

        def fail_once(event):
            if event.event_type == "PAPER_TRADE_OPENED" and not fired:
                fired.append(True)
                raise OSError("synthetic required post-fill audit failure")
            return original(event)

        monkeypatch.setattr(bot.audit_logger, "append_event", fail_once)
    else:
        original = database.insert_paper_trade_event

        def fail_once(paper_trade_id, event_type, payload, **kwargs):
            if event_type == "PAPER_TRADE_OPENED" and not fired:
                fired.append(True)
                raise OSError("synthetic required paper lifecycle event failure")
            return original(paper_trade_id, event_type, payload, **kwargs)

        monkeypatch.setattr(database, "insert_paper_trade_event", fail_once)
    try:
        summary = bot.run()
        assert fired
        # The first position exists; its incomplete audit must remain visible.
        assert database.count_rows("paper_trades") == 1
        assert summary.halt_reason
    finally:
        database.close()


@pytest.mark.parametrize("change", ("real_account", "disconnected"))
def test_run_revalidates_connection_and_account_before_next_cycle(review_case, tmp_path, monkeypatch, change):
    bot, database, client, clock = forward_bot(review_case, tmp_path, monkeypatch, cycles=2)
    next_event = review_event(221)
    original = bot.heartbeat.write
    writes = []

    def advance(payload):
        result = original(payload)
        writes.append(True)
        if len(writes) == 1:
            client.event = next_event
            clock.instant = next_event.timestamp_utc
            if change == "real_account":
                client.trade_mode = client.ACCOUNT_TRADE_MODE_REAL
            else:
                client.connected = False
        return result

    monkeypatch.setattr(bot.heartbeat, "write", advance)
    try:
        summary = bot.run()
        assert database.count_rows("paper_trades") == 1
        if change == "disconnected":
            # Revalidated before the cycle: skipped without touching the book.
            assert summary.mt5_connected is False
            assert summary.skip_reason == "MT5_CONNECTION_UNVERIFIED" and not summary.lifecycle_halted
        else:
            assert summary.halt_reason == "ACCOUNT_REAL_DETECTED_READ_ONLY" and summary.lifecycle_halted
    finally:
        database.close()


def test_restart_cannot_forget_required_postfill_audit_failure(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch)
    original = database.insert_paper_trade_event
    fired = []

    def fail_once(paper_trade_id, event_type, payload, **kwargs):
        if event_type == "PAPER_TRADE_OPENED" and not fired:
            fired.append(True)
            raise OSError("synthetic required lifecycle audit failure")
        return original(paper_trade_id, event_type, payload, **kwargs)

    monkeypatch.setattr(database, "insert_paper_trade_event", fail_once)
    try:
        bot.run()
        assert fired and database.count_rows("paper_trades") == 1
    finally:
        database.close()
    restarted_case = {**review_case, "event": review_event(221)}
    restarted, database, _, _ = forward_bot(restarted_case, tmp_path, monkeypatch)
    try:
        summary = restarted.run()
        assert database.count_rows("paper_trades") == 1
        assert summary.halt_reason
        assert summary.audit_complete is False
    finally:
        database.close()


@pytest.mark.parametrize("missing_mark", ("absent", "stale"))
def test_incomplete_position_marks_cannot_partially_mutate_book(review_case, tmp_path, monkeypatch, missing_mark):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch, symbols=("EURUSD", "GBPUSD"))
    try:
        bot.run()
        initial_trades = bot.manager.load_open_trades()
        assert len(initial_trades) == 2
        eur_trade = next(item for item in initial_trades if item.symbol == "EURUSD")
    finally:
        database.close()
    next_event = review_event(221)
    quote = next_event.quotes["EURUSD"]
    stop_mark = eur_trade.sl_price + .001 if eur_trade.direction == "SELL" else eur_trade.sl_price - .001
    quote = replace(quote, bid=round(stop_mark, 5), ask=round(stop_mark + .00005, 5))
    next_event = replace(next_event, quotes={"EURUSD": quote})
    restarted, database, client, _ = forward_bot({**review_case, "event": next_event}, tmp_path, monkeypatch,
        symbols=("EURUSD", "GBPUSD"))
    original = client.symbol_info_tick

    def incomplete_tick(symbol):
        tick = original(symbol)
        if symbol.startswith("GBPUSD"):
            if missing_mark == "absent":
                return None
            tick.time -= 60
            tick.time_msc -= 60000
        return tick

    monkeypatch.setattr(client, "symbol_info_tick", incomplete_tick)
    try:
        summary = restarted.run()
        assert len(restarted.manager.load_open_trades()) == 2
        assert all(trade.status == "OPEN" for trade in restarted.manager.load_all_trades())
        # Nothing was mutated, so the live run skips and retries instead of latching.
        assert summary.skip_reason == "OPEN_POSITION_QUOTE_MISSING" and not summary.lifecycle_halted
    finally:
        database.close()


def test_actual_run_managed_stop_remains_on_broker_tick_grid(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch)
    try:
        bot.run()
        trade, = bot.manager.load_open_trades()
    finally:
        database.close()
    event = review_event(221)
    quote = event.quotes["EURUSD"]
    risk_distance = abs(trade.entry_price - trade.sl_price)
    favorable_mark = round(trade.entry_price + (-.9 if trade.direction == "SELL" else .9) * risk_distance, 5)
    bid = favorable_mark - .00005 if trade.direction == "SELL" else favorable_mark
    quote = replace(quote, bid=round(bid, 5), ask=round(bid + .00005, 5))
    event = replace(event, quotes={"EURUSD": quote})
    restarted, database, _, _ = forward_bot({**review_case, "event": event}, tmp_path, monkeypatch)
    try:
        restarted.run()
        updated = next(item for item in restarted.manager.load_all_trades() if item.paper_trade_id == trade.paper_trade_id)
        assert updated.sl_price != trade.sl_price
        assert is_price_on_tick_grid(updated.sl_price, quote.tick_size), updated.sl_price
    finally:
        database.close()


def _measured(bot, client, clock, monkeypatch):
    bars = client.event.decisions[0].bars
    monkeypatch.setattr(MT5DataOnlyBot, "_read_timeframes", lambda self, *_args: {"M5": bars, "M15": bars, "H1": bars})
    bot.decision_evidence_provider = LiveDecisionEvidence(max_spread_points=bot.config.max_spread_points_default, clock=clock)


def test_measured_live_evidence_opens_paper_trades_without_injected_scores(review_case, tmp_path, monkeypatch):
    bot, database, client, clock = forward_bot(review_case, tmp_path, monkeypatch, symbols=("EURUSD", "GBPUSD"))
    _measured(bot, client, clock, monkeypatch)
    try:
        summary = bot.run()
        # Identical bars measure correlation 1.0, so the second symbol is
        # rejected (by the ranker) instead of opening correlated risk.
        assert summary.paper_trades_opened == 1 and database.count_rows("paper_trades") == 1
        rejected = [row for row in database.fetch_all("events") if row["event_type"] == "PAPER_CANDIDATE_REJECTED"]
        assert len(rejected) == 1 and '"reject_code":"REJECT_CORRELATED"' in rejected[0]["payload_json"]
        assert not any("BROKER_EVIDENCE_MISSING" in row["payload_json"] for row in rejected)
    finally:
        database.close()


def test_skip_that_cannot_be_audited_latches(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch)
    client.connected = False
    original = JsonlAuditLogger.append_event

    def fail_skip(logger, event):
        if event.event_type == "PAPER_CYCLE_SKIPPED":
            raise OSError("injected skip audit failure")
        return original(logger, event)

    monkeypatch.setattr(JsonlAuditLogger, "append_event", fail_skip)
    try:
        summary = bot.run()
        assert summary.lifecycle_halted and not summary.audit_complete
        assert database.get_operational_state()["paper_lifecycle_halted"] is True
        assert database.count_rows("paper_trades") == 0
    finally:
        database.close()


def test_skip_never_clears_an_existing_latch(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch)
    database.update_operational_state({"paper_lifecycle_halted": True, "halt_reason": "STATEFUL_EVENT_ERROR"})
    client.connected = False
    try:
        summary = bot.run()
        assert summary.lifecycle_halted and summary.halt_reason == "PAPER_LIFECYCLE_HALTED"
        assert summary.cycles_skipped == 0
    finally:
        database.close()

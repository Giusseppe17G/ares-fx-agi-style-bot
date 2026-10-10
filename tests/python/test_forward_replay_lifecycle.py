"""Controlled reader-to-ledger episodes; strategy/risk/scan are never patched."""

from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5.backtesting.stateful_replay import ClosedBarInput, ReplayEvidence, StatefulReplayEvent
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.instruments.registry import InstrumentRegistry
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

from test_mt5_data_mode import MockMT5DataClient
from test_shared_strategy_features import _bars, _snapshot
from test_stateful_replay import replay_case, run_case


class EpisodeClient(MockMT5DataClient):
    """Only documented read methods; events advance at account observation."""

    def __init__(self, events, clock):
        super().__init__()
        self.events = tuple(events)
        self.symbols_available = tuple(dict.fromkeys(symbol for event in events for symbol in event.quotes))
        self.clock = clock
        self.index = -1

    def account_info(self):
        self.index = min(self.index + 1, len(self.events) - 1)
        self.clock.instant = self.events[self.index].timestamp_utc
        if hasattr(self, 'on_observe'):
            self.on_observe(self.index)
        value = super().account_info()
        value.login = 7
        value.margin_free = 10000.
        return value

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    @property
    def event(self):
        return self.events[max(self.index, 0)]

    def symbol_info_tick(self, symbol):
        quote = self.event.quotes.get(symbol)
        if quote is None:
            return None
        return SimpleNamespace(bid=quote.bid, ask=quote.ask,
            time=int(quote.timestamp_utc.timestamp()), time_msc=int(quote.timestamp_utc.timestamp()*1000))

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        candidate = next((item for item in self.event.decisions if item.symbol == symbol), None)
        if candidate is None:
            return []
        bars = candidate.bars.copy()
        # Other timeframes are actually read/normalized, but current strategy
        # consumes M5 only. Give each timeframe its own closed timestamps.
        if timeframe != self.TIMEFRAME_M5:
            import pandas as pd
            bars['timestamp_utc'] = pd.date_range(end=self.event.timestamp_utc-timedelta(minutes=timeframe),
                periods=len(bars), freq=f'{timeframe}min', tz='UTC')
        return [{'time': int(row.timestamp_utc.timestamp()), 'open': row.open,
            'high': row.high, 'low': row.low, 'close': row.close,
            'tick_volume': row.volume, 'spread': row.spread_points, 'real_volume': 0.}
            for row in bars.itertuples()]

    def copy_rates_range(self, *args):
        return []


@pytest.fixture
def lifecycle_case(replay_case):
    bars = _bars(220)
    bars['spread_points'] = [4. if i % 2 else 6. for i in range(len(bars))]
    quote = _snapshot(bars, 219)
    bid = round(quote.bid, 5)
    quote = replace(quote, bid=bid, ask=round(bid+.00005, 5))
    case = dict(replay_case)
    case['event'] = StatefulReplayEvent('cycle-1', quote.timestamp_utc, {'EURUSD': quote},
        (ClosedBarInput('EURUSD', 'M5', bars),), {'EURUSD': ReplayEvidence(quote.timestamp_utc, 85., None)})
    spec = replace(case['instrument_snapshot'].registry.get('EURUSD'), broker_symbol='EURUSD')
    case['instrument_snapshot'] = replace(case['instrument_snapshot'], registry=InstrumentRegistry.from_specs([spec]))
    return case


def forward_episode(case, path, events, *, on_observe=None):
    clock = FrozenClock(events[0].timestamp_utc)
    client = EpisodeClient(events, clock)
    database = TelemetryDatabase(path / 'forward.sqlite3')
    if on_observe is not None:
        client.on_observe = lambda index: on_observe(index, database)
    def evidence(snapshot, features, book):
        value = client.event.evidence.get(snapshot.symbol)
        return {} if value is None else vars(value)
    bot = ForwardShadowBot(config=case['config'], symbols=client.symbols_available,
        audit_logger=JsonlAuditLogger(path / 'events'), database=database,
        mt5_client=client, clock=clock, max_cycles=len(events), report_dir=str(path / 'reports'),
        ml_filter=case['model_filter'], decision_evidence_provider=evidence)
    bot.manager.fill_model = replace(case['fill_model'], clock=clock)
    summary = bot.run()
    return bot, database, summary, client


def test_stale_quality_cannot_open_in_actual_forward_run(lifecycle_case, tmp_path):
    event = lifecycle_case['event']
    stale = replace(event, evidence={'EURUSD': ReplayEvidence(event.timestamp_utc-timedelta(days=1), 85., None)})
    replay = run_case(lifecycle_case, tmp_path/'replay', [stale])
    assert not replay.trades
    assert replay.rejections[0]['reject_code'] == 'BROKER_EVIDENCE_TIME_INVALID'
    bot, database, summary, client = forward_episode(lifecycle_case, tmp_path/'forward', [stale])
    try:
        assert not bot.manager.load_all_trades(), summary
    finally:
        database.close()


@pytest.mark.parametrize('event_type', ['SIGNAL_GENERATED', 'PAPER_TRADE_OPENED', 'PAPER_CYCLE_COMPLETED'])
def test_shared_audit_failures_match_actual_callers(lifecycle_case, tmp_path, monkeypatch, event_type):
    original = JsonlAuditLogger.append_event
    # Keep each failed logger alive: the replay logger is freed before the
    # forward one exists, and CPython may reuse its id() for the new logger.
    failures = {}
    def fail_once_per_store(logger, event):
        if event.event_type == event_type and id(logger) not in failures:
            failures[id(logger)] = logger
            raise OSError('injected audit unavailable')
        return original(logger, event)
    monkeypatch.setattr(JsonlAuditLogger, 'append_event', fail_once_per_store)
    first = lifecycle_case['event']
    events = [first, quote_event(first, 1, first.quotes['EURUSD'].bid, decisions=first.decisions)]
    replay = run_case(lifecycle_case, tmp_path/'replay', events)
    bot, database, summary, client = forward_episode(lifecycle_case, tmp_path/'forward', events)
    try:
        assert len(failures) == 2
        assert summary.lifecycle_halted == replay.halted is True
        assert summary.audit_complete == replay.audit_complete is False
        assert summary.cycles_completed == replay.events_completed == 0
        assert bot.paper_cycle_results[-1].trades == replay.trades
        assert [decision.to_dict() for decision in bot.paper_cycle_results[-1].decisions] == [decision.to_dict() for decision in replay.decisions]
        assert database.get_operational_state()['paper_audit_complete'] is False
    finally:
        database.close()


@pytest.mark.parametrize('limit', [1, 2])
def test_two_symbol_exposure_and_limits_match_actual_callers(lifecycle_case, tmp_path, limit):
    first = lifecycle_case['event']
    quote = first.quotes['EURUSD']
    bars = first.decisions[0].bars
    event = replace(first, quotes={**first.quotes, 'GBPUSD': replace(quote, symbol='GBPUSD')},
        decisions=first.decisions+(ClosedBarInput('GBPUSD', 'M5', bars),),
        evidence={**first.evidence, 'GBPUSD': ReplayEvidence(first.timestamp_utc, 85., 0.)})
    spec = lifecycle_case['instrument_snapshot'].registry.get('EURUSD')
    gbp = replace(spec, symbol='GBPUSD', canonical_symbol='GBPUSD', broker_symbol='GBPUSD', currency_base='GBP')
    case = dict(lifecycle_case, config=replace(lifecycle_case['config'], max_open_paper_trades=limit),
        instrument_snapshot=replace(lifecycle_case['instrument_snapshot'], registry=InstrumentRegistry.from_specs([spec, gbp])))
    replay = run_case(case, tmp_path/'replay', [event])
    bot, database, summary, client = forward_episode(case, tmp_path/'forward', [event])
    try:
        assert not replay.halted and not summary.lifecycle_halted
        assert len(replay.trades) == limit
        result = bot.paper_cycle_results[0]
        assert result.trades == replay.trades
        assert [decision.to_dict() for decision in result.decisions] == [decision.to_dict() for decision in replay.decisions]
        assert result.valuation == replay.valuations[0]
        assert result.valuation['open_positions'] == limit
        assert result.valuation['open_risk_amount'] > 0
    finally:
        database.close()


@pytest.mark.parametrize('manual,required', [(False, False), (False, True), (True, False)])
def test_daily_rollover_respects_pause_owner_and_manual_resume(lifecycle_case, tmp_path, manual, required):
    first = lifecycle_case['event']
    loss = quote_event(first, 1, first.quotes['EURUSD'].bid+.02)
    midnight = first.timestamp_utc.replace(hour=0, minute=0, second=0)+timedelta(days=1)
    last = replace(loss, event_id='cycle-3', timestamp_utc=midnight,
        quotes={'EURUSD': replace(loss.quotes['EURUSD'], timestamp_utc=midnight)}, decisions=(), evidence={})
    case = dict(lifecycle_case, config=replace(lifecycle_case['config'], manual_resume_required=required))
    def manual_command(index, database):
        if manual and index == 1:
            database.set_shadow_paused(True, reason='operator review', paused_by='operator')
    bot, database, summary, _ = forward_episode(case, tmp_path/'forward', [first, loss, last], on_observe=manual_command)
    try:
        assert summary.cycles_completed == 3 and not summary.lifecycle_halted
        assert bot.paper_cycle_results[1].valuation['daily_halted']
        assert bot.paper_cycle_results[1].paused
        assert not bot.paper_cycle_results[2].valuation['daily_halted']
        assert summary.shadow_paused is (manual or required)
        if manual:
            runtime = database.get_operational_state()
            assert runtime['paused_reason'] == 'operator review' and runtime['paused_by'] == 'operator'
    finally:
        database.close()


@pytest.mark.parametrize('event_type', ['SIGNAL_GENERATED', 'PAPER_TRADE_OPENED', 'MARKET_DATA_READ'])
def test_required_audit_failure_stops_actual_forward_run(lifecycle_case, tmp_path, monkeypatch, event_type):
    original = JsonlAuditLogger.append_event
    failures = []
    def fail_once(logger, event):
        if event.event_type == event_type and not failures:
            failures.append(event.event_type)
            raise OSError('injected required audit failure')
        return original(logger, event)
    monkeypatch.setattr(JsonlAuditLogger, 'append_event', fail_once)
    first = lifecycle_case['event']
    second = quote_event(first, 1, first.quotes['EURUSD'].bid, decisions=first.decisions)
    bot, database, summary, client = forward_episode(lifecycle_case, tmp_path/'forward', [first, second])
    try:
        assert failures
        assert summary.lifecycle_halted and not summary.audit_complete
        assert summary.cycles_completed == 0
        assert client.calls.count('account_info') == 1
        assert len(bot.manager.load_all_trades()) == (1 if event_type == 'PAPER_TRADE_OPENED' else 0)
        assert all(not decision.accepted for result in bot.paper_cycle_results for decision in result.decisions)
    finally:
        database.close()


def test_failed_halt_audit_remains_incomplete_after_restart(lifecycle_case, tmp_path, monkeypatch):
    original = JsonlAuditLogger.append_event
    failures = []
    def fail_halt_once(logger, event):
        if event.event_type == 'PAPER_CYCLE_HALTED' and not failures:
            failures.append(True)
            raise OSError('injected halt audit failure')
        return original(logger, event)
    monkeypatch.setattr(JsonlAuditLogger, 'append_event', fail_halt_once)
    with monkeypatch.context() as disconnected:
        disconnected.setattr(EpisodeClient, 'terminal_info', lambda self: SimpleNamespace(connected=False))
        bot, database, summary, _ = forward_episode(lifecycle_case, tmp_path, [lifecycle_case['event']])
        try:
            assert failures and not summary.audit_complete
            assert database.get_operational_state()['paper_audit_complete'] is False
            assert database.count_rows('paper_trades') == 0
        finally:
            database.close()
    _, database, restarted, _ = forward_episode(lifecycle_case, tmp_path, [lifecycle_case['event']])
    try:
        assert restarted.lifecycle_halted and not restarted.audit_complete
        assert database.get_operational_state()['paper_audit_complete'] is False
        assert database.count_rows('paper_trades') == 0
    finally:
        database.close()


@pytest.mark.parametrize('currency', [None, 123, True, 'US', 'US1'])
def test_account_currency_must_be_explicit_text(lifecycle_case, tmp_path, monkeypatch, currency):
    original = EpisodeClient.account_info
    def account(self):
        value = original(self)
        value.currency = currency
        return value
    monkeypatch.setattr(EpisodeClient, 'account_info', account)
    bot, database, summary, _ = forward_episode(lifecycle_case, tmp_path, [lifecycle_case['event']])
    try:
        assert summary.lifecycle_halted and summary.halt_reason == 'ACCOUNT_INFO_INVALID'
        assert not bot.manager.load_all_trades()
    finally:
        database.close()


def quote_event(entry, index, bid, *, decisions=(), evidence_age=0):
    now = entry.timestamp_utc + timedelta(seconds=60 * index)
    base = entry.quotes['EURUSD']
    quote = replace(base, timestamp_utc=now, bid=round(bid, 5), ask=round(bid+.00005, 5))
    return StatefulReplayEvent(f'cycle-{index+1}', now, {'EURUSD': quote}, decisions,
        {'EURUSD': ReplayEvidence(now-timedelta(seconds=evidence_age), 85., 0.)})


def test_vwap_overflow_blocks_actual_forward_and_replay_before_candidate(lifecycle_case, tmp_path):
    first = lifecycle_case['event']
    bars = first.decisions[0].bars.copy(deep=True)
    bars['volume'] = 1e308
    event = replace(first, decisions=(replace(first.decisions[0], bars=bars),))
    replay = run_case(lifecycle_case, tmp_path/'replay', [event])
    assert replay.halted and replay.audit_complete and not replay.trades
    assert not replay.decisions
    bot, database, summary, client = forward_episode(lifecycle_case, tmp_path/'forward', [event])
    try:
        # Forward catches feature failure during acquisition and excludes the
        # candidate. Replay catches it inside the lifecycle and halts that run.
        # Both must persist evidence and prevent strategy/risk/order decisions.
        assert summary.audit_complete
        assert database.count_rows('paper_trades') == 0
        assert not bot.paper_cycle_results[0].decisions
        audit = [json.loads(line) for path in (tmp_path/'forward'/'events').glob('*.jsonl')
                 for line in path.read_text(encoding='utf-8').splitlines()]
        failures = [json.loads(item['payload_json']) for item in audit
                    if item['event_type'] == 'FORWARD_FEATURE_BUILD_FAILED']
        assert len(failures) == 1
        assert 'VWAP arithmetic' in failures[0]['feature_build_exception']
        assert failures[0]['execution_attempted'] is False
        assert not any(call in {'order_send', 'order_check'} for call in client.calls)
    finally:
        database.close()


@pytest.mark.parametrize('episode', ['stop_gap', 'profit', 'managed_stop', 'same_candle', 'stale_evidence', 'missing_quote'])
def test_actual_forward_run_matches_replay_economics(lifecycle_case, tmp_path, episode):
    """Real run acquisition+core+manager; no strategy/risk/scan/evaluator mocks."""
    first = lifecycle_case['event']
    bid = first.quotes['EURUSD'].bid
    if episode == 'stop_gap':
        events = [first, quote_event(first, 1, bid+.02)]
    elif episode == 'profit':
        events = [first, quote_event(first, 1, bid-.003)]
    elif episode == 'managed_stop':
        events = [first, quote_event(first, 1, bid-.0009), quote_event(first, 2, bid+.0002)]
    elif episode == 'same_candle':
        events = [first, quote_event(first, 1, bid, decisions=first.decisions)]
    elif episode == 'stale_evidence':
        first = replace(first, evidence={'EURUSD': ReplayEvidence(first.timestamp_utc-timedelta(days=1), 85., None)})
        events = [first]
    else:
        events = [first, replace(quote_event(first, 1, bid), quotes={})]
    replay = run_case(lifecycle_case, tmp_path/'replay', events)
    bot, database, summary, client = forward_episode(lifecycle_case, tmp_path/'forward', events)
    try:
        actual = bot.paper_cycle_results
        assert summary.cycles_completed == replay.events_completed
        assert summary.lifecycle_halted == replay.halted
        assert summary.audit_complete == replay.audit_complete
        assert tuple(trade for trade in actual[-1].trades) == replay.trades
        assert [item.to_dict() for result in actual for item in result.decisions] == [item.to_dict() for item in replay.decisions]
        assert [result.valuation for result in actual if result.valuation is not None] == list(replay.valuations)
        assert [item['reject_code'] for result in actual for item in result.rejections] == [item['reject_code'] for item in replay.rejections]
        assert client.calls.count('account_info') == len(events)
        assert not any(call in {'order_send', 'order_check', 'positions_get'} for call in client.calls)
        if episode == 'stop_gap':
            assert actual[-1].paused and actual[-1].valuation['daily_halted']
            assert replay.trades[0]['status'] == 'CLOSED'
        if episode not in {'stale_evidence'}:
            assert actual[0].decisions[0].accepted
    finally:
        database.close()

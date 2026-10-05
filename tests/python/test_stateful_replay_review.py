"""Independent replay review: complete audit, broker lattice and event causality."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import numpy as np
import pytest

from agi_style_forex_bot_mt5.backtesting.stateful_replay import (
    ClosedBarInput, ReplayEvidence, StatefulReplayEvent, run_stateful_replay,
)
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState, MarketSnapshot
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.instruments import InstrumentRegistry, InstrumentRegistrySnapshot, InstrumentSpec
from agi_style_forex_bot_mt5.core.operational_state.errors import PaperStateError
from agi_style_forex_bot_mt5.ml import MLFilter
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot, PaperFillModel
from agi_style_forex_bot_mt5.paper_trading.decision_state import (
    build_paper_decision_state, capture_paper_daily_reference,
)
from agi_style_forex_bot_mt5.paper_trading.paper_trade import PaperTrade
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

from test_stateful_replay import replay_case, run_case, next_quote_event
from test_shared_strategy_features import _bars, _snapshot


NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
ACCOUNT = AccountState(1, "DEMO", 10000, 10000, 10000, is_demo=True, trade_allowed=True)


def _quote(now=NOW, **changes):
    return replace(MarketSnapshot("EURUSD", "M5", now, 1.1000, 1.1001, 10, 5,
        0.00001, 1., 0.00001, 0.01, 100., 0.01, 0, 0), **changes)


def _metadata(now=NOW):
    spec = InstrumentSpec(symbol="EURUSD", canonical_symbol="EURUSD", broker_symbol="EURUSD",
        digits=5, point=0.00001, tick_size=0.00001, tick_value=1., contract_size=100000.,
        min_volume=0.01, max_volume=100., volume_step=0.01, stops_level_points=0,
        freeze_level_points=0, currency_base="EUR", currency_quote="USD", source="mt5:symbol_info")
    return InstrumentRegistrySnapshot(InstrumentRegistry.from_specs([spec]), now)


def _event(identity="event-a", now=NOW, quote=None):
    return StatefulReplayEvent(identity, now, {"EURUSD": quote or _quote(now)}, (), {})


def _run(tmp_path, events, **changes):
    kwargs = dict(config=BotConfig(paper_allow_disabled_ml=True), initial_account=ACCOUNT,
        instrument_snapshot=_metadata(), output_dir=tmp_path,
        model_filter=MLFilter.disabled_for_research(), fill_model=PaperFillModel())
    kwargs.update(changes)
    return run_stateful_replay(events, **kwargs)


def _trade(lot=0.1):
    return PaperTrade(paper_trade_id="review-position", signal_id="review-signal", idempotency_key="review-key",
        symbol="EURUSD", broker_symbol="EURUSD", direction="BUY", entry_time_utc=NOW.isoformat(),
        entry_price=1.1001, sl_price=1.099, tp_price=1.102, lot=lot, risk_pct=.2, risk_amount=20,
        strategy_name="review", strategy_version="test", regime="TREND_UP", session="LONDON", score=90,
        reasons=(), metadata={"pnl_basis": "APPROVED_LOT_UNSCALED_V1"})


def _state(db, trades=(), *, now=NOW, quote=None, capture=False):
    builder = capture_paper_daily_reference if capture else build_paper_decision_state
    return builder(database=db, trades=trades, snapshots_by_symbol={"EURUSD": quote or _quote(now)},
                   account_template=ACCOUNT, now_utc=now)


def next_candidate_event(case, *, correlation=0.):
    """The next observed synthetic candle; retain the complete prior prefix."""
    bars = _bars(214)
    assert bars.iloc[:-1].equals(case["event"].decisions[0].bars)
    quote = _snapshot(bars, 213)
    bid = round(quote.bid, quote.digits)
    quote = replace(quote, bid=bid, ask=round(bid + .00005, quote.digits))
    return StatefulReplayEvent("next-closed-bar", quote.timestamp_utc, {"EURUSD": quote},
        (ClosedBarInput("EURUSD", "M5", bars),),
        {"EURUSD": ReplayEvidence(quote.timestamp_utc, 85., correlation)})


def test_every_replay_event_has_distinct_received_and_completed_sqlite_audit(tmp_path):
    result = _run(tmp_path, [_event(), _event("event-b", NOW + timedelta(seconds=1))])
    assert result.events_completed == 2
    assert result.audit_complete
    with sqlite3.connect(tmp_path / "replay.sqlite3") as conn:
        for event_type in ("STATEFUL_EVENT_RECEIVED", "STATEFUL_EVENT_COMPLETED"):
            rows = conn.execute("SELECT payload_json FROM events WHERE event_type = ?", (event_type,)).fetchall()
            assert {json.loads(row[0])["event_id"] for row in rows} == {"event-a", "event-b"}


def test_failed_required_audit_marks_result_incomplete_even_if_halt_audit_succeeds(tmp_path, monkeypatch):
    original = JsonlAuditLogger.append_event

    def fail_received(self, event):
        if event.event_type == "STATEFUL_EVENT_RECEIVED":
            raise OSError("synthetic audit failure")
        return original(self, event)

    monkeypatch.setattr(JsonlAuditLogger, "append_event", fail_received)
    result = _run(tmp_path, [_event()])
    assert result.halted
    assert result.events_completed == 0
    assert result.audit_complete is False


def test_state_accepts_broker_lattice_anchored_to_minimum(tmp_path):
    with TelemetryDatabase(tmp_path / "valid-lattice.sqlite3") as db:
        _state(db)
        result = _state(db, [_trade(lot=.15)], quote=_quote(volume_min=.05, volume_step=.1))
    assert len(result.risk_state.open_positions) == 1
    assert result.risk_state.open_positions[0].volume == .15


def test_state_rejects_volume_on_zero_lattice_but_not_broker_minimum_lattice(tmp_path):
    with TelemetryDatabase(tmp_path / "invalid-lattice.sqlite3") as db:
        _state(db)
        with pytest.raises(PaperStateError):
            _state(db, [_trade(lot=.1)], quote=_quote(volume_min=.05, volume_step=.1))


@pytest.mark.parametrize("offset", (-6, 1))
def test_stale_or_future_explicit_quotes_halt_before_any_candidate(tmp_path, offset):
    result = _run(tmp_path, [_event(quote=_quote(NOW + timedelta(seconds=offset)))])
    assert result.halted and result.events_completed == 0
    assert result.rejections[0]["reject_code"] == "QUOTE_TIME_INVALID"
    assert not result.trades


def test_future_metadata_halts_event(tmp_path):
    result = _run(tmp_path, [_event()], instrument_snapshot=_metadata(NOW + timedelta(seconds=1)))
    assert result.rejections[0]["reject_code"] == "INSTRUMENT_METADATA_FROM_FUTURE"
    assert not result.trades


def test_quote_only_replay_is_economically_deterministic_without_terminal_callbacks(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("terminal acquisition was attempted")

    monkeypatch.setattr(ForwardShadowBot, "_connect", forbidden)
    monkeypatch.setattr(ForwardShadowBot, "_snapshot_for", forbidden)
    events = [_event(), _event("event-b", NOW + timedelta(seconds=1))]
    first = _run(tmp_path / "first", events)
    second = _run(tmp_path / "second", events)
    assert first.result_digest == second.result_digest
    assert first.valuations == second.valuations
    assert first.input_digest == second.input_digest
    assert not first.halted and not second.halted


def test_midnight_reference_requires_exact_boundary_quote_and_preserves_reference(tmp_path):
    midnight = NOW.replace(hour=0) + timedelta(days=1)
    with TelemetryDatabase(tmp_path / "midnight.sqlite3") as db:
        _state(db)
        _state(db, [_trade()])
        with pytest.raises(PaperStateError):
            _state(db, [_trade()], now=midnight, quote=_quote(midnight - timedelta(seconds=1)), capture=True)
        captured = _state(db, [_trade()], now=midnight, quote=_quote(midnight), capture=True)
        later = _state(db, [_trade()], now=midnight + timedelta(seconds=1),
                       quote=_quote(midnight + timedelta(seconds=1), bid=1.1005, ask=1.1006))
        assert captured.risk_state.daily_equity_reference == later.risk_state.daily_equity_reference
        assert captured.account.equity != later.account.equity


@pytest.mark.parametrize("config_change, code", (
    ({"max_open_trades": 1}, "MAX_OPEN_TRADES"),
    ({"max_open_risk_pct": .55}, "MAX_OPEN_RISK"),
))
def test_real_replay_risk_sees_existing_position_before_next_candidate(replay_case, tmp_path, config_change, code):
    entry = replay_case["event"]
    second = next_candidate_event(replay_case)
    result = run_case(replay_case, tmp_path / "result", [entry, second],
                      config=replace(replay_case["config"], **config_change))
    assert not result.halted
    assert result.decisions[0].accepted
    assert result.decisions[1].reject_code == code
    assert len(result.trades) == 1
    assert result.valuations[1]["open_positions"] == 1
    assert result.valuations[1]["open_risk_amount"] >= result.trades[0]["risk_amount"]


@pytest.mark.parametrize("config_change, correlation, code", (
    ({"max_open_trades": 1}, 0., "MAX_OPEN_TRADES"),
    ({"max_open_risk_pct": .55}, 0., "MAX_OPEN_RISK"),
    ({}, .9, "REJECT_CORRELATED"),
))
def test_exposed_second_decision_traces_ignore_random_position_ids(replay_case, tmp_path, config_change, correlation, code):
    entry = replay_case["event"]
    second = next_candidate_event(replay_case, correlation=correlation)
    config = replace(replay_case["config"], **config_change)
    first = run_case(replay_case, tmp_path / "first", [entry, second], config=config)
    repeat = run_case(replay_case, tmp_path / "repeat", [entry, second], config=config)
    assert first.decisions[1].reject_code == code
    assert first.result_digest == repeat.result_digest
    assert first.to_dict() == repeat.to_dict()
    with sqlite3.connect(tmp_path / "first/replay.sqlite3") as left, sqlite3.connect(tmp_path / "repeat/replay.sqlite3") as right:
        # The test really changes persisted UUIDs; equivalent traces must still
        # represent the same economic book and risk decisions.
        left_id = left.execute("SELECT paper_trade_id FROM paper_trades").fetchone()[0]
        right_id = right.execute("SELECT paper_trade_id FROM paper_trades").fetchone()[0]
        assert left_id != right_id


def test_open_position_missing_quote_cannot_fallback_to_terminal(replay_case, tmp_path, monkeypatch):
    entry = replay_case["event"]
    observed = replay_case["instrument_snapshot"]
    eur = observed.registry.get("EURUSD")
    gbp = replace(eur, symbol="GBPUSD", canonical_symbol="GBPUSD", broker_symbol="GBPUSD.raw", currency_base="GBP")
    metadata = replace(observed, registry=InstrumentRegistry.from_specs([eur, gbp]))
    second = next_quote_event(entry)
    # Keep a nonempty, valid event quote map, but omit the actually open symbol.
    second = replace(second, quotes={"GBPUSD": replace(second.quotes["EURUSD"], symbol="GBPUSD")})

    def forbidden(*_args, **_kwargs):
        raise AssertionError("missing explicit replay quote triggered terminal acquisition")

    monkeypatch.setattr(ForwardShadowBot, "_snapshot_for", forbidden)
    result = run_case(replay_case, tmp_path / "result", [entry, second], instrument_snapshot=metadata)
    assert result.halted and result.events_completed == 1
    assert result.rejections[-1]["reject_code"] == "OPEN_POSITION_QUOTE_MISSING"
    assert result.decisions[0].accepted
    assert result.trades[0]["status"] == "OPEN"


@pytest.mark.parametrize("quote_offset", (-6, 1))
def test_noncausal_gap_quote_cannot_close_an_existing_position(replay_case, tmp_path, quote_offset):
    entry = replay_case["event"]
    second = next_quote_event(entry, identity="invalid-stop", bid=1.09)
    second = replace(second, quotes={"EURUSD": replace(second.quotes["EURUSD"],
                       timestamp_utc=second.timestamp_utc + timedelta(seconds=quote_offset))})
    result = run_case(replay_case, tmp_path / "result", [entry, second])
    assert result.halted and result.events_completed == 1
    assert result.rejections[-1]["reject_code"] == "QUOTE_TIME_INVALID"
    assert result.trades[0]["status"] == "OPEN"
    assert result.trades[0]["exit_price"] is None


@pytest.mark.parametrize("boundary_quote_age", (0, 1))
def test_real_overnight_replay_uses_only_exact_midnight_equity(replay_case, tmp_path, boundary_quote_age):
    entry = replay_case["event"]
    boundary = entry.timestamp_utc.replace(hour=0, minute=0, second=0) + timedelta(days=1)
    midnight = next_quote_event(entry, identity="midnight", seconds=int((boundary - entry.timestamp_utc).total_seconds()))
    midnight = replace(midnight, quotes={"EURUSD": replace(midnight.quotes["EURUSD"],
                       timestamp_utc=boundary - timedelta(seconds=boundary_quote_age))})
    result = run_case(replay_case, tmp_path / "result", [entry, midnight])
    if boundary_quote_age:
        assert result.halted and result.events_completed == 1
        assert result.rejections[-1]["reject_code"] == "DAILY_DRAWDOWN_REFERENCE_MISSING"
    else:
        assert not result.halted and result.events_completed == 2
        assert result.valuations[1]["daily_reference"] == result.valuations[1]["equity"]
        assert result.valuations[1]["daily_reference"] < 10000


def test_signal_audit_failure_halts_before_later_real_candidates(replay_case, tmp_path, monkeypatch):
    original = JsonlAuditLogger.append_event
    attempted_signals = []

    def fail_signal(self, event):
        if event.event_type == "SIGNAL_GENERATED":
            attempted_signals.append(event)
            raise OSError("synthetic signal audit failure")
        return original(self, event)

    monkeypatch.setattr(JsonlAuditLogger, "append_event", fail_signal)
    entry = replay_case["event"]
    second = next_quote_event(entry, decisions=entry.decisions)
    result = run_case(replay_case, tmp_path / "result", [entry, second])
    assert result.halted and not result.audit_complete
    assert result.events_completed == 0
    assert len(attempted_signals) == 1
    assert not result.trades


def test_wrapped_post_fill_audit_failure_is_reported_incomplete(replay_case, tmp_path, monkeypatch):
    original = TelemetryDatabase.insert_event

    def fail_reconciliation(self, event):
        if getattr(event, "event_type", None) == "PAPER_FILL_RISK_RECONCILED":
            raise OSError("synthetic reconciliation audit failure")
        return original(self, event)

    monkeypatch.setattr(TelemetryDatabase, "insert_event", fail_reconciliation)
    result = run_case(replay_case, tmp_path / "result")
    assert result.halted and result.events_completed == 0
    assert not result.audit_complete
    assert not result.trades
    assert not result.decisions[0].accepted


class _ReviewProbabilityModel:
    def predict_proba(self, values):
        return np.full(len(values), .9)


class _ReviewCalibrator:
    def predict(self, values):
        return values


@pytest.mark.parametrize("future", (True, False))
def test_model_without_available_past_timestamp_cannot_open(replay_case, tmp_path, future):
    model = MLFilter.disabled_for_research()
    metadata = {"approved_for_shadow_filtering": True}
    if future:
        metadata["created_at_utc"] = (replay_case["event"].timestamp_utc + timedelta(seconds=1)).isoformat()
    model.bundle = {"metadata": metadata, "model": _ReviewProbabilityModel(), "calibrator": _ReviewCalibrator()}
    result = run_case(replay_case, tmp_path / "result", model_filter=model)
    assert not result.trades
    assert result.decisions[0].reject_code == ("ML_MODEL_FROM_FUTURE" if future else "ML_PROVENANCE_MISSING")


def test_non_executable_quote_grid_halts_before_account_marking(tmp_path):
    quote = _quote(bid=1.100001, ask=1.100101)
    result = _run(tmp_path, [_event(quote=quote)])
    assert result.halted and result.events_completed == 0
    assert not result.valuations


def test_caller_identity_lookup_storage_failure_cannot_become_permission_to_open(tmp_path, monkeypatch):
    with TelemetryDatabase(tmp_path / "lookup.sqlite3") as database:
        bot = ForwardShadowBot(config=BotConfig(paper_allow_disabled_ml=True), symbols=("EURUSD",),
            database=database, audit_logger=JsonlAuditLogger(tmp_path / "events"),
            clock=FrozenClock(NOW), ml_filter=MLFilter.disabled_for_research())

        def unreadable():
            raise OSError("synthetic history lookup failure")

        monkeypatch.setattr(database, "fetch_paper_trades", unreadable)
        with pytest.raises(OSError):
            bot._paper_signal_already_traded("review-candidate", "EURUSD")
        assert database.count_rows("paper_trades") == 0

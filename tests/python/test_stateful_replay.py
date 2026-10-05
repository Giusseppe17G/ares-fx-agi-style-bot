"""Explicit synthetic quotes exercise the real forward/paper lifecycle offline."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from agi_style_forex_bot_mt5.backtesting.stateful_replay import (
    ClosedBarInput, ReplayEvidence, StatefulReplayEvent, run_stateful_replay,
)
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState
from agi_style_forex_bot_mt5.core.instruments.registry import InstrumentRegistry, InstrumentSpec
from agi_style_forex_bot_mt5.core.instruments.snapshot import InstrumentRegistrySnapshot
from agi_style_forex_bot_mt5.ml import MLFilter
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot, PaperFillModel
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

from test_shared_strategy_features import _bars, _snapshot


@pytest.fixture
def replay_case():
    # Fixed deterministic oscillation; no strategy or scores are patched. The
    # actual features/ensemble produce a BUY at closed bar 212 under ACTIVE.
    bars = _bars(213)
    quote = _snapshot(bars, 212)
    bid = round(quote.bid, quote.digits)
    quote = replace(quote, bid=bid, ask=round(bid + .00005, quote.digits))
    spec = InstrumentSpec("EURUSD", "EURUSD", "EURUSD.raw", 5, .00001,
        .00001, 1., 100000., .01, 100., .01, 10, 5, "EUR", "USD", "mt5:symbol_info")
    instruments = InstrumentRegistrySnapshot(InstrumentRegistry.from_specs([spec]), quote.timestamp_utc - timedelta(days=1))
    event = StatefulReplayEvent("entry", quote.timestamp_utc, {"EURUSD": quote},
        (ClosedBarInput("EURUSD", "M5", bars),),
        {"EURUSD": ReplayEvidence(quote.timestamp_utc, 85., None)})
    return {"event": event, "config": BotConfig(signal_profile="ACTIVE", paper_allow_disabled_ml=True),
        "initial_account": AccountState(7, "DEMO", 10000., 10000., 10000., currency="USD", is_demo=True, trade_allowed=True),
        "instrument_snapshot": instruments, "fill_model": PaperFillModel(slippage_points=1., commission_per_lot_round_turn=4.),
        "model_filter": MLFilter.disabled_for_research()}


def run_case(case, path, events=None, **overrides):
    arguments = {key: value for key, value in case.items() if key != "event"}
    arguments.update(overrides)
    return run_stateful_replay(events or [case["event"]], output_dir=path, **arguments)


def next_quote_event(event, *, identity="mark", seconds=60, bid=None, decisions=(), correlation=0.):
    now = event.timestamp_utc + timedelta(seconds=seconds)
    base = event.quotes["EURUSD"]
    bid = base.bid if bid is None else bid
    quote = replace(base, timestamp_utc=now, bid=round(bid, 5), ask=round(bid + .00005, 5))
    return StatefulReplayEvent(identity, now, {"EURUSD": quote}, tuple(decisions),
        {"EURUSD": ReplayEvidence(now, 85., correlation)})


def test_real_strategy_opens_and_explicit_quote_closes_once(replay_case, tmp_path):
    entry = replay_case["event"]
    close = next_quote_event(entry, identity="stop", bid=1.09)
    result = run_case(replay_case, tmp_path / "result", [entry, close])
    assert result.audit_complete and not result.halted, result.to_dict()
    assert result.events_completed == 2
    assert result.decisions[0].accepted, result.decisions[0].to_dict()
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["status"] == "CLOSED"
    assert trade["exit_time_utc"] == close.timestamp_utc.isoformat()
    assert trade["profit"] == trade["raw_pnl"] == trade["scaled_paper_pnl"]
    assert result.valuations[0]["open_positions"] == 1
    assert result.valuations[0]["equity"] < 10000
    assert result.valuations[1]["balance"] == pytest.approx(10000 + trade["profit"])
    assert result.valuations[1]["open_positions"] == 0
    assert result.to_dict()["execution_authorized"] is False


def test_determinism_and_manifest_cover_source_config_models_and_costs(replay_case, tmp_path):
    entry = replay_case["event"]
    events = [entry, next_quote_event(entry)]
    first = run_case(replay_case, tmp_path / "first", events)
    second = run_case(replay_case, tmp_path / "second", events)
    assert first.to_dict() == second.to_dict()
    manifest = json.loads((tmp_path / "first/manifest.json").read_text())
    assert manifest["run_manifest"]["source_tree_hash"]
    assert manifest["run_manifest"]["git_commit_sha"]
    assert manifest["run_manifest"]["dataset_hash"] == first.input_digest
    assert manifest["run_manifest"]["python_version"]
    assert manifest["model_thresholds"]["minimum_probability_for_shadow_trade"] == .58
    assert manifest["fill_assumptions"]["commission_per_lot_round_turn"] == 4.
    changed = MLFilter(load_bundle=False, minimum_probability_for_shadow_trade=.6)
    run_case(replay_case, tmp_path / "changed", events, model_filter=changed)
    changed_manifest = json.loads((tmp_path / "changed/manifest.json").read_text())
    assert changed_manifest["run_manifest"]["run_id"] != manifest["run_manifest"]["run_id"]


def test_invalid_third_event_preserves_prior_completed_acceptance(replay_case, tmp_path):
    entry = replay_case["event"]
    mark = next_quote_event(entry)
    failed = replace(mark, event_id="missing-quotes", timestamp_utc=mark.timestamp_utc + timedelta(seconds=1), quotes={})
    result = run_case(replay_case, tmp_path / "result", [entry, mark, failed])
    assert result.halted and result.audit_complete
    assert result.events_completed == 2
    assert result.decisions[0].accepted
    assert result.trades[0]["status"] == "OPEN"
    assert result.rejections[-1]["reject_code"] == "EVENT_QUOTES_MISSING"


def test_every_market_event_is_durably_audited(replay_case, tmp_path):
    entry = replay_case["event"]
    result = run_case(replay_case, tmp_path / "result", [entry, next_quote_event(entry)])
    assert not result.halted
    with sqlite3.connect(tmp_path / "result/replay.sqlite3") as database:
        for event_type in ("STATEFUL_EVENT_RECEIVED", "STATEFUL_EVENT_COMPLETED"):
            assert database.execute("SELECT count(*) FROM events WHERE event_type=?", (event_type,)).fetchone()[0] == 2


@pytest.mark.parametrize("failure,code", [
    ("evidence", "BROKER_EVIDENCE_MISSING"), ("future_evidence", "BROKER_EVIDENCE_TIME_INVALID"),
    ("future_metadata", "INSTRUMENT_METADATA_FROM_FUTURE"), ("changed_metadata", "QUOTE_METADATA_MISMATCH"),
])
def test_missing_or_noncausal_market_evidence_cannot_open(replay_case, tmp_path, failure, code):
    event = replay_case["event"]
    overrides = {}
    if failure == "evidence":
        event = replace(event, evidence={})
    elif failure == "future_evidence":
        event = replace(event, evidence={"EURUSD": ReplayEvidence(event.timestamp_utc + timedelta(seconds=1), 85., None)})
    elif failure == "future_metadata":
        overrides["instrument_snapshot"] = replace(replay_case["instrument_snapshot"], captured_at_utc=event.timestamp_utc + timedelta(seconds=1))
    else:
        event = replace(event, quotes={"EURUSD": replace(event.quotes["EURUSD"], tick_value=2.)})
    result = run_case(replay_case, tmp_path / "result", [event], **overrides)
    assert not result.trades
    assert result.rejections[0]["reject_code"] == code


def test_missing_correlation_with_open_exposure_rejects_second_candidate(replay_case, tmp_path):
    entry = replay_case["event"]
    second = next_quote_event(entry, decisions=entry.decisions, correlation=None)
    result = run_case(replay_case, tmp_path / "result", [entry, second])
    assert result.events_completed == 2 and len(result.trades) == 1
    assert result.rejections[-1]["reject_code"] == "CORRELATION_UNVERIFIED"


def test_no_local_model_or_connector_access(replay_case, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline replay attempted external discovery")
    monkeypatch.setattr(MLFilter, "load_latest_model", forbidden)
    monkeypatch.setattr(ForwardShadowBot, "_snapshot_for", forbidden)
    monkeypatch.setattr(ForwardShadowBot, "run", forbidden)
    result = run_case(replay_case, tmp_path / "result")
    assert result.decisions[0].accepted and not result.halted


def test_replay_output_cannot_be_reused(replay_case, tmp_path):
    path = tmp_path / "result"
    run_case(replay_case, path)
    before = (path / "result.json").read_bytes()
    with pytest.raises(ValueError, match="new or empty"):
        run_case(replay_case, path)
    assert (path / "result.json").read_bytes() == before


def test_lifecycle_events_use_quote_time_and_utc_not_ingestion_clock(replay_case, tmp_path):
    entry = replay_case["event"]
    stop = next_quote_event(entry, identity="stop", bid=1.09)
    result = run_case(replay_case, tmp_path / "result", [entry, stop])
    assert not result.halted
    with sqlite3.connect(tmp_path / "result/replay.sqlite3") as database:
        rows = dict(database.execute("SELECT event_type,timestamp_utc FROM paper_trade_events"))
    assert rows["PAPER_TRADE_OPENED"] == entry.timestamp_utc.isoformat()
    assert rows["PAPER_TRADE_CLOSED"] == stop.timestamp_utc.isoformat()


@pytest.mark.parametrize("stage,trade_count", [("PAPER_DECISION_COMPLETED", 0), ("PAPER_TRADE_OPENED", 1)])
def test_failed_required_audit_stops_and_preserves_actual_book(replay_case, tmp_path, monkeypatch, stage, trade_count):
    original = JsonlAuditLogger.append_event

    def fail(self, event):
        if event.event_type == stage:
            raise RuntimeError("private-storage-secret")
        return original(self, event)

    monkeypatch.setattr(JsonlAuditLogger, "append_event", fail)
    result = run_case(replay_case, tmp_path / "result", [replay_case["event"], next_quote_event(replay_case["event"])])
    assert result.halted and not result.audit_complete
    assert result.events_completed == 0
    assert len(result.trades) == trade_count
    assert all(not decision.accepted for decision in result.decisions)
    assert "private-storage-secret" not in json.dumps(result.to_dict())


def test_constructor_error_still_closes_isolated_database(replay_case, tmp_path, monkeypatch):
    closed = []
    original = TelemetryDatabase.close

    def close(self):
        closed.append(self.path)
        return original(self)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic constructor failure")

    monkeypatch.setattr(TelemetryDatabase, "close", close)
    monkeypatch.setattr(ForwardShadowBot, "__init__", fail)
    with pytest.raises(RuntimeError):
        run_case(replay_case, tmp_path / "result")
    assert closed == [tmp_path / "result/replay.sqlite3"]


def test_future_ohlc_is_never_invented_as_an_intrabar_quote(replay_case, tmp_path):
    event = replay_case["event"]
    original = run_case(replay_case, tmp_path / "original")
    bars = _bars(300)
    bars.loc[213:, ["open", "high", "low", "close"]] *= 5
    changed_event = replace(event, decisions=(ClosedBarInput("EURUSD", "M5", bars),))
    changed = run_case(replay_case, tmp_path / "changed", [changed_event])
    assert original.decisions == changed.decisions
    assert original.trades == changed.trades
    assert original.valuations == changed.valuations


def test_disabled_ml_is_explicit_research_policy_not_an_implicit_approval(replay_case, tmp_path):
    result = run_case(replay_case, tmp_path / "result", config=replace(replay_case["config"], paper_allow_disabled_ml=False))
    assert not result.trades
    assert result.decisions[0].reject_code == "ML_DISABLED_NOT_ALLOWED"


@pytest.mark.parametrize("close", (False, True))
def test_created_identity_is_not_reevaluated_or_reopened(replay_case, tmp_path, close):
    entry = replay_case["event"]
    repeated = next_quote_event(entry, decisions=entry.decisions, bid=1.09 if close else None)
    result = run_case(replay_case, tmp_path / "result", [entry, repeated])
    assert not result.halted and result.events_completed == 2
    assert len(result.decisions) == len(result.trades) == 1
    assert result.trades[0]["status"] == ("CLOSED" if close else "OPEN")
    assert result.rejections[-1]["reject_code"] == "CANDIDATE_ALREADY_TRADED"
    with sqlite3.connect(tmp_path / "result/replay.sqlite3") as database:
        assert database.execute("SELECT count(*) FROM events WHERE event_type='CANDIDATE_ALREADY_TRADED'").fetchone()[0] == 1


def test_rejected_identity_can_be_retried_with_observed_evidence(replay_case, tmp_path):
    entry = replay_case["event"]
    rejected = replace(entry, evidence={})
    retry = next_quote_event(entry, decisions=entry.decisions)
    result = run_case(replay_case, tmp_path / "result", [rejected, retry])
    assert not result.halted and result.events_completed == 2
    assert result.rejections[0]["reject_code"] == "BROKER_EVIDENCE_MISSING"
    assert len(result.trades) == 1 and result.decisions[0].accepted

"""Post-fill risk is bounded and persisted before any new paper position."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from agi_style_forex_bot_mt5.contracts import Direction, EntryType, MarketSnapshot, RiskDecision, TradeSignal
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel
from agi_style_forex_bot_mt5.paper_trading.paper_position_manager import APPROVED_LOT_BASIS, PaperPositionManager
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path):
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    yield db
    db.close()


def _snapshot(**changes):
    base = MarketSnapshot("EURUSD", "M5", NOW, 1.1000, 1.1001, 10, 5,
                          0.00001, 1.0, 0.00001, 0.01, 100, 0.01, 0, 0)
    return replace(base, **changes)


def _signal(direction=Direction.BUY, **changes):
    base = TradeSignal("fill-risk-fixture", NOW, "EURUSD", "M5", direction, EntryType.MARKET,
                       1.0991 if direction == Direction.BUY else 1.1010,
                       1.1031 if direction == Direction.BUY else 1.0970,
                       risk_pct=0.5, metadata={"parameters_version": "test-v1"})
    return replace(base, **changes)


def _risk(**changes):
    base = RiskDecision("fill-risk-fixture", True, approved_lot=0.5, risk_amount_account_currency=50,
                        checks={"effective_risk_pct": 0.5, "account_equity": {"status": "passed", "equity": 10_000}})
    return replace(base, **changes)


def _manager(database, *, slip=1.0, commission=0.0, **kwargs):
    return PaperPositionManager(database=database, fill_model=PaperFillModel(
        slippage_points=slip, commission_per_lot_round_turn=commission,
        clock=FrozenClock(NOW + timedelta(seconds=4))), **kwargs)


def _open(manager, *, signal=None, risk=None, snapshot=None, version="test-v1"):
    return manager.open_trade(signal=signal or _signal(), risk_decision=risk or _risk(),
                              snapshot=snapshot or _snapshot(), broker_symbol="EURUSD", score=90,
                              reasons=("fixture",), strategy_name="test", strategy_version=version,
                              regime="TREND_UP", session="LONDON")


@pytest.mark.parametrize("direction", (Direction.BUY, Direction.SELL))
def test_fill_slippage_cannot_exceed_approved_risk_in_either_direction(database, direction):
    trade = _open(_manager(database), signal=_signal(direction))
    # Original lot 0.5 would risk 50.5 after entry slip and 51 with exit reserve.
    assert trade.lot == 0.49
    assert trade.risk_amount == pytest.approx(49.98)
    assert trade.risk_pct == pytest.approx(0.4998)
    assert trade.metadata["initial_risk_amount"] == trade.risk_amount
    assert trade.metadata["pnl_basis"] == APPROVED_LOT_BASIS
    assert trade.metadata["fill_risk_reconciliation"]["exit_slippage_reserve_per_lot"] == 1
    assert trade.risk_amount <= 50


def test_round_turn_commission_recomputed_for_reduced_lot_and_charged_once(database):
    manager = _manager(database, commission=7)
    trade = _open(manager)
    assert trade.lot == 0.45
    assert trade.commission_assumed == pytest.approx(3.15)
    assert trade.metadata["entry_fill"]["commission"] == pytest.approx(3.15)
    assert trade.metadata["commission_model_used"]["commission"] == pytest.approx(3.15)
    assert trade.risk_amount == pytest.approx(49.05)
    closed = manager.close_trade(trade, _snapshot(timestamp_utc=NOW + timedelta(seconds=1)), "SL", trade.sl_price)
    assert closed.profit == pytest.approx(-49.05)
    assert closed.r_multiple == pytest.approx(-1)
    assert closed.multiplier_applied is False


@pytest.mark.parametrize("direction", (Direction.BUY, Direction.SELL))
def test_fractional_slippage_reserve_includes_price_rounding(database, direction):
    manager = _manager(database, slip=0.6)
    trade = _open(manager, signal=_signal(direction), risk=_risk(risk_amount_account_currency=50.9))
    assert trade.lot == 0.49
    assert trade.risk_amount == pytest.approx(49.98)
    closed = manager.close_trade(trade, _snapshot(), "SL", trade.sl_price)
    assert -closed.profit <= 50.9
    assert -closed.profit == pytest.approx(trade.risk_amount)


def test_broker_minimum_that_cannot_fit_costs_blocks_entry_and_is_audited(database):
    manager = _manager(database)
    with pytest.raises(ValueError, match="minimum lot"):
        _open(manager, snapshot=_snapshot(volume_min=0.5))
    assert not manager.load_all_trades()
    events = database.fetch_all("events")
    assert events[-1]["event_type"] == "PAPER_FILL_RISK_REJECTED"
    assert json.loads(events[-1]["payload_json"])["reason"] == "POST_FILL_LOT_BELOW_MINIMUM"


def test_step_lattice_is_anchored_to_broker_minimum(database):
    trade = _open(_manager(database), risk=_risk(approved_lot=0.15, risk_amount_account_currency=15),
                  snapshot=_snapshot(volume_min=0.05, volume_step=0.1))
    assert trade.lot == 0.05
    assert trade.risk_amount <= 15


@pytest.mark.parametrize("field,value", (("sl_price", 1.09911), ("tp_price", 1.10311), ("entry_price", 1.10011)))
def test_protection_and_explicit_entry_prices_must_fit_tick_grid(database, field, value):
    with pytest.raises(ValueError, match="broker tick grid"):
        _open(_manager(database, slip=0), signal=_signal(**{field: value}), snapshot=_snapshot(tick_size=0.00005))
    assert not database.fetch_paper_trades()


def test_fill_provider_cannot_return_price_outside_tick_grid(database):
    class OffGridFill(PaperFillModel):
        def entry_result(self, **kwargs):
            return replace(super().entry_result(**kwargs), fill_price=1.10011)

    manager = PaperPositionManager(database=database, fill_model=OffGridFill(slippage_points=0, clock=FrozenClock(NOW)))
    with pytest.raises(ValueError, match="broker tick grid"):
        _open(manager, snapshot=_snapshot(tick_size=0.00005))
    assert not database.fetch_paper_trades()


def test_coarser_tick_size_is_accepted_when_all_prices_are_aligned(database):
    trade = _open(_manager(database, slip=0), snapshot=_snapshot(tick_size=0.00005))
    assert trade.entry_price == 1.1001
    assert trade.lot == 0.5
    assert trade.risk_amount == 10


@pytest.mark.parametrize("field", ("slippage_points", "commission_per_lot_round_turn"))
@pytest.mark.parametrize("value", (float("nan"), float("inf"), -1.0))
def test_manager_rejects_corrupted_cost_assumptions(database, field, value):
    manager = _manager(database)
    # Provider corruption after construction must also fail closed at the sink.
    object.__setattr__(manager.fill_model, field, value)
    with pytest.raises(ValueError):
        _open(manager)
    assert not manager.load_all_trades()


@pytest.mark.parametrize("field", ("commission", "assumed_slippage_points", "fill_price"))
def test_nonfinite_fill_result_is_rejected(database, field):
    class CorruptFill(PaperFillModel):
        def entry_result(self, **kwargs):
            return replace(super().entry_result(**kwargs), **{field: float("nan")})

    manager = PaperPositionManager(database=database, fill_model=CorruptFill(clock=FrozenClock(NOW)))
    with pytest.raises(ValueError):
        _open(manager)
    assert not manager.load_all_trades()


@pytest.mark.parametrize("failure", ("false_ack", "exception"))
def test_audit_failure_blocks_trade_insertion(database, monkeypatch, failure):
    def fail(event):
        if failure == "exception":
            raise OSError("synthetic write failure")
        return False

    monkeypatch.setattr(database, "insert_event", fail)
    manager = _manager(database)
    with pytest.raises(ValueError, match="audit failed"):
        _open(manager)
    assert not manager.load_all_trades()


def test_reconciliation_event_is_committed_before_trade_insert(database, monkeypatch):
    original = database.insert_paper_trade
    checked = []

    def insert(trade):
        # A different connection must see the event before position persistence.
        with sqlite3.connect(database.path) as independent_reader:
            rows = independent_reader.execute("SELECT event_type FROM events").fetchall()
        assert ("PAPER_FILL_RISK_RECONCILED",) in rows
        assert not database.fetch_paper_trades()
        checked.append(True)
        return original(trade)

    monkeypatch.setattr(database, "insert_paper_trade", insert)
    _open(_manager(database))
    assert checked == [True]


def test_rejected_risk_cannot_reach_fill_or_position(database, monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("fill must not run")

    monkeypatch.setattr(PaperFillModel, "entry_result", fail)
    decision = RiskDecision("fill-risk-fixture", False, reject_code="TEST_REJECT")
    manager = _manager(database)
    with pytest.raises(ValueError, match="accepted matching"):
        _open(manager, risk=decision)
    assert not manager.load_all_trades()


@pytest.mark.parametrize("change", ("direction", "sl", "tp", "version", "metadata", "fill_config"))
def test_same_signal_id_conflicting_intent_cannot_open_second_trade(database, change):
    manager = _manager(database)
    first = _open(manager)
    candidate = _signal()
    kwargs = {}
    if change == "direction":
        candidate = _signal(Direction.SELL)
    elif change == "sl":
        candidate = replace(candidate, sl_price=1.0989)
    elif change == "tp":
        candidate = replace(candidate, tp_price=1.104)
    elif change == "version":
        kwargs["version"] = "test-v2"
    elif change == "metadata":
        candidate = replace(candidate, metadata={"parameters_version": "test-v2"})
    elif change == "fill_config":
        manager = _manager(database, slip=2)
    with pytest.raises(ValueError, match="identity conflicts"):
        _open(manager, signal=candidate, **kwargs)
    assert len(manager.load_all_trades()) == 1
    assert manager.load_all_trades()[0].paper_trade_id == first.paper_trade_id


def test_equal_retry_after_break_even_returns_original_position(database):
    manager = _manager(database, trailing_start_r=5)
    opened = _open(manager)
    updated = manager.update_with_snapshot(opened, _snapshot(bid=1.1009, ask=1.1010, timestamp_utc=NOW + timedelta(seconds=1)))
    assert updated.sl_price == updated.entry_price
    retried = _open(manager)
    assert retried.paper_trade_id == opened.paper_trade_id
    assert retried.sl_price == updated.sl_price
    assert len(manager.load_all_trades()) == 1


def test_config_file_body_change_under_same_path_conflicts(database, tmp_path):
    profile = tmp_path / "profile.ini"
    profile.write_text("PAPER_RISK_MULTIPLIER=0.1\n")
    manager = _manager(database, profile_config=str(profile))
    _open(manager)
    profile.write_text("PAPER_RISK_MULTIPLIER=0.2\n")
    with pytest.raises(ValueError, match="identity conflicts"):
        _open(manager)
    assert len(manager.load_all_trades()) == 1


def test_legacy_directional_key_is_detected_and_never_duplicated(database, tmp_path):
    source = TelemetryDatabase(tmp_path / "source.sqlite3")
    try:
        trade = _open(_manager(source))
    finally:
        source.close()
    legacy = trade.replace(idempotency_key="paper_trade:fill-risk-fixture:EURUSD:BUY")
    database.insert_paper_trade(legacy.to_dict())
    manager = _manager(database)
    assert _open(manager).paper_trade_id == trade.paper_trade_id
    with pytest.raises(ValueError, match="identity conflicts"):
        _open(manager, signal=_signal(Direction.SELL))
    assert len(manager.load_all_trades()) == 1


def test_unknown_legacy_intent_fails_closed(database):
    manager = _manager(database)
    trade = _open(manager)
    metadata = dict(trade.metadata)
    metadata.pop("entry_intent_fingerprint")
    database.update_paper_trade(trade.replace(metadata=metadata).to_dict())
    with pytest.raises(ValueError, match="unverifiable legacy"):
        _open(manager)
    assert len(manager.load_all_trades()) == 1

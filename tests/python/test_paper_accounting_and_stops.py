from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agi_style_forex_bot_mt5.contracts import MarketSnapshot, TradeSignal, RiskDecision, Direction, EntryType
from agi_style_forex_bot_mt5.paper_trading.paper_position_manager import PaperPositionManager, APPROVED_LOT_BASIS
from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.core.clock import FrozenClock


NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def snapshot(bid=1.1, seconds=0):
    return MarketSnapshot(symbol="EURUSD", timeframe="M5", timestamp_utc=NOW + timedelta(seconds=seconds),
                          bid=bid, ask=round(bid + 0.0001, 5), spread_points=10., digits=5, point=0.00001,
                          tick_value=1., tick_size=0.00001, volume_min=.01, volume_max=100., volume_step=.01,
                          stops_level_points=0, freeze_level_points=0)


def signal():
    return TradeSignal(signal_id="synthetic-signal", created_at_utc=NOW, symbol="EURUSD", timeframe="M5",
                       direction=Direction.BUY, entry_type=EntryType.MARKET, sl_price=1.0991, tp_price=1.1031, risk_pct=.1)


def open_trade(manager, decision=None):
    return manager.open_trade(signal=signal(), risk_decision=decision or RiskDecision(signal_id="synthetic-signal", accepted=True,
        approved_lot=.1, risk_amount_account_currency=10.), snapshot=snapshot(), broker_symbol="EURUSD",
        score=90., reasons=("fixture",), strategy_name="fixture", strategy_version="test", regime="TREND_UP", session="LONDON")


def test_new_paper_pnl_uses_approved_lot_once_even_with_micro_overlay(tmp_path):
    profile = tmp_path / "micro.ini"
    profile.write_text("PAPER_RISK_MULTIPLIER=0.1\n")
    db = TelemetryDatabase(tmp_path / "paper.db")
    try:
        manager = PaperPositionManager(database=db, fill_model=PaperFillModel(slippage_points=0, clock=FrozenClock(NOW + timedelta(seconds=3))), profile_config=str(profile))
        trade = open_trade(manager)
        closed = manager.close_trade(trade, snapshot(1.1011, 1), "TEST_EXIT", 1.1011)
        assert closed.profit == pytest.approx(10.)
        assert closed.raw_pnl == closed.scaled_paper_pnl == closed.profit
        assert closed.r_multiple == pytest.approx(1.)
        assert closed.pnl_formula_version == "paper_pnl_approved_lot_v1"
        assert closed.metadata["pnl_basis"] == APPROVED_LOT_BASIS
    finally:
        db.close()


def test_break_even_remains_manageable_and_preserves_initial_risk(tmp_path):
    db = TelemetryDatabase(tmp_path / "paper.db")
    try:
        manager = PaperPositionManager(database=db, fill_model=PaperFillModel(slippage_points=0, clock=FrozenClock(NOW + timedelta(seconds=3))), trailing_start_r=5)
        opened = open_trade(manager)
        moved = manager.update_with_snapshot(opened, snapshot(1.10075, 1))
        assert moved.status == "OPEN" and moved.sl_price == moved.entry_price
        closed = manager.update_with_snapshot(moved, snapshot(1.10005, 2))
        assert closed.status == "CLOSED" and closed.exit_reason == "BREAK_EVEN"
        assert closed.exit_price == pytest.approx(1.10005)
        assert closed.profit < 0  # observed price gapped through the stop
        assert closed.metadata["initial_risk_distance"] == pytest.approx(.001)
    finally:
        db.close()


def test_gap_through_stop_cannot_fill_at_stale_better_stop_price(tmp_path):
    db = TelemetryDatabase(tmp_path / "paper.db")
    try:
        manager = PaperPositionManager(database=db, fill_model=PaperFillModel(slippage_points=0, clock=FrozenClock(NOW + timedelta(seconds=3))))
        trade = open_trade(manager)
        closed = manager.update_with_snapshot(trade, snapshot(1.0981, 1))
        assert closed.exit_price == pytest.approx(1.0981)
        assert closed.profit == pytest.approx(-20.)
    finally:
        db.close()


@pytest.mark.parametrize("kwargs", [dict(accepted=False, approved_lot=0., risk_amount_account_currency=0., reject_code="TEST_REJECT", reject_reason="fixture"), dict(signal_id="other"), dict(approved_lot=.015), dict(approved_lot=float("nan")), dict(risk_amount_account_currency=0)])
def test_manager_rejects_invalid_decision_before_creating_paper_trade(tmp_path, kwargs):
    db = TelemetryDatabase(tmp_path / "paper.db")
    try:
        manager = PaperPositionManager(database=db)
        decision = replace(RiskDecision(signal_id="synthetic-signal", accepted=True, approved_lot=.1, risk_amount_account_currency=10.), **kwargs)
        with pytest.raises(ValueError):
            open_trade(manager, decision)
        assert not manager.load_all_trades()
    finally:
        db.close()

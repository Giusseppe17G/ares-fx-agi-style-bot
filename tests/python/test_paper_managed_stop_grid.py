"""Managed protection stays executable without restating original risk."""

from dataclasses import replace
from datetime import timedelta

import pytest

from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.price_grid import is_price_on_tick_grid
from agi_style_forex_bot_mt5.core.operational_state.errors import PaperStateError
from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel
from agi_style_forex_bot_mt5.paper_trading.paper_position_manager import PaperPositionManager
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from test_paper_decision_state import NOW, build, snapshot, trade


def position(direction, tick):
    sign = 1 if direction == "BUY" else -1
    initial_sl = round(1.1 - sign * 101 * tick, 5)
    base = trade(direction=direction, sl_price=initial_sl, tp_price=round(1.1 + sign * 300 * tick, 5))
    return base.replace(metadata={**base.metadata, "initial_sl_price": initial_sl,
        "initial_risk_distance": abs(1.1 - initial_sl), "initial_risk_amount": base.risk_amount})


def mark(direction, tick, excursion=91):
    price = round(1.1 + (1 if direction == "BUY" else -1) * excursion * tick, 5)
    bid = price if direction == "BUY" else round(price - tick, 5)
    return replace(snapshot(now=NOW + timedelta(seconds=1), bid=bid, ask=round(bid + tick, 5)), tick_size=tick)


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
@pytest.mark.parametrize("tick", (.00001, .00005))
def test_trailing_rounds_conservatively_and_never_loosens_original_stop(tmp_path, direction, tick):
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as database:
        manager = PaperPositionManager(database=database,
            fill_model=PaperFillModel(clock=FrozenClock(NOW + timedelta(seconds=1))))
        original = position(direction, tick)
        database.insert_paper_trade(original.to_dict())
        moved = manager.update_with_snapshot(original, mark(direction, tick))
        expected = round(1.1 + (1 if direction == "BUY" else -1) * 40 * tick, 5)
        assert moved.sl_price == expected
        assert is_price_on_tick_grid(moved.sl_price, tick)
        quote = mark(direction, tick, 50)
        retraced = manager.update_with_snapshot(moved, quote)
        assert retraced.sl_price == moved.sl_price and retraced.status == "OPEN"
        assert retraced.sl_price < quote.bid if direction == "BUY" else retraced.sl_price > quote.ask
        assert retraced.metadata["initial_risk_distance"] == original.metadata["initial_risk_distance"]
        assert retraced.risk_amount == original.risk_amount
        assert manager.load_open_trades()[0].sl_price == expected


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
def test_break_even_uses_entry_then_trailing_uses_original_distance(tmp_path, direction):
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as database:
        manager = PaperPositionManager(database=database)
        original = position(direction, .00001)
        database.insert_paper_trade(original.to_dict())
        moved = manager.update_with_snapshot(original, mark(direction, .00001, 65))
        assert moved.sl_price == original.entry_price
        trailed = manager.update_with_snapshot(moved, mark(direction, .00001, 91))
        assert trailed.sl_price == round(1.1 + (1 if direction == "BUY" else -1) * .0004, 5)
        assert trailed.metadata == original.metadata


@pytest.mark.parametrize("field", ("entry_price", "sl_price", "tp_price"))
def test_persisted_offgrid_protection_blocks_valuation_and_management(tmp_path, field):
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as database:
        build(database)
        original = position("BUY", .00001)
        invalid = original.replace(**{field: getattr(original, field) + .000005})
        database.insert_paper_trade(invalid.to_dict())
        with pytest.raises(PaperStateError) as caught:
            build(database, [invalid])
        assert caught.value.detail["reject_code"] == "PAPER_PROTECTION_GRID_INVALID"
        manager = PaperPositionManager(database=database)
        before = manager.load_all_trades()[0].to_dict()
        with pytest.raises(ValueError, match="tick grid"):
            manager.update_with_snapshot(invalid, mark("BUY", .00001))
        assert manager.load_all_trades()[0].to_dict() == before


@pytest.mark.parametrize("field,value", [("tick_value", float("nan")), ("volume_step", float("inf")),
    ("tick_size", .000015), ("freeze_level_points", -1)])
def test_invalid_broker_metadata_cannot_mutate_stop(tmp_path, field, value):
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as database:
        manager = PaperPositionManager(database=database)
        original = position("BUY", .00001)
        database.insert_paper_trade(original.to_dict())
        quote = replace(mark("BUY", .00001), **{field: value})
        with pytest.raises(ValueError):
            manager.update_with_snapshot(original, quote)
        assert manager.load_all_trades()[0].sl_price == original.sl_price

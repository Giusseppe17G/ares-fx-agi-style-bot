from dataclasses import replace
from datetime import timedelta

import pytest

from test_paper_accounting_and_stops import snapshot, NOW
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel


def test_fill_rechecks_freshness_after_pipeline_work():
    clock = FrozenClock(NOW)
    model = PaperFillModel(clock=clock)
    assert model.entry_result(direction="BUY", snapshot=snapshot(), lot=.1).accepted
    clock.advance(timedelta(seconds=6))
    decision = model.entry_result(direction="BUY", snapshot=snapshot(), lot=.1)
    assert not decision.accepted and decision.reject_code == "TICK_STALE"


def test_future_fill_snapshot_is_rejected():
    model = PaperFillModel(clock=FrozenClock(NOW))
    with pytest.raises(ValueError, match="future"):
        model.entry_result(direction="BUY", snapshot=snapshot(seconds=1), lot=.1)


@pytest.mark.parametrize("change", [dict(max_tick_age_seconds=6), dict(max_tick_age_seconds=0), dict(slippage_points=float("nan")), dict(commission_per_lot_round_turn=float("inf")), dict(commission_per_lot_round_turn=-1)])
def test_paper_fill_cannot_weaken_age_or_accept_invalid_costs(change):
    with pytest.raises(ValueError):
        replace(PaperFillModel(), **change)

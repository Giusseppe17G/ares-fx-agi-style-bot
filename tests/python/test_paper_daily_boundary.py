"""Exact observed midnight references never reset existing intraday risk."""

from datetime import timedelta

import pytest

from agi_style_forex_bot_mt5.core.operational_state.errors import PaperStateError
from agi_style_forex_bot_mt5.paper_trading.decision_state import capture_paper_daily_reference
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from test_paper_decision_state import NOW, TEMPLATE, build, snapshot, trade


def test_boundary_preserves_reference_and_latched_halt_on_repeated_capture(tmp_path):
    midnight = NOW.replace(hour=0) + timedelta(days=1)
    position = trade(lot=1., sl_price=1.08, risk_amount=2000.)
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as database:
        build(database)
        build(database, [position])

        def capture(bid):
            return capture_paper_daily_reference(database=database, trades=[position],
                snapshots_by_symbol={"EURUSD": snapshot(now=midnight, bid=bid, ask=round(bid + .0002, 5))},
                account_template=TEMPLATE, now_utc=midnight)

        first = capture(1.1)
        assert first.risk_state.daily_equity_reference == 10000
        assert not first.risk_state.kill_switch.active
        loss = capture(1.096)
        assert loss.risk_state.kill_switch.active
        recovery = capture(1.1)
        assert recovery.risk_state.kill_switch.active
        assert recovery.risk_state.daily_equity_reference == 10000


@pytest.mark.parametrize("delta", (-1, 1))
def test_boundary_time_cannot_be_approximated(tmp_path, delta):
    now = NOW.replace(hour=0) + timedelta(days=1, seconds=delta)
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as database:
        build(database)
        with pytest.raises(PaperStateError):
            capture_paper_daily_reference(database=database, trades=[],
                snapshots_by_symbol={"EURUSD": snapshot(now=now)}, account_template=TEMPLATE, now_utc=now)


def test_boundary_validates_all_supplied_quotes_even_without_exposure(tmp_path):
    midnight = NOW.replace(hour=0) + timedelta(days=1)
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as database:
        build(database)
        with pytest.raises(PaperStateError):
            capture_paper_daily_reference(database=database, trades=[],
                snapshots_by_symbol={"EURUSD": snapshot(now=midnight - timedelta(seconds=1))},
                account_template=TEMPLATE, now_utc=midnight)

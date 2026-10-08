"""Paper equity, persistent risk references and complete portfolio exposure."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agi_style_forex_bot_mt5.contracts import AccountState, Direction, MarketSnapshot
from agi_style_forex_bot_mt5.core.operational_state.errors import PaperStateError
from agi_style_forex_bot_mt5.paper_trading.decision_state import (
    PAPER_DECISION_STATE_KEY,
    PAPER_PNL_ACCOUNTING_BASIS,
    build_paper_decision_state,
)
from agi_style_forex_bot_mt5.paper_trading.paper_trade import PaperTrade
from agi_style_forex_bot_mt5.risk.portfolio_guard import PortfolioGuard
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
TEMPLATE = AccountState(login=7, trade_mode="DEMO", balance=10000, equity=10000, margin_free=10000, currency="USD", is_demo=True, trade_allowed=True)


@pytest.fixture
def database(tmp_path):
    with TelemetryDatabase(tmp_path / "paper.sqlite3") as db:
        yield db


def snapshot(*, now=NOW, symbol="EURUSD", bid=1.101, ask=1.1012):
    return MarketSnapshot(symbol=symbol, timeframe="M5", timestamp_utc=now, bid=bid, ask=ask, spread_points=(ask-bid)/0.00001, digits=5, point=0.00001, tick_value=1.0, tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, stops_level_points=0, freeze_level_points=0)


def trade(identity="one", **updates):
    base = PaperTrade(paper_trade_id=f"ptr_{identity}", signal_id=f"signal_{identity}", idempotency_key=f"paper_{identity}", symbol="EURUSD", broker_symbol="EURUSD.raw", direction="BUY", entry_time_utc=NOW.isoformat(), entry_price=1.1, sl_price=1.098, tp_price=1.104, lot=0.1, risk_pct=0.2, risk_amount=20, strategy_name="fixture", strategy_version="1", regime="TREND_UP", session="LONDON", score=80, reasons=(), metadata={"pnl_basis": PAPER_PNL_ACCOUNTING_BASIS})
    return base.replace(**updates)


def closed(identity="one", *, pnl=-20, **updates):
    fields = dict(status="CLOSED", exit_time_utc=NOW.isoformat(), exit_price=1.098, exit_reason="SL", profit=pnl, raw_pnl=pnl, scaled_paper_pnl=pnl, pnl_formula_version="paper_pnl_approved_lot_v1")
    return trade(identity, **{**fields, **updates})


def build(db, history=(), *, now=NOW, snapshots=None, **kwargs):
    return build_paper_decision_state(database=db, trades=history, snapshots_by_symbol={"EURUSD": snapshot(now=now)} if snapshots is None else snapshots, account_template=kwargs.pop("account_template", TEMPLATE), now_utc=now, **kwargs)


def test_bootstrap_persists_capital_without_claiming_signal_audit(database):
    result = build(database)
    assert result.account.balance == result.account.equity == 10000
    assert result.risk_state.daily_equity_reference == 10000
    assert result.risk_state.audit_confirmed is False
    assert result.risk_state.open_positions == ()
    persisted = database.get_operational_state()[PAPER_DECISION_STATE_KEY]
    assert persisted["initial_balance"] == 10000
    assert "login" not in str(persisted)
    assert "account" not in str(persisted)
    assert result.account.login == TEMPLATE.login
    assert result.account.is_demo is True
    assert result.account.margin_free == 0


def test_existing_history_without_baseline_fails_closed(database):
    with pytest.raises(PaperStateError) as caught:
        build(database, [closed()])
    assert caught.value.detail["reject_code"] == "PAPER_CAPITAL_REFERENCE_MISSING"
    assert PAPER_DECISION_STATE_KEY not in database.get_operational_state()


def test_pnl_basis_survives_real_trade_persistence_and_redaction(database):
    build(database)
    assert database.insert_paper_trade(trade().to_dict()) is True
    restored = PaperTrade.from_json(database.fetch_paper_trades()[0]["payload_json"])
    assert restored.metadata["pnl_basis"] == PAPER_PNL_ACCOUNTING_BASIS
    result = build(database, [restored])
    assert result.account.equity == pytest.approx(10010)


def test_balances_use_paper_realized_and_marked_float_not_current_broker_balance(database):
    build(database)
    result = build(database, [closed("loss", pnl=-100), trade()], account_template=replace(TEMPLATE, balance=900000, equity=950000), audit_confirmed=True)
    assert result.realized_pnl == -100
    assert result.floating_pnl == pytest.approx(10)
    assert result.account.balance == 9900
    assert result.account.equity == pytest.approx(9910)
    assert result.risk_state.daily_equity_reference == 10000
    assert result.risk_state.floating_drawdown_reference == 9900
    assert result.risk_state.audit_confirmed is True
    assert len(result.risk_state.open_positions) == 1
    position = result.risk_state.open_positions[0]
    assert position.direction is Direction.BUY
    assert result.risk_state.open_position_risk_amounts[position.ticket] == pytest.approx(30)
    assert result.risk_state.snapshots_by_symbol["EURUSD"].bid == 1.101
    assert result.portfolio_open_trades[0]["risk_pct"] == pytest.approx(30 / 9910 * 100)
    assert result.portfolio_open_trades[0]["risk_amount_current"] == pytest.approx(30)
    assert result.portfolio_open_trades[0]["risk_amount"] == 20


def test_sell_marks_use_ask_and_commission_once(database):
    build(database)
    position = trade(direction="SELL", entry_price=1.103, sl_price=1.106, tp_price=1.098, commission_assumed=0.4)
    result = build(database, [position])
    assert result.floating_pnl == pytest.approx(17.6)


def test_restart_keeps_original_daily_reference_and_open_identity(database):
    build(database)
    first = build(database, [trade()])
    second = build(database, [trade()], now=NOW + timedelta(seconds=30), account_template=replace(TEMPLATE, balance=999999))
    assert first.initial_balance == second.initial_balance == 10000
    assert first.risk_state.daily_equity_reference == second.risk_state.daily_equity_reference == 10000
    assert first.risk_state.open_positions[0].ticket == second.risk_state.open_positions[0].ticket


def test_baseline_survives_database_close_and_reopen(tmp_path):
    path = tmp_path / "paper.sqlite3"
    with TelemetryDatabase(path) as db:
        build(db)
        build(db, [closed(pnl=-200)])
    with TelemetryDatabase(path) as db:
        result = build(db, [closed(pnl=-200)], account_template=replace(TEMPLATE, balance=9800), now=NOW + timedelta(minutes=1))
    assert result.account.balance == 9800
    assert result.risk_state.daily_equity_reference == 10000


def test_daily_halt_remains_after_equity_recovers_and_new_day_references_realized_balance(database):
    build(database)
    loss = closed("loss", pnl=-300)
    halted = build(database, [loss])
    assert halted.risk_state.kill_switch.active is True
    recovered = build(database, [loss, closed("gain", pnl=300)])
    assert recovered.account.equity == 10000
    assert recovered.risk_state.kill_switch.active is True
    next_day = build(database, [loss, closed("gain", pnl=300)], now=NOW + timedelta(days=1))
    assert next_day.risk_state.kill_switch.active is False
    assert next_day.risk_state.daily_equity_reference == 10000
    assert len(database.get_operational_state()[PAPER_DECISION_STATE_KEY]["daily_references"]) == 2


def test_new_day_reference_includes_only_closes_before_midnight(database):
    build(database)
    old = closed(pnl=-120)
    build(database, [old])
    result = build(database, [old], now=NOW + timedelta(days=1))
    assert result.risk_state.daily_equity_reference == 9880


def test_missing_overnight_reference_is_not_reconstructed_from_current_prices(database):
    build(database)
    build(database, [trade()])
    with pytest.raises(PaperStateError) as caught:
        build(database, [trade()], now=NOW + timedelta(days=1))
    assert caught.value.detail["reject_code"] == "DAILY_DRAWDOWN_REFERENCE_MISSING"
    assert len(database.get_operational_state()[PAPER_DECISION_STATE_KEY]["daily_references"]) == 1


def test_closed_overnight_trade_also_requires_real_midnight_reference(database):
    build(database)
    overnight = closed(exit_time_utc=(NOW + timedelta(days=1)).isoformat())
    with pytest.raises(PaperStateError) as caught:
        build(database, [overnight], now=NOW + timedelta(days=1))
    assert caught.value.detail["reject_code"] == "DAILY_DRAWDOWN_REFERENCE_MISSING"


@pytest.mark.parametrize("bad_snapshot", [
    None, replace(snapshot(), timestamp_utc=NOW-timedelta(seconds=6)),
    replace(snapshot(), timestamp_utc=NOW+timedelta(seconds=1)),
    replace(snapshot(), tick_value=float("nan")), replace(snapshot(), tick_value=0),
    replace(snapshot(), tick_size=float("inf")), replace(snapshot(), point=True),
    replace(snapshot(), digits=5.5), replace(snapshot(), freeze_level_points=None),
    replace(snapshot(), bid=1.097, ask=1.0972),
])
def test_every_open_position_requires_valid_fresh_market_and_metadata(database, bad_snapshot):
    build(database)
    with pytest.raises(PaperStateError):
        build(database, [trade()], snapshots={"EURUSD": bad_snapshot})


def test_missing_snapshot_of_another_open_symbol_blocks_whole_state(database):
    build(database)
    with pytest.raises(PaperStateError):
        build(database, [trade(), trade("gbp", symbol="GBPUSD")])


@pytest.mark.parametrize("changes", [
    {"metadata": {}}, {"paper_risk_multiplier": 0.1}, {"risk_multiplier": 0.5},
    {"multiplier_applied": True}, {"lot": float("inf")}, {"lot": 0.013},
    {"risk_amount": 0}, {"sl_price": 0}, {"tp_price": 0}, {"direction": "UNKNOWN"},
    {"status": "PENDING"}, {"entry_time_utc": "2026-10-05T12:00:00"},
])
def test_legacy_ambiguous_or_invalid_positions_block_state(database, changes):
    build(database)
    with pytest.raises(PaperStateError):
        build(database, [trade(**changes)])


def test_inconsistent_scaled_closed_pnl_is_not_adopted(database):
    build(database)
    with pytest.raises(PaperStateError):
        build(database, [closed().replace(scaled_paper_pnl=-2)])
    with pytest.raises(PaperStateError):
        build(database, [closed().replace(pnl_formula_version="paper_pnl_scaled_v1")])


def test_history_cannot_disappear_change_economic_terms_or_reopen(database):
    build(database)
    build(database, [trade()])
    with pytest.raises(PaperStateError):
        build(database, [])
    with pytest.raises(PaperStateError):
        build(database, [trade(lot=0.2)])
    build(database, [closed()])
    with pytest.raises(PaperStateError):
        build(database, [trade()])
    with pytest.raises(PaperStateError):
        build(database, [closed(pnl=-1)])


def test_duplicate_trade_ids_are_rejected(database):
    build(database)
    with pytest.raises(PaperStateError):
        build(database, [trade(), trade()])


def test_zero_equity_halts_are_persisted_before_state_rejection(database):
    build(database)
    with pytest.raises(PaperStateError):
        build(database, [closed(pnl=-10000)])
    assert database.get_operational_state()[PAPER_DECISION_STATE_KEY]["daily_references"]["2026-10-05"]["halted"] is True


def test_risk_state_counts_all_positions_and_preserves_initial_risk_after_stop_moves(database):
    build(database)
    history = [trade(str(index), risk_amount=60) for index in range(10)]
    result = build(database, history)
    assert len(result.risk_state.open_positions) == 10
    assert sum(result.risk_state.open_position_risk_amounts.values()) == 600
    portfolio = PortfolioGuard().evaluate(equity=result.account.equity, candidate_symbol="GBPUSD", candidate_risk_amount=10, open_positions=result.risk_state.open_positions, snapshots_by_symbol=result.risk_state.snapshots_by_symbol, open_position_risk_amounts=result.risk_state.open_position_risk_amounts)
    assert portfolio.reject_code == "MAX_OPEN_TRADES"
    moved = trade(sl_price=1.1)
    # A separate baseline avoids rewriting previously persisted economic terms.
    fresh = MemoryStore()
    build(fresh)
    protected = build(fresh, [moved])
    assert next(iter(protected.risk_state.open_position_risk_amounts.values())) == 20


def test_consecutive_losses_uses_complete_closed_history(database):
    build(database)
    history = [closed("one", pnl=-1), closed("two", pnl=-2), closed("three", pnl=-3)]
    assert build(database, history).risk_state.consecutive_losses == 3


def test_complete_exposure_blocks_more_than_five_percent_open_risk(database):
    build(database)
    result = build(database, [trade("one", risk_amount=300), trade("two", risk_amount=300)])
    portfolio = PortfolioGuard().evaluate(equity=result.account.equity, candidate_symbol="GBPUSD", candidate_risk_amount=10, open_positions=result.risk_state.open_positions, snapshots_by_symbol=result.risk_state.snapshots_by_symbol, open_position_risk_amounts=result.risk_state.open_position_risk_amounts)
    assert portfolio.reject_code == "MAX_OPEN_RISK"


class MemoryStore:
    def __init__(self):
        self.value = {}

    def get_operational_state(self):
        return copy.deepcopy(self.value)

    def update_operational_state(self, updates):
        self.value.update(copy.deepcopy(updates))
        return self.get_operational_state()


@pytest.mark.parametrize("behavior", ["error", "silent", "corrupt"])
def test_persistence_must_succeed_and_read_back(behavior):
    class BrokenStore(MemoryStore):
        def update_operational_state(self, updates):
            if behavior == "error":
                raise OSError("password=PRIVATE")
            if behavior == "corrupt":
                self.value = {PAPER_DECISION_STATE_KEY: {"invalid": True}}
            return {}

    with pytest.raises(PaperStateError) as caught:
        build(BrokenStore())
    assert "PRIVATE" not in str(caught.value)


def test_corrupt_persisted_state_is_never_reseeded_from_broker_balance():
    store = MemoryStore()
    store.value[PAPER_DECISION_STATE_KEY] = None
    with pytest.raises(PaperStateError):
        build(store)
    store.value[PAPER_DECISION_STATE_KEY] = {"initial_balance": 10000}
    with pytest.raises(PaperStateError):
        build(store)


def test_clock_rewind_currency_change_and_fabricated_audit_type_reject(database):
    build(database)
    with pytest.raises(PaperStateError):
        build(database, now=NOW-timedelta(seconds=1))
    with pytest.raises(PaperStateError):
        build(database, account_template=replace(TEMPLATE, currency="JPY"))
    with pytest.raises(PaperStateError):
        build(database, audit_confirmed="True")

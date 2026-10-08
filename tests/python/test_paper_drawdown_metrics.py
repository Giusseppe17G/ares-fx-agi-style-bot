"""Daily percentage alerts must never reinterpret historical money drawdown."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agi_style_forex_bot_mt5.contracts import AccountState, MarketSnapshot
from agi_style_forex_bot_mt5.core import FrozenClock
from agi_style_forex_bot_mt5.observability import AlertRuleEngine, MetricsCollector
from agi_style_forex_bot_mt5.paper_trading.decision_state import PAPER_DECISION_STATE_KEY, build_paper_decision_state
from agi_style_forex_bot_mt5.paper_trading.paper_trade import PaperTrade
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
ACCOUNT = AccountState(7, "DEMO", 10000, 10000, 0, is_demo=True, trade_allowed=True)


def trade(identity="one", *, profit=-4, opened=False):
    return PaperTrade(paper_trade_id=f"ptr_{identity}", signal_id=f"signal_{identity}", idempotency_key=f"paper_{identity}", symbol="EURUSD", broker_symbol="EURUSD", direction="BUY", entry_time_utc=NOW.isoformat(), entry_price=1.1, sl_price=1.09, tp_price=1.11, lot=1, risk_pct=0.5, risk_amount=50, strategy_name="fixture", strategy_version="1", regime="TREND_UP", session="LONDON", score=80, reasons=(), status="OPEN" if opened else "CLOSED", exit_time_utc=None if opened else NOW.isoformat(), exit_price=None if opened else 1.09996, profit=0 if opened else profit, raw_pnl=0 if opened else profit, scaled_paper_pnl=0 if opened else profit, r_multiple=0 if opened else profit/50, pnl_formula_version="" if opened else "paper_pnl_approved_lot_v1", metadata={"pnl_basis": "APPROVED_LOT_UNSCALED_V1"})


def value(db, *, now=NOW, bid=1.1):
    snapshot = MarketSnapshot("EURUSD", "M5", now, bid, bid+0.0001, 10, 5, 0.00001, 1, 0.00001, 0.01, 100, 0.01, 0, 0)
    history = [PaperTrade.from_json(row["payload_json"]) for row in db.fetch_paper_trades()]
    return build_paper_decision_state(database=db, trades=history, snapshots_by_symbol={"EURUSD": snapshot}, account_template=ACCOUNT, now_utc=now)


@pytest.fixture
def database(tmp_path):
    with TelemetryDatabase(tmp_path / "metrics.sqlite3") as db:
        value(db)
        yield db


def collect(db, now=NOW):
    return MetricsCollector(db, clock=FrozenClock(now)).collect()


def codes(db, metrics):
    return {alert.alert_code for alert in AlertRuleEngine(db).evaluate({**metrics, "mt5_connected": True})}


def test_four_currency_units_do_not_trigger_a_three_percent_halt(database):
    database.insert_paper_trade(trade(profit=-4).to_dict())
    value(database)
    metrics = collect(database)
    assert metrics["paper_risk_state_status"] == "VERIFIED"
    assert metrics["daily_drawdown_pct"] == pytest.approx(0.04)
    assert metrics["drawdown_paper"] == pytest.approx(-0.04)
    assert metrics["historical_drawdown_amount"] == -4
    assert metrics["historical_drawdown_currency"] == "USD"
    assert "PAPER_DAILY_DRAWDOWN" not in codes(database, metrics)


def test_actual_three_percent_equity_loss_triggers_daily_halt(database):
    database.insert_paper_trade(trade(profit=-300).to_dict())
    value(database)
    metrics = collect(database)
    assert metrics["daily_drawdown_pct"] == 3
    assert metrics["daily_drawdown_halted"] is True
    assert "PAPER_DAILY_DRAWDOWN" in codes(database, metrics)


def test_open_mark_to_market_is_included_in_daily_and_floating_alerts(database):
    database.insert_paper_trade(trade(opened=True).to_dict())
    value(database, bid=1.094)
    metrics = collect(database)
    assert metrics["paper_realized_pnl"] == 0
    assert metrics["paper_floating_pnl"] == pytest.approx(-600)
    assert metrics["daily_drawdown_pct"] == pytest.approx(6)
    assert metrics["floating_drawdown_pct"] == pytest.approx(6)
    assert {"PAPER_DAILY_DRAWDOWN", "PAPER_FLOATING_DRAWDOWN"}.issubset(codes(database, metrics))


def test_daily_halt_persists_after_recovery_but_historical_money_does_not_rehalt_next_day(database):
    database.insert_paper_trade(trade("loss", profit=-300).to_dict())
    value(database)
    database.insert_paper_trade(trade("gain", profit=400).to_dict())
    value(database)
    recovered = collect(database)
    assert recovered["daily_drawdown_pct"] == 0
    assert "PAPER_DAILY_DRAWDOWN" in codes(database, recovered)
    tomorrow = NOW + timedelta(days=1)
    value(database, now=tomorrow)
    renewed = collect(database, tomorrow)
    assert renewed["historical_drawdown_amount"] == -300
    assert renewed["daily_drawdown_pct"] == 0
    assert "PAPER_DAILY_DRAWDOWN" not in codes(database, renewed)


def test_legacy_history_without_references_is_unknown_not_zero_or_three_percent(tmp_path):
    with TelemetryDatabase(tmp_path / "legacy.sqlite3") as db:
        db.insert_paper_trade(trade().replace(metadata={}, pnl_formula_version="").to_dict())
        metrics = collect(db)
        assert metrics["paper_risk_state_status"] == "UNKNOWN"
        assert metrics["daily_drawdown_pct"] is None
        assert metrics["drawdown_paper"] is None
        assert "PAPER_RISK_DATA_MISSING" in codes(db, metrics)
        assert "PAPER_DAILY_DRAWDOWN" not in codes(db, metrics)


def test_book_change_requires_a_new_mark_even_when_prior_valuation_is_fresh(database):
    database.insert_paper_trade(trade().to_dict())
    metrics = collect(database)
    assert metrics["paper_risk_state_reason"] == "PAPER_BOOK_CHANGED_SINCE_VALUATION"
    assert metrics["daily_drawdown_pct"] is None
    assert "PAPER_RISK_DATA_MISSING" in codes(database, metrics)


@pytest.mark.parametrize("delta", [timedelta(seconds=6), timedelta(seconds=-1), timedelta(days=1)])
def test_stale_future_or_previous_day_valuation_is_unknown(database, delta):
    database.insert_paper_trade(trade().to_dict())
    value(database)
    metrics = collect(database, NOW+delta)
    assert metrics["paper_risk_state_status"] == "UNKNOWN"
    assert metrics["daily_drawdown_pct"] is None


@pytest.mark.parametrize("field,value_", [("balance", float("nan")), ("equity", float("inf")), ("balance", 12000), ("trade_state_hash", "invalid")])
def test_corrupt_valuation_cannot_claim_verified_metrics(database, field, value_):
    state = database.get_operational_state()[PAPER_DECISION_STATE_KEY]
    state["observed_valuation"][field] = value_
    database.update_operational_state({PAPER_DECISION_STATE_KEY: state})
    assert collect(database)["paper_risk_state_status"] == "UNKNOWN"


def test_legacy_unlabelled_drawdown_metric_is_not_assumed_to_be_a_percent(database):
    result = codes(database, {"drawdown_paper": -4})
    assert "PAPER_DAILY_DRAWDOWN" not in result
    assert "PAPER_RISK_DATA_MISSING" in result


def test_closed_history_metadata_decoration_does_not_invalidate_economic_fingerprint(database):
    item = trade()
    database.insert_paper_trade(item.to_dict())
    value(database)
    database.update_paper_trade(item.replace(metadata={**item.metadata, "display_note": "reviewed"}).to_dict())
    assert collect(database)["paper_risk_state_status"] == "VERIFIED"


def test_closed_today_uses_injected_utc_day_and_normalizes_record_offsets(database):
    record = trade().replace(exit_time_utc="2026-10-04T23:30:00-05:00")
    database.insert_paper_trade(record.to_dict())
    local_clock = NOW.astimezone(timezone(timedelta(hours=-5)))
    metrics = collect(database, local_clock)
    assert metrics["closed_paper_trades_today"] == 1

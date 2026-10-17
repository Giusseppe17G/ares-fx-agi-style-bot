"""Tick value is the broker's, or derived from price; never an assumed 1.0.

One tick of 0.001 JPY on a 100,000 USD lot is 100 JPY, about 0.67 USD near
150. The legacy placeholder priced it at 1.0 USD, overstating every USDJPY
profit, loss and drawdown by roughly half. Crosses such as EURJPY need a third
rate that nothing here has, so they fail closed instead of borrowing a constant.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import backtester
from agi_style_forex_bot_mt5.backtesting.backtester import (
    BacktestSettings, Backtester, CostModel, Direction, TradeCandidate, _snapshot_from_row,
    assumed_instrument_for_bars, run_backtest_for_symbols, run_strategy_backtest,
)
from agi_style_forex_bot_mt5.backtesting.walk_forward_optimizer import _run_param_backtest
from agi_style_forex_bot_mt5.calibration import analyze_signal_frequency, get_signal_profile
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.core.instruments import ASSUMED_SOURCE, assumed_fx_point, assumed_fx_spec, derive_tick_value, resolve_registry
from agi_style_forex_bot_mt5.core.instruments.snapshot import instrument_metadata_hash
from agi_style_forex_bot_mt5.core.operational_state.errors import InstrumentError
from agi_style_forex_bot_mt5.core.parity import build_fixture
from agi_style_forex_bot_mt5.micro_v2_lifecycle_risk_comparison.open_trade_lifecycle_audit import audit_open_trade_lifecycle
from agi_style_forex_bot_mt5.micro_v2_lifecycle_risk_comparison.pnl_readiness_audit import audit_pnl_readiness
from agi_style_forex_bot_mt5.paper_pnl_audit import run_paper_pnl_audit, run_paper_risk_recommendation
from agi_style_forex_bot_mt5.paper_pnl_audit.paper_pnl_audit_report import _recommended_action, _status
from agi_style_forex_bot_mt5.paper_pnl_audit.pnl_formula_auditor import audit_pnl_formulas
from agi_style_forex_bot_mt5.paper_pnl_audit.symbol_contract_auditor import audit_symbol_contracts
from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import calculate_raw_pnl
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)

EURUSD_VALUES = {
    "digits": 5, "point": 0.00001, "tick_size": 0.00001, "tick_value": 1.0, "contract_size": 100000.0,
    "min_volume": 0.01, "max_volume": 100.0, "volume_step": 0.01, "stops_level_points": 0,
    "freeze_level_points": 0, "currency_base": "EUR", "currency_quote": "USD",
}


def _candles(start: float, *, step: float, digits: int, bars: int = 120) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=bars, freq="5min", tz="UTC")
    rows, price = [], start
    for index, timestamp in enumerate(timestamps):
        price = round(price + (step if index % 3 else -step / 2), digits)
        rows.append({"timestamp": timestamp, "open": price, "high": round(price + 2 * step, digits),
                     "low": round(price - 2 * step, digits), "close": round(price + step / 2, digits),
                     "volume": 1000 + index, "spread_points": 10.0})
    return pd.DataFrame(rows)


def _write_csv(directory: Path, symbol: str, candles: pd.DataFrame) -> None:
    frame = candles.rename(columns={"timestamp": "time", "volume": "tick_volume", "spread_points": "spread"})
    frame["time"] = frame["time"].map(lambda value: value.isoformat())
    frame.to_csv(directory / f"{symbol}_M5.csv", index=False)


# --------------------------------------------------------------------------- derivation


def test_usd_quoted_tick_value_is_tick_size_times_contract_size() -> None:
    assert derive_tick_value(currency_base="EUR", currency_quote="USD", tick_size=0.00001, contract_size=100000.0) == pytest.approx(1.0)
    # The pair's own price does not enter a USD-quoted tick value.
    assert derive_tick_value(currency_base="GBP", currency_quote="USD", tick_size=0.00001, contract_size=100000.0, price=1.27) == pytest.approx(1.0)
    assert derive_tick_value(currency_base="XAU", currency_quote="USD", tick_size=0.01, contract_size=100.0) == pytest.approx(1.0)


@pytest.mark.parametrize("base,quote,tick_size,price,expected", [
    ("USD", "JPY", 0.001, 150.0, 100.0 / 150.0),
    ("USD", "JPY", 0.001, 80.0, 1.25),
    ("USD", "CHF", 0.00001, 0.9, 1.0 / 0.9),
    ("USD", "CAD", 0.00001, 1.35, 1.0 / 1.35),
])
def test_usd_base_tick_value_divides_by_the_pairs_own_price(base: str, quote: str, tick_size: float, price: float, expected: float) -> None:
    value = derive_tick_value(currency_base=base, currency_quote=quote, tick_size=tick_size, contract_size=100000.0, price=price)
    assert value == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("price", [None, 0.0, -150.0, math.nan, math.inf, True, "150"])
def test_usd_base_tick_value_without_a_valid_price_fails_closed(price: object) -> None:
    with pytest.raises(InstrumentError):
        derive_tick_value(currency_base="USD", currency_quote="JPY", tick_size=0.001, contract_size=100000.0, price=price)


@pytest.mark.parametrize("base,quote", [("EUR", "JPY"), ("EUR", "GBP"), ("GBP", "JPY"), ("AUD", "CAD")])
def test_cross_tick_value_has_no_conversion_rate_and_fails_closed(base: str, quote: str) -> None:
    with pytest.raises(InstrumentError):
        derive_tick_value(currency_base=base, currency_quote=quote, tick_size=0.001, contract_size=100000.0, price=150.0)


@pytest.mark.parametrize("field,value", [("tick_size", 0.0), ("tick_size", math.nan), ("contract_size", -1.0), ("contract_size", None)])
def test_tick_value_rejects_invalid_geometry(field: str, value: object) -> None:
    arguments = {"currency_base": "EUR", "currency_quote": "USD", "tick_size": 0.00001, "contract_size": 100000.0, field: value}
    with pytest.raises(InstrumentError):
        derive_tick_value(**arguments)


# --------------------------------------------------------------------------- assumed specs


def test_assumed_usdjpy_spec_no_longer_claims_one_dollar_per_tick() -> None:
    spec = assumed_fx_spec("USDJPY", reference_price=150.0)
    assert spec.tick_value == pytest.approx(0.666667, rel=1e-6)
    assert spec.tick_value != 1.0
    assert (spec.digits, spec.tick_size, spec.source) == (3, 0.001, ASSUMED_SOURCE)
    assert assumed_fx_spec("EURUSD").tick_value == pytest.approx(1.0)
    assert assumed_fx_spec("USDCHF", reference_price=0.9).tick_value == pytest.approx(1.0 / 0.9)


def test_assumed_spec_fails_closed_when_tick_value_cannot_be_derived() -> None:
    with pytest.raises(InstrumentError):
        assumed_fx_spec("USDJPY")
    with pytest.raises(InstrumentError):
        assumed_fx_spec("EURJPY", reference_price=160.0)
    with pytest.raises(InstrumentError):
        assumed_fx_spec("EURGBP", reference_price=0.85)


def test_assumed_point_carries_price_grid_only() -> None:
    assert assumed_fx_point("USDJPY") == 0.001
    assert assumed_fx_point("EURJPY") == 0.001
    assert assumed_fx_point("EURUSD") == 0.00001


def test_parity_fixture_does_not_lend_eurusd_tick_value_to_other_pairs() -> None:
    assert build_fixture().instrument.tick_value == 1.0
    with pytest.raises(InstrumentError):
        build_fixture(symbol="EURJPY")


def test_resolved_assumed_registry_prices_base_currency_pairs() -> None:
    registry, source = resolve_registry(symbols=["EURUSD", "USDJPY"], reference_prices={"usdjpy": 125.0})
    assert source == ASSUMED_SOURCE
    assert registry.get("USDJPY").tick_value == pytest.approx(0.8)
    assert registry.get("EURUSD").tick_value == pytest.approx(1.0)
    with pytest.raises(InstrumentError):
        resolve_registry(symbols=["EURUSD", "USDJPY"])
    with pytest.raises(InstrumentError):
        resolve_registry(symbols=["EURJPY"], reference_prices={"EURJPY": 160.0})


# --------------------------------------------------------------------------- backtesting


def test_backtest_snapshot_derives_tick_value_from_the_bar_close() -> None:
    row = pd.Series({"close": 150.000, "spread_points": 10.0, "timestamp_utc": NOW})
    snapshot = _snapshot_from_row(row, symbol="USDJPY", timeframe="M5", point=0.001, config=BotConfig())
    assert snapshot.tick_value == pytest.approx(100.0 / 150.0)
    with pytest.raises(InstrumentError):
        _snapshot_from_row(row, symbol="EURJPY", timeframe="M5", point=0.001, config=BotConfig())


def test_strategy_backtest_prices_usdjpy_at_its_first_close() -> None:
    candles = _candles(150.0, step=0.005, digits=3)
    outcome = run_strategy_backtest(candles, symbol="USDJPY")
    first_close = float(candles["close"].iloc[0])
    assert outcome.settings.cost_model.tick_value == pytest.approx(100.0 / first_close)
    assert all(trade.tick_value == outcome.settings.cost_model.tick_value for trade in outcome.trades)
    with pytest.raises(InstrumentError):
        run_strategy_backtest(_candles(160.0, step=0.005, digits=3), symbol="EURJPY")


@pytest.mark.parametrize("commission", [0.0, 7.0])
def test_usdjpy_trade_profit_is_in_usd_at_the_first_close(commission: float) -> None:
    # The strategy fixtures above are too short to trade (candidates start at bar
    # 220), so the money unit is pinned here on one explicit candidate.
    timestamps = pd.date_range("2026-01-05", periods=50, freq="5min", tz="UTC")
    closes = [round(150.0 + 0.02 * index, 3) for index in range(50)]
    candles = pd.DataFrame({"timestamp": timestamps, "open": closes, "close": closes,
                            "high": [round(close + 0.01, 3) for close in closes],
                            "low": [round(close - 0.01, 3) for close in closes], "spread_points": 0.0})
    cost_model = CostModel(commission_per_lot_round_turn=commission).with_instrument(assumed_instrument_for_bars("USDJPY", candles))
    candidate = TradeCandidate(timestamp=timestamps[1], symbol="USDJPY", direction=Direction.BUY, sl_price=149.5, tp_price=150.5, lot=1.0)
    trade = Backtester(BacktestSettings(cost_model=cost_model)).run(candles, [candidate]).trades[0]
    assert (trade.entry_price, trade.exit_price, trade.exit_reason) == (150.02, 150.5, "TP")
    usd_per_tick = 100.0 / 150.0  # 0.001 JPY on 100,000 USD at the first close
    ticks, risk_ticks = 480, 520  # 0.48 JPY gained, 0.52 JPY to the stop
    assert trade.tick_value == pytest.approx(usd_per_tick)
    # 320.00 USD before commission; the 1.0 placeholder reported 480.00.
    assert trade.profit == pytest.approx(ticks * usd_per_tick * 1.0 - commission)
    assert trade.r_multiple == pytest.approx((ticks * usd_per_tick - commission) / (risk_ticks * usd_per_tick))
    # R is unchanged without commission; a fixed USD commission per lot weighs
    # more on smaller USD amounts, so R is slightly lower with one.
    placeholder_r = (ticks * 1.0 - commission) / (risk_ticks * 1.0)
    if commission:
        assert trade.r_multiple < placeholder_r
    else:
        assert trade.r_multiple == pytest.approx(placeholder_r)


def test_walk_forward_window_prices_usdjpy_at_its_first_close() -> None:
    candles = _candles(150.0, step=0.005, digits=3)
    outcome = _run_param_backtest(candles, "USDJPY", {})
    assert outcome.settings.cost_model.tick_value == pytest.approx(100.0 / float(candles["close"].iloc[0]))
    with pytest.raises(InstrumentError):
        _run_param_backtest(_candles(160.0, step=0.005, digits=3), "EURJPY", {})


def test_backtest_batch_prices_assumed_usdjpy_from_its_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    candles = _candles(150.0, step=0.005, digits=3)
    _write_csv(data_dir, "USDJPY", candles)
    used: dict[str, float] = {}
    original = backtester.run_strategy_backtest

    def capture(*args, **kwargs):
        used[kwargs["symbol"]] = kwargs["instrument"].tick_value
        return original(*args, **kwargs)

    monkeypatch.setattr(backtester, "run_strategy_backtest", capture)
    result = run_backtest_for_symbols(data_dir=data_dir, symbols=("USDJPY",), report_dir=tmp_path / "reports")
    assert result.summary["instrument_metadata_assumed"] is True
    assert used["USDJPY"] == pytest.approx(100.0 / float(candles["close"].iloc[0]))


def test_backtest_batch_reads_each_history_in_turn_and_hashes_the_specs_it_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    histories = {"EURUSD": _candles(1.1, step=0.00005, digits=5), "USDJPY": _candles(150.0, step=0.005, digits=3)}
    for symbol, candles in histories.items():
        _write_csv(data_dir, symbol, candles)
    events: list[tuple[str, str]] = []
    original_load, original_run = backtester.load_historical_csv, backtester.run_strategy_backtest

    def load(*args, **kwargs):
        events.append(("load", kwargs["symbol"]))
        return original_load(*args, **kwargs)

    def run(*args, **kwargs):
        events.append(("run", kwargs["symbol"]))
        return original_run(*args, **kwargs)

    monkeypatch.setattr(backtester, "load_historical_csv", load)
    monkeypatch.setattr(backtester, "run_strategy_backtest", run)
    result = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD", "USDJPY"))
    # One history at a time, as before tick values were derived from the data.
    assert events == [("load", "EURUSD"), ("run", "EURUSD"), ("load", "USDJPY"), ("run", "USDJPY")]
    expected, _ = resolve_registry(symbols=list(histories), reference_prices={symbol: float(candles["close"].iloc[0]) for symbol, candles in histories.items()})
    assert result.summary["run_manifest"]["instrument_metadata_hash"] == instrument_metadata_hash(expected)
    assert result.summary["instrument_metadata_source"] == ASSUMED_SOURCE


def test_backtest_batch_refuses_assumed_crosses(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _write_csv(data_dir, "EURJPY", _candles(160.0, step=0.005, digits=3))
    with pytest.raises(InstrumentError):
        run_backtest_for_symbols(data_dir=data_dir, symbols=("EURJPY",), report_dir=tmp_path / "reports")


def test_strict_backtest_refuses_symbols_missing_from_the_sidecar(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _write_csv(data_dir, "EURUSD", _candles(1.1, step=0.00005, digits=5))
    _write_csv(data_dir, "GBPUSD", _candles(1.27, step=0.00005, digits=5))
    (data_dir / "instruments.json").write_text(json.dumps({"EURUSD": EURUSD_VALUES}), encoding="utf-8")
    with pytest.raises(InstrumentError):
        run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD", "GBPUSD"), report_dir=tmp_path / "strict", allow_assumed_instruments=False)
    # Allowed, the assumed symbol is declared instead of hiding behind the sidecar label.
    allowed = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD", "GBPUSD"), report_dir=tmp_path / "allowed")
    assert allowed.summary["instrument_metadata_source"].startswith("dataset:")
    assert allowed.summary["instrument_metadata_assumed"] is True


# --------------------------------------------------------------------------- paper PnL and audits


def _paper_trade(symbol: str, entry: float, exit_price: float, **extra: object) -> dict[str, object]:
    return {"symbol": symbol, "direction": "BUY", "entry_price": entry, "exit_price": exit_price, "lot": 1.0, **extra}


def test_paper_pnl_without_tick_value_converts_usdjpy_at_the_exit_price() -> None:
    pnl = calculate_raw_pnl(_paper_trade("USDJPY", 150.000, 150.500))
    # 0.5 JPY on 100,000 USD is 50,000 JPY, converted at the exit rate.
    assert pnl == pytest.approx(50_000.0 / 150.5)
    assert pnl != pytest.approx(500.0)
    assert calculate_raw_pnl(_paper_trade("EURUSD", 1.1000, 1.1010)) == pytest.approx(100.0)


def test_paper_pnl_keeps_the_broker_tick_value() -> None:
    contract = {"tick_size": 0.001, "tick_value": 0.6612}
    assert calculate_raw_pnl(_paper_trade("USDJPY", 150.000, 150.500), symbol_contract=contract) == pytest.approx(500 * 0.6612)


@pytest.mark.parametrize("trade", [
    _paper_trade("EURJPY", 160.000, 160.500),
    _paper_trade("USDJPY", 150.000, 150.500, tick_value=-1.0),
    _paper_trade("USDJPY", 150.000, 150.500, tick_value="unknown"),
])
def test_paper_pnl_fails_closed_without_a_usable_tick_value(trade: dict[str, object]) -> None:
    with pytest.raises(InstrumentError):
        calculate_raw_pnl(trade)


def test_pnl_formula_audit_derives_or_flags_tick_value() -> None:
    trades = [
        {"trade_id": "jpy", "volume": 1.0, "reported_profit": 50_000.0 / 150.5, **_paper_trade("USDJPY", 150.000, 150.500)},
        {"trade_id": "cross", "volume": 1.0, "reported_profit": 300.0, **_paper_trade("EURJPY", 160.000, 160.500)},
    ]
    contracts = audit_symbol_contracts(trades)
    assert all(row["tick_value"] is None for row in contracts)
    rows = {row["trade_id"]: row for row in audit_pnl_formulas(trades, contracts)}
    assert rows["jpy"]["pnl_with_tick_value"] == pytest.approx(50_000.0 / 150.5)
    assert "TICK_VALUE_UNAVAILABLE" not in rows["jpy"]["audit_flags"]
    assert rows["cross"]["pnl_with_tick_value"] is None
    assert "TICK_VALUE_UNAVAILABLE" in rows["cross"]["audit_flags"]


UNVALUED = [{"audit_flags": "TICK_VALUE_UNAVAILABLE"}]


@pytest.mark.parametrize("drawdown_flags,scaling", [
    ([], {"multiplier_application_ready": True}),
    ([], {"multiplier_application_ready": True, "legacy_unscaled_trade_count": 2}),
    (["DRAWDOWN_HISTORY_LEAK"], {}),
    (["DRAWDOWN_TRIGGER_VALID"], {"multiplier_application_ready": True}),
])
def test_paper_pnl_status_never_clears_a_trade_it_could_not_value(drawdown_flags: list[str], scaling: dict[str, object]) -> None:
    status, root_cause = _status(UNVALUED, {}, {"trigger_flags": drawdown_flags}, scaling)
    assert (status, root_cause) == ("PAPER_PNL_AUDIT_INCONCLUSIVE", "TICK_VALUE_UNAVAILABLE")
    assert _recommended_action(status, root_cause) == "KEEP_BLOCKED"
    # Every trade valued: the same inputs still reach their usual statuses.
    valued = _status([{"audit_flags": ""}], {}, {"trigger_flags": drawdown_flags}, scaling)
    assert valued[0] in {"PAPER_PNL_SCALING_FIXED", "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS", "DRAWDOWN_HISTORY_LEAK"}


def test_paper_pnl_status_still_names_a_proven_formula_bug_next_to_an_unvalued_trade() -> None:
    formulas = [*UNVALUED, {"audit_flags": "PNL_SIGN_ERROR"}]
    assert _status(formulas, {}, {"trigger_flags": []}, {"multiplier_application_ready": True}) == ("PAPER_PNL_SCALING_BUG", "PNL_SIGN_ERROR")


def test_paper_pnl_audit_keeps_an_unvaluable_trade_blocked_end_to_end(tmp_path: Path) -> None:
    profile = tmp_path / "paper_risk" / "balanced_stable_micro.ini"
    profile.parent.mkdir(parents=True)
    profile.write_text("SIGNAL_PROFILE=BALANCED_STABLE_MICRO\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\nPAPER_RISK_MULTIPLIER=0.1\n", encoding="utf-8")
    database = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        # A legacy (unscaled) trade is recomputed by the formula audit; a cross has no tick value to derive.
        database.insert_paper_trade({
            "paper_trade_id": "cross", "signal_id": "sig_cross", "idempotency_key": "paper:cross", "symbol": "EURJPY",
            "status": "CLOSED", "entry_time_utc": NOW.isoformat(), "exit_time_utc": NOW.isoformat(), "direction": "BUY",
            "entry_price": 160.0, "exit_price": 160.5, "sl_price": 159.5, "tp_price": 161.5, "lot": 0.1, "profit": 31.0,
            "commission_assumed": 0.0, "metadata": {"profile": "BALANCED_STABLE_MICRO", "paper_risk_multiplier": 0.1},
        })
        summary = run_paper_pnl_audit(database=database, log_dir=tmp_path / "logs", reports_root=tmp_path / "reports",
                                      paper_risk_dir=profile.parent, daily_risk_dir=tmp_path / "daily",
                                      profile_config=profile, output_dir=tmp_path / "audit")
    finally:
        database.close()
    # Before, the ready multiplier alone made this PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS,
    # recommended READY_FOR_NEW_MICRO_CLEARANCE.
    assert summary["current_engine_multiplier_ready"] is True
    assert summary["legacy_unscaled_trade_count"] == 1
    assert (summary["paper_pnl_audit_status"], summary["root_cause"]) == ("PAPER_PNL_AUDIT_INCONCLUSIVE", "TICK_VALUE_UNAVAILABLE")
    assert summary["recommended_action"] == "KEEP_BLOCKED"
    recommendation = run_paper_risk_recommendation(reports_root=tmp_path / "reports", pnl_audit_dir=tmp_path / "audit", output_dir=tmp_path / "audit")
    assert recommendation["whether_new_clearance_allowed"] is False
    assert recommendation["recommendation"] == "KEEP_BLOCKED"


def test_open_trade_audit_reports_unvaluable_pnl_as_an_issue() -> None:
    dataset = {"paper_trades": [
        {"paper_trade_id": "cross", "symbol": "EURJPY", "status": "OPEN", "direction": "BUY", "entry_price": 160.0,
         "current_price": 160.5, "sl_price": 159.5, "tp_price": 161.0, "volume": 1.0, "opened_at_utc": NOW.isoformat()},
    ], "events": []}
    lifecycle = audit_open_trade_lifecycle(dataset, profile_config="missing.ini", now_utc=NOW)
    assert lifecycle["open_trades"][0]["pnl_tick_value_unavailable"] is True
    readiness = audit_pnl_readiness(lifecycle, {})
    assert readiness["pnl_readiness_status"] == "PNL_READINESS_ISSUE"
    assert {"trade_id": "cross", "issue": "PNL_TICK_VALUE_UNAVAILABLE"} in readiness["pnl_issue_rows"]


# --------------------------------------------------------------------------- calibration


def test_signal_frequency_refuses_a_cross_once_and_prices_usdjpy(tmp_path: Path) -> None:
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    for symbol, base in (("EURJPY", 160.0), ("USDJPY", 150.0)):
        rows = []
        for index in range(1200):
            price = round(base + (index % 50) * 0.001, 3)
            rows.append({"time": (start + pd.Timedelta(minutes=5 * index)).isoformat(), "open": price,
                         "high": round(price + 0.02, 3), "low": round(price - 0.02, 3),
                         "close": round(price + 0.003, 3), "tick_volume": 100 + index, "spread": 8})
        pd.DataFrame(rows).to_csv(tmp_path / f"{symbol}_M5.csv", index=False)
    summary = analyze_signal_frequency(symbols=("EURJPY", "USDJPY"), data_dir=tmp_path, profile=get_signal_profile("BALANCED"), max_rows_per_symbol=5)
    cross = [record for record in summary["records"] if record["symbol"] == "EURJPY"]
    # One record for the symbol, not one analysis error per sampled row.
    assert len(cross) == 1 and cross[0]["raw_blocking_reason"].startswith("INSTRUMENT_METADATA_UNAVAILABLE")
    assert cross[0]["required_data_missing"] is True
    usdjpy = [record for record in summary["records"] if record["symbol"] == "USDJPY"]
    assert usdjpy
    assert not any(str(record["raw_blocking_reason"]).startswith(("INSTRUMENT_METADATA_UNAVAILABLE", "analysis error")) for record in usdjpy)

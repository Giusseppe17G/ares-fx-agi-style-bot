from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.contracts import AccountState, Direction, EntryType, MarketSnapshot, RiskDecision, TradeSignal, utc_now
from agi_style_forex_bot_mt5.execution_simulation import CommissionModel, FillModel, SlippageModel, SpreadModel, compare_paper_vs_backtest
from agi_style_forex_bot_mt5.paper_trading import PaperPositionManager
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _snapshot(*, spread: float = 10, timestamp=None) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EURUSD",
        timeframe="M5",
        timestamp_utc=timestamp or utc_now(),
        bid=1.1000,
        ask=1.1000 + spread * 0.00001,
        spread_points=spread,
        digits=5,
        point=0.00001,
        tick_value=1.0,
        tick_size=0.00001,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        stops_level_points=10,
        freeze_level_points=5,
    )


def test_fill_model_uses_bid_ask_for_entries_and_exits() -> None:
    snapshot = _snapshot()
    model = FillModel(slippage_model=SlippageModel(fixed_points=0))

    assert model.market_entry(direction="BUY", snapshot=snapshot).fill_price == snapshot.ask
    assert model.market_entry(direction="SELL", snapshot=snapshot).fill_price == snapshot.bid
    assert model.market_exit(direction="BUY", snapshot=snapshot).fill_price == snapshot.bid
    assert model.market_exit(direction="SELL", snapshot=snapshot).fill_price == snapshot.ask


def test_fill_model_rejects_extreme_spread_and_stale_tick() -> None:
    model = FillModel(max_spread_points=25, max_tick_age_seconds=60)
    spread = model.market_entry(direction="BUY", snapshot=_snapshot(spread=40))
    stale = model.market_entry(direction="BUY", snapshot=_snapshot(timestamp=utc_now() - timedelta(minutes=5)))

    assert spread.accepted is False
    assert spread.reject_code == "SPREAD_EXTREME"
    assert stale.accepted is False
    assert stale.reject_code == "TICK_STALE"


def test_slippage_adverse_and_commission_model() -> None:
    snapshot = _snapshot()
    model = FillModel(slippage_model=SlippageModel(fixed_points=2), commission_model=CommissionModel(round_turn_per_lot=7.0))
    buy_entry = model.market_entry(direction="BUY", snapshot=snapshot, lot=0.5)
    sell_exit = model.market_exit(direction="SELL", snapshot=snapshot, lot=0.5)

    assert buy_entry.fill_price > snapshot.ask
    assert sell_exit.fill_price > snapshot.ask
    assert buy_entry.commission == 3.5


def test_same_bar_conservative_and_gap_through_sl() -> None:
    model = FillModel()
    same_bar = model.resolve_bar_exit(direction="BUY", open_price=1.1000, high=1.1200, low=1.0900, sl=1.0950, tp=1.1150, mode="conservative")
    gap = model.resolve_bar_exit(direction="BUY", open_price=1.0900, high=1.1000, low=1.0850, sl=1.0950, tp=1.1150)

    assert same_bar is not None
    assert same_bar["exit_reason"] == "SL"
    assert same_bar["ambiguous"] is True
    assert gap is not None
    assert gap["exit_reason"] == "GAP_THROUGH_SL"
    assert gap["exit_price"] < 1.0950


def test_spread_model_uses_p95_fallback() -> None:
    profile = {"symbols": {"EURUSD": {"spread_p95": 18, "spread_p99": 25, "spread_median": 9}}}
    estimate = SpreadModel(max_spread_points=30, broker_cost_profile=profile).estimate(symbol="EURUSD")

    assert estimate.current_spread is None
    assert estimate.p95_spread == 18
    assert estimate.trade_allowed_by_spread is True


def test_paper_trade_metadata_includes_fill_assumptions(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        manager = PaperPositionManager(database=db)
        signal = TradeSignal(
            signal_id="sig_1",
            created_at_utc=utc_now(),
            symbol="EURUSD",
            timeframe="M5",
            direction=Direction.BUY,
            entry_type=EntryType.MARKET,
            sl_price=1.0950,
            tp_price=1.1150,
            risk_pct=0.5,
        )
        decision = RiskDecision(signal_id="sig_1", accepted=True, approved_lot=0.1, risk_amount_account_currency=10)
        trade = manager.open_trade(signal=signal, risk_decision=decision, snapshot=_snapshot(), broker_symbol="EURUSD", score=80, reasons=("test",), strategy_name="strategy", strategy_version="1", regime="TREND_UP", session="LONDON")

        assert trade.metadata["execution_simulation_version"]
        assert trade.metadata["spread_model_used"]
        assert trade.metadata["slippage_model_used"]
        assert trade.metadata["commission_model_used"]
        assert trade.metadata["latency_assumption"]
        assert trade.metadata["fill_quality"] in {"GOOD", "ACCEPTABLE", "POOR"}
    finally:
        db.close()


def test_paper_vs_backtest_detects_optimistic_backtest(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    (reports_root / "backtests").mkdir(parents=True)
    (reports_root / "backtests" / "summary.json").write_text('{"expectancy_r":0.4,"winrate":60,"assumed_spread_points":5}', encoding="utf-8")
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        for index in range(20):
            trade = {
                "paper_trade_id": f"ptr_{index}",
                "signal_id": f"sig_{index}",
                "idempotency_key": f"paper:{index}",
                "symbol": "EURUSD",
                "broker_symbol": "EURUSD",
                "direction": "BUY",
                "entry_time_utc": utc_now().isoformat(),
                "entry_price": 1.1,
                "sl_price": 1.09,
                "tp_price": 1.12,
                "lot": 0.1,
                "risk_pct": 0.5,
                "risk_amount": 10,
                "strategy_name": "strategy",
                "strategy_version": "1",
                "regime": "TREND_UP",
                "session": "LONDON",
                "score": 80,
                "reasons": ("test",),
                "status": "CLOSED",
                "exit_time_utc": utc_now().isoformat(),
                "profit": -10,
                "r_multiple": -1,
                "spread_at_entry": 10,
            }
            db.insert_paper_trade(trade)
        report = compare_paper_vs_backtest(database=db, reports_root=reports_root, output_dir=tmp_path / "paper_vs_backtest")
        assert report["classification"] in {"BACKTEST_TOO_OPTIMISTIC", "COST_ASSUMPTION_TOO_LOW"}
        assert report["execution_attempted"] is False
    finally:
        db.close()


def test_cli_modes_and_telegram_fills(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "run_simulation_calibration", lambda **_kwargs: {"mode": "simulation-calibration", "classification": "NEEDS_MORE_FORWARD_DATA", "reports_created": [], "execution_attempted": False})
    monkeypatch.setattr(cli, "compare_paper_vs_backtest", lambda **_kwargs: {"mode": "paper-vs-backtest", "classification": "NEEDS_MORE_FORWARD_DATA", "reports_created": [], "execution_attempted": False})
    sqlite_path = tmp_path / "cli.sqlite3"
    assert cli.main(["--mode", "simulation-calibration", "--sqlite", str(sqlite_path), "--reports-root", str(tmp_path), "--output-dir", str(tmp_path / "sim")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "paper-vs-backtest", "--sqlite", str(sqlite_path), "--reports-root", str(tmp_path), "--output-dir", str(tmp_path / "pvb")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

    from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter

    db = TelemetryDatabase(tmp_path / "tg.sqlite3")
    try:
        result = TelegramCommandCenter(database=db, allowed_chat_id="123").process_update({"message": {"chat": {"id": "123"}, "text": "/fills"}})
        assert result.accepted is True
        assert "execution_attempted" in result.response_text
    finally:
        db.close()


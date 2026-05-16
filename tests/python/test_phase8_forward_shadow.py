from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import Direction, EntryType, MarketSnapshot, RiskDecision, TradeSignal, utc_now
from agi_style_forex_bot_mt5.paper_trading import (
    ForwardShadowBot,
    PaperFillModel,
    PaperPositionManager,
    PaperTrade,
    detect_forward_drift,
    forward_summary_to_json,
    write_forward_shadow_report,
)
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelegramNotifier, TelemetryDatabase


def _snapshot(*, bid: float = 1.1000, ask: float = 1.1001, seconds: int = 0) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EURUSD",
        timeframe="EXECUTION",
        timestamp_utc=utc_now() + timedelta(seconds=seconds),
        bid=bid,
        ask=ask,
        spread_points=(ask - bid) / 0.00001,
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


def _signal(direction: Direction = Direction.BUY) -> TradeSignal:
    return TradeSignal(
        signal_id="sig_paper_1",
        created_at_utc=utc_now(),
        symbol="EURUSD",
        timeframe="M5",
        direction=direction,
        entry_type=EntryType.MARKET,
        sl_price=1.0980 if direction == Direction.BUY else 1.1020,
        tp_price=1.1040 if direction == Direction.BUY else 1.0960,
        risk_pct=0.5,
        confidence=0.8,
        strategy_name="strategy_ensemble",
    )


def _risk() -> RiskDecision:
    return RiskDecision(
        signal_id="sig_paper_1",
        accepted=True,
        approved_lot=0.1,
        risk_amount_account_currency=20.0,
    )


def _manager(tmp_path: Path, **kwargs) -> tuple[PaperPositionManager, TelemetryDatabase]:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    return PaperPositionManager(database=db, fill_model=PaperFillModel(slippage_points=0), **kwargs), db


def _open_trade(manager: PaperPositionManager) -> PaperTrade:
    return manager.open_trade(
        signal=_signal(),
        risk_decision=_risk(),
        snapshot=_snapshot(),
        broker_symbol="EURUSD",
        score=72,
        reasons=("test",),
        strategy_name="strategy_ensemble",
        strategy_version="0.1.0",
        regime="TREND_UP",
        session="LONDON",
    )


def test_paper_trade_serializes_roundtrip() -> None:
    trade = PaperTrade(
        paper_trade_id="ptr_1",
        signal_id="sig_1",
        idempotency_key="k",
        symbol="EURUSD",
        broker_symbol="EURUSD",
        direction="BUY",
        entry_time_utc=utc_now().isoformat(),
        entry_price=1.1,
        sl_price=1.09,
        tp_price=1.12,
        lot=0.1,
        risk_pct=0.5,
        risk_amount=10,
        strategy_name="s",
        strategy_version="1",
        regime="RANGE",
        session="LONDON",
        score=70,
        reasons=("ok",),
    )
    assert PaperTrade.from_json(trade.to_json()).paper_trade_id == "ptr_1"


def test_fill_model_uses_bid_ask_and_slippage() -> None:
    fill = PaperFillModel(slippage_points=2)
    snap = _snapshot(bid=1.1000, ask=1.1002)
    assert fill.entry_price(direction="BUY", snapshot=snap) == pytest.approx(1.10022)
    assert fill.entry_price(direction="SELL", snapshot=snap) == pytest.approx(1.09998)
    assert fill.exit_price(direction="BUY", snapshot=snap) == pytest.approx(1.09998)
    assert fill.exit_price(direction="SELL", snapshot=snap) == pytest.approx(1.10022)


def test_fill_model_rejects_extreme_spread() -> None:
    fill = PaperFillModel(max_spread_points=5, slippage_points=0)
    with pytest.raises(ValueError, match="spread exceeds maximum"):
        fill.entry_price(direction="BUY", snapshot=_snapshot(bid=1.1000, ask=1.1010))


def test_position_manager_opens_and_idempotency_blocks_duplicate(tmp_path: Path) -> None:
    manager, db = _manager(tmp_path)
    try:
        first = _open_trade(manager)
        second = _open_trade(manager)
        assert first.paper_trade_id == second.paper_trade_id
        assert db.count_rows("paper_trades") == 1
        assert len(manager.load_open_trades()) == 1
    finally:
        db.close()


def test_sqlite_persists_and_reloads_open_paper_trades(tmp_path: Path) -> None:
    manager, db = _manager(tmp_path)
    try:
        opened = _open_trade(manager)
    finally:
        db.close()

    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        reloaded = PaperPositionManager(database=db, fill_model=PaperFillModel(slippage_points=0)).load_open_trades()
        assert len(reloaded) == 1
        assert reloaded[0].paper_trade_id == opened.paper_trade_id
    finally:
        db.close()


def test_position_manager_closes_by_sl_and_tp(tmp_path: Path) -> None:
    manager, db = _manager(tmp_path)
    try:
        sl_trade = _open_trade(manager)
        closed_sl = manager.update_with_snapshot(sl_trade, _snapshot(bid=1.0979, ask=1.0980, seconds=10))
        assert closed_sl.status == "CLOSED"
        assert closed_sl.exit_reason == "SL"
    finally:
        db.close()

    manager, db = _manager(tmp_path / "tp")
    try:
        tp_trade = _open_trade(manager)
        closed_tp = manager.update_with_snapshot(tp_trade, _snapshot(bid=1.1041, ask=1.1042, seconds=10))
        assert closed_tp.status == "CLOSED"
        assert closed_tp.exit_reason == "TP"
    finally:
        db.close()


def test_break_even_and_trailing_never_retreat(tmp_path: Path) -> None:
    manager, db = _manager(tmp_path, trailing_distance_r=0.4)
    try:
        trade = _open_trade(manager)
        moved = manager.update_with_snapshot(trade, _snapshot(bid=1.1030, ask=1.1031, seconds=10))
        assert moved.sl_price >= trade.sl_price
        later = manager.update_with_snapshot(moved, _snapshot(bid=1.1025, ask=1.1026, seconds=20))
        assert later.sl_price >= moved.sl_price
    finally:
        db.close()


def test_time_stop_closes_trade(tmp_path: Path) -> None:
    manager, db = _manager(tmp_path, time_stop_seconds=1)
    try:
        trade = _open_trade(manager)
        closed = manager.update_with_snapshot(trade, _snapshot(bid=1.1002, ask=1.1003, seconds=5))
        assert closed.status == "CLOSED"
        assert closed.exit_reason == "TIME_STOP"
    finally:
        db.close()


def test_forward_report_and_drift_detector(tmp_path: Path) -> None:
    manager, db = _manager(tmp_path)
    try:
        trade = manager.close_trade(_open_trade(manager), _snapshot(bid=1.0979, ask=1.0980), "SL", 1.0980)
        files = write_forward_shadow_report([trade], tmp_path / "reports")
        drift = detect_forward_drift(
            forward={"closed_trades": 50, "expectancy_r": -0.2, "winrate": 30, "max_drawdown_shadow": -20},
            baseline={"expectancy_r": 0.2, "winrate": 55, "max_drawdown_pct": -5},
        )
        assert (tmp_path / "reports" / "summary.json").exists()
        assert files
        assert drift["classification"] in {"PERFORMANCE_DRIFT", "REJECT_STRATEGY"}
    finally:
        db.close()


def test_forward_shadow_no_order_send_and_telegram_failure_safe(tmp_path: Path) -> None:
    class FakeMT5:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def initialize(self):
            self.calls.append("initialize")
            return True

        def account_info(self):
            return SimpleNamespace(
                login=100,
                trade_mode=0,
                balance=10000.0,
                equity=10000.0,
                margin_free=9000.0,
                currency="USD",
                trade_allowed=True,
            )

        def symbol_info(self, symbol):
            return SimpleNamespace(name=symbol, visible=True, trade_mode=1, digits=5, point=0.00001, trade_tick_value=1, trade_tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, trade_stops_level=10, trade_freeze_level=5)

        def symbol_info_tick(self, symbol):
            now = int(utc_now().timestamp())
            return SimpleNamespace(bid=1.1000, ask=1.1001, time=now, time_msc=now * 1000)

        def last_error(self):
            return (0, "")

        def order_send(self, request):
            self.calls.append("order_send")
            raise AssertionError("order_send must not be called")

    def fail_sender(*_args, **_kwargs):
        raise RuntimeError("telegram down")

    db = TelemetryDatabase(tmp_path / "fwd.sqlite3")
    fake = FakeMT5()
    try:
        bot = ForwardShadowBot(
            config=BotConfig(),
            symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            database=db,
            telegram_notifier=TelegramNotifier(database=db, enabled=True, bot_token="123456:abcdefghijklmnopqrstuvwxyz", chat_id="123456", sender=fail_sender),
            mt5_client=fake,
            max_cycles=1,
            cycle_seconds=0,
            report_dir=str(tmp_path / "reports"),
        )
        summary = bot.run()
        assert summary.execution_attempted is False
        assert "order_send" not in fake.calls
        assert '"execution_attempted": false' in forward_summary_to_json(summary)
    finally:
        db.close()


def test_forward_shadow_cli_accepts_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    class FakeBot:
        def __init__(self, **_kwargs) -> None:
            pass

        def run(self):
            return SimpleNamespace(mode="forward-shadow", mt5_connected=False, cycles_completed=1, open_trades=0, paper_trades_opened=0, paper_trades_closed=0, execution_attempted=False)

    monkeypatch.setattr(cli, "ForwardShadowBot", FakeBot)
    code = cli.main(["--mode", "forward-shadow", "--sqlite", str(tmp_path / "f.sqlite3"), "--max-cycles", "1"])
    assert code == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

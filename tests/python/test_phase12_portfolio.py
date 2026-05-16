from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import SignalAction, StrategySignal, utc_now
from agi_style_forex_bot_mt5.ml.ml_filter import MLFilterDecision
from agi_style_forex_bot_mt5.portfolio import (
    DynamicRiskAllocator,
    PortfolioGuard,
    SignalRanker,
    calculate_currency_exposure,
    compute_correlation_matrix,
)
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def test_currency_exposure_buy_sell_and_usd_accumulation() -> None:
    exposure = calculate_currency_exposure(
        [
            {"symbol": "EURUSD", "direction": "BUY", "risk_pct": 0.5},
            {"symbol": "GBPUSD", "direction": "SELL", "risk_pct": 0.4},
            {"symbol": "USDJPY", "direction": "BUY", "risk_pct": 0.3},
        ]
    )

    assert exposure.net["EUR"] == 0.5
    assert exposure.net["GBP"] == -0.4
    assert round(exposure.net["USD"], 6) == 0.2
    assert round(exposure.gross["USD"], 6) == 1.2
    assert exposure.execution_attempted is False


def test_correlation_matrix_detects_high_correlation(tmp_path: Path) -> None:
    base = pd.DataFrame({"time": range(6), "close": [1, 2, 3, 4, 5, 6]})
    twin = pd.DataFrame({"time": range(6), "close": [2, 4, 6, 8, 10, 12]})
    base.to_csv(tmp_path / "EURUSD_M5.csv", index=False)
    twin.to_csv(tmp_path / "GBPUSD_M5.csv", index=False)

    report = compute_correlation_matrix(tmp_path, window=6)

    assert report["highly_correlated_pairs"]
    assert report["execution_attempted"] is False


def test_portfolio_guard_rejects_exposure_and_correlation() -> None:
    guard = PortfolioGuard(max_currency_exposure_pct=2.0, max_usd_exposure_pct=3.0)
    open_trades = [{"symbol": "EURUSD", "direction": "BUY", "risk_pct": 1.8}]

    exposure_decision = guard.evaluate(candidate={"symbol": "EURJPY", "direction": "BUY", "risk_pct": 0.5}, open_trades=open_trades)
    correlation_decision = guard.evaluate(candidate={"symbol": "GBPUSD", "direction": "BUY", "risk_pct": 0.2}, open_trades=[], correlation=0.9)

    assert exposure_decision.accepted is False
    assert exposure_decision.reject_code == "CURRENCY_EXPOSURE_HIGH"
    assert correlation_decision.accepted is False
    assert correlation_decision.reject_code == "CORRELATION_CLUSTER_HIGH"


def test_dynamic_risk_reduces_and_never_exceeds_one() -> None:
    allocator = DynamicRiskAllocator()

    dd = allocator.allocate({"drawdown_pct": 3.5})
    losses = allocator.allocate({"consecutive_losses": 3})
    clean = allocator.allocate({"ml_probability": 0.9})

    assert dd.risk_multiplier == 0.5
    assert losses.risk_multiplier == 0.25
    assert clean.risk_multiplier <= 1.0
    assert clean.execution_attempted is False


def test_signal_ranker_prioritizes_ml_probability_and_penalizes_spread() -> None:
    ranked = SignalRanker().rank(
        [
            {"symbol": "EURUSD", "ml_probability": 0.7, "strategy_score": 70, "spread_percentile": 90},
            {"symbol": "GBPUSD", "ml_probability": 0.8, "strategy_score": 70, "spread_percentile": 10},
        ],
        top_n=1,
    )

    assert ranked[0]["symbol"] == "GBPUSD"
    assert ranked[0]["ranking_decision"] == "ACCEPT_TOP_N"
    assert ranked[1]["ranking_decision"] == "REJECT_LOW_RANK"


def test_forward_shadow_audits_portfolio_decision(monkeypatch, tmp_path: Path) -> None:
    import agi_style_forex_bot_mt5.paper_trading.forward_shadow_bot as fsb

    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO = 0

        def initialize(self):
            return True

        def account_info(self):
            return SimpleNamespace(login=1, trade_mode=0, balance=10000, equity=10000, margin_free=9000, currency="USD", trade_allowed=True)

        def symbol_info(self, symbol):
            return SimpleNamespace(name=symbol, visible=True, trade_mode=1, digits=5, point=0.00001, trade_tick_value=1, trade_tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, trade_stops_level=10, trade_freeze_level=5)

        def symbol_info_tick(self, symbol):
            now = int(utc_now().timestamp())
            return SimpleNamespace(bid=1.1000, ask=1.1001, time=now, time_msc=now * 1000)

        def last_error(self):
            return (0, "")

        def order_send(self, request):
            raise AssertionError("order_send must not be called")

    monkeypatch.setattr(fsb.MT5DataOnlyBot, "_read_timeframes", lambda self, *args, **kwargs: {"M5": object()})
    monkeypatch.setattr(fsb.MT5DataOnlyBot, "_features_from_bars", lambda self, *args, **kwargs: {"regime": "TREND_UP", "session": "LONDON", "atr": 0.001})
    monkeypatch.setattr(fsb, "evaluate_ensemble", lambda *_args, **_kwargs: StrategySignal(SignalAction.BUY, 82, ("ok",), "strategy_ensemble", {"atr": 0.001, "version": "test"}))
    monkeypatch.setattr(fsb.MLFilter, "load_latest_model", staticmethod(lambda: SimpleNamespace(approve_or_reject=lambda signal, features: MLFilterDecision("ML_DISABLED", None, None, None, None, None, 0.58, ("no model",)))))

    db = TelemetryDatabase(tmp_path / "fwd.sqlite3")
    try:
        bot = fsb.ForwardShadowBot(config=BotConfig(), symbols=("EURUSD",), audit_logger=JsonlAuditLogger(tmp_path / "logs"), database=db, mt5_client=FakeMT5(), max_cycles=1, cycle_seconds=0)
        summary = bot.run()
        events = [row["event_type"] for row in db.fetch_all("events")]
        assert summary.execution_attempted is False
        assert "PORTFOLIO_DECISION" in events
        assert "DYNAMIC_RISK_ADJUSTED" in events
    finally:
        db.close()


def test_cli_portfolio_modes_and_telegram(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "build_portfolio_status", lambda **_kwargs: {"mode": "portfolio-status", "portfolio_risk_pct": 0, "currency_exposure": {}, "concentration_flags": [], "reports_created": [], "execution_attempted": False})
    monkeypatch.setattr(cli, "build_exposure_report", lambda **_kwargs: {"mode": "exposure-report", "portfolio_risk_pct": 0, "currency_exposure": {}, "concentration_flags": [], "reports_created": [], "execution_attempted": False})
    monkeypatch.setattr(cli, "build_correlation_report", lambda **_kwargs: {"mode": "correlation-report", "portfolio_risk_pct": 0, "currency_exposure": {}, "concentration_flags": [], "reports_created": [], "execution_attempted": False})

    assert cli.main(["--mode", "portfolio-status", "--sqlite", str(tmp_path / "p.sqlite3"), "--reports-root", str(tmp_path / "reports")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "exposure-report", "--sqlite", str(tmp_path / "e.sqlite3"), "--output-dir", str(tmp_path / "portfolio")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "correlation-report", "--data-dir", str(tmp_path), "--output-dir", str(tmp_path / "portfolio")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

    from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter

    db = TelemetryDatabase(tmp_path / "tg.sqlite3")
    try:
        result = TelegramCommandCenter(database=db, allowed_chat_id="123").process_update({"message": {"chat": {"id": "123"}, "text": "/portfolio"}})
        assert result.accepted is True
        assert "portfolio_risk_pct" in result.response_text
    finally:
        db.close()


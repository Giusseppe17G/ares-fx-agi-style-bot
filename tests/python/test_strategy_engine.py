from agi_style_forex_bot_mt5.contracts import MarketSnapshot, Regime, SignalAction, utc_now
from agi_style_forex_bot_mt5.strategy import PromotionEvidence, evaluate_ensemble


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EURUSD",
        timeframe="M5",
        timestamp_utc=utc_now(),
        bid=1.10000,
        ask=1.10010,
        spread_points=10,
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


def test_strategy_ensemble_returns_buy_in_shadow_mode() -> None:
    signal = evaluate_ensemble(
        _snapshot(),
        {
            "regime": Regime.TREND_UP,
            "close": 1.10120,
            "previous_close": 1.10080,
            "ema_fast": 1.10130,
            "ema_slow": 1.10030,
            "trend_slope": 0.00030,
            "rsi": 48,
            "atr_points": 18,
            "session": "LONDON",
            "momentum_points": 12,
            "range_points": 25,
            "body_ratio": 0.62,
            "prior_high": 1.10100,
            "atr_mean_points": 12,
        },
    )

    assert signal.action == SignalAction.BUY
    assert 0 <= signal.score <= 100
    assert signal.reasons
    assert signal.metadata["mode"] == "shadow"


def test_strategy_ensemble_returns_sell_in_shadow_mode() -> None:
    signal = evaluate_ensemble(
        _snapshot(),
        {
            "regime": Regime.TREND_DOWN,
            "close": 1.09880,
            "previous_close": 1.09920,
            "ema_fast": 1.09870,
            "ema_slow": 1.09970,
            "trend_slope": -0.00030,
            "rsi": 54,
            "atr_points": 18,
            "session": "NEW_YORK",
            "momentum_points": -12,
            "range_points": 25,
            "body_ratio": 0.64,
            "prior_low": 1.09900,
            "atr_mean_points": 12,
        },
    )

    assert signal.action == SignalAction.SELL
    assert 0 <= signal.score <= 100
    assert signal.reasons


def test_strategy_ensemble_returns_none_when_data_is_unsafe_or_weak() -> None:
    signal = evaluate_ensemble(
        _snapshot(),
        {
            "regime": Regime.SPREAD_DANGER,
            "close": 1.10005,
            "rsi": 50,
            "spread_points": 40,
        },
    )

    assert signal.action == SignalAction.NONE
    assert signal.score == 0
    assert "regime blocks strategy" in signal.reasons[0]


def test_demo_mode_fails_closed_without_promotion_evidence() -> None:
    signal = evaluate_ensemble(
        _snapshot(),
        {
            "regime": Regime.TREND_UP,
            "close": 1.10120,
            "previous_close": 1.10080,
            "ema_fast": 1.10130,
            "ema_slow": 1.10030,
            "trend_slope": 0.00030,
            "rsi": 48,
            "atr_points": 18,
        },
        mode="demo",
    )

    assert signal.action == SignalAction.NONE
    assert signal.score == 0
    assert signal.metadata["promotion_gate"]["approved"] is False


def test_demo_mode_can_emit_candidate_after_promotion_gate_passes() -> None:
    # The cumulative gate (docs/decisions/2026-10-22-deflated-promotion-gate.md)
    # also needs shadow approval (>= 300 trades, PF > 1.25), Phase 8 forward
    # evidence and deflated statistics; the old 260 trades at PF 1.25 no longer pass.
    returns = tuple(1.5 if index % 5 < 3 else -1.0 for index in range(400))
    evidence = PromotionEvidence(
        historical_trades=400,
        oos_profit_factor=1.40,
        oos_expected_payoff=2.5,
        oos_max_drawdown_pct=4.0,
        max_drawdown_limit_pct=6.0,
        max_profit_concentration_pct=35.0,
        spread_slippage_sensitivity_passed=True,
        walk_forward_passed=True,
        optimization_used=True,
        shadow_signals=35,
        shadow_days=15,
        shadow_audit_complete=True,
        shadow_approval_classification="APPROVED_FOR_SHADOW_OBSERVATION",
        oos_expectancy_r=0.2,
        forward_paper_trades=210,
        forward_profit_factor=1.2,
        forward_expectancy_r=0.1,
        forward_controls_passed=True,
        return_sequence=returns,
        trials=1,
        pbo=0.05,
    )
    signal = evaluate_ensemble(
        _snapshot(),
        {
            "regime": Regime.TREND_UP,
            "close": 1.10120,
            "previous_close": 1.10080,
            "ema_fast": 1.10130,
            "ema_slow": 1.10030,
            "trend_slope": 0.00030,
            "rsi": 48,
            "atr_points": 18,
            "session": "LONDON",
            "momentum_points": 12,
            "range_points": 25,
            "body_ratio": 0.62,
        },
        mode="demo",
        promotion_evidence=evidence,
    )

    assert signal.action == SignalAction.BUY
    assert signal.metadata["mode"] == "demo"
    assert signal.metadata["promotion_gate"]["approved"] is True

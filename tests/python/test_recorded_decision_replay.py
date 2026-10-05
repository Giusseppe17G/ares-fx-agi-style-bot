"""Differential evidence for real forward/replay callers, never return parity."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from test_shared_decision_core import NOW, fixture
from agi_style_forex_bot_mt5.backtesting.decision_replay import RecordedDecision, replay_decisions
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.decision import SharedDecisionPipeline, build_trade_signal
from agi_style_forex_bot_mt5.ml import MLFilter
from agi_style_forex_bot_mt5.paper_risk_calibration import evaluate_paper_trade_limits
from agi_style_forex_bot_mt5.paper_risk_calibration.paper_trade_limit_policy import PaperRiskLimits
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.portfolio import DynamicRiskAllocator, PortfolioGuard, SignalRanker
from agi_style_forex_bot_mt5.risk import RiskEngine
from agi_style_forex_bot_mt5.strategy import evaluate_ensemble
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _strong_context(ctx):
    snapshot = replace(ctx.snapshot, ask=1.10005, spread_points=5)
    features = {**ctx.features,
        "close": 1.1012, "previous_close": 1.1008, "ema_fast": 1.1013,
        "ema_slow": 1.1003, "trend_slope": 0.0003, "rsi": 48,
        "atr_points": 18, "momentum_points": 12, "range_points": 25,
        "body_ratio": 0.62, "prior_high": 1.101, "atr_mean_points": 12,
        "trend_structure": "UP", "spread_points": 5,
        "broker_readiness_score": 80, "atr_percentile": 50,
        "risk_reward_score": 70, "portfolio_fit": 75,
    }
    return replace(ctx, snapshot=snapshot, features=features)


@pytest.fixture
def callers(fixture, tmp_path):
    original, _, _ = fixture
    ctx = _strong_context(original)
    forward_db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    replay_db = TelemetryDatabase(tmp_path / "replay.sqlite3")
    forward = ForwardShadowBot(config=ctx.config, symbols=("EURUSD",),
        audit_logger=JsonlAuditLogger(tmp_path / "forward-logs"), database=forward_db,
        clock=FrozenClock(NOW))
    forward.ml_filter = MLFilter(tmp_path / "forward-model")
    clock = FrozenClock(NOW)
    signal_log = tmp_path / "replay-signals.jsonl"
    result_log = tmp_path / "replay-results.jsonl"

    def persist_signal(signal, context):
        with signal_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"signal_id": signal.signal_id, "symbol": signal.symbol}) + "\n")
        return True

    def limits(context, now):
        cfg = context.config
        policy = PaperRiskLimits(profile=cfg.signal_profile, paper_risk_multiplier=cfg.paper_risk_multiplier,
            max_open_paper_trades=cfg.max_open_paper_trades, max_paper_trades_per_day=cfg.max_paper_trades_per_day,
            cooldown_after_loss_minutes=cfg.cooldown_after_loss_minutes,
            cooldown_after_drawdown_halt_minutes=cfg.cooldown_after_drawdown_halt_minutes,
            block_new_entries_after_daily_halt=cfg.block_new_entries_after_daily_halt,
            manual_resume_required=cfg.manual_resume_required)
        return evaluate_paper_trade_limits(database=replay_db, now=now, limits=policy)

    def persist_decision(decision):
        with result_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(decision.to_dict(), sort_keys=True) + "\n")
        return True

    pipeline = SharedDecisionPipeline(clock=clock, strategy_evaluator=evaluate_ensemble,
        signal_builder=build_trade_signal, risk_engine=RiskEngine(ctx.config),
        ml_filter=MLFilter(tmp_path / "replay-model"), signal_ranker=SignalRanker(),
        portfolio_guard=PortfolioGuard(), dynamic_risk_allocator=DynamicRiskAllocator(),
        persist_signal=persist_signal, paper_limit_evaluator=limits)
    yield ctx, forward, pipeline, clock, persist_decision, forward_db, signal_log, result_log
    forward_db.close()
    replay_db.close()


@pytest.mark.parametrize("case", ["accepted", "spread", "drawdown", "no_ml_policy", "ml_error", "correlation", "future"])
def test_actual_forward_and_recorded_replay_full_decision_traces_match(callers, case):
    ctx, forward, pipeline, clock, persist, forward_db, signal_log, result_log = callers
    if case == "spread":
        ctx = replace(ctx, snapshot=replace(ctx.snapshot, spread_points=30, ask=1.1003),
                      features={**ctx.features, "spread_points": 30})
    elif case == "drawdown":
        ctx = replace(ctx, account=replace(ctx.account, equity=9600))
    elif case == "no_ml_policy":
        config = replace(ctx.config, paper_allow_disabled_ml=False)
        ctx = replace(ctx, config=config, allow_disabled_ml=False)
        forward.config = config
        pipeline.risk_engine = RiskEngine(config)
    elif case == "ml_error":
        for instance in (forward.ml_filter, pipeline.ml_filter):
            instance.bundle = {"metadata": {"approved_for_shadow_filtering": True}, "model": object()}
        ctx = replace(ctx, ml_model_available_at_utc=NOW)
    elif case == "correlation":
        ctx = replace(ctx, correlation=0.9)
    elif case == "future":
        ctx = replace(ctx, features_available_at_utc=NOW + timedelta(microseconds=1))
    actual_forward = forward._evaluate_paper_decision(ctx)
    replay = replay_decisions((RecordedDecision(NOW, ctx),), pipeline=pipeline, clock=clock, persist_decision=persist)
    actual_replay = replay.decisions[0]
    assert actual_forward.to_dict() == actual_replay.to_dict()
    assert actual_forward.accepted is (case == "accepted"), actual_forward.to_dict()
    if case == "drawdown":
        assert actual_replay.reject_code == "DAILY_DRAWDOWN_LIMIT"
    elif case == "no_ml_policy":
        assert actual_replay.reject_code == "ML_DISABLED_NOT_ALLOWED"
    elif case == "ml_error":
        assert actual_replay.reject_code == "ML_ERROR"
    elif case == "correlation":
        assert actual_replay.reject_code == "REJECT_CORRELATED"
    elif case == "future":
        assert actual_replay.reject_code == "FUTURE_DATA"
    assert result_log.exists()
    assert any(row["event_type"] == "PAPER_DECISION_COMPLETED" for row in forward_db.fetch_all("events"))
    assert replay.audit_complete
    assert replay.scope == "RECORDED_DECISION_REPLAY"
    assert replay.full_pipeline_verified is replay.performance_verified is replay.execution_attempted is False


@pytest.mark.parametrize("failure", ["false", "exception"])
def test_replay_audit_failure_revokes_risk_and_stops_before_next_record(callers, failure):
    ctx, _, pipeline, clock, _, _, signal_log, _ = callers

    def reject_audit(decision):
        assert decision.accepted  # This fixture reached all real stages successfully.
        if failure == "exception":
            raise OSError("private-storage-path")
        return False

    replay = replay_decisions((RecordedDecision(NOW, ctx),
        RecordedDecision(NOW, replace(ctx, decision_id="must-not-run"))),
        pipeline=pipeline, clock=clock, persist_decision=reject_audit)
    assert not replay.audit_complete
    assert len(replay.decisions) == 1
    decision = replay.decisions[0]
    assert decision.reject_code == "DECISION_AUDIT_FAILED"
    assert not decision.accepted
    assert not decision.risk_decision.accepted
    assert decision.risk_decision.approved_lot == decision.risk_decision.risk_amount_account_currency == 0
    assert "must-not-run" not in signal_log.read_text()
    assert "private-storage-path" not in json.dumps(decision.to_dict())


def test_recorded_replay_enforces_order_and_identity(callers):
    ctx, _, pipeline, clock, persist, *_ = callers
    with pytest.raises(ValueError, match="chronological"):
        replay_decisions((RecordedDecision(NOW, ctx),
            RecordedDecision(NOW - timedelta(seconds=1), replace(ctx, decision_id="earlier"))),
            pipeline=pipeline, clock=clock, persist_decision=persist)
    with pytest.raises(ValueError, match="duplicate"):
        replay_decisions((RecordedDecision(NOW, ctx), RecordedDecision(NOW, ctx)),
                         pipeline=pipeline, clock=clock, persist_decision=persist)

"""Isolated decision fixtures; no terminal connection or trading side effects."""

import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from agi_style_forex_bot_mt5.calibration.decision_policy import COMPONENTS
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState, Direction, MarketSnapshot, PositionState, SignalAction, StrategySignal
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.decision import DecisionContext, SharedDecisionPipeline, build_trade_signal
from agi_style_forex_bot_mt5.core.decision.pipeline import STAGES
from agi_style_forex_bot_mt5.ml import MLFilter
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DataOnlyBot
from agi_style_forex_bot_mt5.paper_risk_calibration import evaluate_paper_trade_limits
from agi_style_forex_bot_mt5.portfolio import DynamicRiskAllocator, PortfolioGuard, SignalRanker
from agi_style_forex_bot_mt5.risk import RiskEngine, RiskRuntimeState
from agi_style_forex_bot_mt5.strategy import EnsembleConfig, evaluate_ensemble
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _strategy(snapshot, features, **kwargs):
    return StrategySignal(SignalAction.BUY, 90, ("fixture",), "fixture", {
        "component_scores": {key: 90 for key in COMPONENTS},
        "setup_quality_score": 90, "atr": 0.001, "version": "fixture-v1",
    })


@pytest.fixture
def fixture(tmp_path):
    config = BotConfig(paper_allow_disabled_ml=True)
    snapshot = MarketSnapshot("EURUSD", "M5", NOW, 1.1000, 1.1001, 10, 5,
                              0.00001, 1, 0.00001, 0.01, 100, 0.01, 0, 0)
    context = DecisionContext(
        decision_id="fixture-candidate", config=config, snapshot=snapshot,
        features={"regime": "TREND_UP", "session": "LONDON", "atr": 0.001, "spread_percentile": 40.0},
        features_available_at_utc=NOW, state_available_at_utc=NOW,
        account=AccountState(1, "DEMO", 10000, 10000, 9000, is_demo=True, trade_allowed=True),
        risk_state=RiskRuntimeState(daily_equity_reference=10000, floating_drawdown_reference=10000,
                                   open_positions=(), snapshots_by_symbol={}),
        open_trades=(), broker_symbol="EURUSD", broker_readiness_score=80,
        correlation=None, shadow_paused=False, consecutive_losses=0,
        allow_disabled_ml=True, ml_model_available_at_utc=None,
    )
    database = TelemetryDatabase(tmp_path / "isolated.sqlite3")
    audit = tmp_path / "signals.jsonl"

    def persist(signal, ctx):
        with audit.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"signal_id": signal.signal_id, "symbol": signal.symbol}) + "\n")
        return True

    pipeline = SharedDecisionPipeline(
        clock=FrozenClock(NOW), strategy_evaluator=_strategy,
        signal_builder=lambda ctx, strategy: MT5DataOnlyBot._trade_signal_from_strategy(
            SimpleNamespace(config=ctx.config), ctx.snapshot, strategy),
        risk_engine=RiskEngine(config), ml_filter=MLFilter(tmp_path / "absent-model"),
        signal_ranker=SignalRanker(), portfolio_guard=PortfolioGuard(),
        dynamic_risk_allocator=DynamicRiskAllocator(), persist_signal=persist,
        paper_limit_evaluator=lambda ctx, now: evaluate_paper_trade_limits(database=database, now=now),
    )
    yield context, pipeline, audit
    database.close()


def _trace(result, stage):
    return next(item for item in result.trace if item.stage_id == stage)


def test_real_components_match_direct_calls_and_signal_builder(fixture):
    ctx, pipeline, audit = fixture
    result = pipeline.evaluate(ctx)
    assert result.accepted, result.to_dict()
    direct_signal = pipeline.signal_builder(ctx, _strategy(ctx.snapshot, ctx.features))
    assert result.trade_signal == replace(direct_signal, signal_id=ctx.decision_id)
    direct_risk = pipeline.risk_engine.evaluate(
        signal=result.trade_signal, snapshot=ctx.snapshot, account=ctx.account,
        state=replace(ctx.risk_state, now_utc=NOW, audit_confirmed=True),
    )
    assert _trace(result, "risk_engine").payload == asdict(direct_risk)
    direct_ml = pipeline.ml_filter.approve_or_reject(result.trade_signal, {**ctx.features, "score": 90})
    assert _trace(result, "ml_filter").payload["ml_status"] == direct_ml.ml_status
    ranking = _trace(result, "signal_ranker").payload
    assert ranking == pipeline.signal_ranker.rank([ranking], top_n=1)[0]
    direct_portfolio = pipeline.portfolio_guard.evaluate(
        candidate=ranking, open_trades=ctx.open_trades, correlation=ctx.correlation,
        shadow_paused=ctx.shadow_paused, daily_drawdown_pct=0, consecutive_losses=0)
    assert _trace(result, "portfolio_guard").payload == asdict(direct_portfolio)
    dynamic = _trace(result, "dynamic_risk").payload
    assert dynamic["risk_multiplier"] == pipeline.dynamic_risk_allocator.allocate(dynamic["checks"]).risk_multiplier
    assert _trace(result, "paper_limits").payload == pipeline.paper_limit_evaluator(ctx, NOW)
    assert result.risk_decision.approved_lot == direct_risk.approved_lot
    assert audit.read_text().count("fixture-candidate") == 1
    assert all(item.status == "passed" for item in result.trace)


def test_repeat_is_deterministic_despite_existing_signal_builder_uuid(fixture):
    ctx, pipeline, _ = fixture
    assert pipeline.evaluate(ctx).to_dict() == pipeline.evaluate(ctx).to_dict()


def test_real_ensemble_delegation_and_no_signal_stops_downstream(fixture):
    ctx, pipeline, audit = fixture
    pipeline.strategy_evaluator = evaluate_ensemble
    ctx = replace(ctx, features={"regime": "SPREAD_DANGER", "session": "LONDON", "spread_percentile": 40.0})
    expected = evaluate_ensemble(ctx.snapshot, ctx.features, mode="shadow", config=EnsembleConfig(threshold=70))
    result = pipeline.evaluate(ctx)
    assert result.strategy_signal == expected
    assert result.reject_code == "NO_SIGNAL"
    assert [item.stage_id for item in result.trace] == list(STAGES)
    assert _trace(result, "risk_engine").status == "skipped"
    assert _trace(result, "risk_engine").reason == "blocked_by:strategy:NO_SIGNAL"
    assert not audit.exists()


@pytest.mark.parametrize("field", ["features_available_at_utc", "state_available_at_utc"])
def test_future_context_never_reaches_strategy(fixture, field):
    ctx, pipeline, audit = fixture
    result = pipeline.evaluate(replace(ctx, **{field: NOW + timedelta(microseconds=1)}))
    assert result.reject_code == "FUTURE_DATA"
    assert _trace(result, "strategy").status == "skipped"
    assert not audit.exists()


@pytest.mark.parametrize("age,accepted", [(0, True), (305, True), (305.000001, False), (30 * 86400, False)])
def test_feature_freshness_uses_timeframe_plus_snapshot_tolerance(fixture, age, accepted):
    ctx, pipeline, _ = fixture
    result = pipeline.evaluate(replace(ctx, features_available_at_utc=NOW - timedelta(seconds=age)))
    assert result.accepted is accepted
    if not accepted:
        assert result.reject_code == "STALE_FEATURES"
        assert _trace(result, "strategy").status == "skipped"


@pytest.mark.parametrize("metadata", [
    {"available_at_utc": (NOW - timedelta(seconds=1)).isoformat()},
    {"source_bar_timestamp_utc": (NOW - timedelta(minutes=10)).isoformat()},
    {"available_at_utc": NOW, "source_bar_timestamp_utc": NOW},
])
def test_conflicting_feature_time_evidence_rejects(fixture, metadata):
    ctx, pipeline, _ = fixture
    result = pipeline.evaluate(replace(ctx, features={**ctx.features, **metadata}))
    assert result.reject_code == "FEATURE_TEMPORAL_MISMATCH"
    assert _trace(result, "strategy").status == "skipped"


def test_matching_feature_time_evidence_and_unknown_duration(fixture):
    ctx, pipeline, _ = fixture
    ctx = replace(ctx, features={**ctx.features, "available_at_utc": NOW.isoformat(),
                                "source_bar_timestamp_utc": (NOW - timedelta(minutes=5)).isoformat()})
    assert pipeline.evaluate(ctx).accepted
    assert pipeline.evaluate(replace(ctx, snapshot=replace(ctx.snapshot, timeframe="UNKNOWN"))).reject_code == "FEATURE_TIMEFRAME_INVALID"


@pytest.mark.parametrize("change,code", [
    ({"state_available_at_utc": NOW - timedelta(seconds=6)}, "STALE_STATE"),
    ({"state_available_at_utc": NOW.replace(tzinfo=None)}, "TIMESTAMP_INVALID"),
    ({"broker_readiness_score": None}, "BROKER_QUALITY_UNVERIFIED"),
    ({"broker_readiness_score": float("nan")}, "BROKER_QUALITY_UNVERIFIED"),
    ({"open_trades": None}, "POSITION_STATE_MISSING"),
    ({"features": {}}, "FEATURE_CONTEXT_MISSING"),
    ({"shadow_paused": None}, "POLICY_STATE_INVALID"),
])
def test_missing_state_fails_closed(fixture, change, code):
    ctx, pipeline, _ = fixture
    result = pipeline.evaluate(replace(ctx, **change))
    assert result.reject_code == code
    assert result.risk_decision is None


@pytest.mark.parametrize("multiplier", [0.0, -1.0, float("nan"), 2.0])
def test_invalid_paper_multiplier_never_becomes_one(fixture, multiplier):
    ctx, pipeline, _ = fixture
    config = replace(ctx.config, paper_risk_multiplier=multiplier)
    pipeline.risk_engine = RiskEngine(config)
    result = pipeline.evaluate(replace(ctx, config=config))
    assert result.reject_code == "PAPER_RISK_INVALID"


def test_audit_failure_prevents_risk_and_marks_remaining_skipped(fixture):
    ctx, pipeline, _ = fixture
    pipeline.persist_signal = lambda signal, context: False
    result = pipeline.evaluate(ctx)
    assert result.reject_code == "SIGNAL_AUDIT_FAILED"
    assert result.risk_decision is None
    assert _trace(result, "risk_engine").status == "skipped"


@pytest.mark.parametrize("stage", ["strategy", "signal_audit", "paper_limits"])
def test_dependency_exceptions_are_closed_and_secret_text_not_logged(fixture, stage):
    ctx, pipeline, _ = fixture

    def fail(*args, **kwargs):
        raise RuntimeError("private-account-or-secret")

    setattr(pipeline, {"strategy": "strategy_evaluator", "signal_audit": "persist_signal", "paper_limits": "paper_limit_evaluator"}[stage], fail)
    result = pipeline.evaluate(ctx)
    assert result.reject_code == "DECISION_STAGE_ERROR"
    assert _trace(result, stage).status == "error"
    assert "private-account-or-secret" not in json.dumps(result.to_dict())
    if result.risk_decision:
        assert not result.risk_decision.accepted
        assert result.risk_decision.approved_lot == result.risk_decision.risk_amount_account_currency == 0


def test_missing_ml_requires_explicit_policy(fixture):
    ctx, pipeline, _ = fixture
    config = replace(ctx.config, paper_allow_disabled_ml=False)
    pipeline.risk_engine = RiskEngine(config)
    result = pipeline.evaluate(replace(ctx, config=config, allow_disabled_ml=False))
    assert result.reject_code == "ML_DISABLED_NOT_ALLOWED"
    assert result.risk_decision.approved_lot == 0


class ConstantProbability:
    def __init__(self, value):
        self.value = value

    def predict_proba(self, features):
        return np.array([self.value])

    def predict(self, values):
        return values


@pytest.mark.parametrize("available,code", [
    (None, "ML_PROVENANCE_MISSING"),
    (NOW + timedelta(microseconds=1), "ML_MODEL_FROM_FUTURE"),
    (NOW, ""),
])
def test_real_ml_filter_model_temporal_cutoff(fixture, available, code):
    ctx, pipeline, _ = fixture
    model = ConstantProbability(0.73)
    pipeline.ml_filter.bundle = {"metadata": {"approved_for_shadow_filtering": True}, "model": model, "calibrator": model}
    result = pipeline.evaluate(replace(ctx, ml_model_available_at_utc=available))
    assert result.reject_code == code, result.to_dict()
    assert result.accepted == (not code)


def test_real_ml_error_blocks_instead_of_bypassing_filter(fixture):
    ctx, pipeline, _ = fixture
    pipeline.ml_filter.bundle = {"metadata": {"approved_for_shadow_filtering": True}, "model": object()}
    result = pipeline.evaluate(replace(ctx, ml_model_available_at_utc=NOW))
    assert result.reject_code == "ML_ERROR"
    assert _trace(result, "signal_ranker").status == "skipped"


def test_risk_rejection_keeps_real_reason(fixture):
    ctx, pipeline, _ = fixture
    result = pipeline.evaluate(replace(ctx, account=replace(ctx.account, equity=9600)))
    assert result.reject_code == "DAILY_DRAWDOWN_LIMIT"
    assert result.risk_decision.approved_lot == 0
    assert _trace(result, "ml_filter").status == "skipped"


def test_risk_reduction_preserves_existing_exposure_and_broker_step(fixture):
    ctx, pipeline, _ = fixture
    config = replace(ctx.config, paper_risk_multiplier=0.15)
    pipeline.risk_engine = RiskEngine(config)
    existing = PositionState(2, "EURUSD", Direction.BUY, 0.50, 1.1001, 1.0991, 1.1021, 1)
    state = replace(ctx.risk_state, open_positions=(existing,), snapshots_by_symbol={"EURUSD": ctx.snapshot})
    row = {"symbol": "EURUSD", "direction": "BUY", "strategy_name": "existing", "regime": "TREND_UP", "risk_pct": 0.5}
    result = pipeline.evaluate(replace(ctx, config=config, risk_state=state, open_trades=(row,), correlation=0.2))
    assert result.accepted, result.to_dict()
    assert result.risk_decision.approved_lot == 0.07
    assert result.risk_decision.open_risk_pct_after_trade == pytest.approx(0.57)
    assert result.risk_decision.risk_amount_account_currency == pytest.approx(7)


def test_paper_limit_delegate_rejection_and_paper_only_output(fixture):
    ctx, pipeline, _ = fixture
    pipeline.paper_limit_evaluator = lambda c, now: {"can_open_new_paper_trade": False, "blocking_reason": "PAPER_COOLDOWN_BLOCK"}
    result = pipeline.evaluate(ctx)
    assert result.reject_code == "PAPER_COOLDOWN_BLOCK"
    payload = result.to_dict()
    assert payload["execution_authorized"] is False
    assert payload["decision_audit_required"] is True
    assert not any(payload[key] for key in ("execution_attempted", "order_send_called", "order_check_called", "live_trading_approved"))


def test_missing_profile_metadata_does_not_bypass_gate(fixture):
    ctx, pipeline, audit = fixture
    pipeline.strategy_evaluator = lambda *args, **kwargs: replace(_strategy(None, None), metadata={})
    result = pipeline.evaluate(ctx)
    assert result.reject_code == "PROFILE_THRESHOLD_BLOCK"
    assert _trace(result, "signal_audit").status == "skipped"
    assert not audit.exists()


def test_shared_signal_builder_uses_feature_atr_not_ensemble_metadata(fixture):
    ctx, _, _ = fixture
    ctx = replace(ctx, features={**ctx.features, "atr": 0.003})
    signal = build_trade_signal(ctx, _strategy(None, None))
    assert signal.sl_price == pytest.approx(1.0971)
    assert signal.tp_price == pytest.approx(1.1055)
    assert signal.signal_id == ctx.decision_id
    for atr in (None, 0, float("nan")):
        with pytest.raises(ValueError, match="ATR"):
            build_trade_signal(replace(ctx, features={**ctx.features, "atr": atr}), _strategy(None, None))


def test_live_forward_adapter_runs_shared_core_and_persists_decision(fixture, tmp_path, monkeypatch):
    from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
    from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger
    import agi_style_forex_bot_mt5.paper_trading.forward_shadow_bot as forward

    ctx, _, _ = fixture
    db = TelemetryDatabase(tmp_path / "forward-caller.sqlite3")
    try:
        bot = ForwardShadowBot(config=ctx.config, symbols=("EURUSD",),
            audit_logger=JsonlAuditLogger(tmp_path / "forward-audit"), database=db, clock=FrozenClock(NOW))
        bot.ml_filter = MLFilter(tmp_path / "forward-no-model")
        monkeypatch.setattr(forward, "evaluate_ensemble", _strategy)
        result = bot._evaluate_paper_decision(ctx)
        assert result.accepted, result.to_dict()
        events = db.fetch_all("events")
        kinds = [row["event_type"] for row in events]
        assert kinds.index("SIGNAL_GENERATED") < kinds.index("PAPER_DECISION_COMPLETED")
        assert "ML_PREDICTION" in kinds
        assert all(row["signal_id"] == ctx.decision_id for row in events)
        assert len({row["correlation_id"] for row in events}) == 1
        assert events[0]["correlation_id"] == f"{bot.run_id}:{ctx.decision_id}"
        assert db.count_rows("paper_trades") == 0  # only caller's later fill owns this mutation
        event = next(row for row in events if row["event_type"] == "PAPER_DECISION_COMPLETED")
        payload = json.loads(event["payload_json"])
        assert payload["accepted"] is True
        assert payload["timestamp_utc"] == NOW.isoformat()
        # A real MLFilter error must fail in the real forward adapter too.
        bot.ml_filter.bundle = {"metadata": {"approved_for_shadow_filtering": True}, "model": object()}
        rejected = bot._evaluate_paper_decision(replace(ctx, ml_model_available_at_utc=NOW))
        assert rejected.reject_code == "ML_ERROR"
        assert rejected.risk_decision.approved_lot == 0
        assert db.count_rows("paper_trades") == 0
        completed = [row for row in db.fetch_all("events") if row["event_type"] == "PAPER_DECISION_COMPLETED"]
        assert len(completed) == 2
        assert {json.loads(row["payload_json"])["accepted"] for row in completed} == {True, False}
        assert len({row["correlation_id"] for row in completed}) == 1
    finally:
        db.close()


def test_explicit_disabled_ml_config_defaults_and_ini(tmp_path):
    from agi_style_forex_bot_mt5.config import load_config

    assert BotConfig().paper_allow_disabled_ml is False
    path = tmp_path / "research.ini"
    path.write_text("PAPER_ALLOW_DISABLED_ML=True\n", encoding="utf-8")
    assert load_config(path).paper_allow_disabled_ml is True


def test_explicit_paper_limits_are_used_instead_of_micro_defaults(tmp_path):
    from agi_style_forex_bot_mt5.paper_risk_calibration.paper_trade_limit_policy import PaperRiskLimits

    db = TelemetryDatabase(tmp_path / "paper-limits.sqlite3")
    try:
        limits = PaperRiskLimits(profile="CONSERVATIVE", max_open_paper_trades=0, max_paper_trades_per_day=50)
        result = evaluate_paper_trade_limits(database=db, now=NOW, limits=limits)
        assert result["blocking_reason"] == "PAPER_MAX_OPEN_TRADES_BLOCK"
        assert result["limits"]["profile"] == "CONSERVATIVE"
        assert result["limits"]["max_paper_trades_per_day"] == 50
        with pytest.raises(ValueError, match="multiplier"):
            evaluate_paper_trade_limits(database=db, now=NOW, limits=replace(limits, paper_risk_multiplier=0))
    finally:
        db.close()


@pytest.mark.parametrize("profile", ["CONSERVATIVE", "BALANCED_STABLE"])
def test_forward_scan_uses_actual_shared_pipeline_and_paper_state(fixture, tmp_path, monkeypatch, profile):
    from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot, PaperFillModel
    from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger
    import agi_style_forex_bot_mt5.paper_trading.forward_shadow_bot as forward

    ctx, _, _ = fixture
    if profile == "BALANCED_STABLE":
        ctx = replace(ctx, config=replace(ctx.config, signal_profile=profile,
                      stability_filters_applied=True, paper_risk_multiplier=0.1))
    db = TelemetryDatabase(tmp_path / "scan.sqlite3")
    try:
        bot = ForwardShadowBot(config=ctx.config, symbols=("EURUSD",), database=db,
            audit_logger=JsonlAuditLogger(tmp_path / "scan-logs"), clock=FrozenClock(NOW),
            decision_evidence_provider=lambda snapshot, features, positions: {"observed_at_utc": bot.clock.now_utc(), "broker_readiness_score": 80, "correlation": 0.0})
        bot.ml_filter = MLFilter(tmp_path / "scan-no-model")
        bot.manager.fill_model = PaperFillModel(slippage_points=0, clock=bot.clock)
        resolution = SimpleNamespace(broker_symbol="EURUSD", canonical_symbol="EURUSD")
        bot.connector = SimpleNamespace(mt5=SimpleNamespace(terminal_info=lambda: SimpleNamespace(connected=True)), resolve_symbol=lambda symbol: (SimpleNamespace(accepted=True), resolution))
        monkeypatch.setattr(bot, "_snapshot_for", lambda *args: ctx.snapshot)
        monkeypatch.setattr(MT5DataOnlyBot, "_read_timeframes", lambda *args: {"M5": object()})
        monkeypatch.setattr(MT5DataOnlyBot, "_features_from_bars", lambda *args: {**ctx.features, "available_at_utc": ctx.snapshot.timestamp_utc})
        monkeypatch.setattr(forward, "evaluate_ensemble", _strategy)
        assert bot._scan_new_paper_trades(ctx.account) == 1
        assert db.count_rows("paper_trades") == 1
        payloads = [json.loads(row["payload_json"]) for row in db.fetch_all("events")]
        completed = [payload for payload in payloads if payload.get("scope") == "PAPER_DECISION_ONLY"]
        assert completed and completed[-1]["accepted"]
        # Repeated scans of a consumed candle stop before a changed book can
        # create a second intent. The next closed candle is evaluated normally.
        assert bot._scan_new_paper_trades(ctx.account) == 0
        assert any(row["event_type"] == "CANDIDATE_ALREADY_TRADED" for row in db.fetch_all("events"))
        later = NOW + timedelta(minutes=5)
        ctx = replace(ctx, snapshot=replace(ctx.snapshot, timestamp_utc=later))
        bot.clock.instant = later
        # Missing broker quality cannot be converted into an all-clear score.
        bot.decision_evidence_provider = None
        assert bot._scan_new_paper_trades(ctx.account) == 0
        assert db.count_rows("paper_trades") == 1
        payloads = [json.loads(row["payload_json"]) for row in db.fetch_all("events")]
        assert any(payload.get("reject_code") == "BROKER_EVIDENCE_MISSING" for payload in payloads)
    finally:
        db.close()


@pytest.mark.parametrize("refresh_fails", [False, True])
def test_forward_refreshes_risk_metrics_even_without_new_signals(fixture, tmp_path, monkeypatch, refresh_fails):
    from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
    from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger

    ctx, _, _ = fixture
    db = TelemetryDatabase(tmp_path / "metrics-loop.sqlite3")
    try:
        bot = ForwardShadowBot(config=ctx.config, symbols=("EURUSD",), database=db,
            audit_logger=JsonlAuditLogger(tmp_path / "metrics-logs"), clock=FrozenClock(NOW),
            max_cycles=1, cycle_seconds=0, report_dir=str(tmp_path / "reports"))
        monkeypatch.setattr(bot, "_connect", lambda: True)
        from agi_style_forex_bot_mt5.paper_trading.lifecycle import PaperAccountObservation, PaperCycleInput
        observation = PaperAccountObservation(ctx.account, NOW, True)
        monkeypatch.setattr(bot, "_observe_account", lambda: observation)
        monkeypatch.setattr(bot, "_acquire_paper_cycle", lambda observed, **kwargs:
            PaperCycleInput(kwargs['event_id'], NOW, observed, {"EURUSD": ctx.snapshot}, (), {}))
        monkeypatch.setattr(bot.recovery_manager, "recover", lambda: {"status": "OK"})
        seen = []
        calls = []
        original = bot._refresh_paper_risk_state

        def refresh(account, **kwargs):
            calls.append("refresh")
            if refresh_fails:
                raise OSError("sensitive-private-path")
            return original(account, **kwargs)

        def legacy_override(metrics):
            raise AssertionError("a legacy override must not reset current verified risk")

        monkeypatch.setattr(bot, "_refresh_paper_risk_state", refresh)
        monkeypatch.setattr(bot, "_micro_legacy_drawdown_adjusted_metrics", legacy_override)
        monkeypatch.setattr(bot.alerts, "evaluate", lambda metrics: seen.append(metrics) or [])
        result = bot.run()
        if refresh_fails:
            # A valuation storage failure now aborts the shared economic cycle;
            # publishing a successful heartbeat with unknown equity is unsafe.
            assert result.cycles_completed == 0 and result.lifecycle_halted
            assert result.audit_complete is False
            assert calls == ["refresh"] and seen == []
            events = db.fetch_all("events")
            assert any(row["event_type"] == "PAPER_CYCLE_HALTED" for row in events)
            assert all("sensitive-private-path" not in row["payload_json"] for row in events)
        else:
            assert result.cycles_completed == 1 and not result.lifecycle_halted
            assert calls == ["refresh", "refresh"] and len(seen) == 1
            assert seen[0]["paper_risk_state_status"] == "VERIFIED"
            assert seen[0]["daily_drawdown_pct"] == 0
            assert seen[0]["paper_equity"] == 10000
    finally:
        db.close()

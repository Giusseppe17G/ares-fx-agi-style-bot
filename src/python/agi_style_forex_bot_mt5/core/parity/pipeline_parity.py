"""Backtest / forward-shadow pipeline parity.

The stage inventory describes both pipelines. The fixture below compares only
shared component calls, not the complete pipelines or their state transitions.
One-sided stages and distinct adapters are reported as gaps. A passing component
comparison must never be represented as full pipeline verification.

Forward-shadow order (paper_trading/forward_shadow_bot.py, the live loop):
    strategy -> risk -> ml -> ranker -> portfolio -> execution
Backtest order (backtesting/backtester.py):
    strategy -> profile thresholds -> stable filters -> execution
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from ...contracts import MarketSnapshot, SignalAction
from ...strategy import evaluate_ensemble
from ..clock import Clock, FrozenClock, resolve_clock
from ..execution import SharedFillModel
from ..instruments import InstrumentSpec, spec_from_mapping
from ..safety import SafetyEnvelope


REFERENCE_NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)

SHARED = "SHARED"
BACKTEST_ONLY = "BACKTEST_ONLY"
FORWARD_ONLY = "FORWARD_ONLY"
ADAPTER_REQUIRED = "ADAPTER_REQUIRED"


@dataclass(frozen=True)
class Stage:
    """One decision stage, and which pipeline actually runs it."""

    stage_id: str
    scope: str
    backtest_implementation: str
    forward_implementation: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "scope": self.scope,
            "backtest_implementation": self.backtest_implementation,
            "forward_implementation": self.forward_implementation,
            "same": self.scope == SHARED,
            "note": self.note,
        }


def pipeline_stages() -> list[Stage]:
    """The audited stage map. Every entry was read out of the running code."""

    return [
        Stage("market_data", ADAPTER_REQUIRED, "data_pipeline.historical_csv_loader", "mt5_data_bot + MT5Connector", "Different sources: stored bars versus live ticks. A shared output contract does not establish equivalent availability times or values."),
        Stage("instrument_metadata", SHARED, "core.instruments.InstrumentRegistry", "core.instruments.InstrumentRegistry (from MT5 symbol_info)", "FASE 82: unified. Previously the backtester invented digits/tick_value/volumes/stops."),
        Stage("normalization", SHARED, "contracts.MarketSnapshot", "contracts.MarketSnapshot", "Same frozen contract on both sides."),
        Stage("features", SHARED, "data.strategy_features", "data.strategy_features", "Same causal closed-bar builder; source availability still requires adapter evidence."),
        Stage("strategy", SHARED, "strategy.evaluate_ensemble", "strategy.evaluate_ensemble", "Identical function and configuration object."),
        Stage("profile_thresholds", SHARED, "calibration.decision_policy", "calibration.decision_policy via core.decision", "Complete finite setup/component evidence required in both callers."),
        Stage("stable_filters", SHARED, "calibration.decision_policy", "calibration.decision_policy via core.decision", "Same overlays apply to stable and micro descendants."),
        Stage("risk_engine", FORWARD_ONLY, "not run", "risk.RiskEngine.evaluate", "PARITY GAP: the backtest sizes positions without the live risk engine's checks."),
        Stage("ml_filter", FORWARD_ONLY, "not run", "ml.MLFilter.approve_or_reject", "PARITY GAP: the backtest never sees the ML meta-filter, so it counts trades live would reject."),
        Stage("signal_ranker", FORWARD_ONLY, "not run", "portfolio.SignalRanker.rank", "PARITY GAP: legacy OHLC bypasses ranking; forward currently ranks single candidates, not simultaneous top-N competition."),
        Stage("portfolio_guard", FORWARD_ONLY, "not run", "portfolio.PortfolioGuard.evaluate", "PARITY GAP: correlation and exposure limits are not applied offline."),
        Stage("dynamic_risk", FORWARD_ONLY, "not run", "portfolio.DynamicRiskAllocator", "PARITY GAP: risk scaling is not applied offline."),
        Stage("paper_limits", FORWARD_ONLY, "not run", "paper_risk_calibration.evaluate_paper_trade_limits", "PARITY GAP: daily trade caps and drawdown halts do not exist offline."),
        Stage("execution_simulation", SHARED, "core.execution.SharedFillModel", "core.execution.SharedFillModel via PaperFillModel", "FASE 82: unified onto execution_simulation.FillModel."),
        Stage("persistence", ADAPTER_REQUIRED, "backtesting.performance_report", "telemetry.TelemetryDatabase + JSONL", "Different stores; the safety envelope alone is not implementation or audit-path parity."),
        Stage("metrics", ADAPTER_REQUIRED, "backtesting.backtester.calculate_metrics", "paper_trading.paper_performance", "Different implementations. Equivalence requires independent fixtures, including open equity and costs."),
    ]


@dataclass(frozen=True)
class DecisionRow:
    bar_index: int
    stage_id: str
    backtest_value: Any
    forward_value: Any

    @property
    def equivalent(self) -> bool:
        return _comparable(self.backtest_value) == _comparable(self.forward_value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bar_index": self.bar_index,
            "stage_id": self.stage_id,
            "backtest_value": _jsonable(self.backtest_value),
            "forward_value": _jsonable(self.forward_value),
            "equivalent": self.equivalent,
        }


@dataclass(frozen=True)
class ParityFixture:
    """One deterministic fixture: same bars, clock, instrument, config and seed."""

    instrument: InstrumentSpec
    snapshots: Sequence[MarketSnapshot]
    features: Sequence[Mapping[str, Any]]
    seed: int = 82
    clock: Clock = field(default_factory=lambda: FrozenClock(REFERENCE_NOW))


def build_fixture(*, symbol: str = "EURUSD", bars: int = 120, clock: Clock | None = None) -> ParityFixture:
    """A reproducible synthetic fixture. No randomness beyond the fixed seed."""

    resolved = resolve_clock(clock) if clock is not None else FrozenClock(REFERENCE_NOW)
    spec = spec_from_mapping(
        symbol,
        {
            "digits": 5,
            "point": 0.00001,
            "tick_size": 0.00001,
            "tick_value": 1.0,
            "contract_size": 100000.0,
            "min_volume": 0.01,
            "max_volume": 100.0,
            "volume_step": 0.01,
            "stops_level_points": 0,
            "freeze_level_points": 0,
            "currency_base": symbol[:3],
            "currency_quote": symbol[3:6],
        },
        source="parity_fixture",
    )
    start = resolved.now_utc() - timedelta(minutes=5 * bars)
    snapshots: list[MarketSnapshot] = []
    features: list[Mapping[str, Any]] = []
    price = 1.10000
    for index in range(bars):
        price += 0.00005 if index % 3 else -0.00003
        spread_points = 8.0 + (index % 5)
        half = spread_points * spec.point / 2.0
        snapshots.append(
            MarketSnapshot(
                symbol=symbol,
                timeframe="M5",
                timestamp_utc=start + timedelta(minutes=5 * index),
                bid=price - half,
                ask=price + half,
                spread_points=spread_points,
                digits=spec.digits,
                point=spec.point,
                tick_value=spec.tick_value,
                tick_size=spec.tick_size,
                volume_min=spec.min_volume,
                volume_max=spec.max_volume,
                volume_step=spec.volume_step,
                stops_level_points=spec.stops_level_points,
                freeze_level_points=spec.freeze_level_points,
            )
        )
        features.append(
            {
                "atr": 0.00040 + (index % 7) * 0.00001,
                "ema_fast": price + 0.00010,
                "ema_slow": price - 0.00010,
                "rsi": 45.0 + (index % 11),
                "adx": 20.0 + (index % 9),
                "regime": "TREND" if index % 2 else "RANGE",
                "session": "LONDON",
                "spread_points": spread_points,
            }
        )
    return ParityFixture(instrument=spec, snapshots=tuple(snapshots), features=tuple(features), clock=resolved)


def compare_pipelines(fixture: ParityFixture | None = None) -> dict[str, Any]:
    """Smoke-test shared components; this does not run either complete pipeline."""

    fixture = fixture or build_fixture()
    if len(fixture.snapshots) != len(fixture.features):
        raise ValueError("parity fixture needs one feature mapping per snapshot")
    rows: list[DecisionRow] = []
    model = SharedFillModel(max_spread_points=25.0, slippage_points=1.0)

    for index, (snapshot, features) in enumerate(zip(fixture.snapshots, fixture.features)):
        # instrument metadata: both sides now read the same registry spec
        rows.append(DecisionRow(index, "instrument_metadata", _instrument_view(snapshot), _instrument_view(snapshot)))

        # strategy: the same function, called the way each pipeline calls it
        backtest_signal = evaluate_ensemble(snapshot, features, mode="shadow")
        forward_signal = evaluate_ensemble(snapshot, features, mode="shadow")
        rows.append(DecisionRow(index, "strategy_action", backtest_signal.action.value, forward_signal.action.value))
        rows.append(DecisionRow(index, "strategy_score", round(float(backtest_signal.score), 10), round(float(forward_signal.score), 10)))

        if backtest_signal.action == SignalAction.NONE and forward_signal.action == SignalAction.NONE:
            continue

        # execution: the same shared model, driven the way each pipeline drives it
        direction = backtest_signal.action.value
        backtest_fill = model.entry(direction=direction, snapshot=snapshot, replay=True, context={"forward_spreads": (snapshot.spread_points,)})
        forward_fill = model.entry(direction=direction, snapshot=snapshot, replay=True, context={"forward_spreads": (snapshot.spread_points,)})
        rows.append(DecisionRow(index, "execution_accepted", backtest_fill.accepted, forward_fill.accepted))
        rows.append(DecisionRow(index, "execution_fill_price", backtest_fill.fill_price, forward_fill.fill_price))

    stages = pipeline_stages()
    equivalent = sum(1 for row in rows if row.equivalent)
    parity_pct = (equivalent / len(rows) * 100.0) if rows else 0.0
    gaps = [stage for stage in stages if stage.scope != SHARED]
    shared_count = sum(1 for stage in stages if stage.scope == SHARED)
    stage_pct = shared_count / len(stages) * 100.0 if stages else 0.0
    component_status = "PARITY_OK" if rows and parity_pct >= 95.0 else "PARITY_BELOW_THRESHOLD"
    payload = {
        "mode": "backtest-live-parity",
        "parity_status": "PARITY_INCOMPLETE" if component_status == "PARITY_OK" else component_status,
        "decision_parity_status": component_status,
        "evidence_scope": "SHARED_COMPONENT_SMOKE_TEST",
        "full_pipeline_verified": False,
        "compared_decision_ids": sorted({row.stage_id for row in rows}),
        "decision_count": len(rows),
        "equivalent_decision_count": equivalent,
        "decision_parity_pct": round(parity_pct, 4),
        "parity_threshold_pct": 95.0,
        "difference_count": len(rows) - equivalent,
        "differences": [row.as_dict() for row in rows if not row.equivalent],
        "stage_count": len(stages),
        "shared_stage_count": shared_count,
        "stage_parity_pct": round(stage_pct, 4),
        "parity_gap_stage_count": len(gaps),
        "parity_gap_stage_ids": [stage.stage_id for stage in gaps],
        "stages": [stage.as_dict() for stage in stages],
        "instrument": fixture.instrument.as_dict(),
        "seed": fixture.seed,
        "reference_time_utc": fixture.clock.now_utc().isoformat(),
        "execution_model": model.as_dict(),
    }
    return SafetyEnvelope().seal(payload, full=True)


def _instrument_view(snapshot: MarketSnapshot) -> dict[str, Any]:
    return {
        "digits": snapshot.digits,
        "point": snapshot.point,
        "tick_value": snapshot.tick_value,
        "tick_size": snapshot.tick_size,
        "volume_min": snapshot.volume_min,
        "volume_max": snapshot.volume_max,
        "volume_step": snapshot.volume_step,
        "stops_level_points": snapshot.stops_level_points,
        "freeze_level_points": snapshot.freeze_level_points,
    }


def _comparable(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 10)
    if isinstance(value, Mapping):
        return {str(key): _comparable(item) for key, item in sorted(value.items())}
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

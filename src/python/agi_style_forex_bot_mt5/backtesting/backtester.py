"""Deterministic Python backtesting engine.

The engine consumes OHLC bars and explicit trade candidates. It does not create
signals or execution requests; it only validates and simulates already-audited
research candidates with conservative cost and exit assumptions.
"""

from __future__ import annotations

import json
import math
from hashlib import sha256
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from ..calibration.decision_policy import evaluate_profile_thresholds, evaluate_stability_filters, resolve_signal_profile
from ..config import BotConfig
from ..contracts import Direction, MarketSnapshot, SignalAction
from ..data import normalize_ohlcv_bars
from ..data.strategy_features import prepare_strategy_features, strategy_features_at
from ..data_pipeline.historical_csv_loader import load_historical_csv_contract
from ..data_pipeline.historical_data_resolver import resolve_historical_data
from ..core.execution import SharedFillModel
from ..core.price_grid import is_price_on_tick_grid, snap_price_to_tick
from ..core.decision.signal_builder import build_signal_prices
from ..core.clock import FrozenClock
from ..core.run_manifest import RunManifest
from ..core.instruments.snapshot import instrument_metadata_hash
from ..core.operational_state.errors import ExecutionSimulationError
from ..core.instruments import ASSUMED_SOURCE, InstrumentRegistry, InstrumentSpec, assumed_fx_spec, resolve_registry
from ..strategy import evaluate_ensemble
from ..strategy.strategy_ensemble import EnsembleConfig, STRATEGY_VERSION


ENGINE_VERSION = "0.3.2"


@dataclass(frozen=True)
class CostModel:
    """Spread, slippage and commission assumptions for one backtest run."""

    spread_points: float = 0.0
    slippage_points: float = 0.0
    commission_per_lot_round_turn: float = 0.0
    point: float = 0.00001
    tick_value: float = 1.0
    tick_size: float = 0.00001
    max_spread_points: float = 25.0

    def validate(self) -> None:
        if not all(math.isfinite(value) for value in asdict(self).values()):
            raise ValueError("cost model values must be finite")
        if self.spread_points < 0 or self.slippage_points < 0:
            raise ValueError("spread and slippage must be non-negative")
        if self.commission_per_lot_round_turn < 0:
            raise ValueError("commission must be non-negative")
        if self.point <= 0 or self.tick_value <= 0 or self.tick_size <= 0:
            raise ValueError("point, tick_value and tick_size must be positive")
        if self.max_spread_points < 0:
            raise ValueError("max_spread_points must be non-negative")

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    def with_instrument(self, spec: "InstrumentSpec") -> "CostModel":
        """Take point/tick geometry from the instrument registry, keep the cost assumptions."""

        return CostModel(
            spread_points=self.spread_points,
            slippage_points=self.slippage_points,
            commission_per_lot_round_turn=self.commission_per_lot_round_turn,
            point=spec.point,
            tick_value=spec.tick_value,
            tick_size=spec.tick_size,
            max_spread_points=self.max_spread_points,
        )


@dataclass(frozen=True)
class TradeCandidate:
    """Research trade candidate used by the backtester."""

    timestamp: datetime | str | pd.Timestamp
    symbol: str
    direction: Direction | str
    sl_price: float
    tp_price: float
    timeframe: str = ""
    signal_id: str = ""
    lot: float = 1.0
    entry_price: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # Source-bar timestamp is retained for attribution. This is the earliest
    # instant at which all inputs to the decision were actually available.
    available_at_utc: datetime | str | pd.Timestamp | None = None


@dataclass(frozen=True)
class BacktestSettings:
    """Run settings for the deterministic bar simulator."""

    run_id: str = "backtest"
    strategy_name: str = "research"
    strategy_version: str = "0.1.0"
    initial_balance: float = 10_000.0
    cost_model: CostModel = field(default_factory=CostModel)
    break_even_trigger_r: float | None = None
    break_even_lock_points: float = 0.0
    trailing_start_r: float | None = None
    trailing_distance_points: float = 0.0
    max_bars_in_trade: int | None = None
    use_next_bar_open: bool = False
    data_source: str = "unspecified"
    code_commit: str = "unknown"
    modeling_mode: str = "ohlc"
    timezone: str = "UTC"
    random_seed: int | None = None
    data_fingerprint: str = "unknown"
    broker_profile: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        self.cost_model.validate()
        if self.break_even_trigger_r is not None and self.break_even_trigger_r < 0:
            raise ValueError("break_even_trigger_r must be non-negative")
        if self.trailing_start_r is not None and self.trailing_start_r < 0:
            raise ValueError("trailing_start_r must be non-negative")
        if self.trailing_distance_points < 0 or self.break_even_lock_points < 0:
            raise ValueError("break-even and trailing points must be non-negative")
        if self.max_bars_in_trade is not None and self.max_bars_in_trade <= 0:
            raise ValueError("max_bars_in_trade must be positive")


@dataclass(frozen=True)
class TradeResult:
    """Closed simulated trade with audit-friendly execution details."""

    signal_id: str
    symbol: str
    direction: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    initial_sl_price: float
    final_sl_price: float
    tp_price: float
    lot: float
    profit: float
    r_multiple: float
    exit_reason: str
    duration_bars: int
    duration_seconds: float
    mae: float
    mfe: float
    spread_points: float
    slippage_points: float
    commission: float
    point: float
    tick_value: float
    tick_size: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestMetrics:
    """Metrics required by the project backtesting contract."""

    total_return_pct: float
    net_profit: float
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    daily_max_drawdown_pct: float
    sharpe: float | None
    sortino: float | None
    expectancy: float
    expected_payoff: float
    average_r: float
    trades_total: int
    average_duration_seconds: float
    average_mae: float
    average_mfe: float
    max_consecutive_losses: int
    average_consecutive_losses: float
    exposure_time_pct: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    recovery_factor: float | None
    monthly_returns: Mapping[str, float]
    trades_per_month: Mapping[str, int]
    positive_months: int
    negative_months: int
    worst_day_return_pct: float
    worst_week_return_pct: float
    worst_month_return_pct: float
    drawdown_percentiles: Mapping[str, float]
    mae_mfe_summary: Mapping[str, float]

    def to_project_result(self, *, run_id: str, artifact_dir: str = "") -> dict[str, Any]:
        """Return a dict shaped like the PROJECT_SPEC BacktestResult contract."""

        status = "INCONCLUSIVE"
        rejection_reason = "promotion gate not evaluated"
        return {
            "run_id": run_id,
            "net_profit": self.net_profit,
            "profit_factor": self.profit_factor,
            "max_drawdown_pct": self.max_drawdown_pct,
            "daily_max_drawdown_pct": self.daily_max_drawdown_pct,
            "trades_total": self.trades_total,
            "win_rate_pct": self.win_rate_pct,
            "expected_payoff": self.expected_payoff,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "recovery_factor": self.recovery_factor,
            "notes": "Python OHLC research backtest; not an MT5 execution report.",
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "payoff_ratio": self.payoff_ratio,
            "max_consecutive_losses": self.max_consecutive_losses,
            "exposure_time_pct": self.exposure_time_pct,
            "monthly_returns_json": json.dumps(self.monthly_returns, sort_keys=True),
            "regime_breakdown_json": json.dumps({}, sort_keys=True),
            "mae_mfe_summary_json": json.dumps(self.mae_mfe_summary, sort_keys=True),
            "parameter_sensitivity_json": json.dumps({}, sort_keys=True),
            "artifact_dir": artifact_dir,
            "equity_curve_path": "",
            "trades_path": "",
            "events_path": "",
            "config_snapshot_path": "",
            "report_path": "",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "rejection_reason": rejection_reason,
            "result_fingerprint": "",
        }


@dataclass(frozen=True)
class BacktestOutcome:
    """Complete deterministic backtest output."""

    settings: BacktestSettings
    metrics: BacktestMetrics
    trades: tuple[TradeResult, ...]
    rejected_candidates: tuple[dict[str, Any], ...]
    equity_curve: pd.DataFrame

    def trades_frame(self) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for trade in self.trades:
            row = asdict(trade)
            metadata = dict(row.get("metadata") or {})
            for key in ("regime", "session", "score", "strategy_name", "setup_quality", "setup_score", "ensemble_score", "profile_hash", "thresholds_used", "passed_thresholds", "threshold_failures"):
                if key in metadata:
                    row[key] = metadata[key]
            rows.append(row)
        return pd.DataFrame(rows)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "settings": _jsonable(asdict(self.settings)),
            "metrics": _jsonable(asdict(self.metrics)),
            "rejected_candidates": list(self.rejected_candidates),
        }


@dataclass(frozen=True)
class DataQualityReport:
    """CSV data quality summary used to reproduce backtests."""

    symbol: str
    timeframe: str
    rows: int
    start_utc: str
    end_utc: str
    duplicate_timestamps: int
    largest_gap_seconds: float
    expected_gap_seconds: float
    gap_count: int
    fingerprint: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromotionGateResult:
    """Backtest-level Strategy Promotion Gate classification."""

    status: str
    reasons: tuple[str, ...]
    checks: Mapping[str, bool]


@dataclass(frozen=True)
class BacktestBatchResult:
    """Multi-symbol backtest output plus grouped report tables."""

    summary: Mapping[str, Any]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    by_symbol: pd.DataFrame
    by_regime: pd.DataFrame
    by_session: pd.DataFrame
    by_weekday: pd.DataFrame
    by_hour_utc: pd.DataFrame
    data_quality: tuple[DataQualityReport, ...]
    promotion: Mapping[str, PromotionGateResult]
    reports_created: tuple[str, ...] = ()


class Backtester:
    """Conservative OHLC backtester for precomputed trade candidates."""

    def __init__(self, settings: BacktestSettings | None = None) -> None:
        self.settings = settings or BacktestSettings()
        self.settings.validate()

    def run(
        self,
        candles: pd.DataFrame,
        candidates: Iterable[TradeCandidate | Mapping[str, Any]],
    ) -> BacktestOutcome:
        """Run a deterministic backtest over OHLC candles and candidates."""

        bars = _normalize_candles(candles)
        normalized_candidates = sorted(
            (_normalize_candidate(candidate) for candidate in candidates),
            key=lambda item: pd.Timestamp(item.timestamp),
        )
        trades: list[TradeResult] = []
        rejected: list[dict[str, Any]] = []
        exposure_indices: set[int] = set()
        for candidate in normalized_candidates:
            stable_reason = dict(candidate.metadata).get("stable_rejection_reason")
            if stable_reason:
                rejected.append(
                    {
                        "signal_id": candidate.signal_id,
                        "timestamp": str(candidate.timestamp),
                        "symbol": candidate.symbol,
                        "reason": str(stable_reason),
                    }
                )
                continue
            try:
                trade, used_indices = self._simulate_candidate(bars, candidate)
            except ValueError as exc:
                rejected.append(
                    {
                        "signal_id": candidate.signal_id,
                        "timestamp": str(candidate.timestamp),
                        "symbol": candidate.symbol,
                        "reason": str(exc),
                    }
                )
                continue
            if trade is not None:
                trades.append(trade)
                exposure_indices.update(used_indices)
        equity_curve = build_equity_curve(
            trades,
            initial_balance=self.settings.initial_balance,
            candles=bars,
        )
        metrics = calculate_metrics(
            trades,
            initial_balance=self.settings.initial_balance,
            equity_curve=equity_curve,
            total_bars=len(bars),
            exposed_bars=len(exposure_indices),
        )
        return BacktestOutcome(
            settings=self.settings,
            metrics=metrics,
            trades=tuple(trades),
            rejected_candidates=tuple(rejected),
            equity_curve=equity_curve,
        )

    def _simulate_candidate(
        self, bars: pd.DataFrame, candidate: TradeCandidate
    ) -> tuple[TradeResult | None, set[int]]:
        if not math.isfinite(candidate.lot) or candidate.lot <= 0:
            raise ValueError("candidate lot must be positive")
        if not all(math.isfinite(value) and value > 0 for value in (candidate.sl_price, candidate.tp_price)):
            raise ValueError("candidate requires positive SL and TP")
        if not all(is_price_on_tick_grid(value, self.settings.cost_model.tick_size)
                   for value in (candidate.sl_price, candidate.tp_price)):
            raise ValueError("candidate SL and TP must be on the executable tick grid")

        timestamp = pd.to_datetime(candidate.timestamp, utc=True)
        if pd.isna(timestamp):
            raise ValueError("candidate timestamp must be valid")
        if candidate.available_at_utc is not None:
            available_at = pd.to_datetime(candidate.available_at_utc, utc=True)
            if pd.isna(available_at) or available_at < timestamp:
                raise ValueError("candidate availability must be valid and not precede its source")
            if candidate.entry_price is not None:
                raise ValueError("availability-based market entry cannot override entry_price")
            timestamp = available_at
        start_idx = _first_bar_index_at_or_after(bars, timestamp)
        if start_idx is None:
            raise ValueError("candidate timestamp is outside candle data")
        # Legacy external candidates retain their documented timing switch.
        # Explicit availability is authoritative; applying the switch again
        # would introduce a second, artificial bar of delay.
        if self.settings.use_next_bar_open and candidate.available_at_utc is None:
            start_idx += 1
            if start_idx >= len(bars):
                raise ValueError("no next bar available for entry")

        entry_bar = bars.iloc[start_idx]
        spread_points = _bar_spread_points(entry_bar, self.settings.cost_model.spread_points)
        if spread_points > self.settings.cost_model.max_spread_points:
            raise ValueError("spread exceeds configured maximum")

        direction = _direction_value(candidate.direction)
        base_entry = float(candidate.entry_price if candidate.entry_price is not None else entry_bar.open)
        entry_price = _apply_entry_cost(
            base_entry,
            direction=direction,
            spread_points=spread_points,
            slippage_points=self.settings.cost_model.slippage_points,
            point=self.settings.cost_model.point,
            tick_size=self.settings.cost_model.tick_size,
            max_spread_points=self.settings.cost_model.max_spread_points,
        )
        _validate_directional_prices(direction, entry_price, candidate.sl_price, candidate.tp_price)

        initial_sl = float(candidate.sl_price)
        current_sl = initial_sl
        tp_price = float(candidate.tp_price)
        entry_decimal = Decimal(str(entry_price))
        risk_distance = float(abs(entry_decimal - Decimal(str(initial_sl))))
        if risk_distance <= 0:
            raise ValueError("SL distance must be positive")

        max_idx = len(bars) - 1
        if self.settings.max_bars_in_trade is not None:
            max_idx = min(max_idx, start_idx + self.settings.max_bars_in_trade - 1)

        mae = 0.0
        mfe = 0.0
        exit_base_price = float(bars.iloc[max_idx].close)
        exit_reason = "END_OF_DATA"
        exit_idx = max_idx
        used_indices: set[int] = set()

        for idx in range(start_idx, max_idx + 1):
            row = bars.iloc[idx]
            used_indices.add(idx)
            high = float(row.high)
            low = float(row.low)
            if direction == Direction.BUY.value:
                mae = min(mae, float(Decimal(str(low)) - entry_decimal))
                mfe = max(mfe, float(Decimal(str(high)) - entry_decimal))
                if low <= current_sl:
                    exit_base_price = current_sl
                    exit_reason = "SL"
                    exit_idx = idx
                    break
                if high >= tp_price:
                    exit_base_price = tp_price
                    exit_reason = "TP"
                    exit_idx = idx
                    break
                current_sl = self._maybe_move_stop(
                    direction=direction,
                    current_sl=current_sl,
                    entry_price=entry_price,
                    favorable_excursion=mfe,
                    risk_distance=risk_distance,
                    bar_extreme=high,
                )
            else:
                mae = min(mae, float(entry_decimal - Decimal(str(high))))
                mfe = max(mfe, float(entry_decimal - Decimal(str(low))))
                if high >= current_sl:
                    exit_base_price = current_sl
                    exit_reason = "SL"
                    exit_idx = idx
                    break
                if low <= tp_price:
                    exit_base_price = tp_price
                    exit_reason = "TP"
                    exit_idx = idx
                    break
                current_sl = self._maybe_move_stop(
                    direction=direction,
                    current_sl=current_sl,
                    entry_price=entry_price,
                    favorable_excursion=mfe,
                    risk_distance=risk_distance,
                    bar_extreme=low,
                )

        exit_price = _apply_exit_cost(
            exit_base_price,
            direction=direction,
            spread_points=spread_points,
            slippage_points=self.settings.cost_model.slippage_points,
            point=self.settings.cost_model.point,
            tick_size=self.settings.cost_model.tick_size,
            max_spread_points=self.settings.cost_model.max_spread_points,
        )
        commission = self.settings.cost_model.commission_per_lot_round_turn * candidate.lot
        profit = _profit_for_price_move(
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            lot=candidate.lot,
            tick_size=self.settings.cost_model.tick_size,
            tick_value=self.settings.cost_model.tick_value,
            commission=commission,
        )
        planned_risk = (
            risk_distance / self.settings.cost_model.tick_size
        ) * self.settings.cost_model.tick_value * candidate.lot
        r_multiple = profit / planned_risk if planned_risk > 0 else 0.0
        entry_time = pd.Timestamp(bars.iloc[start_idx].timestamp)
        exit_time = pd.Timestamp(bars.iloc[exit_idx].timestamp)
        duration_seconds = max((exit_time - entry_time).total_seconds(), 0.0)
        signal_id = candidate.signal_id or f"candidate_{start_idx}_{len(used_indices)}"
        trade = TradeResult(
            signal_id=signal_id,
            symbol=candidate.symbol,
            direction=direction,
            entry_time=entry_time.isoformat(),
            exit_time=exit_time.isoformat(),
            entry_price=entry_price,
            exit_price=exit_price,
            initial_sl_price=initial_sl,
            final_sl_price=current_sl,
            tp_price=tp_price,
            lot=candidate.lot,
            profit=profit,
            r_multiple=r_multiple,
            exit_reason=exit_reason,
            duration_bars=len(used_indices),
            duration_seconds=duration_seconds,
            mae=mae,
            mfe=mfe,
            spread_points=spread_points,
            slippage_points=self.settings.cost_model.slippage_points,
            commission=commission,
            point=self.settings.cost_model.point,
            tick_value=self.settings.cost_model.tick_value,
            tick_size=self.settings.cost_model.tick_size,
            metadata={
                **dict(candidate.metadata),
                **({
                    "source_bar_timestamp_utc": pd.to_datetime(candidate.timestamp, utc=True).isoformat(),
                    "available_at_utc": timestamp.isoformat(),
                    "entry_timing": "FIRST_OPEN_AT_OR_AFTER_AVAILABILITY",
                } if candidate.available_at_utc is not None else {}),
            },
        )
        return trade, used_indices

    def _maybe_move_stop(
        self,
        *,
        direction: str,
        current_sl: float,
        entry_price: float,
        favorable_excursion: float,
        risk_distance: float,
        bar_extreme: float,
    ) -> float:
        new_sl = Decimal(str(current_sl))
        point = Decimal(str(self.settings.cost_model.point))
        entry = Decimal(str(entry_price))
        extreme = Decimal(str(bar_extreme))
        excursion = Decimal(str(favorable_excursion))
        risk = Decimal(str(risk_distance))
        if (
            self.settings.break_even_trigger_r is not None
            and excursion >= Decimal(str(self.settings.break_even_trigger_r)) * risk
        ):
            lock = Decimal(str(self.settings.break_even_lock_points)) * point
            if direction == Direction.BUY.value:
                new_sl = max(new_sl, entry + lock)
            else:
                new_sl = min(new_sl, entry - lock)
        if (
            self.settings.trailing_start_r is not None
            and self.settings.trailing_distance_points > 0
            and excursion >= Decimal(str(self.settings.trailing_start_r)) * risk
        ):
            distance = Decimal(str(self.settings.trailing_distance_points)) * point
            if direction == Direction.BUY.value:
                new_sl = max(new_sl, extreme - distance)
            else:
                new_sl = min(new_sl, extreme + distance)
        # An adjusted protective stop cannot claim an unexecutable extra tick
        # of profit. The existing stop was validated and is never loosened.
        aligned = snap_price_to_tick(new_sl, self.settings.cost_model.tick_size,
                                     rounding="down" if direction == Direction.BUY.value else "up")
        return max(current_sl, aligned) if direction == Direction.BUY.value else min(current_sl, aligned)


def load_historical_csv(
    path: str | Path,
    *,
    symbol: str,
    timeframe: str = "M5",
    expected_gap_seconds: float | None = None,
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Load and validate one local historical CSV for reproducible backtests."""

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"historical CSV not found: {csv_path}")
    loaded = load_historical_csv_contract(csv_path, symbol=symbol, timeframe=timeframe)
    if loaded.diagnostics["status"] != "OK":
        status = str(loaded.diagnostics["status"])
        if status == "CSV_EMPTY":
            raise ValueError("historical CSV is empty")
        if status in {"CSV_MISSING_OHLC", "CSV_NUMERIC_CONVERSION_ERROR"}:
            raise ValueError(f"historical CSV missing columns or invalid numeric values: {status}")
        raise ValueError(status)
    duplicate_count = int(loaded.diagnostics.get("duplicates", 0) or 0)
    normalized = loaded.frame.rename(columns={"tick_volume": "volume", "spread": "spread_points"}).copy()
    normalized = normalized.drop(columns=["real_volume"], errors="ignore")
    frame = normalize_ohlcv_bars(normalized, symbol=symbol, timeframe=timeframe)
    frame = frame.rename(columns={"timestamp_utc": "timestamp"})
    if "spread_points" not in frame.columns:
        frame["spread_points"] = np.nan
    gap_expectation = expected_gap_seconds or _timeframe_seconds(timeframe)
    gaps = frame["timestamp"].diff().dt.total_seconds().dropna()
    largest_gap = float(gaps.max()) if len(gaps) else 0.0
    gap_count = int((gaps > gap_expectation * 3.0).sum()) if gap_expectation > 0 else 0
    warnings: list[str] = []
    if duplicate_count:
        warnings.append("duplicate timestamps detected and de-duplicated")
    if gap_count:
        warnings.append("large timestamp gaps detected")
    fingerprint = sha256(csv_path.read_bytes()).hexdigest()
    quality = DataQualityReport(
        symbol=symbol,
        timeframe=timeframe,
        rows=len(frame),
        start_utc=pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
        end_utc=pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
        duplicate_timestamps=duplicate_count,
        largest_gap_seconds=largest_gap,
        expected_gap_seconds=float(gap_expectation),
        gap_count=gap_count,
        fingerprint=fingerprint,
        warnings=tuple(warnings),
    )
    return frame, quality


def run_strategy_backtest(
    candles: pd.DataFrame,
    *,
    symbol: str,
    settings: BacktestSettings | None = None,
    config: BotConfig | None = None,
    timeframe: str = "M5",
    instrument: InstrumentSpec | None = None,
) -> BacktestOutcome:
    """Generate ensemble candidates from bars and simulate them offline."""

    cfg = config or BotConfig()
    cfg.validate_safety()
    run_settings = settings or BacktestSettings(
        strategy_name="strategy_ensemble",
        strategy_version=STRATEGY_VERSION,
        break_even_trigger_r=0.6,
        trailing_start_r=0.8,
        trailing_distance_points=80,
        max_bars_in_trade=96,
    )
    spec = instrument or assumed_fx_spec(symbol)
    # One instrument source drives both candidate geometry and the cost model, so a
    # backtest can no longer size trades against different metadata than it prices them with.
    run_settings = replace(run_settings, cost_model=run_settings.cost_model.with_instrument(spec))
    bars = _normalize_candles(candles)
    candidates = generate_strategy_candidates(
        bars,
        symbol=symbol,
        timeframe=timeframe,
        config=cfg,
        point=spec.point,
        instrument=spec,
    )
    return Backtester(run_settings).run(bars, candidates)


def generate_strategy_candidates(
    candles: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    config: BotConfig,
    point: float,
    instrument: InstrumentSpec | None = None,
) -> tuple[TradeCandidate, ...]:
    """Create deterministic offline trade candidates from the current ensemble."""

    bars = _normalize_candles(candles)
    bar_duration = pd.Timedelta(seconds=_timeframe_seconds(timeframe))
    indicator_input = bars.rename(columns={"timestamp": "timestamp_utc"}).copy()
    indicator_input["volume"] = indicator_input.get("volume", indicator_input.get("tick_volume", 0))
    enriched = prepare_strategy_features(
        indicator_input, point=point, max_spread_points=config.max_spread_points_default,
    )
    candidates: list[TradeCandidate] = []
    last_candidate_idx = -999
    profile = _signal_profile_settings(config.signal_profile, config.profile_config)
    if profile.get("apply_stability_filters") and symbol.upper() in set(profile.get("disabled_symbols", [])):
        return (
            TradeCandidate(
                timestamp=pd.Timestamp(bars.iloc[0]["timestamp"]),
                symbol=symbol,
                direction=Direction.BUY,
                sl_price=0.0,
                tp_price=0.0,
                timeframe=timeframe,
                signal_id=f"stable_block_{symbol}",
                metadata={"stable_rejection_reason": "STABLE_SYMBOL_DISABLED"},
            ),
        )
    for idx in range(220, len(enriched)):
        row = enriched.iloc[idx]
        if pd.isna(row[["ema20", "ema50", "ema200", "rsi14", "atr14"]]).any():
            continue
        if idx - last_candidate_idx < 3:
            continue
        snapshot = _snapshot_from_row(row, symbol=symbol, timeframe=timeframe, point=point, config=config, instrument=instrument)
        available_at = pd.Timestamp(row["timestamp_utc"]) + bar_duration
        snapshot = replace(snapshot, timestamp_utc=available_at.to_pydatetime())
        features = _features_from_row(enriched, idx, snapshot, config)
        signal = evaluate_ensemble(
            snapshot,
            features,
            mode="shadow",
            config=EnsembleConfig(mode="shadow", threshold=float(profile["ensemble_min_score"])),
        )
        if signal.action == SignalAction.NONE:
            continue
        passed_thresholds, threshold_failures = _profile_threshold_result(signal.metadata, profile, ensemble_score=signal.score)
        if not passed_thresholds:
            continue
        session = session_for_timestamp(available_at)
        regime = str(row["regime"])
        stable_passed, stable_reason = _stable_filter_result(
            profile,
            symbol=symbol,
            strategy_name=signal.strategy_name,
            session=session,
            regime=regime,
        )
        if not stable_passed:
            candidates.append(
                TradeCandidate(
                    timestamp=pd.Timestamp(row["timestamp_utc"]),
                    symbol=symbol,
                    direction=Direction.BUY if signal.action == SignalAction.BUY else Direction.SELL,
                    sl_price=0.0,
                    tp_price=0.0,
                    timeframe=timeframe,
                    signal_id=f"stable_block_{symbol}_{idx}",
                    available_at_utc=available_at,
                    metadata={"stable_rejection_reason": stable_reason},
                )
            )
            last_candidate_idx = idx
            continue
        direction = Direction.BUY if signal.action == SignalAction.BUY else Direction.SELL
        sl_price, tp_price = build_signal_prices(snapshot, signal.action, float(features["atr"]))
        candidates.append(
            TradeCandidate(
                timestamp=pd.Timestamp(row["timestamp_utc"]),
                symbol=symbol,
                direction=direction,
                sl_price=round(sl_price, snapshot.digits),
                tp_price=round(tp_price, snapshot.digits),
                timeframe=timeframe,
                signal_id=f"bt_{symbol}_{idx}",
                lot=1.0,
                available_at_utc=available_at,
                metadata={
                    "regime": regime,
                    "session": session,
                    "score": signal.score,
                    "ensemble_score": signal.score,
                    "reasons": tuple(signal.reasons),
                    "strategy_name": signal.strategy_name,
                    "signal_profile": profile["name"],
                    "profile_hash": profile["profile_hash"],
                    "thresholds_used": dict(profile),
                    "setup_score": signal.metadata.get("setup_quality_score", 0.0),
                    "passed_thresholds": passed_thresholds,
                    "threshold_failures": tuple(threshold_failures),
                    "setup_quality": signal.metadata.get("setup_quality", ""),
                    "component_scores": dict(signal.metadata.get("component_scores") or {}),
                },
            )
        )
        last_candidate_idx = idx
    return tuple(candidates)


def _profile_allows_signal(metadata: Mapping[str, Any], profile: Mapping[str, Any]) -> bool:
    """Apply calibrated research thresholds without disabling safety gates."""

    return _profile_threshold_result(metadata, profile)[0]


def _profile_threshold_result(metadata: Mapping[str, Any], profile: Mapping[str, Any], *, ensemble_score: float | None = None) -> tuple[bool, tuple[str, ...]]:
    """Return whether metadata passes effective profile thresholds."""

    return evaluate_profile_thresholds(metadata, profile, ensemble_score=ensemble_score)


def _signal_profile_settings(name: str, profile_config: str = "") -> dict[str, Any]:
    return resolve_signal_profile(BotConfig(signal_profile=name, profile_config=profile_config))


def _stable_filter_result(profile: Mapping[str, Any], *, symbol: str, strategy_name: str, session: str, regime: str) -> tuple[bool, str]:
    return evaluate_stability_filters(profile, symbol=symbol, strategy_name=strategy_name, session=session, regime=regime)


def classify_sample_size(total_trades: int) -> str:
    """Classify whether a trade sample is usable for research evidence."""

    count = int(total_trades)
    if count < 30:
        return "LOW_SAMPLE"
    if count < 100:
        return "SMALL_SAMPLE"
    if count < 300:
        return "USABLE_SAMPLE"
    return "PROMOTION_SAMPLE_SIZE"


def _top_rejection_reasons(rejections: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for rejection in rejections:
        reason = _canonical_trade_blocker(str(rejection.get("reason", "")))
        counts[reason] = counts.get(reason, 0) + 1
    return [
        {"blocking_reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]
    ]


def _average_metadata_numeric(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else 0.0


def _canonical_trade_blocker(reason: str) -> str:
    text = reason.lower()
    if "stable_symbol_disabled" in text:
        return "STABLE_SYMBOL_DISABLED"
    if "stable_strategy_disabled" in text:
        return "STABLE_STRATEGY_DISABLED"
    if "stable_session_block" in text:
        return "STABLE_SESSION_BLOCK"
    if "stable_regime_block" in text:
        return "STABLE_REGIME_BLOCK"
    if "sl" in text or "tp" in text or "directional" in text:
        return "MISSING_SL_TP" if "positive sl" in text or "positive sl and tp" in text else "INVALID_RR"
    if "spread" in text:
        return "SPREAD_BLOCK"
    if "risk" in text:
        return "RISK_REJECTED"
    if "portfolio" in text:
        return "PORTFOLIO_BLOCK"
    if "session" in text:
        return "SESSION_BLOCK"
    return "TRADE_SIMULATION_REJECTED"


def run_backtest_for_symbols(
    *,
    data_dir: str | Path,
    symbols: Iterable[str],
    report_dir: str | Path | None = None,
    settings: BacktestSettings | None = None,
    config: BotConfig | None = None,
    timeframe: str = "M5",
    instruments: InstrumentRegistry | None = None,
    allow_assumed_instruments: bool = True,
) -> BacktestBatchResult:
    """Run a reproducible multi-symbol backtest from local CSV history."""

    cfg = config or BotConfig()
    cfg.validate_safety()
    run_settings = settings or BacktestSettings(
        run_id="backtest",
        strategy_name="strategy_ensemble",
        strategy_version=STRATEGY_VERSION,
        break_even_trigger_r=0.6,
        trailing_start_r=0.8,
        trailing_distance_points=80,
        max_bars_in_trade=96,
        parameters={
            "DEMO_ONLY": cfg.demo_only,
            "LIVE_TRADING_APPROVED": cfg.live_trading_approved,
            "SIGNAL_PROFILE": cfg.signal_profile,
        },
    )
    profile = _signal_profile_settings(cfg.signal_profile, cfg.profile_config)
    resolved_symbols = [item.strip().upper() for item in symbols if item.strip()]
    registry, instrument_metadata_source = resolve_registry(
        registry=instruments,
        data_dir=data_dir,
        symbols=resolved_symbols,
        allow_assumptions=allow_assumed_instruments,
    )
    all_trades: list[pd.DataFrame] = []
    all_equity: list[pd.DataFrame] = []
    all_rejections: list[dict[str, Any]] = []
    qualities: list[DataQualityReport] = []
    promotions: dict[str, PromotionGateResult] = {}
    data_valid_symbols: list[str] = []
    signals_generated = 0
    dataset_paths: list[Path] = []
    dataset_end = pd.Timestamp("1970-01-01T00:00:00Z")
    for symbol in resolved_symbols:
        path = _find_history_csv(Path(data_dir), symbol, timeframe)
        dataset_paths.append(path)
        candles, quality = load_historical_csv(path, symbol=symbol, timeframe=timeframe)
        dataset_end = max(dataset_end, pd.Timestamp(candles["timestamp"].max()) + pd.Timedelta(seconds=_timeframe_seconds(timeframe)))
        qualities.append(quality)
        data_valid_symbols.append(symbol)
        spec = registry.get(symbol) if registry.has(symbol) else assumed_fx_spec(symbol)
        outcome = run_strategy_backtest(candles, symbol=symbol, settings=run_settings, config=cfg, timeframe=timeframe, instrument=spec)
        signals_generated += len(outcome.trades) + len(outcome.rejected_candidates)
        all_rejections.extend(dict(item) | {"symbol": symbol} for item in outcome.rejected_candidates)
        trades = outcome.trades_frame()
        if not trades.empty:
            trades["symbol"] = symbol
            all_trades.append(trades)
        equity = outcome.equity_curve.copy()
        equity["symbol"] = symbol
        all_equity.append(equity)
        promotions[symbol] = classify_strategy_promotion(outcome.metrics, trades)

    trades_frame = pd.concat(all_trades, ignore_index=True) if all_trades else _empty_trades_frame()
    equity_curve = _aggregate_equity_curves(all_equity, run_settings.initial_balance)
    metrics = calculate_metrics(trades_frame.to_dict("records"), initial_balance=run_settings.initial_balance, equity_curve=equity_curve)
    by_symbol = _group_metrics(trades_frame, "symbol")
    by_regime = _group_metrics(trades_frame, "regime")
    by_session = _group_metrics(trades_frame, "session")
    by_strategy = _group_metrics(trades_frame, "strategy_name")
    by_weekday = _group_metrics(_with_time_columns(trades_frame), "weekday")
    by_hour = _group_metrics(_with_time_columns(trades_frame), "hour_utc")
    rejection_blockers = _top_rejection_reasons(all_rejections)
    classification = "OK"
    if signals_generated == 0:
        classification = "WARNING_NO_SIGNALS"
    elif metrics.trades_total == 0:
        classification = "WARNING_NO_TRADES"
    summary: dict[str, Any] = {
        "mode": "backtest",
        "scope": "INDEPENDENT_RESEARCH_CANDIDATES",
        "full_risk_pipeline_applied": False,
        "operationally_eligible": False,
        "instrument_metadata_source": instrument_metadata_source,
        "instrument_metadata_assumed": instrument_metadata_source == ASSUMED_SOURCE,
        "signal_profile_used": profile["name"],
        "thresholds_used": dict(profile),
        "profile_hash": profile["profile_hash"],
        "profile_not_for_demo_live": bool(profile["not_for_demo_live"]),
        "profile_allowed_for_shadow": profile["name"] in {"CONSERVATIVE", "BALANCED", "BALANCED_FILTERED"} and not bool(profile["not_for_demo_live"]),
        "symbols_tested": len(qualities),
        "data_valid_symbols": data_valid_symbols,
        "signals_generated": signals_generated,
        "blocked_by_threshold": 0,
        "passed_by_threshold": metrics.trades_total,
        "avg_setup_score": _average_metadata_numeric(trades_frame, "setup_score"),
        "avg_ensemble_score": _average_metadata_numeric(trades_frame, "ensemble_score"),
        "trades_generated": metrics.trades_total,
        "sample_status": classify_sample_size(metrics.trades_total),
        "min_required_trades": 30,
        "trades_by_symbol": by_symbol.to_dict("records"),
        "trades_by_strategy": by_strategy.to_dict("records"),
        "top_blocking_reasons": [{"blocking_reason": "NO_SETUP_DETECTED", "count": len(qualities)}] if signals_generated == 0 else rejection_blockers,
        "total_trades": metrics.trades_total,
        "net_return_pct": metrics.total_return_pct,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "profit_factor": metrics.profit_factor,
        "winrate": metrics.win_rate_pct,
        "expectancy_r": metrics.average_r,
        "sharpe": metrics.sharpe,
        "sortino": metrics.sortino,
        "classification": "WARNING_SIGNALS_NO_TRADES" if signals_generated > 0 and metrics.trades_total == 0 else classification,
        "execution_attempted": False,
        "reports_created": [],
    }
    provenance = RunManifest.build(
        mode="backtest", clock=FrozenClock(dataset_end.to_pydatetime()),
        config={"bot": asdict(cfg), "settings": asdict(run_settings), "effective_profile": profile},
        dataset_paths=dataset_paths, symbols=resolved_symbols, timeframe=timeframe,
        seed=run_settings.random_seed, instrument_metadata_hash=instrument_metadata_hash(registry),
    )
    summary = provenance.attach(summary)
    result = BacktestBatchResult(
        summary=summary,
        trades=trades_frame,
        equity_curve=equity_curve,
        by_symbol=by_symbol,
        by_regime=by_regime,
        by_session=by_session,
        by_weekday=by_weekday,
        by_hour_utc=by_hour,
        data_quality=tuple(qualities),
        promotion=promotions,
    )
    if report_dir is not None:
        from .performance_report import write_batch_reports

        artifacts = write_batch_reports(result, report_dir)
        summary = {**summary, "reports_created": list(artifacts)}
        result = BacktestBatchResult(
            summary=summary,
            trades=trades_frame,
            equity_curve=equity_curve,
            by_symbol=by_symbol,
            by_regime=by_regime,
            by_session=by_session,
            by_weekday=by_weekday,
            by_hour_utc=by_hour,
            data_quality=tuple(qualities),
            promotion=promotions,
            reports_created=tuple(artifacts),
        )
    return result


def classify_strategy_promotion(
    metrics: BacktestMetrics,
    trades: pd.DataFrame | None = None,
    *,
    oos_positive: bool = False,
    monte_carlo_ruin_ok: bool = False,
    spread_slippage_ok: bool = False,
) -> PromotionGateResult:
    """Classify a symbol for the Phase 4 promotion gate."""

    trade_count = int(metrics.trades_total)
    checks = {
        "sample_size": trade_count >= 300,
        "profit_factor": metrics.profit_factor > 1.25,
        "drawdown": abs(metrics.max_drawdown_pct) < 12.0,
        "expectancy_r": metrics.average_r > 0,
        "oos_positive": bool(oos_positive),
        "monte_carlo": bool(monte_carlo_ruin_ok),
        "spread_slippage": bool(spread_slippage_ok),
        "profit_concentration": not _depends_on_few_large_trades(trades),
        "week_concentration": not _is_concentrated_in_one_week(trades),
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    core_failed = [name for name in ("profit_factor", "drawdown", "expectancy_r") if not checks[name]]
    if not failed:
        status = "APPROVED_FOR_SHADOW_OBSERVATION"
    elif core_failed or trade_count == 0:
        status = "REJECTED"
    else:
        status = "WATCHLIST"
    reasons = tuple(f"failed: {name}" for name in failed) or ("promotion gate passed",)
    return PromotionGateResult(status=status, reasons=reasons, checks=checks)


def session_for_timestamp(timestamp: pd.Timestamp) -> str:
    """Return a coarse FX session label for UTC timestamps."""

    hour = pd.Timestamp(timestamp).hour
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 17:
        return "NY_OVERLAP"
    if 17 <= hour < 22:
        return "NEW_YORK"
    if 22 <= hour or hour < 7:
        return "ASIA"
    return "UNKNOWN"


def calculate_metrics(
    trades: Iterable[TradeResult | Mapping[str, Any]],
    *,
    initial_balance: float = 10_000.0,
    equity_curve: pd.DataFrame | None = None,
    total_bars: int | None = None,
    exposed_bars: int | None = None,
) -> BacktestMetrics:
    """Calculate project-required metrics from closed trades."""

    normalized = _ordered_trade_mappings(trades)
    profits = np.array([float(trade["profit"]) for trade in normalized], dtype=float)
    r_values = np.array([float(trade.get("r_multiple", 0.0)) for trade in normalized], dtype=float)
    wins = profits[profits > 0]
    losses = profits[profits < 0]
    net_profit = float(profits.sum()) if len(profits) else 0.0
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    profit_factor = math.inf if gross_profit > 0 and gross_loss == 0 else (
        gross_profit / gross_loss if gross_loss > 0 else 0.0
    )
    trades_total = len(profits)
    win_rate_pct = (len(wins) / trades_total * 100.0) if trades_total else 0.0
    expectancy = float(profits.mean()) if trades_total else 0.0
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss < 0 else 0.0
    average_r = float(r_values.mean()) if len(r_values) else 0.0
    durations = np.array([float(trade.get("duration_seconds", 0.0)) for trade in normalized])
    maes = np.array([float(trade.get("mae", 0.0)) for trade in normalized])
    mfes = np.array([float(trade.get("mfe", 0.0)) for trade in normalized])

    if equity_curve is None:
        equity_curve = build_equity_curve(normalized, initial_balance=initial_balance)
    equity_curve = _equity_with_initial_balance(equity_curve, initial_balance)
    equity = equity_curve["equity"].astype(float)
    max_dd_pct, drawdown_pct = _max_drawdown_pct(equity)
    daily_max_dd_pct = _daily_max_drawdown_pct(equity_curve, initial_balance)
    trade_returns = _trade_returns(profits, initial_balance)
    sharpe = _sharpe(trade_returns)
    sortino = _sortino(trade_returns)
    max_dd_amount = float((equity.cummax() - equity).max()) if len(equity) else 0.0
    recovery_factor = net_profit / max_dd_amount if max_dd_amount > 0 else None
    monthly_returns, trades_per_month = _monthly_stats(normalized, initial_balance)
    worst_day, worst_week, worst_month = _worst_period_returns(equity_curve, initial_balance)
    exposure_time_pct = _exposure_time_pct(
        normalized,
        total_bars=total_bars,
        exposed_bars=exposed_bars,
    )
    loss_runs = _loss_runs(profits)
    average_consecutive_losses = float(np.mean(loss_runs)) if loss_runs else 0.0
    drawdown_percentiles = {
        "p50": float(np.percentile(drawdown_pct, 50)) if len(drawdown_pct) else 0.0,
        "p75": float(np.percentile(drawdown_pct, 75)) if len(drawdown_pct) else 0.0,
        "p95": float(np.percentile(drawdown_pct, 95)) if len(drawdown_pct) else 0.0,
    }
    mae_mfe_summary = {
        "average_mae": float(maes.mean()) if len(maes) else 0.0,
        "worst_mae": float(maes.min()) if len(maes) else 0.0,
        "average_mfe": float(mfes.mean()) if len(mfes) else 0.0,
        "best_mfe": float(mfes.max()) if len(mfes) else 0.0,
    }
    return BacktestMetrics(
        total_return_pct=(net_profit / initial_balance * 100.0) if initial_balance else 0.0,
        net_profit=net_profit,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd_pct,
        daily_max_drawdown_pct=daily_max_dd_pct,
        sharpe=sharpe,
        sortino=sortino,
        expectancy=expectancy,
        expected_payoff=expectancy,
        average_r=average_r,
        trades_total=trades_total,
        average_duration_seconds=float(durations.mean()) if len(durations) else 0.0,
        average_mae=float(maes.mean()) if len(maes) else 0.0,
        average_mfe=float(mfes.mean()) if len(mfes) else 0.0,
        max_consecutive_losses=max(loss_runs) if loss_runs else 0,
        average_consecutive_losses=average_consecutive_losses,
        exposure_time_pct=exposure_time_pct,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff_ratio,
        recovery_factor=recovery_factor,
        monthly_returns=monthly_returns,
        trades_per_month=trades_per_month,
        positive_months=sum(1 for value in monthly_returns.values() if value > 0),
        negative_months=sum(1 for value in monthly_returns.values() if value < 0),
        worst_day_return_pct=worst_day,
        worst_week_return_pct=worst_week,
        worst_month_return_pct=worst_month,
        drawdown_percentiles=drawdown_percentiles,
        mae_mfe_summary=mae_mfe_summary,
    )


def build_equity_curve(
    trades: Iterable[TradeResult | Mapping[str, Any]],
    *,
    initial_balance: float,
    candles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build realized equity, including capital before the first realization.

    All simultaneous closes form one net realization. Candle timestamps add
    observations without hiding closes between bars. If the first observation
    is also a close, its initial-capital row precedes the close at the same time.
    """

    normalized = _ordered_trade_mappings(trades)
    timestamps: list[pd.Timestamp] = []
    if candles is not None and len(candles):
        bars = _normalize_candles(candles)
        timestamps.extend(bars["timestamp"])
    grouped: dict[pd.Timestamp, list[float]] = {}
    for trade in normalized:
        ts = pd.to_datetime(trade["exit_time"], utc=True)
        grouped.setdefault(ts, []).append(float(trade["profit"]))
    timestamps.extend(grouped)
    ordered = sorted(set(timestamps)) or [pd.Timestamp("1970-01-01T00:00:00Z")]
    equity = float(initial_balance)
    observations = [{"timestamp": ordered[0], "equity": equity}]
    for timestamp in ordered:
        if timestamp == ordered[0] and timestamp not in grouped:
            continue
        equity += math.fsum(grouped.get(timestamp, ()))
        observations.append({"timestamp": timestamp, "equity": equity})
    return pd.DataFrame(observations)


def _normalize_candles(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"candles missing columns: {sorted(missing)}")
    bars = candles.copy()
    if "timestamp" not in bars.columns:
        if isinstance(bars.index, pd.DatetimeIndex):
            bars = bars.reset_index().rename(columns={bars.index.name or "index": "timestamp"})
        else:
            raise ValueError("candles require a timestamp column or DatetimeIndex")
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    for column in ("open", "high", "low", "close"):
        bars[column] = bars[column].astype(float)
    if "spread_points" in bars.columns:
        bars["spread_points"] = bars["spread_points"].astype(float)
    if (bars["high"] < bars["low"]).any():
        raise ValueError("candle high cannot be below low")
    return bars.sort_values("timestamp").reset_index(drop=True)


def _normalize_candidate(candidate: TradeCandidate | Mapping[str, Any]) -> TradeCandidate:
    if isinstance(candidate, TradeCandidate):
        return candidate
    return TradeCandidate(**dict(candidate))


def _direction_value(direction: Direction | str) -> str:
    value = direction.value if isinstance(direction, Direction) else str(direction).upper()
    if value not in {Direction.BUY.value, Direction.SELL.value}:
        raise ValueError("direction must be BUY or SELL")
    return value


def _first_bar_index_at_or_after(bars: pd.DataFrame, timestamp: pd.Timestamp) -> int | None:
    timestamps = bars["timestamp"]
    positions = np.flatnonzero(timestamps >= timestamp)
    return int(positions[0]) if len(positions) else None


def _bar_spread_points(row: pd.Series, default: float) -> float:
    value = float(row["spread_points"]) if "spread_points" in row else float(default)
    if not math.isfinite(value) or value < 0:
        raise ValueError("bar spread must be finite and non-negative")
    return value


def _apply_entry_cost(
    base_price: float,
    *,
    direction: str,
    spread_points: float,
    slippage_points: float,
    point: float,
    tick_size: float | None = None,
    max_spread_points: float = 25.0,
) -> float:
    """Entry price under the shared execution model.

    Delegates to `execution_simulation.FillModel` via SharedFillModel, the same
    model paper trading uses, including its price precision and spread gate.
    """

    return _shared_fill_price(
        base_price,
        direction=direction,
        spread_points=spread_points,
        slippage_points=slippage_points,
        point=point,
        tick_size=tick_size,
        is_entry=True,
        max_spread_points=max_spread_points,
    )


def _shared_fill_price(
    base_price: float,
    *,
    direction: str,
    spread_points: float,
    slippage_points: float,
    point: float,
    is_entry: bool,
    tick_size: float | None = None,
    max_spread_points: float = 25.0,
) -> float:
    snapshot = _replay_snapshot(base_price, spread_points=spread_points, point=point, tick_size=tick_size)
    model = SharedFillModel(max_spread_points=max_spread_points, slippage_points=slippage_points)
    # Reapply the same limit as the run's gate, without inflating it.
    # Preserve the observed spread exactly, including zero.
    context = {"forward_spreads": (spread_points,)}
    if is_entry:
        result = model.entry(direction=direction, snapshot=snapshot, replay=True, context=context)
    else:
        result = model.exit(direction=direction, snapshot=snapshot, replay=True, context=context)
    if not result.accepted or result.fill_price is None:
        raise ExecutionSimulationError(
            f"replay fill rejected: {result.reject_reason or result.reject_code}",
            source="backtester",
            detail={"reject_code": result.reject_code, "spread_points": spread_points},
        )
    return float(result.fill_price)


def _replay_snapshot(base_price: float, *, spread_points: float, point: float,
                     tick_size: float | None = None) -> MarketSnapshot:
    """Price-only replay, never a live tick or a source of volume limits.

    Legacy private price callers may omit tick_size; Backtester always passes
    the explicit instrument geometry from CostModel. lot=0 requests only a
    price estimate from SharedFillModel, so placeholder volume fields do not
    validate candidate sizing. Instrument-aware callers must validate sizing.
    """

    half = spread_points * point / 2.0
    digits = max(0, int(round(-math.log10(point)))) if point > 0 else 5
    return MarketSnapshot(
        symbol="REPLAY",
        timeframe="REPLAY",
        timestamp_utc=datetime(1970, 1, 1, tzinfo=timezone.utc),
        bid=max(point, base_price - half),
        ask=base_price + half,
        spread_points=spread_points,
        digits=digits,
        point=point,
        tick_value=1.0,
        tick_size=point if tick_size is None else tick_size,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        stops_level_points=0,
        freeze_level_points=0,
    )


def _apply_exit_cost(
    base_price: float,
    *,
    direction: str,
    spread_points: float,
    slippage_points: float,
    point: float,
    tick_size: float | None = None,
    max_spread_points: float = 25.0,
) -> float:
    return _shared_fill_price(
        base_price, direction=direction, spread_points=spread_points,
        slippage_points=slippage_points, point=point, is_entry=False,
        tick_size=tick_size,
        max_spread_points=max_spread_points,
    )


def _validate_directional_prices(direction: str, entry: float, sl: float, tp: float) -> None:
    if direction == Direction.BUY.value and not (sl < entry < tp):
        raise ValueError("BUY candidate requires sl < entry < tp")
    if direction == Direction.SELL.value and not (tp < entry < sl):
        raise ValueError("SELL candidate requires tp < entry < sl")


def _profit_for_price_move(
    *,
    direction: str,
    entry_price: float,
    exit_price: float,
    lot: float,
    tick_size: float,
    tick_value: float,
    commission: float,
) -> float:
    move = exit_price - entry_price
    if direction == Direction.SELL.value:
        move *= -1.0
    return (move / tick_size) * tick_value * lot - commission


def _trade_to_mapping(trade: TradeResult | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(trade, TradeResult):
        return asdict(trade)
    return trade


def _ordered_trade_mappings(trades: Iterable[TradeResult | Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Order realized outcomes by UTC close time, with deterministic identity ties."""
    normalized = [_trade_to_mapping(trade) for trade in trades]

    def ordering(trade: Mapping[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp, str]:
        exit_time = pd.to_datetime(trade["exit_time"], utc=True)
        entry_time = pd.to_datetime(trade.get("entry_time", trade["exit_time"]), utc=True)
        if pd.isna(exit_time) or pd.isna(entry_time):
            raise ValueError("closed-trade metrics require valid timestamps")
        return exit_time, entry_time, str(trade.get("signal_id", ""))

    return sorted(normalized, key=ordering)


def _equity_with_initial_balance(equity_curve: pd.DataFrame, initial_balance: float) -> pd.DataFrame:
    """Normalize observation order and restore a missing pre-realization baseline."""
    curve = equity_curve[["timestamp", "equity"]].copy()
    curve["timestamp"] = pd.to_datetime(curve["timestamp"], utc=True)
    if curve["timestamp"].isna().any():
        raise ValueError("equity observations require valid timestamps")
    curve = curve.sort_values("timestamp", kind="stable").reset_index(drop=True)
    if curve.empty:
        return pd.DataFrame({"timestamp": [pd.Timestamp("1970-01-01T00:00:00Z")], "equity": [float(initial_balance)]})
    if float(curve["equity"].iloc[0]) != initial_balance:
        baseline = pd.DataFrame({"timestamp": [curve["timestamp"].iloc[0]], "equity": [float(initial_balance)]})
        curve = pd.concat([baseline, curve], ignore_index=True)
    return curve


def _max_drawdown_pct(equity: pd.Series) -> tuple[float, np.ndarray]:
    if len(equity) == 0:
        return 0.0, np.array([], dtype=float)
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max.replace(0, np.nan) * 100.0
    drawdown = drawdown.fillna(0.0)
    return float(drawdown.min()), np.abs(drawdown.to_numpy(dtype=float))


def _daily_max_drawdown_pct(equity_curve: pd.DataFrame, initial_balance: float) -> float:
    if len(equity_curve) == 0:
        return 0.0
    curve = equity_curve.copy()
    curve["timestamp"] = pd.to_datetime(curve["timestamp"], utc=True)
    worst = 0.0
    previous_close = float(initial_balance)
    for _, group in curve.groupby(curve["timestamp"].dt.date):
        values = pd.Series([previous_close, *group["equity"].astype(float)], dtype=float)
        dd, _ = _max_drawdown_pct(values)
        worst = min(worst, dd)
        previous_close = float(values.iloc[-1])
    return float(worst)


def _trade_returns(profits: np.ndarray, initial_balance: float) -> np.ndarray:
    returns: list[float] = []
    equity = float(initial_balance)
    for profit in profits:
        returns.append(float(profit) / equity if equity else 0.0)
        equity += float(profit)
    return np.array(returns, dtype=float)


def _sharpe(returns: np.ndarray) -> float | None:
    if len(returns) < 2:
        return None
    std = float(returns.std(ddof=1))
    if std == 0:
        return None
    return float(returns.mean() / std * math.sqrt(len(returns)))


def _sortino(returns: np.ndarray) -> float | None:
    if len(returns) < 2:
        return None
    downside = returns[returns < 0]
    if len(downside) == 0:
        return None
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else abs(float(downside[0]))
    if downside_std == 0:
        return None
    return float(returns.mean() / downside_std * math.sqrt(len(returns)))


def _monthly_stats(
    trades: list[Mapping[str, Any]], initial_balance: float
) -> tuple[dict[str, float], dict[str, int]]:
    equity = float(initial_balance)
    profits_by_month: dict[str, float] = {}
    counts_by_month: dict[str, int] = {}
    for trade in trades:
        month = pd.to_datetime(trade["exit_time"], utc=True).strftime("%Y-%m")
        profits_by_month[month] = profits_by_month.get(month, 0.0) + float(trade["profit"])
        counts_by_month[month] = counts_by_month.get(month, 0) + 1
    returns: dict[str, float] = {}
    for month in sorted(profits_by_month):
        profit = profits_by_month[month]
        returns[month] = profit / equity * 100.0 if equity else 0.0
        equity += profit
    return returns, counts_by_month


def _worst_period_returns(equity_curve: pd.DataFrame, initial_balance: float) -> tuple[float, float, float]:
    if len(equity_curve) < 2:
        return 0.0, 0.0, 0.0
    curve = equity_curve.copy()
    curve["timestamp"] = pd.to_datetime(curve["timestamp"], utc=True)
    curve = curve.set_index("timestamp").sort_index(kind="stable")

    def worst(freq: str) -> float:
        period = curve["equity"].resample(freq).last().dropna()
        previous = period.shift(1)
        if len(previous):
            previous.iloc[0] = initial_balance
        returns = ((period - previous) / previous.replace(0, np.nan) * 100.0).dropna()
        return float(returns.min()) if len(returns) else 0.0

    return worst("D"), worst("W"), worst("ME")


def _exposure_time_pct(
    trades: list[Mapping[str, Any]],
    *,
    total_bars: int | None,
    exposed_bars: int | None,
) -> float:
    if total_bars and exposed_bars is not None:
        return min(100.0, exposed_bars / total_bars * 100.0)
    if not trades:
        return 0.0
    starts = [pd.Timestamp(trade["entry_time"]) for trade in trades]
    exits = [pd.Timestamp(trade["exit_time"]) for trade in trades]
    total = (max(exits) - min(starts)).total_seconds()
    exposed = sum(max((exit_ - start).total_seconds(), 0.0) for start, exit_ in zip(starts, exits))
    return min(100.0, exposed / total * 100.0) if total > 0 else 0.0


def _loss_runs(profits: np.ndarray) -> list[int]:
    runs: list[int] = []
    current = 0
    for profit in profits:
        if profit < 0:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _timeframe_seconds(timeframe: str) -> float:
    normalized = timeframe.strip().upper()
    units = {"M": 60, "H": 3600, "D": 86400, "W": 604800}
    if len(normalized) < 2 or normalized[0] not in units or not normalized[1:].isdigit():
        raise ValueError("timeframe must have an explicit fixed bar duration")
    count = int(normalized[1:])
    if count <= 0:
        raise ValueError("timeframe duration must be positive")
    return float(count * units[normalized[0]])


def _snapshot_from_row(
    row: pd.Series,
    *,
    symbol: str,
    timeframe: str,
    point: float,
    config: BotConfig,
    instrument: InstrumentSpec | None = None,
) -> MarketSnapshot:
    """Build the backtest snapshot from real instrument metadata.

    FASE 82: every instrument field now comes from the InstrumentRegistry, the
    same source forward-shadow fills from MT5 `symbol_info`. The old inline
    guesses (digits from a JPY substring, tick_value=1.0, volume_min=0.01,
    stops_level=10, freeze_level=5) are gone from this function.
    """

    spec = instrument or assumed_fx_spec(symbol)
    spread_points = float(row.get("spread_points", config.max_spread_points_default))
    if math.isnan(spread_points):
        spread_points = config.max_spread_points_default
    close = float(row["close"])
    half_spread = spread_points * spec.point / 2.0
    return MarketSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        timestamp_utc=pd.Timestamp(row["timestamp_utc"]).to_pydatetime(),
        bid=max(spec.point, close - half_spread),
        ask=close + half_spread,
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


def _features_from_row(
    frame: pd.DataFrame,
    idx: int,
    snapshot: MarketSnapshot,
    config: BotConfig,
) -> dict[str, Any]:
    return strategy_features_at(frame, idx, snapshot, max_spread_points=config.max_spread_points_default)


def _find_history_csv(data_dir: Path, symbol: str, timeframe: str) -> Path:
    resolution = resolve_historical_data(data_dir, symbol=symbol, timeframe=timeframe, min_bars=0)
    if resolution.found:
        return Path(resolution.path)
    raise FileNotFoundError(f"no CSV found for {symbol} {timeframe} in {data_dir}: {resolution.reason}")


def _empty_trades_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "signal_id",
            "symbol",
            "direction",
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "profit",
            "r_multiple",
            "exit_reason",
            "regime",
            "session",
            "strategy_name",
        ]
    )


def _aggregate_equity_curves(curves: list[pd.DataFrame], initial_balance: float) -> pd.DataFrame:
    if not curves:
        return pd.DataFrame({"timestamp": [pd.Timestamp("1970-01-01T00:00:00Z")], "equity": [initial_balance]})
    combined = pd.concat(curves, ignore_index=True)
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
    pivot = combined.pivot_table(index="timestamp", columns="symbol", values="equity", aggfunc="last")
    pivot = pivot.sort_index().ffill().fillna(initial_balance)
    aggregate = pivot.sum(axis=1) - (len(pivot.columns) - 1) * initial_balance
    return pd.DataFrame({"timestamp": aggregate.index, "equity": aggregate.values})


def _with_time_columns(trades: pd.DataFrame) -> pd.DataFrame:
    frame = trades.copy()
    if frame.empty or "exit_time" not in frame.columns:
        frame["weekday"] = []
        frame["hour_utc"] = []
        return frame
    times = pd.to_datetime(frame["exit_time"], utc=True)
    frame["weekday"] = times.dt.day_name()
    frame["hour_utc"] = times.dt.hour
    return frame


def _group_metrics(trades: pd.DataFrame, group_column: str) -> pd.DataFrame:
    if trades.empty or group_column not in trades.columns:
        return pd.DataFrame(columns=[group_column, "trades", "net_profit", "net_return_pct", "profit_factor", "winrate", "expectancy_r"])
    rows: list[dict[str, Any]] = []
    for value, group in trades.groupby(group_column, dropna=False):
        metrics = calculate_metrics(group.to_dict("records"))
        rows.append(
            {
                group_column: value,
                "trades": metrics.trades_total,
                "net_profit": metrics.net_profit,
                "net_return_pct": metrics.total_return_pct,
                "profit_factor": metrics.profit_factor,
                "winrate": metrics.win_rate_pct,
                "expectancy_r": metrics.average_r,
            }
        )
    return pd.DataFrame(rows).sort_values(group_column).reset_index(drop=True)


def _depends_on_few_large_trades(trades: pd.DataFrame | None) -> bool:
    if trades is None or trades.empty or "profit" not in trades.columns:
        return True
    positive = trades[trades["profit"] > 0]["profit"].astype(float).sort_values(ascending=False)
    if len(positive) <= 2:
        return True
    top_two = float(positive.head(2).sum())
    total_positive = float(positive.sum())
    return bool(total_positive > 0 and top_two / total_positive > 0.5)


def _is_concentrated_in_one_week(trades: pd.DataFrame | None) -> bool:
    if trades is None or trades.empty or "exit_time" not in trades.columns or "profit" not in trades.columns:
        return True
    frame = trades.copy()
    frame["week"] = pd.to_datetime(frame["exit_time"], utc=True).dt.strftime("%G-W%V")
    weekly = frame.groupby("week")["profit"].sum()
    total = abs(float(weekly.sum()))
    if total <= 0 or len(weekly) <= 1:
        return True
    return bool(abs(float(weekly.abs().max())) / total > 0.5)

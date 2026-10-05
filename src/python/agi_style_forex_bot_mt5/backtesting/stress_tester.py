"""Explicitly limited post-trade cost and concentration approximations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .backtester import TradeResult, calculate_metrics, classify_sample_size, run_backtest_for_symbols
from .monte_carlo import (
    EVIDENCE_VERSION, _canonical_json, _evidence_manifest, _finite_number,
    _integer, _jsonable, _positive_number, _runtime_versions, sequence_metrics,
)


APPROXIMATION_SCOPE = "POST_TRADE_APPROXIMATION"
UNMODELED_SCOPE = "REQUIRES_EXPLICIT_QUOTE_REPLAY"
UNMODELED_SCENARIOS = ("entry_delay_one_bar", "session_shift", "fill_rate", "missing_bars")
SCENARIO_CONFIG = {
    "spread_multipliers": [1.0, 1.5, 2.0, 3.0],
    "slippage_multipliers": [1.0, 1.5, 2.0, 3.0],
    "commission_multipliers": [1.0, 1.5, 2.0],
    "remove_best_percent": [1, 5, 10], "losses_added": [3, 5, 8],
    "periodic_omission_percent": [5, 10], "fixed_profit_haircut_pct": 5,
}


@dataclass(frozen=True)
class StressResult:
    scenario: str
    parameters: Mapping[str, Any]
    metrics: Any
    status: str = "COMPLETED"
    evidence_scope: str = APPROXIMATION_SCOPE


class StressTester:
    """Apply deterministic degradation scenarios to closed trades."""

    def __init__(self, *, initial_balance: float = 10_000.0) -> None:
        self.initial_balance = _positive_number(initial_balance, "initial_balance")

    def spread_slippage_sensitivity(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any]],
        *,
        spread_multipliers: Iterable[float] = (1.0, 1.5, 2.0),
        extra_slippage_points: Iterable[float] = (0.0, 1.0, 2.0),
    ) -> list[StressResult]:
        source = _source_trades(trades)
        spread_multipliers = tuple(_nonnegative(value, "spread_multiplier") for value in spread_multipliers)
        extra_slippage_points = tuple(_nonnegative(value, "extra_slippage_points") for value in extra_slippage_points)
        results: list[StressResult] = []
        for spread_multiplier in spread_multipliers:
            for slippage_points in extra_slippage_points:
                stressed = [
                    _apply_cost_penalty(
                        trade,
                        spread_multiplier=spread_multiplier,
                        extra_slippage_points=slippage_points,
                    )
                    for trade in source
                ]
                metrics = self._metrics(stressed)
                results.append(
                    StressResult(
                        scenario="spread_slippage",
                        parameters={
                            "spread_multiplier": spread_multiplier,
                            "extra_slippage_points": slippage_points,
                        },
                        metrics=metrics if source else None,
                        status="COMPLETED" if source else "NO_INPUT",
                    )
                )
        return results

    def remove_best_trades(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any]],
        *,
        counts: Iterable[int] = (1, 3, 5),
    ) -> list[StressResult]:
        source = _source_trades(trades)
        results: list[StressResult] = []
        for count in counts:
            count = _integer(count, "remove count", minimum=0)
            remaining = _remove_best(source, count)
            metrics = self._metrics(remaining)
            results.append(
                StressResult(
                    scenario="remove_best_trades",
                    parameters={"removed_count": min(count, len(source))},
                    metrics=metrics if source else None,
                    status="COMPLETED" if source else "NO_INPUT",
                )
            )
        return results

    def comprehensive(
        self,
        trades: Iterable[TradeResult | Mapping[str, Any]],
    ) -> list[StressResult]:
        """Perturb closed PnL; operational scenarios remain explicitly unmodeled."""

        source = _source_trades(trades)
        results: list[StressResult] = []
        for multiplier in SCENARIO_CONFIG["spread_multipliers"]:
            stressed = [_apply_cost_penalty(trade, spread_multiplier=multiplier, extra_slippage_points=0.0) for trade in source]
            results.append(StressResult("spread_multiplier", {"spread_multiplier": multiplier}, self._metrics(stressed)))
        for multiplier in SCENARIO_CONFIG["slippage_multipliers"]:
            stressed = [_apply_cost_penalty(trade, spread_multiplier=1.0, extra_slippage_points=trade.slippage_points * (multiplier - 1.0)) for trade in source]
            results.append(StressResult("slippage_multiplier", {"slippage_multiplier": multiplier}, self._metrics(stressed)))
        for multiplier in SCENARIO_CONFIG["commission_multipliers"]:
            stressed = [_penalize(trade, trade.commission * (multiplier - 1.0)) for trade in source]
            results.append(StressResult("commission_multiplier", {"commission_multiplier": multiplier}, self._metrics(stressed)))
        for pct in SCENARIO_CONFIG["remove_best_percent"]:
            results.append(self._remove_best_percent(source, pct))
        for count in SCENARIO_CONFIG["losses_added"]:
            loss_trade = _synthetic_loss(source)
            if source and loss_trade is None:
                results.append(StressResult("artificial_loss_streak", {
                    "losses_added": 0, "reason": "NO_NONZERO_OBSERVED_PNL_MAGNITUDE",
                }, None, status="INSUFFICIENT_INPUT"))
                continue
            stressed = list(source) + [loss_trade] * count if loss_trade is not None else list(source)
            metrics = sequence_metrics(stressed, initial_balance=self.initial_balance,
                source_indices=tuple(range(len(source))) + ((None,) * count if loss_trade is not None else ()))
            results.append(StressResult("artificial_loss_streak", {
                "losses_added": count if source else 0,
                "loss_rule": "WORST_OBSERVED_LOSS_OR_NEGATIVE_SMALLEST_ABSOLUTE_PROFIT",
            }, metrics))
        for pct in SCENARIO_CONFIG["periodic_omission_percent"]:
            kept = [trade for index, trade in enumerate(source) if (index + 1) % int(100 / pct) != 0]
            results.append(StressResult("periodic_trade_omission", {
                "nominal_removed_trade_pct": pct, "removed_count": len(source) - len(kept),
            }, self._metrics(kept)))
        haircut = SCENARIO_CONFIG["fixed_profit_haircut_pct"]
        degraded = [_penalize(trade, abs(trade.profit) * haircut / 100) for trade in source]
        results.append(StressResult("fixed_profit_haircut", {"profit_penalty_pct": haircut}, self._metrics(degraded)))
        results.extend(StressResult(name, {"reason": "REQUIRED_EXPLICIT_QUOTE_REPLAY"}, None,
            status="NOT_MODELED", evidence_scope=UNMODELED_SCOPE) for name in UNMODELED_SCENARIOS)
        if not source:
            results = [replace(result, status="NO_INPUT", metrics=None) if result.status == "COMPLETED" else result for result in results]
        return results

    def _remove_best_percent(self, trades: list[TradeResult], pct: int) -> StressResult:
        count = max(1, int(len(trades) * pct / 100.0)) if trades else 0
        remaining = _remove_best(trades, count)
        return StressResult(
            "remove_best_percent",
            {"removed_pct": pct, "removed_count": count},
            self._metrics(remaining),
        )

    def _metrics(self, trades: list[TradeResult]) -> Any:
        # Validate numeric overflow before invoking the calendar metric helper.
        sequence_metrics(trades, initial_balance=self.initial_balance)
        return calculate_metrics(trades, initial_balance=self.initial_balance)


def run_stress_report(
    *,
    trades: Iterable[TradeResult | Mapping[str, Any]] | None = None,
    data_dir: str | Path | None = None,
    symbols: Iterable[str] | None = None,
    report_dir: str | Path,
    initial_balance: float = 10_000.0,
) -> dict[str, Any]:
    """Run stress scenarios and write JSON/CSV reports."""

    input_files: list[str] = []
    upstream_manifest = None
    if trades is None:
        if data_dir is None or symbols is None:
            raise ValueError("either trades or data_dir+symbols is required")
        batch = run_backtest_for_symbols(data_dir=data_dir, symbols=symbols, report_dir=None)
        source = batch.trades.to_dict("records")
        input_files = [str(data_dir)]
        upstream_manifest = batch.summary.get("run_manifest")
    else:
        source = list(trades)
    source = _source_trades(source)
    sample_status = classify_sample_size(len(source))
    results = StressTester(initial_balance=initial_balance).comprehensive(source)
    rows = [_stress_row(item) for item in results]
    classification = _classify_stress(rows)
    if source and len(source) < 30:
        classification = "LOW_SAMPLE_WARNING"
    inputs = {"trades": [_reproducible_trade(trade) for trade in source]}
    config = {
        "evidence_version": EVIDENCE_VERSION, "initial_balance": float(initial_balance),
        "scenarios": SCENARIO_CONFIG, "evidence_scope": APPROXIMATION_SCOPE,
        "cost_model": "FIXED_TICK_VALUE_POST_TRADE_MONETARY_PENALTY",
        "cost_assumptions": {
            "extra_spread_charged_once": True, "extra_slippage_charged_per_side": True,
            "input_commission_is_round_trip": True, "position_resizing": False,
            "fills_replayed": False, "negative_cost_penalties_allowed": False,
            "r_denominator": "ORIGINAL_PNL_DIVIDED_BY_R_OR_INITIAL_SL_DISTANCE",
        },
        "unmodeled_scenarios": list(UNMODELED_SCENARIOS),
        "runtime_versions": _runtime_versions(),
    }
    manifest = _evidence_manifest("stress-test", config, inputs)
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    summary_path = path / "summary.json"
    scenarios_path = path / "scenarios.csv"
    inputs_path = path / "inputs.json"
    details_path = path / "scenarios.json"
    pd.DataFrame(rows).to_csv(scenarios_path, index=False)
    inputs_path.write_text(_canonical_json(inputs), encoding="utf-8")
    details_path.write_text(_canonical_json(_jsonable([asdict(result) for result in results])), encoding="utf-8")
    summary = {
        "mode": "stress-test",
        "input_files": input_files,
        "scenario_count": len(rows),
        "classification": classification,
        "total_trades": len(source),
        "sample_status": sample_status,
        "reports_created": [str(summary_path), str(scenarios_path), str(inputs_path), str(details_path)],
        "execution_attempted": False,
        "evidence_version": EVIDENCE_VERSION,
        "evidence_scope": APPROXIMATION_SCOPE,
        "classification_scope": "OBSERVATIONAL_DIAGNOSTIC_ONLY",
        "effective_config": config,
        "completed_scenario_count": sum(result.status == "COMPLETED" for result in results),
        "not_modeled_scenario_count": sum(result.status == "NOT_MODELED" for result in results),
        "no_input_scenario_count": sum(result.status == "NO_INPUT" for result in results),
        "insufficient_input_scenario_count": sum(result.status == "INSUFFICIENT_INPUT" for result in results),
        "operational_scenarios_tested": False,
        "promotion_eligible": False,
        "upstream_provenance_status": "RECORDED_NOT_AUTHENTICATED" if upstream_manifest else "UNKNOWN",
        "upstream_run_manifest": upstream_manifest,
        "reference_time_policy": "FIXED_IDENTITY_ANCHOR_NOT_MARKET_TIME",
    }
    summary = manifest.attach(summary)
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _ensure_trade(trade: TradeResult | Mapping[str, Any]) -> TradeResult:
    if isinstance(trade, TradeResult):
        return trade
    if not isinstance(trade, Mapping):
        raise ValueError("every stress input must be a complete trade record")
    payload = dict(trade)
    allowed = {field.name for field in fields(TradeResult)}
    extras = {key: value for key, value in payload.items() if key not in allowed}
    clean = {key: value for key, value in payload.items() if key in allowed}
    raw_metadata = clean.get("metadata") or {}
    if isinstance(raw_metadata, str):
        try:
            raw_metadata = json.loads(raw_metadata)
        except ValueError as exc:
            raise ValueError("trade metadata must be a mapping or JSON object") from exc
    if not isinstance(raw_metadata, Mapping):
        raise ValueError("trade metadata must be a mapping")
    metadata = dict(raw_metadata)
    metadata.update(extras)
    clean["metadata"] = metadata
    try:
        return TradeResult(**clean)
    except TypeError as exc:
        raise ValueError("incomplete trade record") from exc


def _source_trades(trades: Iterable[TradeResult | Mapping[str, Any]]) -> list[TradeResult]:
    source = []
    for raw in trades:
        trade = _ensure_trade(raw)
        values = {name: _finite_number(getattr(trade, name), name) for name in (
            "profit", "r_multiple", "mae", "mfe", "duration_seconds", "duration_bars",
            "commission", "spread_points", "slippage_points", "lot", "point", "tick_size", "tick_value",
            "entry_price", "exit_price", "initial_sl_price", "final_sl_price", "tp_price",
        )}
        for name in ("lot", "point", "tick_size", "tick_value", "entry_price", "exit_price", "initial_sl_price", "final_sl_price", "tp_price"):
            if values[name] <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("commission", "spread_points", "slippage_points", "duration_seconds", "duration_bars"):
            if values[name] < 0:
                raise ValueError(f"{name} must be non-negative")
        entry, exit_ = _timestamp(trade.entry_time), _timestamp(trade.exit_time)
        if exit_ < entry:
            raise ValueError("exit_time must not precede entry_time")
        _risk_denominator(trade)
        values["duration_bars"] = _integer(trade.duration_bars, "duration_bars", minimum=0)
        source.append(replace(trade, **values, entry_time=entry.isoformat(), exit_time=exit_.isoformat()))
    return sorted(source, key=lambda trade: (trade.exit_time, trade.entry_time, trade.signal_id))


def _timestamp(value: Any) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("trade timestamps must be timezone-aware") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError("trade timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _nonnegative(value: Any, name: str) -> float:
    number = _finite_number(value, name)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _remove_best(source: list[TradeResult], count: int) -> list[TradeResult]:
    removed = set(sorted(range(len(source)), key=lambda index: source[index].profit, reverse=True)[:count])
    return [trade for index, trade in enumerate(source) if index not in removed]


def _risk_denominator(trade: TradeResult) -> float:
    if trade.profit != 0 and trade.r_multiple != 0:
        risk = trade.profit / trade.r_multiple
    else:
        risk = abs(trade.entry_price - trade.initial_sl_price) / trade.tick_size * trade.tick_value * trade.lot
    return _positive_number(risk, "original risk denominator")


def _penalize(trade: TradeResult, penalty: float) -> TradeResult:
    penalty = _nonnegative(penalty, "cost penalty")
    if penalty == 0:
        return trade
    profit = _finite_number(trade.profit - penalty, "stressed profit")
    r_multiple = _finite_number(profit / _risk_denominator(trade), "stressed r_multiple")
    return replace(trade, profit=profit, r_multiple=r_multiple)


def _reproducible_trade(trade: TradeResult) -> dict[str, Any]:
    # Arbitrary metadata may contain private payloads and is not consumed here.
    payload = {field.name: getattr(trade, field.name) for field in fields(TradeResult) if field.name != "metadata"}
    payload["metadata"] = {}
    return payload


def _apply_cost_penalty(
    trade: TradeResult,
    *,
    spread_multiplier: float,
    extra_slippage_points: float,
) -> TradeResult:
    extra_spread_points = max(0.0, trade.spread_points * (spread_multiplier - 1.0))
    extra_round_trip_points = extra_spread_points + (2.0 * extra_slippage_points)
    penalty = (
        extra_round_trip_points
        * trade.point
        / trade.tick_size
        * trade.tick_value
        * trade.lot
    )
    return _penalize(trade, penalty)


def _synthetic_loss(trades: list[TradeResult]) -> TradeResult | None:
    nonzero = [trade for trade in trades if trade.profit != 0]
    if not nonzero:
        return None
    worst = min(nonzero, key=lambda trade: trade.profit)
    # An all-zero source cannot supply a nonzero observed loss magnitude.
    loss = worst.profit if worst.profit < 0 else -abs(worst.profit)
    return replace(worst, profit=loss, r_multiple=loss / _risk_denominator(worst))


def _stress_row(result: StressResult) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "scenario": result.scenario,
        "parameters": json.dumps(dict(result.parameters), sort_keys=True),
        "status": result.status,
        "evidence_scope": result.evidence_scope,
        "trades": metrics.trades_total if metrics is not None else None,
        "net_profit": metrics.net_profit if metrics is not None else None,
        "net_return_pct": metrics.total_return_pct if metrics is not None else None,
        "profit_factor": metrics.profit_factor if metrics is not None else None,
        "max_drawdown_pct": metrics.max_drawdown_pct if metrics is not None else None,
        "expectancy_r": metrics.average_r if metrics is not None else None,
    }


def _classify_stress(rows: list[dict[str, Any]]) -> str:
    rows = [row for row in rows if row.get("status") == "COMPLETED"]
    if not rows:
        return "REJECTED"
    spread_x2 = [row for row in rows if row["scenario"] == "spread_multiplier" and '"spread_multiplier": 2.0' in row["parameters"]]
    top5 = [row for row in rows if row["scenario"] == "remove_best_percent" and '"removed_pct": 5' in row["parameters"]]
    spread_ok = bool(spread_x2 and spread_x2[0]["net_profit"] > 0)
    top5_ok = bool(top5 and top5[0]["net_profit"] > 0)
    if spread_ok and top5_ok:
        return "APPROVED_FOR_SHADOW_OBSERVATION"
    if spread_ok or top5_ok:
        return "WATCHLIST"
    return "REJECTED"

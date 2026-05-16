"""Controlled strategy research runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..backtesting import BacktestSettings, CostModel, load_historical_csv, run_strategy_backtest
from ..backtesting.stress_tester import StressTester
from .candidate_registry import CandidateRegistry
from .objective_functions import composite_score
from .overfit_guard import assess_overfit
from .parameter_space import generate_research_parameter_sets
from .research_report import write_research_reports
from .strategy_candidate import StrategyCandidate
from .symbol_strategy_selector import build_symbol_strategy_mix


def run_research(
    *,
    symbols: Iterable[str],
    data_dir: str | Path,
    reports_root: str | Path,
    output_dir: str | Path,
    max_candidates: int = 100,
) -> dict[str, Any]:
    """Generate, test, guard and report strategy candidates."""

    data_path = Path(data_dir)
    output = Path(output_dir)
    data_quality = _read_json(Path(reports_root) / "data_quality" / "dataset_manifest.json")
    cost_profile = _read_json(Path(reports_root) / "broker_costs" / "broker_cost_profile.json")
    data_fingerprint = str(data_quality.get("dataset_fingerprint", "unknown"))
    cost_fingerprint = _fingerprint(cost_profile)
    registry = CandidateRegistry()
    tested = 0
    for symbol in [item.strip().upper() for item in symbols if item.strip()]:
        csv_path = _find_csv(data_path, symbol)
        candles, _quality = load_historical_csv(csv_path, symbol=symbol, timeframe="M5")
        spread = _spread_for_symbol(cost_profile, symbol)
        settings = BacktestSettings(
            cost_model=CostModel(spread_points=spread, slippage_points=1.0, max_spread_points=max(25.0, spread * 2)),
            max_bars_in_trade=96,
            break_even_trigger_r=0.6,
            trailing_start_r=0.8,
        )
        for strategy_name, params in generate_research_parameter_sets(max_candidates=max_candidates):
            if tested >= max_candidates:
                break
            candidate = StrategyCandidate.build(
                strategy_name=strategy_name,
                symbol=symbol,
                params=params,
                regime="ANY",
                session=str(params.get("session", "ANY")),
                data_fingerprint=data_fingerprint,
                cost_profile_fingerprint=cost_fingerprint,
            )
            outcome = run_strategy_backtest(candles, symbol=symbol, settings=settings)
            metrics = {
                "total_trades": outcome.metrics.trades_total,
                "profit_factor": outcome.metrics.profit_factor,
                "expectancy_r": outcome.metrics.average_r,
                "max_drawdown_pct": outcome.metrics.max_drawdown_pct,
                "net_return_pct": outcome.metrics.total_return_pct,
                "max_allowed_spread_points": spread,
            }
            metrics["composite_score"] = composite_score(metrics)
            stress_results = StressTester().comprehensive(outcome.trades)
            stress_summary = {"classification": "REJECTED" if any(row.metrics.net_profit < 0 for row in stress_results) else "WATCHLIST"}
            assessment = assess_overfit(
                train_metrics=metrics,
                test_metrics=metrics,
                trades_summary=_trade_concentration(outcome),
                stress_summary=stress_summary,
            )
            status = assessment.recommended_status
            if status == "APPROVED_FOR_SHADOW_OBSERVATION" and metrics["composite_score"] < 80:
                status = "WATCHLIST"
            if outcome.metrics.trades_total == 0:
                status = "REJECTED"
            updated = candidate.with_status(
                status,
                rejection_reason="; ".join(assessment.reasons) if status == "REJECTED" else "",
                metrics_summary=metrics,
                validation_artifacts={"overfit_risk": assessment.overfit_risk},
            )
            registry.add(updated)
            tested += 1
        if tested >= max_candidates:
            break
    mix = build_symbol_strategy_mix(registry.list())
    summary = {
        "mode": "research",
        "candidates_tested": len(registry.list()),
        "approved_for_shadow_observation": len(registry.list(status="APPROVED_FOR_SHADOW_OBSERVATION")),
        "watchlist": len(registry.list(status="WATCHLIST")),
        "rejected": len(registry.list(status="REJECTED")),
        "best_candidates": [item.to_dict() for item in registry.top(limit=5)],
        "classification": _classification(registry),
        "execution_attempted": False,
        "reports_created": [],
    }
    reports = write_research_reports(output_dir=output, registry=registry, recommended_mix=mix, summary=summary)
    summary["reports_created"] = reports
    (output / "research_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _find_csv(data_dir: Path, symbol: str) -> Path:
    for candidate in (data_dir / f"{symbol}_M5.csv", data_dir / f"{symbol}.csv"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no M5 CSV for {symbol}")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _fingerprint(payload: dict[str, Any]) -> str:
    import hashlib

    if not payload:
        return "unknown"
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _spread_for_symbol(profile: dict[str, Any], symbol: str) -> float:
    return float(profile.get("symbols", {}).get(symbol, {}).get("spread_p95", 10.0) or 10.0)


def _trade_concentration(outcome: Any) -> dict[str, Any]:
    frame = outcome.trades_frame()
    if frame.empty:
        return {"top_5_profit_concentration_pct": 100, "profitable_days": 0, "profitable_sessions": 0}
    positive = frame[frame["profit"] > 0].copy()
    total_positive = float(positive["profit"].sum()) if not positive.empty else 0.0
    top_count = max(1, int(len(frame) * 0.05))
    top_profit = float(frame.sort_values("profit", ascending=False).head(top_count)["profit"].clip(lower=0).sum())
    concentration = top_profit / total_positive * 100.0 if total_positive > 0 else 100.0
    positive["day"] = positive["exit_time"].astype(str).str[:10]
    return {
        "top_5_profit_concentration_pct": concentration,
        "profitable_days": int(positive["day"].nunique()) if not positive.empty else 0,
        "profitable_sessions": int(positive.get("session", []).nunique()) if "session" in positive else 0,
    }


def _classification(registry: CandidateRegistry) -> str:
    if registry.list(status="APPROVED_FOR_SHADOW_OBSERVATION"):
        return "APPROVED_FOR_SHADOW_OBSERVATION"
    if registry.list(status="WATCHLIST"):
        return "WATCHLIST"
    return "REJECTED"

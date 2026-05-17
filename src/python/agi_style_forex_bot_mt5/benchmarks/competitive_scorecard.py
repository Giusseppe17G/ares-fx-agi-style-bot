"""Competitive scorecard against baselines and validation criteria."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def build_competitive_scorecard(
    *,
    reports_root: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build global competitive scorecard from report artifacts."""

    root = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    backtest = _read_json(root / "backtests" / "summary.json")
    benchmark = _read_json(root / "benchmarks" / "summary.json")
    monte_carlo = _read_json(root / "monte_carlo" / "summary.json")
    stress = _read_json(root / "stress" / "summary.json")
    walk_forward = _read_json(root / "walk_forward" / "summary.json")
    baseline_count = int(benchmark.get("baselines_beaten_global", 0) or 0)
    reasons: list[str] = []
    benchmark_classification = str(benchmark.get("classification", "")).upper()
    oos_ok = str(walk_forward.get("classification", "REJECTED")) == "APPROVED_FOR_SHADOW_OBSERVATION"
    monte_ok = str(monte_carlo.get("classification", "REJECTED")) != "REJECTED"
    stress_ok = str(stress.get("classification", "REJECTED")) != "REJECTED"
    top5_ok = _stress_top5_survived(root / "stress" / "scenarios.csv")
    base_edge = float(backtest.get("expectancy_r", 0) or 0) > 0 and float(backtest.get("profit_factor", 0) or 0) > 1.0
    robustness_score = _score(
        baseline_count=baseline_count,
        oos_ok=oos_ok,
        monte_ok=monte_ok,
        stress_ok=stress_ok,
        top5_ok=top5_ok,
        base_edge=base_edge,
    )
    if benchmark_classification == "NEEDS_MORE_DATA":
        classification = "NEEDS_MORE_DATA"
        reasons.append("benchmark data insufficient")
    elif baseline_count >= 3 and oos_ok and monte_ok and stress_ok and top5_ok and base_edge:
        classification = "COMPETITIVE_CANDIDATE"
    elif base_edge and baseline_count >= 2:
        classification = "NEEDS_OPTIMIZATION"
    elif base_edge:
        classification = "WEAK_EDGE"
    else:
        classification = "REJECTED"
    row = {
        "classification": classification,
        "net_return_pct": backtest.get("net_return_pct", 0),
        "profit_factor": backtest.get("profit_factor", 0),
        "max_drawdown_pct": backtest.get("max_drawdown_pct", 0),
        "expectancy_r": backtest.get("expectancy_r", 0),
        "sharpe": backtest.get("sharpe"),
        "sortino": backtest.get("sortino"),
        "winrate": backtest.get("winrate", 0),
        "trades_count": backtest.get("total_trades", 0),
        "robustness_score": robustness_score,
        "monte_carlo_risk": monte_carlo.get("probability_of_ruin"),
        "stress_survival_score": 1.0 if stress_ok else 0.0,
        "oos_score": 1.0 if oos_ok else 0.0,
        "cost_sensitivity_score": 1.0 if stress_ok and top5_ok else 0.0,
        "baselines_beaten": baseline_count,
    }
    json_path = output / "competitive_scorecard.json"
    csv_path = output / "competitive_scorecard.csv"
    html_path = output / "competitive_scorecard.html"
    summary = {
        "mode": "competitive-scorecard",
        "classification": classification,
        "reasons": reasons,
        "scorecard": row,
        "reports_created": [str(json_path), str(csv_path), str(html_path)],
        "execution_attempted": False,
    }
    json_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame([row]).to_csv(csv_path, index=False)
    html_path.write_text(_html(summary), encoding="utf-8")
    return summary


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _stress_top5_survived(path: Path) -> bool:
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    if frame.empty:
        return False
    rows = frame[(frame["scenario"] == "remove_best_percent") & frame["parameters"].astype(str).str.contains('"removed_pct": 5')]
    return bool(len(rows) and float(rows.iloc[0].get("net_profit", 0)) > 0)


def _score(**checks: Any) -> float:
    score = min(40.0, float(checks["baseline_count"]) / 6.0 * 40.0)
    for key in ("oos_ok", "monte_ok", "stress_ok", "top5_ok", "base_edge"):
        if checks[key]:
            score += 12.0
    return min(100.0, score)


def _html(summary: Mapping[str, Any]) -> str:
    rows = "\n".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in summary["scorecard"].items())
    return f"<!doctype html><html><body><h1>Competitive Scorecard</h1><table>{rows}</table></body></html>"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

"""Report writer for robustness-fast CLI mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..backtesting import classify_sample_size
from ..calibration import profile_allowed_for_shadow
from ..calibration.signal_profile import get_signal_profile
from .cost_sensitivity import analyze_cost_sensitivity
from .monte_carlo_fast import run_monte_carlo_fast
from .robustness_decision_engine import decide_robustness
from .robustness_runner import jsonable, load_balanced_trades, load_profile_summary, metrics_from_values, trade_values, write_json
from .stress_fast import run_stress_fast
from .walk_forward_fast import run_walk_forward_fast


def run_robustness_fast(
    *,
    runs_root: str | Path = "data/runs",
    profile_runs_dir: str | Path = "data/reports/profile_runs",
    profile: str = "BALANCED",
    output_dir: str | Path = "data/reports/robustness",
    simulations: int = 1000,
    seed: int = 0,
) -> dict[str, Any]:
    """Run fast robustness validation from existing artifacts."""

    profile_cfg = get_signal_profile(profile)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trades, trades_source, metrics_source = load_balanced_trades(runs_root=runs_root, profile_runs_dir=profile_runs_dir, profile=profile_cfg.name)
    profile_summary = load_profile_summary(profile_runs_dir, profile_cfg.name)
    values = trade_values(trades)
    base_metrics = metrics_from_values(values.tolist()) if not values.empty else _base_metrics_from_summary(profile_summary)
    base_metrics["sample_status"] = classify_sample_size(int(base_metrics.get("total_trades", 0) or 0))
    base_metrics["metrics_source"] = metrics_source if not values.empty else ("profile_summary" if profile_summary else "none")
    mc_summary, mc_frame = run_monte_carlo_fast(trades, simulations=simulations, seed=seed, metrics_only=profile_summary)
    stress_summary, stress_frame = run_stress_fast(trades)
    wf_summary, wf_frame = run_walk_forward_fast(trades)
    cost_summary, cost_frame = analyze_cost_sensitivity(trades)
    decision = decide_robustness(
        profile=profile_cfg.name,
        base_metrics=base_metrics,
        monte_carlo=mc_summary,
        stress=stress_summary,
        walk_forward=wf_summary,
        cost_sensitivity=cost_summary,
        profile_allowed_for_shadow=profile_allowed_for_shadow(profile_cfg.name),
        not_for_demo_live=bool(profile_cfg.not_for_demo_live),
    )
    paths = _write_reports(
        output,
        base_metrics=base_metrics,
        monte_carlo=mc_summary,
        monte_carlo_frame=mc_frame,
        stress=stress_summary,
        stress_frame=stress_frame,
        walk_forward=wf_summary,
        walk_forward_frame=wf_frame,
        cost=cost_summary,
        cost_frame=cost_frame,
    )
    summary = {
        "mode": "robustness-fast",
        "profile": profile_cfg.name,
        "classification": decision["robustness_decision"],
        "robustness_decision": decision["robustness_decision"],
        "reason": decision["reason"],
        "trades_source": trades_source,
        "metrics_source": base_metrics["metrics_source"],
        "total_trades": int(base_metrics.get("total_trades", 0) or 0),
        "sample_status": base_metrics.get("sample_status", ""),
        "profit_factor": base_metrics.get("profit_factor"),
        "expectancy_r": base_metrics.get("expectancy_r"),
        "monte_carlo_classification": mc_summary.get("classification"),
        "stress_classification": stress_summary.get("classification"),
        "walk_forward_classification": wf_summary.get("classification"),
        "cost_sensitivity_classification": cost_summary.get("classification"),
        "paper_forward_shadow_candidate": decision["robustness_decision"] == "PAPER_FORWARD_SHADOW_CANDIDATE",
        "profile_allowed_for_shadow": profile_allowed_for_shadow(profile_cfg.name),
        "not_for_demo_live": bool(profile_cfg.not_for_demo_live),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "reports_created": paths,
    }
    summary_path = output / "robustness_summary.json"
    write_json(summary_path, summary)
    pd.DataFrame([summary]).to_csv(output / "robustness_summary.csv", index=False)
    _write_html(output / "report.html", summary)
    summary["reports_created"].extend([str(summary_path), str(output / "robustness_summary.csv"), str(output / "report.html")])
    write_json(summary_path, summary)
    return jsonable(summary)


def _write_reports(
    output: Path,
    *,
    base_metrics: dict[str, Any],
    monte_carlo: dict[str, Any],
    monte_carlo_frame: pd.DataFrame,
    stress: dict[str, Any],
    stress_frame: pd.DataFrame,
    walk_forward: dict[str, Any],
    walk_forward_frame: pd.DataFrame,
    cost: dict[str, Any],
    cost_frame: pd.DataFrame,
) -> list[str]:
    paths = {
        "monte_json": output / "monte_carlo_fast.json",
        "monte_csv": output / "monte_carlo_fast.csv",
        "stress_json": output / "stress_fast.json",
        "stress_csv": output / "stress_fast.csv",
        "wf_json": output / "walk_forward_fast.json",
        "wf_csv": output / "walk_forward_fast.csv",
        "cost_json": output / "cost_sensitivity.json",
        "cost_csv": output / "cost_sensitivity.csv",
    }
    write_json(paths["monte_json"], monte_carlo)
    monte_carlo_frame.to_csv(paths["monte_csv"], index=False)
    write_json(paths["stress_json"], stress)
    stress_frame.to_csv(paths["stress_csv"], index=False)
    write_json(paths["wf_json"], walk_forward)
    walk_forward_frame.to_csv(paths["wf_csv"], index=False)
    write_json(paths["cost_json"], cost)
    cost_frame.to_csv(paths["cost_csv"], index=False)
    write_json(output / "base_metrics.json", base_metrics)
    return [str(path) for path in paths.values()]


def _base_metrics_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_trades": int(float(summary.get("trades_generated", summary.get("total_trades", 0)) or 0)),
        "profit_factor": _number(summary.get("profit_factor")),
        "expectancy_r": _number(summary.get("expectancy_r")),
        "winrate": _number(summary.get("winrate")),
        "net_value": _number(summary.get("net_profit")),
    }


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_html(path: Path, summary: dict[str, Any]) -> None:
    rows = "\n".join(f"<tr><th>{key}</th><td>{jsonable(value)}</td></tr>" for key, value in summary.items() if key != "reports_created")
    path.write_text(f"<html><body><h1>Robustness Fast Track</h1><p>Paper/shadow validation only. No demo/live execution.</p><table>{rows}</table></body></html>", encoding="utf-8")

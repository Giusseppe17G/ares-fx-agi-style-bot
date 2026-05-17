"""Report writer for robustness-fast CLI mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..backtesting import classify_sample_size
from ..calibration import profile_allowed_for_shadow
from ..calibration.effective_profile_config import effective_profile_config
from ..calibration.signal_profile import get_signal_profile
from .cost_sensitivity import analyze_cost_sensitivity
from .monte_carlo_fast import run_monte_carlo_fast
from .robustness_decision_engine import decide_robustness
from .robustness_runner import jsonable, load_balanced_trades, load_latest_profile_run_summary, load_profile_summary, metrics_from_values, trade_values, write_json
from .stress_fast import run_stress_fast
from .walk_forward_fast import run_walk_forward_fast


def run_robustness_fast(
    *,
    runs_root: str | Path = "data/runs",
    profile_runs_dir: str | Path = "data/reports/profile_runs",
    profile: str = "BALANCED",
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/robustness",
    simulations: int = 1000,
    seed: int = 0,
) -> dict[str, Any]:
    """Run fast robustness validation from existing artifacts."""

    profile_cfg = get_signal_profile(profile)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trades, trades_source, metrics_source = load_balanced_trades(runs_root=runs_root, profile_runs_dir=profile_runs_dir, profile=profile_cfg.name)
    profile_summary = load_profile_summary(profile_runs_dir, profile_cfg.name) or load_latest_profile_run_summary(runs_root, profile_cfg.name)
    values = trade_values(trades)
    base_metrics = metrics_from_values(values.tolist()) if not values.empty else _base_metrics_from_summary(profile_summary)
    base_metrics["sample_status"] = classify_sample_size(int(base_metrics.get("total_trades", 0) or 0))
    base_metrics["metrics_source"] = metrics_source if not values.empty else ("profile_summary" if profile_summary else "none")
    mc_summary, mc_frame = run_monte_carlo_fast(trades, simulations=simulations, seed=seed, metrics_only=profile_summary)
    stress_summary, stress_frame = run_stress_fast(trades)
    wf_summary, wf_frame = run_walk_forward_fast(trades)
    cost_summary, cost_frame = analyze_cost_sensitivity(trades)
    effective = effective_profile_config(profile_cfg.name, source="robustness-fast", profile_config=profile_config)
    stable_filters = _stable_filters_payload(profile_cfg.name, profile_config, profile_summary)
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
        "profile_config": str(profile_config or ""),
        "stable_filters_applied": bool(stable_filters.get("enabled", False)),
        "stable_filters": stable_filters,
        "profile_hash": effective.profile_hash,
        "classification": decision["robustness_decision"],
        "robustness_decision": decision["robustness_decision"],
        "reason": decision["reason"],
        "trades_source": trades_source,
        "metrics_source": base_metrics["metrics_source"],
        "total_trades": int(base_metrics.get("total_trades", 0) or 0),
        "sample_status": base_metrics.get("sample_status", ""),
        "profit_factor": base_metrics.get("profit_factor"),
        "expectancy_r": base_metrics.get("expectancy_r"),
        "winrate": base_metrics.get("winrate"),
        "monte_carlo_classification": mc_summary.get("classification"),
        "stress_classification": stress_summary.get("classification"),
        "walk_forward_classification": wf_summary.get("classification"),
        "cost_sensitivity_classification": cost_summary.get("classification"),
        "stable_gate_decision": "",
        "paper_shadow_ready": False,
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


def _stable_filters_payload(profile: str, profile_config: str | Path | None, summary: dict[str, Any]) -> dict[str, Any]:
    if profile.strip().upper() != "BALANCED_STABLE":
        return {"profile": profile.strip().upper(), "enabled": False}
    values = _read_simple_ini(Path(profile_config)) if profile_config else {}
    embedded = summary.get("stable_filters_applied") if isinstance(summary.get("stable_filters_applied"), dict) else {}
    enabled = str(values.get("APPLY_STABILITY_FILTERS", values.get("STABILITY_FILTERS_APPLIED", ""))).strip().lower() == "true"
    if not enabled and embedded:
        enabled = bool(embedded.get("enabled", False))
    return {
        "profile": "BALANCED_STABLE",
        "enabled": bool(enabled),
        "profile_config": str(profile_config or ""),
        "disabled_symbols": _csv_values(values.get("DISABLED_SYMBOLS", "")) or list(embedded.get("disabled_symbols", [])),
        "disabled_strategies": _csv_values(values.get("DISABLED_STRATEGIES", "")) or list(embedded.get("disabled_strategies", [])),
        "blocked_sessions": _csv_values(values.get("BLOCKED_SESSIONS", "")) or list(embedded.get("blocked_sessions", [])),
        "blocked_regimes": _csv_values(values.get("BLOCKED_REGIMES", "")) or list(embedded.get("blocked_regimes", [])),
    }


def _read_simple_ini(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _csv_values(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _write_html(path: Path, summary: dict[str, Any]) -> None:
    rows = "\n".join(f"<tr><th>{key}</th><td>{jsonable(value)}</td></tr>" for key, value in summary.items() if key != "reports_created")
    path.write_text(f"<html><body><h1>Robustness Fast Track</h1><p>Paper/shadow validation only. No demo/live execution.</p><table>{rows}</table></body></html>", encoding="utf-8")

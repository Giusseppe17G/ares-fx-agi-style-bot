"""Paper shadow readiness gate for BALANCED_STABLE."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .robustness_runner import jsonable, write_json


def run_stable_robustness_gate(
    *,
    runs_root: str | Path = "data/runs",
    robustness_dir: str | Path = "data/reports/robustness",
    stability_dir: str | Path = "data/reports/stability_repair",
    profile: str = "BALANCED_STABLE",
    output_dir: str | Path = "data/reports/stable_gate",
) -> dict[str, Any]:
    """Evaluate whether BALANCED_STABLE is ready for paper/shadow observation only."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    robustness = _load_robustness_summary(Path(robustness_dir), Path(runs_root))
    stability = _load_json(Path(stability_dir) / "walk_forward_failure_summary.json")
    decision = decide_stable_shadow_readiness(profile=profile, robustness=robustness, stability=stability)
    summary = {
        "mode": "stable-robustness-gate",
        "profile": profile.strip().upper(),
        "robustness_dir": str(robustness_dir),
        "stability_dir": str(stability_dir),
        "total_trades": int(_number(robustness.get("total_trades")) or 0),
        "sample_status": robustness.get("sample_status", ""),
        "profit_factor": robustness.get("profit_factor"),
        "expectancy_r": robustness.get("expectancy_r"),
        "winrate": robustness.get("winrate"),
        "monte_carlo_classification": robustness.get("monte_carlo_classification", ""),
        "stress_classification": robustness.get("stress_classification", ""),
        "walk_forward_classification": robustness.get("walk_forward_classification", ""),
        "cost_sensitivity_classification": robustness.get("cost_sensitivity_classification", ""),
        "stable_filters_applied": bool(robustness.get("stable_filters_applied", False)),
        "not_for_demo_live": bool(robustness.get("not_for_demo_live", True)),
        "stable_gate_decision": decision["stable_gate_decision"],
        "classification": decision["stable_gate_decision"],
        "paper_shadow_ready": decision["stable_gate_decision"] == "PAPER_SHADOW_READY",
        "reason": decision["reason"],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    if robustness:
        updated_robustness = {
            **dict(robustness),
            "stable_gate_decision": summary["stable_gate_decision"],
            "paper_shadow_ready": summary["paper_shadow_ready"],
        }
        robustness_path = Path(robustness_dir) / "robustness_summary.json"
        if robustness_path.exists():
            write_json(robustness_path, updated_robustness)
    reports = _write_reports(output, summary)
    summary["reports_created"] = reports
    write_json(output / "stable_gate_summary.json", summary)
    return jsonable(summary)


def decide_stable_shadow_readiness(*, profile: str, robustness: Mapping[str, Any], stability: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the conservative BALANCED_STABLE paper/shadow readiness decision."""

    profile_name = profile.strip().upper()
    total = int(_number(robustness.get("total_trades")) or 0)
    sample_status = str(robustness.get("sample_status", ""))
    pf = _number(robustness.get("profit_factor"))
    expectancy = _number(robustness.get("expectancy_r"))
    mc = str(robustness.get("monte_carlo_classification", ""))
    stress = str(robustness.get("stress_classification", ""))
    walk_forward = str(robustness.get("walk_forward_classification", ""))
    cost = str(robustness.get("cost_sensitivity_classification", ""))
    stable_filters = bool(robustness.get("stable_filters_applied", False))
    execution_attempted = bool(robustness.get("execution_attempted", False))
    not_for_demo_live = bool(robustness.get("not_for_demo_live", True))
    if profile_name != "BALANCED_STABLE":
        return _decision("REJECT_STABLE_PROFILE", "Stable gate only accepts BALANCED_STABLE.")
    if execution_attempted:
        return _decision("REJECT_STABLE_PROFILE", "Robustness artifact indicates execution_attempted=true.")
    if not stable_filters:
        return _decision("NEEDS_STABILITY_REWORK", "BALANCED_STABLE did not apply stability filters.")
    if not not_for_demo_live:
        return _decision("REJECT_STABLE_PROFILE", "BALANCED_STABLE must remain NOT_FOR_DEMO_LIVE=true.")
    if total < 100 or sample_status not in {"USABLE_SAMPLE", "PROMOTION_SAMPLE_SIZE"}:
        return _decision("NEEDS_MORE_STABLE_DATA", "BALANCED_STABLE needs at least 100 trades and a usable sample.")
    if pf is None or expectancy is None or pf < 1.20 or expectancy <= 0:
        return _decision("NEEDS_STABILITY_REWORK", "Stable profile edge metrics do not meet the paper-shadow gate.")
    if mc not in {"MONTE_CARLO_OK", "MONTE_CARLO_WARNING"}:
        return _decision("NEEDS_MORE_STABLE_DATA", "Monte Carlo evidence is missing or insufficient.")
    if stress == "STRESS_FAILED":
        return _decision("NEEDS_COST_RECALIBRATION", "Stress test is critical under cost/scenario expansion.")
    if walk_forward in {"NEEDS_MORE_WALK_FORWARD_DATA", "WALK_FORWARD_CRITICAL"}:
        return _decision("NEEDS_STABILITY_REWORK", "Walk-forward evidence is critical or insufficient.")
    if cost in {"NEEDS_COST_RECALIBRATION", "COST_FRAGILE"}:
        return _decision("NEEDS_COST_RECALIBRATION", "Cost sensitivity is not stable enough for paper-shadow observation.")
    return _decision("PAPER_SHADOW_READY", "BALANCED_STABLE passed the conservative paper/shadow readiness gate. Demo/live remain disabled.")


def _write_reports(output: Path, summary: dict[str, Any]) -> list[str]:
    json_path = output / "stable_gate_summary.json"
    csv_path = output / "stable_gate_summary.csv"
    html_path = output / "report.html"
    write_json(json_path, summary)
    pd.DataFrame([summary]).to_csv(csv_path, index=False)
    rows = "\n".join(f"<tr><th>{key}</th><td>{jsonable(value)}</td></tr>" for key, value in summary.items() if key != "reports_created")
    html_path.write_text(
        f"<html><body><h1>BALANCED_STABLE Shadow Readiness Gate</h1><p>Paper/shadow only. No demo/live execution.</p><table>{rows}</table></body></html>",
        encoding="utf-8",
    )
    return [str(json_path), str(csv_path), str(html_path)]


def _load_robustness_summary(robustness_dir: Path, runs_root: Path) -> dict[str, Any]:
    for path in (
        robustness_dir / "robustness_summary.json",
        runs_root / "robustness" / "robustness_summary.json",
    ):
        payload = _load_json(path)
        if payload:
            return payload
    return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _decision(decision: str, reason: str) -> dict[str, Any]:
    return {"stable_gate_decision": decision, "reason": reason, "execution_attempted": False}


def _number(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

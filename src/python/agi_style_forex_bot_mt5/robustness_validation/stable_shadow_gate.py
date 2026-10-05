"""Paper shadow readiness gate for BALANCED_STABLE."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .robustness_runner import jsonable, write_json

GATE_CONTRACT_VERSION = "stable_shadow_gate_v2"
ALLOWED_MONTE_CARLO = frozenset({"MONTE_CARLO_OK", "MONTE_CARLO_WARNING"})
ALLOWED_STRESS = frozenset({"STRESS_OK", "STRESS_WARNING"})
ALLOWED_WALK_FORWARD = frozenset({"WALK_FORWARD_OK", "WALK_FORWARD_WARNING"})
ALLOWED_COST = frozenset({"COST_SENSITIVITY_OK"})


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
        "profile": _profile_name(profile),
        "gate_contract_version": GATE_CONTRACT_VERSION,
        "robustness_dir": str(robustness_dir),
        "stability_dir": str(stability_dir),
        "total_trades": _count(robustness.get("total_trades")),
        "sample_status": _state(robustness.get("sample_status")),
        "profit_factor": _number(robustness.get("profit_factor")),
        "expectancy_r": _number(robustness.get("expectancy_r")),
        "winrate": _number(robustness.get("winrate")),
        "monte_carlo_classification": _state(robustness.get("monte_carlo_classification")),
        "stress_classification": _state(robustness.get("stress_classification")),
        "walk_forward_classification": _state(robustness.get("walk_forward_classification")),
        "cost_sensitivity_classification": _state(robustness.get("cost_sensitivity_classification")),
        "stable_filters_applied": _boolean(robustness.get("stable_filters_applied")),
        "not_for_demo_live": _boolean(robustness.get("not_for_demo_live")),
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

    if not isinstance(robustness, Mapping):
        return _decision("REJECT_STABLE_PROFILE", "Robustness evidence must be an object.")
    profile_name = _profile_name(profile)
    total = _count(robustness.get("total_trades"))
    sample_status = _state(robustness.get("sample_status"))
    pf = _number(robustness.get("profit_factor"))
    expectancy = _number(robustness.get("expectancy_r"))
    mc = _state(robustness.get("monte_carlo_classification"))
    stress = _state(robustness.get("stress_classification"))
    walk_forward = _state(robustness.get("walk_forward_classification"))
    cost = _state(robustness.get("cost_sensitivity_classification"))
    if profile_name != "BALANCED_STABLE" or _profile_name(robustness.get("profile")) != profile_name:
        return _decision("REJECT_STABLE_PROFILE", "Requested and evidence profiles must both identify BALANCED_STABLE.")
    if robustness.get("execution_attempted") is not False:
        return _decision("REJECT_STABLE_PROFILE", "Robustness artifact requires explicit execution_attempted=false.")
    for flag in ("order_send_called", "order_check_called"):
        if flag in robustness and robustness[flag] is not False:
            return _decision("REJECT_STABLE_PROFILE", f"Robustness artifact has invalid or unsafe {flag}.")
    if robustness.get("not_for_demo_live") is not True:
        return _decision("REJECT_STABLE_PROFILE", "BALANCED_STABLE requires explicit NOT_FOR_DEMO_LIVE=true.")
    if robustness.get("stable_filters_applied") is not True:
        return _decision("NEEDS_STABILITY_REWORK", "BALANCED_STABLE requires verified boolean stability filters.")
    if total is None or total < 100 or sample_status not in {"USABLE_SAMPLE", "PROMOTION_SAMPLE_SIZE"}:
        return _decision("NEEDS_MORE_STABLE_DATA", "BALANCED_STABLE needs at least 100 trades and a usable sample.")
    if pf is None or expectancy is None or pf < 1.20 or expectancy <= 0:
        return _decision("NEEDS_STABILITY_REWORK", "Stable profile edge metrics do not meet the paper-shadow gate.")
    if "winrate" in robustness:
        winrate = _number(robustness["winrate"])
        if winrate is None or not 0 <= winrate <= 100:
            return _decision("NEEDS_STABILITY_REWORK", "Reported winrate must be a finite percentage in [0, 100].")
    if mc not in ALLOWED_MONTE_CARLO:
        return _decision("NEEDS_MORE_STABLE_DATA", "Monte Carlo evidence is missing or insufficient.")
    if stress == "STRESS_FAILED":
        return _decision("NEEDS_COST_RECALIBRATION", "Stress test is critical under cost/scenario expansion.")
    if stress not in ALLOWED_STRESS:
        return _decision("NEEDS_MORE_STABLE_DATA", "Stress evidence is missing, unknown or insufficient.")
    if walk_forward not in ALLOWED_WALK_FORWARD:
        return _decision("NEEDS_STABILITY_REWORK", "Walk-forward evidence is critical or insufficient.")
    if cost in {"NEEDS_COST_RECALIBRATION", "COST_FRAGILE"}:
        return _decision("NEEDS_COST_RECALIBRATION", "Cost sensitivity is not stable enough for paper-shadow observation.")
    if cost not in ALLOWED_COST:
        return _decision("NEEDS_MORE_STABLE_DATA", "Cost sensitivity evidence is missing, unknown or insufficient.")
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
        if path.exists():
            # An invalid preferred artifact cannot borrow approval from an old fallback.
            return _load_json(path)
    return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _decision(decision: str, reason: str) -> dict[str, Any]:
    return {"stable_gate_decision": decision, "reason": reason, "execution_attempted": False}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _count(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number >= 0 and number.is_integer() else None


def _state(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _profile_name(value: Any) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")

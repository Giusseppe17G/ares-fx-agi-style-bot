"""Conservative BALANCED candidate gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .profile_integrity_checker import run_profile_integrity
from .profile_metric_comparator import load_profile_rows


def run_balanced_candidate_gate(
    *,
    runs_root: str | Path,
    profile_runs_dir: str | Path,
    edge_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Evaluate whether BALANCED is only a paper/shadow candidate or still blocked."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    integrity = _load_json(output / "profile_integrity.json")
    if not integrity:
        integrity = run_profile_integrity(profile_runs_dir=profile_runs_dir, output_dir=output)
    balanced = _balanced_row(profile_runs_dir)
    edge = _load_json(Path(edge_dir) / "edge_summary.json")
    latest = _latest_summary(Path(runs_root))
    decision, reason = _decision(balanced=balanced, integrity=integrity, edge=edge, latest=latest)
    summary = {
        "mode": "balanced-candidate-gate",
        "balanced_decision": decision,
        "reason": reason,
        "profile_integrity_status": integrity.get("profile_integrity_status", ""),
        "active_vs_balanced_similarity": integrity.get("active_vs_balanced_similarity", ""),
        "balanced_metrics": balanced,
        "edge_decision": edge.get("decision", ""),
        "execution_attempted": False,
        "reports_created": [],
    }
    json_path = output / "balanced_candidate_gate.json"
    html_path = output / "balanced_candidate_gate.html"
    json_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text(_html(summary), encoding="utf-8")
    summary["reports_created"] = [str(json_path), str(html_path)]
    json_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    return _jsonable(summary)


def _decision(*, balanced: dict[str, Any], integrity: dict[str, Any], edge: dict[str, Any], latest: dict[str, Any]) -> tuple[str, str]:
    if integrity.get("profile_integrity_status") == "FAILED":
        return "BALANCED_METRICS_UNTRUSTED", "Profile comparison has duplicated or untrusted metrics."
    if not balanced:
        return "BALANCED_NEEDS_MORE_DATA", "BALANCED profile metrics are missing."
    total = int(_number(balanced.get("trades_generated", balanced.get("total_trades", 0))) or 0)
    pf = _number(balanced.get("profit_factor"))
    expectancy = _number(balanced.get("expectancy_r"))
    drawdown = _number(balanced.get("max_drawdown_pct"))
    metrics_status = str(balanced.get("metrics_status", edge.get("metrics_status", "")))
    sample_status = str(balanced.get("sample_status", latest.get("sample_status", "")))
    allowed_for_shadow = _bool_value(balanced.get("allowed_for_shadow", balanced.get("profile_allowed_for_shadow", False)))
    not_for_demo_live = _bool_value(balanced.get("not_for_demo_live", False))
    if metrics_status != "FULL_EDGE_METRICS" or pf is None or expectancy is None:
        return "BALANCED_NEEDS_MORE_DATA", "BALANCED requires full edge metrics before candidate review."
    if not allowed_for_shadow or not_for_demo_live:
        return "BALANCED_REJECTED", "BALANCED profile safety flags do not allow paper/shadow candidate status."
    if total < 100 or sample_status not in {"USABLE_SAMPLE", "PROMOTION_SAMPLE_SIZE"}:
        return "BALANCED_NEEDS_MORE_DATA", "BALANCED needs at least 100 trades and a usable sample."
    if pf < 1.20 or expectancy <= 0:
        return "BALANCED_REJECTED", "BALANCED profit factor or expectancy is insufficient."
    if drawdown is not None and drawdown > 12.0:
        return "BALANCED_REJECTED", "BALANCED drawdown exceeds the conservative gate."
    return "BALANCED_NEEDS_ROBUSTNESS_VALIDATION", "BALANCED has positive edge metrics but still needs walk-forward, Monte Carlo and stress validation."


def _balanced_row(profile_runs_dir: str | Path) -> dict[str, Any]:
    for row in load_profile_rows(profile_runs_dir):
        if str(row.get("profile", "")).upper() == "BALANCED":
            return dict(row)
    return {}


def _latest_summary(runs_root: Path) -> dict[str, Any]:
    if not runs_root.exists():
        return {}
    candidates = [path for path in runs_root.iterdir() if path.is_dir() and (path / "final_summary_compact.json").exists()]
    if not candidates:
        return {}
    latest = sorted(candidates, key=lambda path: (path.stat().st_mtime, path.name))[-1]
    return _load_json(latest / "final_summary_compact.json")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"} if not isinstance(value, bool) else value


def _html(summary: dict[str, Any]) -> str:
    rows = "\n".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in summary.items() if key != "reports_created")
    return f"<html><body><h1>BALANCED Candidate Gate</h1><p>Paper/shadow candidate only. No demo/live execution.</p><table>{rows}</table></body></html>"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value

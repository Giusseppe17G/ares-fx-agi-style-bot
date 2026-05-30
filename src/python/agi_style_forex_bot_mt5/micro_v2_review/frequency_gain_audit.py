"""Frequency gain estimate for a reviewed micro V2 candidate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def estimate_frequency_gain(reports_root: str | Path, diff_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    micro_frequency = _load_json(Path(reports_root) / "micro_frequency_calibration" / "micro_frequency_summary.json")
    base_estimate = micro_frequency.get("estimated_hours_to_10_trades_current_profile")
    candidate_estimate = micro_frequency.get("estimated_hours_to_10_trades_candidate_profile")
    actionable_changes = [row for row in diff_rows if row.get("change_category") not in {"metadata"}]
    if candidate_estimate is None and base_estimate is not None and actionable_changes:
        candidate_estimate = max(float(base_estimate) * 0.9, 0.0)
    improvement = 0.0
    if base_estimate is not None and candidate_estimate is not None:
        improvement = max(float(base_estimate) - float(candidate_estimate), 0.0)
    return {
        "base_estimated_hours_to_10_trades": base_estimate,
        "candidate_estimated_hours_to_10_trades": candidate_estimate,
        "estimated_hours_improvement": round(improvement, 4),
        "actionable_change_count": len(actionable_changes),
        "top_frequency_bottlenecks": micro_frequency.get("top_frequency_bottlenecks", []),
        "frequency_gain_status": "NO_ACTIONABLE_CHANGES" if not actionable_changes else "CONSERVATIVE_GAIN_ESTIMATED",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}

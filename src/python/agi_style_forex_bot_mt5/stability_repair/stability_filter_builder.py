"""Build BALANCED_STABLE profile overlays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..robustness_validation.robustness_runner import jsonable, write_json


def build_balanced_stable_profile(
    *,
    output_dir: str | Path,
    disabled_symbols: list[str],
    disabled_strategies: list[str],
    blocked_sessions: list[str],
    blocked_regimes: list[str],
    stability_summary: dict[str, Any],
) -> dict[str, Any]:
    """Write BALANCED_STABLE INI/JSON/diff artifacts."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ini_path = output / "balanced_stable.ini"
    json_path = output / "balanced_stable.json"
    diff_path = output / "stability_filter_diff.json"
    lines = [
        "; RESEARCH/BACKTEST ONLY - NOT FOR DEMO/LIVE EXECUTION",
        "DEMO_ONLY=True",
        "LIVE_TRADING_APPROVED=False",
        "SIGNAL_PROFILE=BALANCED_STABLE",
        "PROFILE_TYPE=RESEARCH_BACKTEST_ONLY",
        "NOT_FOR_DEMO_LIVE=true",
        "REQUIRES_ROBUSTNESS_RERUN=true",
        "APPLY_STABILITY_FILTERS=true",
        f"DISABLED_SYMBOLS={','.join(disabled_symbols)}",
        f"DISABLED_STRATEGIES={','.join(disabled_strategies)}",
        f"BLOCKED_SESSIONS={','.join(blocked_sessions)}",
        f"BLOCKED_REGIMES={','.join(blocked_regimes)}",
        "EXECUTION_ATTEMPTED=False",
    ]
    ini_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "profile": "BALANCED_STABLE",
        "profile_type": "RESEARCH_BACKTEST_ONLY",
        "not_for_demo_live": True,
        "requires_robustness_rerun": True,
        "disabled_symbols": disabled_symbols,
        "disabled_strategies": disabled_strategies,
        "blocked_sessions": blocked_sessions,
        "blocked_regimes": blocked_regimes,
        "stability_summary": stability_summary,
        "execution_attempted": False,
    }
    write_json(json_path, payload)
    diff = {
        "base_profile": "BALANCED",
        "new_profile": "BALANCED_STABLE",
        "thresholds_changed": False,
        "filters_added": {
            "disabled_symbols": disabled_symbols,
            "disabled_strategies": disabled_strategies,
            "blocked_sessions": blocked_sessions,
            "blocked_regimes": blocked_regimes,
        },
        "execution_attempted": False,
    }
    diff_path.write_text(json.dumps(jsonable(diff), indent=2, sort_keys=True), encoding="utf-8")
    return {**payload, "reports_created": [str(ini_path), str(json_path), str(diff_path)]}

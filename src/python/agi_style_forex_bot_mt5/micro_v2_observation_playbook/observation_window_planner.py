"""Observation window planning for Micro V2 paper dry-run."""

from __future__ import annotations

from typing import Any


def build_observation_schedule() -> dict[str, Any]:
    """Return the minimum safe observation window and checkpoint cadence."""

    return {
        "minimum_market_open_hours": 24,
        "minimum_closed_paper_trades": 10,
        "first_8h_checkpoint_interval_hours": 2,
        "session_close_checkpoint_required": True,
        "demo_live_approval_allowed": False,
        "acceptance_bypass_allowed": False,
        "checkpoints": [
            "T+0h: confirm V2 heartbeat, MT5 connection, isolated SQLite/log paths, and paper-only guardrails.",
            "T+2h: run market-open readiness, dry-run monitor, rejection-labeling audit, and evidence pack.",
            "T+4h: repeat monitor/evidence commands and compare rejection taxonomy against FASE 55.",
            "T+6h: confirm fresh ticks remain present and no safety or paper-state block appeared.",
            "T+8h: run full V2 evidence/acceptance pack and base-vs-V2 comparison.",
            "Each session close: archive monitor, readiness, rejection labeling, forward-evidence, and forward-acceptance outputs.",
        ],
    }


def schedule_markdown(schedule: dict[str, Any]) -> str:
    lines = [
        "# Micro V2 Observation Schedule",
        "",
        f"- Minimum market-open observation: `{schedule['minimum_market_open_hours']}h`.",
        f"- Minimum closed paper trades before acceptance comparison: `{schedule['minimum_closed_paper_trades']}`.",
        f"- First 8h checkpoint cadence: every `{schedule['first_8h_checkpoint_interval_hours']}h`.",
        "- Check again at the close of each relevant trading session.",
        "- This playbook does not approve demo/live and does not bypass forward acceptance.",
        "",
        "## Checkpoints",
        "",
    ]
    lines.extend(f"- {item}" for item in schedule["checkpoints"])
    lines.append("")
    return "\n".join(lines)

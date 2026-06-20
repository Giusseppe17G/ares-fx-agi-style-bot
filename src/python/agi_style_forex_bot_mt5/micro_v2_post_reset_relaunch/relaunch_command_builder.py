"""Manual command pack builder for Micro V2 post-reset relaunch."""

from __future__ import annotations

from typing import Mapping, Any


RELAUNCH_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY "
    "--signal-profile BALANCED_STABLE_MICRO_V2 --profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--stable-gate data\\reports\\stable_gate\\stable_gate_summary.json "
    "--paper-risk-clearance data\\reports\\micro_v2_clearance\\paper_risk_clearance_v2_ledger.json "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --log-dir data\\logs\\forward-shadow-v2-dryrun --cycle-seconds 30"
)

STATUS_COMMAND = "py -m agi_style_forex_bot_mt5.cli --mode status --sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3"
WATCHER_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-reset-watcher "
    "--v2-sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --v2-log-dir data\\logs\\forward-shadow-v2-dryrun "
    "--reports-root data\\reports --v2-profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--post-reset-relaunch-dir data\\reports\\micro_v2_post_reset_relaunch_pack "
    "--pre-relaunch-safety-dir data\\reports\\micro_v2_pre_relaunch_safety_pack "
    "--daily-risk-scope-repair-dir data\\reports\\micro_v2_daily_risk_scope_repair "
    "--output-dir data\\reports\\micro_v2_reset_watcher"
)


def relaunch_commands_ps1(decision: Mapping[str, Any]) -> str:
    allowed = bool(decision.get("relaunch_allowed", False))
    header = [
        "# Micro V2 post-reset relaunch command pack",
        "# Generated for manual operator review only.",
        "# This script intentionally comments out relaunch commands and does not execute forward-shadow automatically.",
        "",
        f"# decision: {decision.get('micro_v2_relaunch_decision')}",
        f"# reason: {decision.get('reason')}",
        "",
    ]
    if allowed:
        header.extend(
            [
                "# Manual relaunch command, copy only after confirming every gate in relaunch_gates.json remains passed:",
                f"# {RELAUNCH_COMMAND}",
                "",
                "# Immediate status check after manual relaunch:",
                f"# {STATUS_COMMAND}",
            ]
        )
    else:
        header.extend(
            [
                "# Relaunch is not allowed. Rerun the reset watcher/orchestrator after remediation:",
                f"# {WATCHER_COMMAND}",
            ]
        )
    return "\n".join(header) + "\n"


def recommendations_markdown(decision: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Post-Reset Relaunch Recommendations

Decision: `{decision.get('micro_v2_relaunch_decision')}`

Reason: {decision.get('reason')}

Recommended next action: `{decision.get('recommended_next_action')}`

This phase does not execute `forward-shadow`; it only writes an auditable command pack.
"""

"""Command builder for Micro V2 post-reset relaunch pack."""

from __future__ import annotations


RELAUNCH_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY "
    "--signal-profile BALANCED_STABLE_MICRO_V2 --profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--stable-gate data\\reports\\stable_gate\\stable_gate_summary.json "
    "--paper-risk-clearance data\\reports\\micro_v2_clearance\\paper_risk_clearance_v2_ledger.json "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --log-dir data\\logs\\forward-shadow-v2-dryrun --cycle-seconds 30"
)

STATUS_COMMAND = "py -m agi_style_forex_bot_mt5.cli --mode status --sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3"

CHECKPOINT_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-observation-checkpoint "
    "--base-sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --base-log-dir data\\logs\\forward-shadow-stable "
    "--v2-sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --v2-log-dir data\\logs\\forward-shadow-v2-dryrun "
    "--reports-root data\\reports --v2-profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--output-dir data\\reports\\micro_v2_observation_checkpoint"
)

RERUN_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-post-reset-relaunch-pack "
    "--v2-sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --v2-log-dir data\\logs\\forward-shadow-v2-dryrun "
    "--reports-root data\\reports --v2-profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--daily-reset-readiness-dir data\\reports\\micro_v2_daily_reset_readiness "
    "--pre-relaunch-safety-dir data\\reports\\micro_v2_pre_relaunch_safety_pack "
    "--daily-risk-scope-repair-dir data\\reports\\micro_v2_daily_risk_scope_repair "
    "--closed-loss-scope-dir data\\reports\\micro_v2_closed_loss_scope_decision "
    "--output-dir data\\reports\\micro_v2_post_reset_relaunch_pack"
)


def command_pack(*, relaunch_allowed: bool) -> dict[str, object]:
    return {
        "relaunch_allowed": relaunch_allowed,
        "relaunch_command": RELAUNCH_COMMAND if relaunch_allowed else "",
        "status_command": STATUS_COMMAND if relaunch_allowed else "",
        "observation_checkpoint_command": CHECKPOINT_COMMAND if relaunch_allowed else "",
        "rerun_post_reset_pack_command": RERUN_COMMAND,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def commands_markdown(*, relaunch_allowed: bool) -> str:
    if relaunch_allowed:
        return f"""# Micro V2 Post-Reset Relaunch Commands

Relaunch V2 manually:

```powershell
{RELAUNCH_COMMAND}
```

Status:

```powershell
{STATUS_COMMAND}
```

Observation checkpoint:

```powershell
{CHECKPOINT_COMMAND}
```
"""
    return f"""# Micro V2 Post-Reset Relaunch Commands

KEEP_V2_STOPPED_AND_RERUN_POST_RESET_RELAUNCH_PACK_LATER.

```powershell
{RERUN_COMMAND}
```
"""

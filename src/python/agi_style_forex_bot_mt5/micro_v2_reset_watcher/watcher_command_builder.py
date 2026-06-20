"""Command text for Micro V2 reset watcher."""

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
    "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-reset-watcher "
    "--v2-sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --v2-log-dir data\\logs\\forward-shadow-v2-dryrun "
    "--reports-root data\\reports --v2-profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--post-reset-relaunch-dir data\\reports\\micro_v2_post_reset_relaunch_pack "
    "--pre-relaunch-safety-dir data\\reports\\micro_v2_pre_relaunch_safety_pack "
    "--daily-risk-scope-repair-dir data\\reports\\micro_v2_daily_risk_scope_repair "
    "--output-dir data\\reports\\micro_v2_reset_watcher"
)


def recommended_commands(*, ready: bool) -> str:
    if ready:
        return f"""# Micro V2 Ready For Manual Relaunch

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

First 15 minutes checklist:
- Confirm `status` is reading `data\\sqlite\\forward-shadow-v2-dryrun.sqlite3`.
- Confirm no `CONFIG_ERROR`.
- Confirm no `PAPER_STATE_ERROR`.
- Confirm `execution_attempted=false`, `order_send_called=false`, `order_check_called=false`.
- Confirm zero-risk guard rejections do not create paper trades.
"""
    return f"""# Micro V2 Reset Watcher

KEEP_V2_STOPPED_AND_RERUN_RESET_WATCHER_LATER.

```powershell
{RERUN_COMMAND}
```
"""

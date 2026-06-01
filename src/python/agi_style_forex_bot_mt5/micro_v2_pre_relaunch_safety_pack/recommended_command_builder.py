"""Recommended command pack for Micro V2 pre-relaunch safety pack."""

from __future__ import annotations

RELAUNCH_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY "
    "--signal-profile BALANCED_STABLE_MICRO_V2 --profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--stable-gate data\\reports\\stable_gate\\stable_gate_summary.json "
    "--paper-risk-clearance data\\reports\\micro_v2_clearance\\paper_risk_clearance_v2_ledger.json "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --log-dir data\\logs\\forward-shadow-v2-dryrun --cycle-seconds 30"
)

RESET_READINESS_COMMAND = (
    "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-daily-reset-readiness "
    "--v2-sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --v2-log-dir data\\logs\\forward-shadow-v2-dryrun "
    "--reports-root data\\reports --v2-profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini "
    "--daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json "
    "--daily-risk-scope-repair-dir data\\reports\\micro_v2_daily_risk_scope_repair "
    "--closed-loss-scope-dir data\\reports\\micro_v2_closed_loss_scope_decision "
    "--output-dir data\\reports\\micro_v2_daily_reset_readiness"
)


def command_markdown(*, relaunch_allowed: bool) -> str:
    if relaunch_allowed:
        return f"""# Micro V2 Relaunch Command

```powershell
{RELAUNCH_COMMAND}
```

Do not run this command from the pre-relaunch safety pack. Operator approval is still required.
"""
    return f"""# Micro V2 Pre-Relaunch Commands

KEEP_V2_STOPPED_AND_RERUN_RESET_READINESS_LATER.

```powershell
{RESET_READINESS_COMMAND}
```
"""

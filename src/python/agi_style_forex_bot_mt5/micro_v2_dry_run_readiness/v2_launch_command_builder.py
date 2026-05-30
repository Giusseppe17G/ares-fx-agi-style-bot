"""Build launch and monitoring commands without executing them."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_launch_command(
    *,
    symbols: str = "EURUSD,GBPUSD,USDJPY",
    profile_config: str | Path,
    stable_gate: str | Path,
    paper_risk_clearance: str | Path,
    daily_risk_ledger: str | Path,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    cycle_seconds: int = 30,
) -> str:
    return (
        "py -m agi_style_forex_bot_mt5.cli --mode forward-shadow "
        f"--symbols {symbols} "
        "--signal-profile BALANCED_STABLE_MICRO_V2 "
        f"--profile-config {profile_config} "
        f"--stable-gate {stable_gate} "
        f"--paper-risk-clearance {paper_risk_clearance} "
        f"--daily-risk-ledger {daily_risk_ledger} "
        f"--sqlite {v2_sqlite} "
        f"--log-dir {v2_log_dir} "
        f"--cycle-seconds {cycle_seconds}"
    )


def build_monitoring_commands(*, v2_sqlite: str | Path, v2_log_dir: str | Path, reports_root: str | Path, v2_reports_dir: str | Path) -> str:
    return f"""# V2 paper dry-run monitoring commands

py -m agi_style_forex_bot_mt5.cli --mode status --sqlite {v2_sqlite}

py -m agi_style_forex_bot_mt5.cli --mode paper-open-trades --sqlite {v2_sqlite} --output-dir {v2_reports_dir}\\paper_state

py -m agi_style_forex_bot_mt5.cli --mode forward-acceptance --sqlite {v2_sqlite} --log-dir {v2_log_dir} --reports-root {reports_root} --output-dir {v2_reports_dir}\\forward_evidence
"""


def build_launch_checklist(command: str) -> str:
    return f"""# BALANCED_STABLE_MICRO_V2 Paper Dry-Run Launch Checklist

- Confirm MT5 is open and connected before any manual launch.
- Confirm this is paper/shadow only.
- Confirm the V2 SQLite and log directory are separate from stable.
- Confirm `DEMO_ONLY=True` and `LIVE_TRADING_APPROVED=False`.
- Do not edit stable gate, ledgers, or active micro profile.
- Launch manually only after explicit approval:

```powershell
{command}
```
"""


def build_rollback_plan() -> str:
    return """# BALANCED_STABLE_MICRO_V2 Dry-Run Rollback Plan

- Close the V2 dry-run terminal.
- Do not touch the existing `forward-shadow-stable` process, SQLite, or logs.
- Do not delete V2 SQLite or logs; preserve evidence.
- Run status/evidence against the V2 SQLite/log path.
- Return to BALANCED_STABLE_MICRO only through the existing stable process and gates if V2 shows errors.
- Never enable demo/live execution as part of rollback.
"""

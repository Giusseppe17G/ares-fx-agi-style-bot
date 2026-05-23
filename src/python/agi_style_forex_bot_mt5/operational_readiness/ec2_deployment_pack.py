"""Generate the Windows EC2 paper-shadow deployment handoff pack."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping


STABLE_TAG = "v0.33.0-weekend-readiness-ec2-prep"


def run_ec2_deployment_pack(*, reports_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Create operator-ready EC2 deployment documents and commands."""

    reports = Path(reports_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    docs = {
        "operator_handoff": output / "EC2_OPERATOR_HANDOFF.md",
        "deployment_checklist": output / "EC2_DEPLOYMENT_CHECKLIST.md",
        "commands": output / "EC2_COMMANDS.ps1",
        "rollback": output / "EC2_ROLLBACK_PLAN.md",
        "guardrails": output / "EC2_SECURITY_GUARDRAILS.md",
        "summary": output / "ec2_deployment_summary.json",
        "html": output / "report.html",
    }
    docs["operator_handoff"].write_text(_operator_handoff(), encoding="utf-8")
    docs["deployment_checklist"].write_text(_deployment_checklist(reports), encoding="utf-8")
    docs["commands"].write_text(_commands(reports), encoding="utf-8")
    docs["rollback"].write_text(_rollback_plan(), encoding="utf-8")
    docs["guardrails"].write_text(_security_guardrails(), encoding="utf-8")

    package_status = "EC2_DEPLOYMENT_PACK_READY" if _guardrails_confirmed(docs) else "EC2_DEPLOYMENT_PACK_NEEDS_REVIEW"
    summary = {
        "mode": "ec2-deployment-pack",
        "package_status": package_status,
        "scripts_created": [
            "scripts\\ec2_operator_handoff.ps1",
            "scripts\\ec2_market_open_runbook.ps1",
            "scripts\\ec2_safe_stop_shadow.ps1",
            "scripts\\ec2_collect_evidence.ps1",
            "scripts\\ec2_backup_and_health.ps1",
        ],
        "docs_created": [str(path) for key, path in docs.items() if key not in {"summary", "html"}],
        "security_guardrails_confirmed": package_status == "EC2_DEPLOYMENT_PACK_READY",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "recommended_next_action": "Copy the pack to EC2, install dependencies, run weekend-readiness and market-open diagnostics, then start paper-only BALANCED_STABLE shadow after market open.",
    }
    docs["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    docs["html"].write_text(_html(summary), encoding="utf-8")
    summary["reports_created"] = [str(path) for path in docs.values()]
    return summary


def _operator_handoff() -> str:
    return """# EC2 Operator Handoff - BALANCED_STABLE Paper Shadow

BALANCED_STABLE is the stability-filtered research/backtest profile selected for paper/shadow observation. It is not a demo/live execution profile.

Paper/shadow means the bot reads MT5 data and creates simulated paper trades in SQLite/JSONL only. It must not place broker orders.

## Not Permitted

- Do not disable `DEMO_ONLY=True`.
- Do not enable the live-trading approval flag.
- Do not call or enable `order_send`.
- Do not call or enable `order_check`.
- Do not store Telegram tokens, MT5 credentials, AWS credentials, `.rdp`, `.pem`, `.key`, SQLite runtime data, logs or reports in git.
- Do not configure auto-start live execution.

## How To Know It Is Running

Use:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode status --sqlite data\\sqlite\\forward-shadow-stable.sqlite3
py -m agi_style_forex_bot_mt5.cli --mode health --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable
py -m agi_style_forex_bot_mt5.cli --mode stable-health --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --stable-gate data\\reports\\stable_gate\\stable_gate_summary.json
```

Healthy paper operation has heartbeats, `execution_attempted=false`, `order_send_called=false`, `order_check_called=false`, and no critical drift or paper audit failures.

## Incident Actions

- `PAPER_DAILY_DRAWDOWN`: pause shadow, run `paper-state-report`, collect evidence, and review before resume.
- `ALL_SYMBOLS_REJECTED`: run `mt5-diagnose`, `live-feature-contract`, and `forward-signal-diagnose`.
- `FEATURE_PIPELINE_NOT_READY`: run `live-feature-contract`; do not relax thresholds until features are valid.
- `MT5 disconnected`: reconnect RDP/MT5, confirm demo account, rerun `mt5-diagnose`.

Pause if critical drift, SQLite/JSONL issues, missing heartbeat, invalid timestamps, paper trade without SL/TP, or stable gate missing.

Do not touch anything when the market is closed and `weekend-readiness` is `WEEKEND_SAFE`; wait for market open checklist.

Send for review: `forward_evidence`, `paper_state`, `forward_diagnostics`, `stable_gate`, `stability_repair`, SQLite backup, and latest logs.
"""


def _deployment_checklist(reports: Path) -> str:
    return f"""# EC2 Deployment Checklist

## Install

- Launch Windows EC2.
- Install Git, Python 3.11+, MetaTrader 5, and project dependencies.
- Log into MT5 demo account by RDP.
- Keep required symbols visible in Market Watch.
- Confirm runtime paths:
  - `data\\logs`
  - `data\\sqlite`
  - `data\\reports`
  - `data\\backups`

## Pre-Market Offline Checks

- Run tests.
- Run `weekend-readiness`.
- Run `ec2-readiness-audit`.
- Confirm `paper_trades_open=0`.
- Confirm `paper_shadow_paused=true`.
- Confirm `{reports}\\stable_gate\\stable_gate_summary.json`.
- Confirm `{reports}\\stability_repair\\balanced_stable.ini`.

## Market Open Checks

- Run `mt5-diagnose`.
- Run `live-feature-contract`.
- Resume shadow only after diagnostics pass.
- Start BALANCED_STABLE paper/shadow.
- After 30-60 minutes run `forward-signal-diagnose`.
- After 2-4 hours run `forward-evidence` and `forward-acceptance`.

## Logs And Backups

- Keep JSONL under `data\\logs`.
- Keep SQLite under `data\\sqlite`.
- Keep reports under `data\\reports`.
- Run backup/db-health/audit-replay daily or before changes.
- Do not commit runtime data.
"""


def _commands(reports: Path) -> str:
    return f"""# EC2 paper-shadow command pack. Safe defaults only.
$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src/python"

# Guardrails: DEMO_ONLY=True; LIVE_TRADING_APPROVED=False; execution_attempted=false; order_send/order_check prohibited.

# Install dependencies
py -m pip install -r requirements.txt

# Validate tests
py -m pytest -q

# Verify safe weekend/offline state
py -m agi_style_forex_bot_mt5.cli --mode weekend-readiness --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root {reports} --output-dir {reports}\\weekend_readiness
py -m agi_style_forex_bot_mt5.cli --mode ec2-readiness-audit --reports-root {reports} --output-dir {reports}\\ec2_readiness

# Market-open diagnostics
py -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols EURUSD,GBPUSD,USDJPY --log-dir data\\logs\\mt5-diagnose-open --sqlite data\\sqlite\\mt5-diagnose-open.sqlite3
py -m agi_style_forex_bot_mt5.cli --mode live-feature-contract --symbols EURUSD,GBPUSD,USDJPY --output-dir {reports}\\forward_diagnostics

# Paper/shadow only resume and run
py -m agi_style_forex_bot_mt5.cli --mode resume-shadow --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --reason "EC2 market open paper-only resume after diagnostics"
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE --profile-config {reports}\\stability_repair\\balanced_stable.ini --stable-gate {reports}\\stable_gate\\stable_gate_summary.json --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --cycle-seconds 30

# Evidence and paper state
py -m agi_style_forex_bot_mt5.cli --mode forward-evidence --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root {reports} --output-dir {reports}\\forward_evidence
py -m agi_style_forex_bot_mt5.cli --mode forward-acceptance --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root {reports} --output-dir {reports}\\forward_evidence
py -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --output-dir {reports}\\paper_state

# Safe pause
py -m agi_style_forex_bot_mt5.cli --mode pause-shadow --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --reason "EC2 operator safe pause"

# Backup and recovery checks
py -m agi_style_forex_bot_mt5.cli --mode backup --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --backup-dir data\\backups
py -m agi_style_forex_bot_mt5.cli --mode db-health --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --report-dir {reports}\\db_health
py -m agi_style_forex_bot_mt5.cli --mode audit-replay --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --report-dir {reports}\\audit_replay
"""


def _rollback_plan() -> str:
    return f"""# EC2 Rollback Plan

1. Pause paper/shadow:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode pause-shadow --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --reason "rollback"
```

2. Stop the PowerShell forward-shadow/watchdog process.
3. Backup SQLite and logs:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode backup --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --backup-dir data\\backups
py -m agi_style_forex_bot_mt5.cli --mode db-health --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --report-dir data\\reports\\db_health
py -m agi_style_forex_bot_mt5.cli --mode audit-replay --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --report-dir data\\reports\\audit_replay
```

4. Restore from the last known-good backup if SQLite/log state is damaged.
5. Return to the stable tag:

```powershell
git checkout {STABLE_TAG}
```

If that tag is unavailable, use the most recent reviewed stable tag. Do not touch MT5 real positions or enable demo/live execution during rollback.
"""


def _security_guardrails() -> str:
    return """# EC2 Security Guardrails

- `DEMO_ONLY=True` is mandatory.
- `LIVE_TRADING_APPROVED=False` is mandatory.
- `order_send` and `order_check` are prohibited for this phase.
- Forward-shadow is paper/shadow only.
- `paper-close-all` modifies only SQLite paper trades.
- Do not store Telegram tokens in git.
- Do not commit SQLite, logs, reports, data exports, `.rdp`, `.pem`, `.key`, MT5 credentials, broker credentials or AWS credentials.
- Do not enable auto-start live execution.
- Do not bypass stable gate, spread guard, tick freshness, risk gates or paper audit.
"""


def _guardrails_confirmed(paths: Mapping[str, Path]) -> bool:
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in paths.values() if path.exists())
    lowered = text.lower()
    return (
        "demo_only=true" in lowered
        and "live_trading_approved=false" in lowered
        and "execution_attempted=false" in lowered
        and "order_send" in lowered
        and "order_check" in lowered
    )


def _html(summary: Mapping[str, Any]) -> str:
    docs = "".join(f"<li>{html.escape(str(path))}</li>" for path in summary.get("docs_created", []))
    scripts = "".join(f"<li>{html.escape(str(path))}</li>" for path in summary.get("scripts_created", []))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>EC2 Deployment Pack</title></head>
<body>
<h1>EC2 Deployment Pack</h1>
<p>Status: <strong>{html.escape(str(summary.get('package_status')))}</strong></p>
<p>execution_attempted=false; order_send_called=false; order_check_called=false</p>
<h2>Docs</h2><ul>{docs}</ul>
<h2>Scripts</h2><ul>{scripts}</ul>
</body></html>
"""

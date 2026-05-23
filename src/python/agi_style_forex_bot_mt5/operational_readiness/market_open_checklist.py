"""Generate a safe market-open checklist for paper/shadow observation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SYMBOLS = "EURUSD,GBPUSD,USDJPY"


def run_market_open_checklist(
    *,
    sqlite_path: str | Path,
    reports_root: str | Path,
    output_dir: str | Path,
    symbols: str = DEFAULT_SYMBOLS,
) -> dict[str, Any]:
    """Write exact PowerShell commands for the next market-open paper run."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    sqlite = Path(sqlite_path)
    reports = Path(reports_root)
    commands = _commands(symbols=symbols, sqlite=sqlite, reports=reports)
    md_path = output / "market_open_checklist.md"
    ps1_path = output / "commands.ps1"
    summary_path = output / "market_open_checklist_summary.json"
    md_path.write_text(_markdown(commands), encoding="utf-8")
    ps1_path.write_text("\n".join(commands) + "\n", encoding="utf-8")
    summary = {
        "mode": "market-open-checklist",
        "classification": "MARKET_OPEN_CHECKLIST_CREATED",
        "market_open_next_action": "At market open, run mt5-diagnose first, then live-feature-contract, then resume paper-only shadow if diagnostics pass.",
        "commands_created": len(commands),
        "reports_created": [str(md_path), str(ps1_path), str(summary_path)],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _commands(*, symbols: str, sqlite: Path, reports: Path) -> list[str]:
    return [
        "$env:PYTHONPATH=\"src/python\"",
        "Get-Date",
        "(Get-Date).ToUniversalTime()",
        "Get-TimeZone",
        f"py -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols {symbols} --log-dir data\\logs\\mt5-diagnose-open --sqlite data\\sqlite\\mt5-diagnose-open.sqlite3",
        f"py -m agi_style_forex_bot_mt5.cli --mode live-feature-contract --symbols {symbols} --output-dir {reports}\\forward_diagnostics",
        f"py -m agi_style_forex_bot_mt5.cli --mode resume-shadow --sqlite {sqlite} --reason \"market open paper-only resume after diagnostics\"",
        f"py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols {symbols} --signal-profile BALANCED_STABLE --profile-config {reports}\\stability_repair\\balanced_stable.ini --stable-gate {reports}\\stable_gate\\stable_gate_summary.json --sqlite {sqlite} --log-dir data\\logs\\forward-shadow-stable --cycle-seconds 30",
        f"py -m agi_style_forex_bot_mt5.cli --mode forward-signal-diagnose --symbols {symbols} --signal-profile BALANCED_STABLE --profile-config {reports}\\stability_repair\\balanced_stable.ini --stable-gate {reports}\\stable_gate\\stable_gate_summary.json --sqlite {sqlite} --log-dir data\\logs\\forward-shadow-stable --reports-root {reports} --output-dir {reports}\\forward_diagnostics",
        f"py -m agi_style_forex_bot_mt5.cli --mode forward-evidence --sqlite {sqlite} --log-dir data\\logs\\forward-shadow-stable --reports-root {reports} --output-dir {reports}\\forward_evidence",
        "# Do not enable demo/live execution. Keep DEMO_ONLY=True and LIVE_TRADING_APPROVED=False.",
    ]


def _markdown(commands: list[str]) -> str:
    checklist = [
        "# Market Open Checklist",
        "",
        "- Confirm MetaTrader 5 is open and logged into a demo account.",
        "- Confirm EURUSD, GBPUSD and USDJPY are visible in Market Watch.",
        "- Run `mt5-diagnose` before resuming shadow.",
        "- Run `live-feature-contract` before resuming shadow.",
        "- Resume only paper/shadow after diagnostics pass.",
        "- After 30-60 minutes, run `forward-signal-diagnose`.",
        "- After 2-4 hours, run `forward-evidence`.",
        "- Do not run demo/live execution.",
        "",
        "```powershell",
        *commands,
        "```",
        "",
        json.dumps({"execution_attempted": False, "order_send_called": False, "order_check_called": False}, sort_keys=True),
        "",
    ]
    return "\n".join(checklist)

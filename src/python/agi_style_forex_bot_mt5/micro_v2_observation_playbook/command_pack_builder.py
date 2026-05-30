"""Command pack generation for Micro V2 observation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_command_pack(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    base_sqlite: str | Path,
    base_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
) -> dict[str, Any]:
    reports = _p(reports_root)
    commands = {
        "status_v2": f"py -m agi_style_forex_bot_mt5.cli --mode status --sqlite {_p(v2_sqlite)}",
        "paper_open_trades_v2": (
            "py -m agi_style_forex_bot_mt5.cli --mode paper-open-trades "
            f"--sqlite {_p(v2_sqlite)} --output-dir {reports}\\micro_v2_dry_run\\paper_state"
        ),
        "market_open_readiness": (
            "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-market-open-readiness "
            f"--v2-sqlite {_p(v2_sqlite)} --v2-log-dir {_p(v2_log_dir)} --reports-root {reports} "
            f"--v2-profile-config {_p(v2_profile_config)} --rejection-labeling-dir {reports}\\rejection_labeling_audit "
            f"--monitor-dir {reports}\\micro_v2_dry_run_monitor --output-dir {reports}\\micro_v2_market_open_readiness"
        ),
        "dry_run_monitor": (
            "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-dry-run-monitor "
            f"--base-sqlite {_p(base_sqlite)} --base-log-dir {_p(base_log_dir)} "
            f"--v2-sqlite {_p(v2_sqlite)} --v2-log-dir {_p(v2_log_dir)} --reports-root {reports} "
            f"--output-dir {reports}\\micro_v2_dry_run_monitor"
        ),
        "rejection_labeling_audit": (
            "py -m agi_style_forex_bot_mt5.cli --mode rejection-labeling-audit "
            f"--base-sqlite {_p(base_sqlite)} --v2-sqlite {_p(v2_sqlite)} "
            f"--base-log-dir {_p(base_log_dir)} --v2-log-dir {_p(v2_log_dir)} --reports-root {reports} "
            f"--output-dir {reports}\\rejection_labeling_audit"
        ),
        "base_vs_v2_comparison": (
            "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-dry-run-monitor "
            f"--base-sqlite {_p(base_sqlite)} --base-log-dir {_p(base_log_dir)} "
            f"--v2-sqlite {_p(v2_sqlite)} --v2-log-dir {_p(v2_log_dir)} --reports-root {reports} "
            f"--output-dir {reports}\\micro_v2_dry_run_monitor"
        ),
    }
    return {
        "commands": commands,
        "launch_commands_md": _commands_markdown("Launch / State Commands", {k: commands[k] for k in ("status_v2", "paper_open_trades_v2")}),
        "monitoring_commands_md": _commands_markdown(
            "Monitoring Commands",
            {k: commands[k] for k in ("market_open_readiness", "dry_run_monitor", "rejection_labeling_audit", "base_vs_v2_comparison")},
        ),
    }


def _commands_markdown(title: str, commands: dict[str, str]) -> str:
    lines = [
        f"# {title}",
        "",
        "Run these manually from the project root. They are read-only/reporting commands and do not launch, pause, resume, open, or close trades.",
        "",
    ]
    for label, command in commands.items():
        lines.extend([f"## {label}", "", "```powershell", command, "```", ""])
    return "\n".join(lines)


def _p(value: str | Path) -> str:
    return str(value)

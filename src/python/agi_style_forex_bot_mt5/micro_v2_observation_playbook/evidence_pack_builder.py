"""Evidence command generation for Micro V2 observation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_evidence_pack(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    base_sqlite: str | Path,
    base_log_dir: str | Path,
    reports_root: str | Path,
) -> dict[str, Any]:
    reports = str(reports_root)
    commands = {
        "forward_acceptance_v2": (
            "py -m agi_style_forex_bot_mt5.cli --mode forward-acceptance "
            f"--sqlite {v2_sqlite} --log-dir {v2_log_dir} --reports-root {reports} "
            f"--output-dir {reports}\\micro_v2_dry_run\\forward_evidence"
        ),
        "forward_evidence_v2": (
            "py -m agi_style_forex_bot_mt5.cli --mode forward-evidence "
            f"--sqlite {v2_sqlite} --log-dir {v2_log_dir} --reports-root {reports} "
            f"--output-dir {reports}\\micro_v2_dry_run\\forward_evidence"
        ),
        "compare_base_vs_v2": (
            "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-dry-run-monitor "
            f"--base-sqlite {base_sqlite} --base-log-dir {base_log_dir} "
            f"--v2-sqlite {v2_sqlite} --v2-log-dir {v2_log_dir} --reports-root {reports} "
            f"--output-dir {reports}\\micro_v2_dry_run_monitor"
        ),
    }
    return {
        "commands": commands,
        "evidence_commands_md": _commands_markdown(commands),
    }


def _commands_markdown(commands: dict[str, str]) -> str:
    lines = [
        "# Evidence Commands",
        "",
        "These commands build evidence only. They do not approve demo/live and do not bypass any risk or acceptance gate.",
        "",
    ]
    for label, command in commands.items():
        lines.extend([f"## {label}", "", "```powershell", command, "```", ""])
    return "\n".join(lines)

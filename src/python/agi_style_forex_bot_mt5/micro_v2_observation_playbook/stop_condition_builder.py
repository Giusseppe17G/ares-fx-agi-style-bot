"""Advancement and rollback criteria for Micro V2 observation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


ADVANCEMENT_CRITERIA = [
    "fresh_tick_symbols is not empty.",
    "market_closed_rejection_count no longer dominates total rejections.",
    "v2_runtime_active=true.",
    "mt5_connected=true.",
    "execution_attempted=false.",
    "order_send_called=false.",
    "order_check_called=false.",
    "paper_state_recovery_status=PAPER_STATE_RECOVERY_OK.",
]

STOP_ROLLBACK_CRITERIA = [
    "execution_attempted=true.",
    "order_send_called=true.",
    "order_check_called=true.",
    "PAPER_STATE_ERROR appears in V2 status, logs, or evidence.",
    "CONFIG_ERROR appears in V2 status, logs, or evidence.",
    "active_scaled_drawdown_count > 0.",
    "invalid open paper trade is detected.",
    "daily risk halt is active.",
    "V2 uses stable SQLite or stable log paths by mistake.",
    "V2 heartbeat becomes stale or missing.",
]


def build_path_isolation_audit(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    base_sqlite: str | Path,
    base_log_dir: str | Path,
) -> dict[str, Any]:
    v2_sqlite_text = _norm(v2_sqlite)
    v2_log_text = _norm(v2_log_dir)
    base_sqlite_text = _norm(base_sqlite)
    base_log_text = _norm(base_log_dir)
    failures = []
    if v2_sqlite_text == base_sqlite_text or "forward-shadow-stable.sqlite3" in v2_sqlite_text:
        failures.append("V2_SQLITE_POINTS_TO_STABLE")
    if v2_log_text == base_log_text or "forward-shadow-stable" in v2_log_text:
        failures.append("V2_LOG_DIR_POINTS_TO_STABLE")
    if "forward-shadow-v2-dryrun" not in v2_sqlite_text:
        failures.append("V2_SQLITE_NOT_ISOLATED_DRYRUN_PATH")
    if "forward-shadow-v2-dryrun" not in v2_log_text:
        failures.append("V2_LOG_DIR_NOT_ISOLATED_DRYRUN_PATH")
    return {
        "path_isolation_valid": not failures,
        "path_isolation_failures": failures,
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "base_sqlite": str(base_sqlite),
        "base_log_dir": str(base_log_dir),
    }


def advancement_markdown() -> str:
    return _criteria_markdown("Advancement Criteria", ADVANCEMENT_CRITERIA, "V2 can move to real-filter analysis only when all criteria are true.")


def stop_rollback_markdown() -> str:
    return _criteria_markdown("Stop / Rollback Criteria", STOP_ROLLBACK_CRITERIA, "Stop V2 observation and preserve evidence if any criterion is true.")


def operator_checklist_markdown(path_audit: dict[str, Any]) -> str:
    status = "PASS" if path_audit.get("path_isolation_valid") else "BLOCKED"
    failures = path_audit.get("path_isolation_failures", [])
    lines = [
        "# Operator Checklist",
        "",
        f"- Path isolation: `{status}`.",
        "- Confirm the V2 terminal is paper/shadow only.",
        "- Confirm the V2 SQLite path is not the stable SQLite.",
        "- Confirm the V2 log directory is not the stable log directory.",
        "- Run market-open readiness before interpreting rejection rates.",
        "- Run dry-run monitor and evidence pack at every checkpoint.",
        "- Do not approve demo/live from this playbook.",
        "- Preserve all reports and logs.",
    ]
    if failures:
        lines.extend(["", "## Blocking Path Findings", ""])
        lines.extend(f"- `{item}`" for item in failures)
    lines.append("")
    return "\n".join(lines)


def _criteria_markdown(title: str, criteria: list[str], intro: str) -> str:
    lines = [f"# {title}", "", intro, ""]
    lines.extend(f"- {item}" for item in criteria)
    lines.append("")
    return "\n".join(lines)


def _norm(value: str | Path) -> str:
    return str(value).replace("/", "\\").lower()

"""Path isolation checks for V2 paper dry-run launch planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_V2_SQLITE = Path("data/sqlite/forward-shadow-v2-dryrun.sqlite3")
DEFAULT_V2_LOG_DIR = Path("data/logs/forward-shadow-v2-dryrun")
DEFAULT_V2_REPORTS_DIR = Path("data/reports/micro_v2_dry_run")


def audit_path_isolation(
    *,
    stable_sqlite: str | Path,
    stable_log_dir: str | Path,
    v2_sqlite: str | Path = DEFAULT_V2_SQLITE,
    v2_log_dir: str | Path = DEFAULT_V2_LOG_DIR,
    v2_reports_dir: str | Path = DEFAULT_V2_REPORTS_DIR,
) -> dict[str, Any]:
    stable_sqlite_path = _norm(stable_sqlite)
    stable_log_path = _norm(stable_log_dir)
    v2_sqlite_path = _norm(v2_sqlite)
    v2_log_path = _norm(v2_log_dir)
    failures: list[dict[str, Any]] = []
    if v2_sqlite_path == stable_sqlite_path:
        failures.append(_failure("V2_SQLITE", "V2 dry-run cannot use the stable forward-shadow SQLite."))
    if v2_log_path == stable_log_path:
        failures.append(_failure("V2_LOG_DIR", "V2 dry-run cannot use the stable forward-shadow log directory."))
    return {
        "path_isolation_status": "PASS" if not failures else "FAIL",
        "stable_sqlite": str(stable_sqlite),
        "stable_log_dir": str(stable_log_dir),
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "v2_reports_dir": str(v2_reports_dir),
        "failures": failures,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _norm(path: str | Path) -> Path:
    return Path(path).resolve()


def _failure(key: str, reason: str) -> dict[str, Any]:
    return {"key": key, "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}

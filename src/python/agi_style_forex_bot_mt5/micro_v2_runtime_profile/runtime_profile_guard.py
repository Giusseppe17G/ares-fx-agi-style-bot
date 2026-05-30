"""Fail-closed runtime guards for BALANCED_STABLE_MICRO_V2 paper dry-run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.calibration.signal_profile import PROFILES
from agi_style_forex_bot_mt5.micro_v2_dry_run_readiness.dry_run_path_planner import DEFAULT_V2_LOG_DIR, DEFAULT_V2_SQLITE, audit_path_isolation
from agi_style_forex_bot_mt5.micro_v2_dry_run_readiness.v2_profile_guard import audit_v2_profile


MICRO_V2_SIGNAL_PROFILE = "BALANCED_STABLE_MICRO_V2"
EXPECTED_V2_PROFILE_NAME = "balanced_stable_micro_v2.ini"
STABLE_SQLITE = Path("data/sqlite/forward-shadow-stable.sqlite3")
STABLE_LOG_DIR = Path("data/logs/forward-shadow-stable")


def signal_profile_choices() -> list[str]:
    """Return the canonical CLI choices for --signal-profile."""

    return list(PROFILES)


def validate_micro_v2_forward_shadow_runtime(
    *,
    mode: str,
    signal_profile: str,
    profile_config: str | Path | None,
    sqlite_path: str | Path | None,
    log_dir: str | Path | None,
    base_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro.ini",
) -> dict[str, Any]:
    """Validate that V2 is used only as an isolated paper/shadow dry-run."""

    profile = str(signal_profile or "").strip().upper()
    failures: list[dict[str, Any]] = []
    if profile != MICRO_V2_SIGNAL_PROFILE:
        return _summary(
            status="MICRO_V2_NOT_REQUESTED",
            mode=mode,
            signal_profile=profile,
            profile_config=profile_config,
            sqlite_path=sqlite_path,
            log_dir=log_dir,
            failures=[],
            profile_guard={},
            path_guard={},
        )

    if mode != "forward-shadow":
        failures.append(_failure("MODE", "BALANCED_STABLE_MICRO_V2 is only valid for --mode forward-shadow."))
    if not profile_config:
        failures.append(_failure("PROFILE_CONFIG", "BALANCED_STABLE_MICRO_V2 requires --profile-config."))
    elif Path(profile_config).name.lower() != EXPECTED_V2_PROFILE_NAME:
        failures.append(_failure("PROFILE_CONFIG", "BALANCED_STABLE_MICRO_V2 requires balanced_stable_micro_v2.ini."))
    if sqlite_path is None:
        failures.append(_failure("SQLITE", "BALANCED_STABLE_MICRO_V2 requires isolated --sqlite."))
    if log_dir is None:
        failures.append(_failure("LOG_DIR", "BALANCED_STABLE_MICRO_V2 requires isolated --log-dir."))

    profile_guard = audit_v2_profile(profile_config or "", base_profile_config=base_profile_config) if profile_config else {}
    if profile_guard and profile_guard.get("profile_guard_status") != "PASS":
        failures.extend(_guard_failures("PROFILE", profile_guard.get("failures", [])))

    path_guard = audit_path_isolation(
        stable_sqlite=STABLE_SQLITE,
        stable_log_dir=STABLE_LOG_DIR,
        v2_sqlite=sqlite_path or "",
        v2_log_dir=log_dir or "",
    )
    if path_guard.get("path_isolation_status") != "PASS":
        failures.extend(_guard_failures("PATH", path_guard.get("failures", [])))
    if sqlite_path is not None and _norm(sqlite_path) != _norm(DEFAULT_V2_SQLITE):
        failures.append(_failure("V2_SQLITE", f"BALANCED_STABLE_MICRO_V2 must use {DEFAULT_V2_SQLITE}."))
    if log_dir is not None and _norm(log_dir) != _norm(DEFAULT_V2_LOG_DIR):
        failures.append(_failure("V2_LOG_DIR", f"BALANCED_STABLE_MICRO_V2 must use {DEFAULT_V2_LOG_DIR}."))

    status = "MICRO_V2_RUNTIME_GUARDS_PASSED" if not failures else _failed_status(failures)
    return _summary(
        status=status,
        mode=mode,
        signal_profile=profile,
        profile_config=profile_config,
        sqlite_path=sqlite_path,
        log_dir=log_dir,
        failures=failures,
        profile_guard=profile_guard,
        path_guard=path_guard,
    )


def _failed_status(failures: list[dict[str, Any]]) -> str:
    keys = {str(item.get("key", "")).upper() for item in failures}
    if "PROFILE_CONFIG" in keys or any(key.startswith("PROFILE") for key in keys):
        return "MICRO_V2_PROFILE_INVALID"
    if "V2_SQLITE" in keys or "V2_LOG_DIR" in keys or "SQLITE" in keys or "LOG_DIR" in keys:
        return "MICRO_V2_PATH_GUARD_REQUIRED"
    return "MICRO_V2_RUNTIME_GUARDS_FAILED"


def _summary(
    *,
    status: str,
    mode: str,
    signal_profile: str,
    profile_config: str | Path | None,
    sqlite_path: str | Path | None,
    log_dir: str | Path | None,
    failures: list[dict[str, Any]],
    profile_guard: dict[str, Any],
    path_guard: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "signal_profile": signal_profile,
        "micro_v2_runtime_guard_status": status,
        "profile_config": str(profile_config or ""),
        "sqlite": str(sqlite_path or ""),
        "log_dir": str(log_dir or ""),
        "failures": failures,
        "profile_guard": profile_guard,
        "path_guard": path_guard,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _guard_failures(prefix: str, failures: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in failures if isinstance(failures, list) else []:
        if isinstance(item, dict):
            rows.append(_failure(f"{prefix}_{item.get('key', 'UNKNOWN')}", str(item.get("reason", "Guard failure."))))
        else:
            rows.append(_failure(f"{prefix}_UNKNOWN", str(item)))
    return rows


def _failure(key: str, reason: str) -> dict[str, Any]:
    return {"key": key, "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}


def _norm(path: str | Path) -> Path:
    return Path(path).resolve()

from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_dry_run_readiness import run_micro_v2_dry_run_readiness
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_approves_valid_v2_profile(tmp_path: Path) -> None:
    summary = _run(tmp_path)

    assert summary["micro_v2_dry_run_readiness_status"] == "MICRO_V2_DRY_RUN_READY"
    assert summary["micro_v2_launch_command_available"] is True


def test_rejects_approved_for_demo_true(tmp_path: Path) -> None:
    summary = _run(tmp_path, profile_overrides={"APPROVED_FOR_DEMO": "true"})

    assert summary["micro_v2_dry_run_readiness_status"] == "MICRO_V2_PROFILE_INVALID"


def test_rejects_approved_for_live_true(tmp_path: Path) -> None:
    summary = _run(tmp_path, profile_overrides={"APPROVED_FOR_LIVE": "true"})

    assert summary["micro_v2_dry_run_readiness_status"] == "MICRO_V2_PROFILE_INVALID"


def test_rejects_paper_only_not_true(tmp_path: Path) -> None:
    summary = _run(tmp_path, profile_overrides={"PAPER_ONLY": "false"})

    assert summary["micro_v2_dry_run_readiness_status"] == "MICRO_V2_PROFILE_INVALID"


def test_rejects_stable_sqlite_as_v2_runtime(tmp_path: Path) -> None:
    sqlite = tmp_path / "stable.sqlite3"
    summary = _run(tmp_path, sqlite=sqlite, v2_sqlite=sqlite)

    assert summary["micro_v2_dry_run_readiness_status"] == "MICRO_V2_PATH_ISOLATION_FAILED"


def test_rejects_stable_log_dir_as_v2_runtime(tmp_path: Path) -> None:
    log_dir = tmp_path / "stable_logs"
    summary = _run(tmp_path, log_dir=log_dir, v2_log_dir=log_dir)

    assert summary["micro_v2_dry_run_readiness_status"] == "MICRO_V2_PATH_ISOLATION_FAILED"


def test_generates_launch_command_without_executing(tmp_path: Path) -> None:
    summary = _run(tmp_path)
    launch = tmp_path / "out" / "launch_command.txt"

    assert launch.exists()
    text = launch.read_text(encoding="utf-8")
    assert "--mode forward-shadow" in text
    assert "--signal-profile BALANCED_STABLE_MICRO_V2" in text
    assert "forward-shadow-v2-dryrun.sqlite3" in text
    assert summary["execution_attempted"] is False


def test_does_not_modify_stable_sqlite(tmp_path: Path) -> None:
    sqlite = tmp_path / "stable.sqlite3"
    db = TelemetryDatabase(sqlite)
    try:
        db.insert_event({"event_id": "evt1", "idempotency_key": "evt1", "event_type": "SIGNAL_REJECTED", "symbol": "EURUSD", "severity": "INFO", "module": "test", "message": "reject", "payload": {"reason": "COOLDOWN_BLOCK"}})
        before = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
    finally:
        db.close()

    summary = _run(tmp_path, sqlite=sqlite)

    db2 = TelemetryDatabase(sqlite)
    try:
        after = (db2.count_rows("events"), db2.count_rows("paper_trades"), db2.get_operational_state())
    finally:
        db2.close()
    assert before == after
    assert summary["sqlite_stable_unchanged"] is True
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_mode_generates_readiness(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "stable.sqlite3"
    db = TelemetryDatabase(sqlite)
    db.close()
    profile = _v2_profile(tmp_path / "v2.ini")
    stable_gate, clearance, daily = _required_files(tmp_path)

    assert cli.main([
        "--mode",
        "micro-v2-dry-run-readiness",
        "--sqlite",
        str(sqlite),
        "--log-dir",
        str(tmp_path / "stable_logs"),
        "--reports-root",
        str(tmp_path / "reports"),
        "--v2-profile-config",
        str(profile),
        "--stable-gate",
        str(stable_gate),
        "--paper-risk-clearance",
        str(clearance),
        "--daily-risk-ledger",
        str(daily),
        "--output-dir",
        str(tmp_path / "out"),
    ]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "micro-v2-dry-run-readiness"
    assert summary["execution_attempted"] is False


def _run(
    tmp_path: Path,
    *,
    profile_overrides: dict[str, str] | None = None,
    sqlite: Path | None = None,
    log_dir: Path | None = None,
    v2_sqlite: Path | None = None,
    v2_log_dir: Path | None = None,
) -> dict[str, object]:
    sqlite_path = sqlite or tmp_path / "stable.sqlite3"
    db = TelemetryDatabase(sqlite_path)
    profile = _v2_profile(tmp_path / "v2.ini", overrides=profile_overrides)
    stable_gate, clearance, daily = _required_files(tmp_path)
    try:
        return run_micro_v2_dry_run_readiness(
            database=db,
            log_dir=log_dir or tmp_path / "stable_logs",
            reports_root=tmp_path / "reports",
            v2_profile_config=profile,
            stable_gate=stable_gate,
            paper_risk_clearance=clearance,
            daily_risk_ledger=daily,
            output_dir=tmp_path / "out",
            v2_sqlite=v2_sqlite or tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
            v2_log_dir=v2_log_dir or tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
            v2_reports_dir=tmp_path / "reports" / "micro_v2_dry_run",
        )
    finally:
        db.close()


def _v2_profile(path: Path, *, overrides: dict[str, str] | None = None) -> Path:
    values = {
        "PROFILE_NAME": "BALANCED_STABLE_MICRO_V2",
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO_V2",
        "PAPER_ONLY": "true",
        "NOT_FOR_DEMO_LIVE": "true",
        "NOT_FOR_LIVE": "true",
        "APPROVED_FOR_PAPER_DRY_RUN_ONLY": "true",
        "APPROVED_FOR_DEMO": "false",
        "APPROVED_FOR_LIVE": "false",
        "REQUIRES_STABLE_GATE": "true",
        "REQUIRES_PAPER_RISK_CLEARANCE": "true",
        "REQUIRES_DAILY_RISK_LEDGER": "true",
        "PAPER_RISK_MULTIPLIER": "0.1",
        "MAX_OPEN_PAPER_TRADES": "1",
        "MAX_PAPER_TRADES_PER_DAY": "3",
    }
    values.update(overrides or {})
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path


def _required_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    stable_gate = tmp_path / "stable_gate.json"
    clearance = tmp_path / "clearance.json"
    daily = tmp_path / "daily_ledger.json"
    stable_gate.write_text("{}", encoding="utf-8")
    clearance.write_text("{}", encoding="utf-8")
    daily.write_text("{}", encoding="utf-8")
    return stable_gate, clearance, daily

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_runtime_profile import MICRO_V2_SIGNAL_PROFILE, run_micro_v2_runtime_profile_check, signal_profile_choices, validate_micro_v2_forward_shadow_runtime


def test_micro_v2_appears_as_signal_profile_choice() -> None:
    assert MICRO_V2_SIGNAL_PROFILE in signal_profile_choices()


def test_forward_shadow_v2_no_longer_fails_invalid_choice(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    profile = _v2_profile(tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini")

    result = cli.main(
        [
            "--mode",
            "forward-shadow",
            "--symbols",
            "EURUSD,GBPUSD,USDJPY",
            "--signal-profile",
            "BALANCED_STABLE_MICRO_V2",
            "--profile-config",
            str(profile),
            "--stable-gate",
            "data/reports/stable_gate/stable_gate_summary.json",
            "--sqlite",
            "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
            "--log-dir",
            "data/logs/forward-shadow-v2-dryrun",
            "--cycle-seconds",
            "30",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["signal_profile_used"] == "BALANCED_STABLE_MICRO_V2"
    assert summary["classification"] != "MICRO_V2_PATH_GUARD_REQUIRED"
    assert summary["execution_attempted"] is False
    assert "invalid choice" not in json.dumps(summary)


def test_micro_v2_rejected_outside_forward_shadow(capsys) -> None:
    result = cli.main(["--mode", "demo", "--signal-profile", "BALANCED_STABLE_MICRO_V2"])

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["classification"] == "MICRO_V2_RUNTIME_GUARDS_FAILED"
    assert summary["execution_attempted"] is False


def test_rejects_v2_with_stable_sqlite(tmp_path: Path) -> None:
    profile = _v2_profile(tmp_path / "balanced_stable_micro_v2.ini")

    guard = validate_micro_v2_forward_shadow_runtime(
        mode="forward-shadow",
        signal_profile="BALANCED_STABLE_MICRO_V2",
        profile_config=profile,
        sqlite_path="data/sqlite/forward-shadow-stable.sqlite3",
        log_dir="data/logs/forward-shadow-v2-dryrun",
    )

    assert guard["micro_v2_runtime_guard_status"] == "MICRO_V2_PATH_GUARD_REQUIRED"


def test_rejects_v2_with_stable_log_dir(tmp_path: Path) -> None:
    profile = _v2_profile(tmp_path / "balanced_stable_micro_v2.ini")

    guard = validate_micro_v2_forward_shadow_runtime(
        mode="forward-shadow",
        signal_profile="BALANCED_STABLE_MICRO_V2",
        profile_config=profile,
        sqlite_path="data/sqlite/forward-shadow-v2-dryrun.sqlite3",
        log_dir="data/logs/forward-shadow-stable",
    )

    assert guard["micro_v2_runtime_guard_status"] == "MICRO_V2_PATH_GUARD_REQUIRED"


def test_rejects_v2_with_wrong_profile_config_name(tmp_path: Path) -> None:
    profile = _v2_profile(tmp_path / "balanced_stable_micro.ini")

    guard = validate_micro_v2_forward_shadow_runtime(
        mode="forward-shadow",
        signal_profile="BALANCED_STABLE_MICRO_V2",
        profile_config=profile,
        sqlite_path="data/sqlite/forward-shadow-v2-dryrun.sqlite3",
        log_dir="data/logs/forward-shadow-v2-dryrun",
    )

    assert guard["micro_v2_runtime_guard_status"] == "MICRO_V2_PROFILE_INVALID"


def test_rejects_v2_approved_for_demo_true(tmp_path: Path) -> None:
    profile = _v2_profile(tmp_path / "balanced_stable_micro_v2.ini", overrides={"APPROVED_FOR_DEMO": "true"})

    guard = validate_micro_v2_forward_shadow_runtime(
        mode="forward-shadow",
        signal_profile="BALANCED_STABLE_MICRO_V2",
        profile_config=profile,
        sqlite_path="data/sqlite/forward-shadow-v2-dryrun.sqlite3",
        log_dir="data/logs/forward-shadow-v2-dryrun",
    )

    assert guard["micro_v2_runtime_guard_status"] == "MICRO_V2_PROFILE_INVALID"


def test_rejects_v2_approved_for_live_true(tmp_path: Path) -> None:
    profile = _v2_profile(tmp_path / "balanced_stable_micro_v2.ini", overrides={"APPROVED_FOR_LIVE": "true"})

    guard = validate_micro_v2_forward_shadow_runtime(
        mode="forward-shadow",
        signal_profile="BALANCED_STABLE_MICRO_V2",
        profile_config=profile,
        sqlite_path="data/sqlite/forward-shadow-v2-dryrun.sqlite3",
        log_dir="data/logs/forward-shadow-v2-dryrun",
    )

    assert guard["micro_v2_runtime_guard_status"] == "MICRO_V2_PROFILE_INVALID"


def test_micro_v2_runtime_profile_check_writes_reports(tmp_path: Path) -> None:
    profile = _v2_profile(tmp_path / "balanced_stable_micro_v2.ini")
    summary = run_micro_v2_runtime_profile_check(
        sqlite_path=tmp_path / "stable.sqlite3",
        log_dir=tmp_path / "stable_logs",
        reports_root=tmp_path / "reports",
        v2_profile_config=profile,
        output_dir=tmp_path / "out",
    )

    assert summary["micro_v2_runtime_profile_check_status"] == "MICRO_V2_SIGNAL_PROFILE_REGISTERED"
    assert (tmp_path / "out" / "micro_v2_runtime_profile_check_summary.json").exists()
    assert (tmp_path / "out" / "signal_profile_registry.json").exists()
    assert (tmp_path / "out" / "v2_runtime_guards.json").exists()
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_runtime_check_does_not_modify_sqlite(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "stable.sqlite3"
    conn = sqlite3.connect(sqlite_path)
    conn.execute("create table marker(id integer primary key, value text)")
    conn.execute("insert into marker(value) values ('before')")
    conn.commit()
    before = sqlite_path.read_bytes()
    conn.close()
    profile = _v2_profile(tmp_path / "balanced_stable_micro_v2.ini")

    run_micro_v2_runtime_profile_check(
        sqlite_path=sqlite_path,
        log_dir=tmp_path / "stable_logs",
        reports_root=tmp_path / "reports",
        v2_profile_config=profile,
        output_dir=tmp_path / "out",
    )

    assert sqlite_path.read_bytes() == before


def _v2_profile(path: Path, *, overrides: dict[str, str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "PROFILE_NAME": "BALANCED_STABLE_MICRO_V2",
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO_V2",
        "PROFILE_TYPE": "PAPER_SHADOW_ONLY",
        "PAPER_ONLY": "true",
        "NOT_FOR_DEMO_LIVE": "true",
        "NOT_FOR_LIVE": "true",
        "APPROVED_FOR_PAPER_DRY_RUN_ONLY": "true",
        "APPROVED_FOR_DEMO": "false",
        "APPROVED_FOR_LIVE": "false",
        "REQUIRES_STABLE_GATE": "true",
        "REQUIRES_PAPER_RISK_CLEARANCE": "true",
        "REQUIRES_DAILY_RISK_LEDGER": "true",
        "STABILITY_FILTERS_APPLIED": "true",
        "PAPER_RISK_MULTIPLIER": "0.1",
        "MAX_OPEN_PAPER_TRADES": "1",
        "MAX_PAPER_TRADES_PER_DAY": "3",
        "COOLDOWN_AFTER_LOSS_MINUTES": "108",
        "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES": "1440",
        "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT": "true",
        "MANUAL_RESUME_REQUIRED": "true",
    }
    values.update(overrides or {})
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path

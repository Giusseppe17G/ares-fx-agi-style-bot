from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_observation_playbook import run_micro_v2_observation_playbook


def test_generates_command_pack_and_criteria(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)

    summary = _run(paths)

    assert summary["micro_v2_observation_playbook_status"] == "MICRO_V2_OBSERVATION_PLAYBOOK_READY"
    assert summary["launch_commands_created"] is True
    assert summary["monitoring_commands_created"] is True
    assert summary["evidence_commands_created"] is True
    assert summary["advancement_criteria_created"] is True
    assert summary["stop_rollback_criteria_created"] is True
    assert (paths["out"] / "launch_commands.md").exists()
    assert (paths["out"] / "monitoring_commands.md").exists()
    assert (paths["out"] / "evidence_commands.md").exists()
    assert "micro-v2-market-open-readiness" in (paths["out"] / "monitoring_commands.md").read_text(encoding="utf-8")
    assert "fresh_tick_symbols is not empty" in (paths["out"] / "advancement_criteria.md").read_text(encoding="utf-8")
    assert "execution_attempted=true" in (paths["out"] / "stop_rollback_criteria.md").read_text(encoding="utf-8")


def test_does_not_modify_sqlite_logs_or_profiles(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8")
    profile_before = paths["profile"].read_text(encoding="utf-8")

    result = cli.main(
        [
            "--mode",
            "micro-v2-observation-playbook",
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--base-sqlite",
            str(paths["base_sqlite"]),
            "--base-log-dir",
            str(paths["base_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8") == log_before
    assert paths["profile"].read_text(encoding="utf-8") == profile_before


def test_blocks_if_v2_paths_are_stable(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)

    summary = run_micro_v2_observation_playbook(
        v2_sqlite=paths["base_sqlite"],
        v2_log_dir=paths["base_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        output_dir=paths["out"],
    )

    assert summary["micro_v2_observation_playbook_status"] == "MICRO_V2_OBSERVATION_PLAYBOOK_BLOCKED"
    assert "V2_SQLITE_POINTS_TO_STABLE" in summary["path_isolation_failures"]
    assert "V2_LOG_DIR_POINTS_TO_STABLE" in summary["path_isolation_failures"]


def test_generated_commands_do_not_include_execution_calls(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)

    combined = "\n".join((paths["out"] / name).read_text(encoding="utf-8") for name in ("launch_commands.md", "monitoring_commands.md", "evidence_commands.md"))
    assert "order_send" not in combined
    assert "order_check" not in combined
    assert summary["execution_attempted"] is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_observation_playbook(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "out": tmp_path / "data" / "reports" / "micro_v2_observation_playbook",
    }
    for key in ("v2_log_dir", "base_log_dir", "reports_root"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text(
        "\n".join(
            [
                "PROFILE_NAME=BALANCED_STABLE_MICRO_V2",
                "PAPER_ONLY=true",
                "NOT_FOR_DEMO_LIVE=true",
                "NOT_FOR_LIVE=true",
                "APPROVED_FOR_PAPER_DRY_RUN_ONLY=true",
                "APPROVED_FOR_DEMO=false",
                "APPROVED_FOR_LIVE=false",
            ]
        ),
        encoding="utf-8",
    )
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT)")
        conn.commit()
    finally:
        conn.close()

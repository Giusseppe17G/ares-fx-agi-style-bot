from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_clearance import run_micro_v2_paper_risk_clearance
from agi_style_forex_bot_mt5.paper_risk_review import validate_micro_resume_clearance
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_grants_clearance_when_v2_phase48_and_phase50_valid(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)

    summary = run_micro_v2_paper_risk_clearance(
        sqlite_path=paths["sqlite"],
        reports_root=paths["reports"],
        base_clearance_ledger=paths["base_ledger"],
        v2_profile_config=paths["profile"],
        micro_v2_review_dir=paths["phase48_dir"],
        runtime_profile_check_dir=paths["phase50_dir"],
        output_dir=paths["out"],
    )

    assert summary["micro_v2_clearance_status"] == "MICRO_V2_PAPER_RISK_CLEARANCE_GRANTED"
    assert Path(str(summary["paper_risk_clearance_v2_ledger"])).exists()
    assert summary["cleared_for_profile_canonical"] == "BALANCED_STABLE_MICRO_V2"
    assert summary["approved_for_demo"] is False
    assert summary["approved_for_live"] is False
    assert summary["execution_attempted"] is False


def test_rejects_without_paper_dry_run_approval(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, profile_overrides={"APPROVED_FOR_PAPER_DRY_RUN_ONLY": "false"})

    summary = run_micro_v2_paper_risk_clearance(
        sqlite_path=paths["sqlite"],
        reports_root=paths["reports"],
        base_clearance_ledger=paths["base_ledger"],
        v2_profile_config=paths["profile"],
        micro_v2_review_dir=paths["phase48_dir"],
        runtime_profile_check_dir=paths["phase50_dir"],
        output_dir=paths["out"],
    )

    assert summary["micro_v2_clearance_status"] == "MICRO_V2_CLEARANCE_REJECTED_PROFILE_INVALID"


def test_rejects_approved_for_demo_true(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, profile_overrides={"APPROVED_FOR_DEMO": "true"})
    summary = _run(paths)
    assert summary["micro_v2_clearance_status"] == "MICRO_V2_CLEARANCE_REJECTED_PROFILE_INVALID"


def test_rejects_approved_for_live_true(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, profile_overrides={"APPROVED_FOR_LIVE": "true"})
    summary = _run(paths)
    assert summary["micro_v2_clearance_status"] == "MICRO_V2_CLEARANCE_REJECTED_PROFILE_INVALID"


def test_rejects_when_phase48_not_approved(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, phase48_status="MICRO_V2_PROPOSED_REJECTED_UNSAFE_CHANGE")
    summary = _run(paths)
    assert summary["micro_v2_clearance_status"] == "MICRO_V2_CLEARANCE_REJECTED_PHASE48_MISSING"


def test_rejects_when_phase50_not_approved(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, phase50_status="MICRO_V2_SIGNAL_PROFILE_NOT_REGISTERED")
    summary = _run(paths)
    assert summary["micro_v2_clearance_status"] == "MICRO_V2_CLEARANCE_REJECTED_PHASE50_MISSING"


def test_does_not_modify_base_clearance_ledger(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before = Path(paths["base_ledger"]).read_bytes()

    _run(paths)

    assert Path(paths["base_ledger"]).read_bytes() == before


def test_runtime_accepts_v2_ledger_for_v2_profile(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)
    db = TelemetryDatabase(paths["v2_sqlite"])
    try:
        result = validate_micro_resume_clearance(
            database=db,
            clearance_ledger=summary["paper_risk_clearance_v2_ledger"],
            profile="BALANCED_STABLE_MICRO_V2",
            profile_config=paths["profile"],
            log_dir=tmp_path / "v2_logs",
            reports_root=tmp_path / "reports",
            paper_risk_dir=tmp_path / "paper_risk",
        )
    finally:
        db.close()

    assert result["accepted"] is True
    assert result["paper_risk_clearance_status"] == "PAPER_RISK_CLEARANCE_ACCEPTED"
    assert result["cleared_for_profile_canonical"] == "BALANCED_STABLE_MICRO_V2"


def test_runtime_rejects_base_ledger_for_v2_profile(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    db = TelemetryDatabase(paths["v2_sqlite"])
    try:
        result = validate_micro_resume_clearance(
            database=db,
            clearance_ledger=paths["base_ledger"],
            profile="BALANCED_STABLE_MICRO_V2",
            profile_config=paths["profile"],
            log_dir=tmp_path / "v2_logs",
            reports_root=tmp_path / "reports",
            paper_risk_dir=tmp_path / "paper_risk",
        )
    finally:
        db.close()

    assert result["accepted"] is False
    assert result["paper_risk_clearance_status"] == "PAPER_RISK_CLEARANCE_PROFILE_MISMATCH"


def test_runtime_rejects_v2_ledger_for_base_micro_profile(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)
    base_profile = _base_micro_profile(tmp_path / "balanced_stable_micro.ini")
    db = TelemetryDatabase(paths["v2_sqlite"])
    try:
        result = validate_micro_resume_clearance(
            database=db,
            clearance_ledger=summary["paper_risk_clearance_v2_ledger"],
            profile="BALANCED_STABLE_MICRO",
            profile_config=base_profile,
            log_dir=tmp_path / "v2_logs",
            reports_root=tmp_path / "reports",
            paper_risk_dir=tmp_path / "paper_risk",
        )
    finally:
        db.close()

    assert result["accepted"] is False
    assert result["paper_risk_clearance_status"] == "PAPER_RISK_CLEARANCE_PROFILE_MISMATCH"


def test_cli_generates_micro_v2_clearance(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)

    assert cli.main(
        [
            "--mode",
            "micro-v2-paper-risk-clearance",
            "--sqlite",
            str(paths["sqlite"]),
            "--reports-root",
            str(paths["reports"]),
            "--base-clearance-ledger",
            str(paths["base_ledger"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--micro-v2-review-dir",
            str(paths["phase48_dir"]),
            "--runtime-profile-check-dir",
            str(paths["phase50_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    ) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "micro-v2-paper-risk-clearance"
    assert summary["micro_v2_clearance_status"] == "MICRO_V2_PAPER_RISK_CLEARANCE_GRANTED"
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_does_not_modify_sqlite(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    conn = sqlite3.connect(paths["sqlite"])
    conn.execute("create table marker(id integer primary key, value text)")
    conn.execute("insert into marker(value) values ('before')")
    conn.commit()
    before = Path(paths["sqlite"]).read_bytes()
    conn.close()

    _run(paths)

    assert Path(paths["sqlite"]).read_bytes() == before


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_paper_risk_clearance(
        sqlite_path=paths["sqlite"],
        reports_root=paths["reports"],
        base_clearance_ledger=paths["base_ledger"],
        v2_profile_config=paths["profile"],
        micro_v2_review_dir=paths["phase48_dir"],
        runtime_profile_check_dir=paths["phase50_dir"],
        output_dir=paths["out"],
    )


def _fixture(
    tmp_path: Path,
    *,
    profile_overrides: dict[str, str] | None = None,
    phase48_status: str = "MICRO_V2_PROPOSED_APPROVED_FOR_PAPER_DRY_RUN",
    phase50_status: str = "MICRO_V2_SIGNAL_PROFILE_REGISTERED",
) -> dict[str, Path]:
    reports = tmp_path / "reports"
    phase48_dir = reports / "micro_v2_review_proposed"
    phase50_dir = reports / "micro_v2_runtime_profile_check"
    phase48_dir.mkdir(parents=True)
    phase50_dir.mkdir(parents=True)
    (phase48_dir / "micro_v2_proposed_review_summary.json").write_text(
        json.dumps({"micro_v2_proposed_review_status": phase48_status, "micro_v2_profile_created": phase48_status == "MICRO_V2_PROPOSED_APPROVED_FOR_PAPER_DRY_RUN"}),
        encoding="utf-8",
    )
    (phase50_dir / "micro_v2_runtime_profile_check_summary.json").write_text(
        json.dumps({"micro_v2_runtime_profile_check_status": phase50_status, "runtime_guard_status": "MICRO_V2_RUNTIME_GUARDS_PASSED" if phase50_status == "MICRO_V2_SIGNAL_PROFILE_REGISTERED" else "FAIL", "launch_command_invalid_choice_resolved": phase50_status == "MICRO_V2_SIGNAL_PROFILE_REGISTERED"}),
        encoding="utf-8",
    )
    base_ledger = tmp_path / "paper_risk_clearance_ledger.json"
    base_ledger.write_text(
        json.dumps(
            {
                "mode": "paper-risk-clearance-ledger",
                "clearances": [
                    {
                        "clearance_id": "base",
                        "created_at_utc": "2026-05-01T00:00:00+00:00",
                        "cleared_for_profile": "BALANCED_STABLE_MICRO",
                        "canonical_cleared_for_profile": "BALANCED_STABLE_MICRO",
                        "cleared_for_paper_shadow": True,
                        "not_for_demo_live": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return {
        "sqlite": tmp_path / "stable.sqlite3",
        "v2_sqlite": tmp_path / "v2.sqlite3",
        "reports": reports,
        "base_ledger": base_ledger,
        "profile": _v2_profile(tmp_path / "balanced_stable_micro_v2.ini", overrides=profile_overrides),
        "phase48_dir": phase48_dir,
        "phase50_dir": phase50_dir,
        "out": tmp_path / "out",
    }


def _v2_profile(path: Path, *, overrides: dict[str, str] | None = None) -> Path:
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
        "PAPER_RISK_MULTIPLIER": "0.1",
        "MAX_OPEN_PAPER_TRADES": "1",
        "MAX_PAPER_TRADES_PER_DAY": "3",
    }
    values.update(overrides or {})
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path


def _base_micro_profile(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE_MICRO",
                "PROFILE_TYPE=PAPER_SHADOW_ONLY",
                "PAPER_ONLY=true",
                "NOT_FOR_DEMO_LIVE=true",
                "PAPER_RISK_MULTIPLIER=0.1",
                "MAX_OPEN_PAPER_TRADES=1",
                "MAX_PAPER_TRADES_PER_DAY=2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path

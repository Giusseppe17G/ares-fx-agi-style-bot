from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_review import run_micro_v2_review
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_rejects_if_risk_multiplier_increases(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    candidate = _profile(tmp_path / "candidate.ini", paper_risk_multiplier="0.2", cooldown="90")
    try:
        summary = run_micro_v2_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, candidate_profile_config=candidate, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["micro_v2_review_status"] == "MICRO_V2_REJECTED_RISK_INCREASE"
    assert summary["micro_v2_profile_created"] is False


def test_rejects_if_paper_only_not_true(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    candidate = _profile(tmp_path / "candidate.ini", paper_only="false")
    try:
        summary = run_micro_v2_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, candidate_profile_config=candidate, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["micro_v2_review_status"] == "MICRO_V2_REJECTED_UNSAFE_CHANGE"


def test_rejects_if_not_for_demo_live_not_true(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    candidate = _profile(tmp_path / "candidate.ini", not_for_demo_live="false")
    try:
        summary = run_micro_v2_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, candidate_profile_config=candidate, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["micro_v2_review_status"] == "MICRO_V2_REJECTED_UNSAFE_CHANGE"


def test_approves_conservative_candidate_and_creates_profile(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini", cooldown="120")
    candidate = _profile(tmp_path / "candidate.ini", cooldown="90")
    try:
        summary = run_micro_v2_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, candidate_profile_config=candidate, output_dir=tmp_path / "out")
    finally:
        db.close()

    final_profile = tmp_path / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini"
    assert summary["micro_v2_review_status"] == "MICRO_V2_APPROVED_FOR_PAPER_DRY_RUN"
    assert final_profile.exists()
    text = final_profile.read_text(encoding="utf-8")
    assert "PROFILE_NAME=BALANCED_STABLE_MICRO_V2" in text
    assert "APPROVED_FOR_PAPER_DRY_RUN_ONLY=true" in text
    assert "NOT_FOR_LIVE=true" in text


def test_no_actionable_changes_does_not_create_profile(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    candidate = _profile(tmp_path / "candidate.ini", not_active=True)
    try:
        summary = run_micro_v2_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, candidate_profile_config=candidate, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["micro_v2_review_status"] == "MICRO_V2_NO_ACTIONABLE_CHANGES"
    assert not (tmp_path / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini").exists()


def test_does_not_modify_base_profile_or_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    candidate = _profile(tmp_path / "candidate.ini", cooldown="90")
    before_profile = base.read_text(encoding="utf-8")
    try:
        db.insert_event({"event_id": "evt1", "idempotency_key": "evt1", "event_type": "SIGNAL_REJECTED", "symbol": "EURUSD", "severity": "INFO", "module": "test", "message": "reject", "payload": {"reason": "REGIME_BLOCK"}})
        before_db = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
        summary = run_micro_v2_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, candidate_profile_config=candidate, output_dir=tmp_path / "out")
        after_db = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
    finally:
        db.close()

    assert base.read_text(encoding="utf-8") == before_profile
    assert before_db == after_db
    assert summary["sqlite_unchanged"] is True
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_mode_generates_review(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    db = TelemetryDatabase(sqlite)
    db.close()
    base = _profile(tmp_path / "base.ini")
    candidate = _profile(tmp_path / "candidate.ini", cooldown="90")

    assert cli.main(["--mode", "micro-v2-review", "--sqlite", str(sqlite), "--reports-root", str(tmp_path / "reports"), "--base-profile-config", str(base), "--candidate-profile-config", str(candidate), "--output-dir", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["mode"] == "micro-v2-review"
    assert (tmp_path / "out" / "micro_v2_review_summary.json").exists()
    assert summary["execution_attempted"] is False


def _profile(
    path: Path,
    *,
    paper_risk_multiplier: str = "0.1",
    cooldown: str = "120",
    paper_only: str = "true",
    not_for_demo_live: str = "true",
    not_active: bool = False,
) -> Path:
    lines = [
        "SIGNAL_PROFILE=BALANCED_STABLE_MICRO",
        "BASE_PROFILE=BALANCED_STABLE",
        f"NOT_FOR_DEMO_LIVE={not_for_demo_live}",
        f"PAPER_ONLY={paper_only}",
        "REQUIRE_STABLE_GATE=true",
        "REQUIRE_PROFILE_CONFIG=true",
        "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT=true",
        f"PAPER_RISK_MULTIPLIER={paper_risk_multiplier}",
        "MAX_OPEN_PAPER_TRADES=1",
        "MAX_PAPER_TRADES_PER_DAY=2",
        f"COOLDOWN_AFTER_LOSS_MINUTES={cooldown}",
        "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES=1440",
    ]
    if not_active:
        lines.insert(0, "NOT_ACTIVE_RESEARCH_ONLY=true")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

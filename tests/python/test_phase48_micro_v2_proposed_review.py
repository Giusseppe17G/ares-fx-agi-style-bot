from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_review import run_micro_v2_proposed_review
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_approves_loss_cooldown_120_to_108(tmp_path: Path) -> None:
    summary, final_profile, _base = _run_review(tmp_path)

    assert summary["micro_v2_proposed_review_status"] == "MICRO_V2_PROPOSED_APPROVED_FOR_PAPER_DRY_RUN"
    text = final_profile.read_text(encoding="utf-8")
    assert "COOLDOWN_AFTER_LOSS_MINUTES=108" in text


def test_approves_max_paper_trades_per_day_2_to_3(tmp_path: Path) -> None:
    summary, final_profile, _base = _run_review(tmp_path)

    assert summary["micro_v2_profile_created"] is True
    assert "MAX_PAPER_TRADES_PER_DAY=3" in final_profile.read_text(encoding="utf-8")


def test_rejects_max_paper_trades_per_day_above_3(tmp_path: Path) -> None:
    summary, final_profile, _base = _run_review(tmp_path, proposed_overrides={"MAX_PAPER_TRADES_PER_DAY": "4"})

    assert summary["micro_v2_proposed_review_status"] == "MICRO_V2_PROPOSED_REJECTED_UNSAFE_CHANGE"
    assert not final_profile.exists()


def test_rejects_drawdown_halt_cooldown_reduction(tmp_path: Path) -> None:
    summary, final_profile, _base = _run_review(tmp_path, proposed_overrides={"COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES": "1200"})

    assert summary["micro_v2_proposed_review_status"] == "MICRO_V2_PROPOSED_REJECTED_UNSAFE_CHANGE"
    assert not final_profile.exists()


def test_rejects_risk_multiplier_increase(tmp_path: Path) -> None:
    summary, final_profile, _base = _run_review(tmp_path, proposed_overrides={"PAPER_RISK_MULTIPLIER": "0.2"})

    assert summary["micro_v2_proposed_review_status"] == "MICRO_V2_PROPOSED_REJECTED_RISK_INCREASE"
    assert not final_profile.exists()


def test_rejects_max_open_trades_above_1(tmp_path: Path) -> None:
    summary, final_profile, _base = _run_review(tmp_path, proposed_overrides={"MAX_OPEN_TRADES": "2"})

    assert summary["micro_v2_proposed_review_status"] == "MICRO_V2_PROPOSED_REJECTED_UNSAFE_CHANGE"
    assert not final_profile.exists()


def test_final_profile_contains_required_approval_markers(tmp_path: Path) -> None:
    summary, final_profile, _base = _run_review(tmp_path)
    text = final_profile.read_text(encoding="utf-8")

    assert summary["micro_v2_profile_created"] is True
    assert "PROFILE_NAME=BALANCED_STABLE_MICRO_V2" in text
    assert "CREATED_FROM=balanced_stable_micro_v2_proposed.ini" in text
    assert "SOURCE_PHASE=FASE_48_MICRO_V2_PROPOSED_REVIEW" in text
    assert "APPROVED_FOR_PAPER_DRY_RUN_ONLY=true" in text
    assert "APPROVED_FOR_DEMO=false" in text
    assert "APPROVED_FOR_LIVE=false" in text


def test_does_not_modify_base_profile_or_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _base_profile(tmp_path / "base.ini")
    proposed = _proposed_profile(tmp_path / "proposed.ini")
    before_profile = base.read_text(encoding="utf-8")
    try:
        db.insert_event({"event_id": "evt1", "idempotency_key": "evt1", "event_type": "SIGNAL_REJECTED", "symbol": "EURUSD", "severity": "INFO", "module": "test", "message": "reject", "payload": {"reason": "COOLDOWN_BLOCK"}})
        before_db = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
        summary = run_micro_v2_proposed_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, proposed_profile_config=proposed, output_dir=tmp_path / "out")
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
    base = _base_profile(tmp_path / "base.ini")
    proposed = _proposed_profile(tmp_path / "proposed.ini")

    assert cli.main(["--mode", "micro-v2-proposed-review", "--sqlite", str(sqlite), "--reports-root", str(tmp_path / "reports"), "--base-profile-config", str(base), "--proposed-profile-config", str(proposed), "--output-dir", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["mode"] == "micro-v2-proposed-review"
    assert summary["execution_attempted"] is False
    assert (tmp_path / "out" / "micro_v2_proposed_review_summary.json").exists()


def _run_review(tmp_path: Path, *, proposed_overrides: dict[str, str] | None = None) -> tuple[dict[str, object], Path, Path]:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _base_profile(tmp_path / "base.ini")
    proposed = _proposed_profile(tmp_path / "proposed.ini", overrides=proposed_overrides)
    try:
        summary = run_micro_v2_proposed_review(database=db, reports_root=tmp_path / "reports", base_profile_config=base, proposed_profile_config=proposed, output_dir=tmp_path / "out")
    finally:
        db.close()
    return summary, tmp_path / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini", base


def _base_profile(path: Path) -> Path:
    values = {
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO",
        "NOT_FOR_DEMO_LIVE": "true",
        "PAPER_ONLY": "true",
        "PAPER_RISK_MULTIPLIER": "0.1",
        "MAX_OPEN_PAPER_TRADES": "1",
        "MAX_PAPER_TRADES_PER_DAY": "2",
        "COOLDOWN_AFTER_LOSS_MINUTES": "120",
        "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES": "1440",
        "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT": "true",
        "REQUIRE_STABLE_GATE": "true",
    }
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path


def _proposed_profile(path: Path, *, overrides: dict[str, str] | None = None) -> Path:
    values = {
        "PROFILE_NAME": "BALANCED_STABLE_MICRO_V2_PROPOSED",
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO_V2_PROPOSED",
        "NOT_ACTIVE_RESEARCH_ONLY": "true",
        "APPROVED_FOR_PAPER_DRY_RUN_ONLY": "false",
        "NOT_FOR_DEMO_LIVE": "true",
        "NOT_FOR_LIVE": "true",
        "PAPER_ONLY": "true",
        "PAPER_RISK_MULTIPLIER": "0.1",
        "MAX_OPEN_PAPER_TRADES": "1",
        "MAX_PAPER_TRADES_PER_DAY": "3",
        "COOLDOWN_AFTER_LOSS_MINUTES": "108",
        "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES": "1440",
        "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT": "true",
        "REQUIRES_STABLE_GATE": "true",
        "REQUIRES_PAPER_RISK_CLEARANCE": "true",
        "REQUIRES_DAILY_RISK_LEDGER": "true",
    }
    values.update(overrides or {})
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path

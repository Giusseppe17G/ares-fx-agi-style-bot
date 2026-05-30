from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_frequency_proposal import run_micro_frequency_proposal
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_no_safe_mapping_reports_status_without_inventing_parameters(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini", include_cooldown=False, include_daily_limit=False)
    freq = _frequency_dir(tmp_path)
    try:
        summary = run_micro_frequency_proposal(database=db, reports_root=tmp_path / "reports", base_profile_config=base, frequency_dir=freq, v2_review_dir=tmp_path / "review", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["proposal_status"] == "NO_SAFE_PARAMETER_MAPPING_FOUND"
    assert summary["proposed_profile_created"] is False
    assert not (tmp_path / "out" / "balanced_stable_micro_v2_proposed.ini").exists()


def test_does_not_increase_risk_multiplier(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    freq = _frequency_dir(tmp_path)
    try:
        summary = run_micro_frequency_proposal(database=db, reports_root=tmp_path / "reports", base_profile_config=base, frequency_dir=freq, v2_review_dir=tmp_path / "review", output_dir=tmp_path / "out")
    finally:
        db.close()

    proposed = (tmp_path / "out" / "balanced_stable_micro_v2_proposed.ini").read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in proposed.splitlines() if "=" in line and not line.startswith(";"))
    assert "PAPER_RISK_MULTIPLIER=0.1" in proposed
    assert float(values["PAPER_RISK_MULTIPLIER"]) <= 0.1
    assert summary["proposal_status"] == "MICRO_FREQUENCY_PROPOSAL_CREATED"


def test_does_not_raise_max_open_trades_above_one(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini", extra={"MAX_OPEN_TRADES": "1"})
    freq = _frequency_dir(tmp_path)
    try:
        run_micro_frequency_proposal(database=db, reports_root=tmp_path / "reports", base_profile_config=base, frequency_dir=freq, v2_review_dir=tmp_path / "review", output_dir=tmp_path / "out")
    finally:
        db.close()

    proposed = (tmp_path / "out" / "balanced_stable_micro_v2_proposed.ini").read_text(encoding="utf-8")
    assert "MAX_OPEN_TRADES=1" in proposed
    assert "MAX_OPEN_PAPER_TRADES=1" in proposed


def test_does_not_reduce_drawdown_halt_cooldown(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    freq = _frequency_dir(tmp_path)
    try:
        summary = run_micro_frequency_proposal(database=db, reports_root=tmp_path / "reports", base_profile_config=base, frequency_dir=freq, v2_review_dir=tmp_path / "review", output_dir=tmp_path / "out")
    finally:
        db.close()

    proposed = (tmp_path / "out" / "balanced_stable_micro_v2_proposed.ini").read_text(encoding="utf-8")
    assert "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES=1440" in proposed
    assert any(item["bottleneck"] == "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES" for item in summary["rejected_possible_changes"])


def test_creates_proposed_ini_only_with_safe_changes(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    freq = _frequency_dir(tmp_path)
    try:
        summary = run_micro_frequency_proposal(database=db, reports_root=tmp_path / "reports", base_profile_config=base, frequency_dir=freq, v2_review_dir=tmp_path / "review", output_dir=tmp_path / "out")
    finally:
        db.close()

    proposed = tmp_path / "out" / "balanced_stable_micro_v2_proposed.ini"
    assert proposed.exists()
    text = proposed.read_text(encoding="utf-8")
    assert "NOT_ACTIVE_RESEARCH_ONLY=true" in text
    assert "APPROVED_FOR_PAPER_DRY_RUN_ONLY=false" in text
    assert "COOLDOWN_AFTER_LOSS_MINUTES=108" in text
    assert "MAX_PAPER_TRADES_PER_DAY=3" in text
    assert summary["proposal_status"] == "MICRO_FREQUENCY_PROPOSAL_CREATED"


def test_does_not_modify_base_profile_or_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    base = _profile(tmp_path / "base.ini")
    freq = _frequency_dir(tmp_path)
    before_profile = base.read_text(encoding="utf-8")
    try:
        db.insert_event({"event_id": "evt1", "idempotency_key": "evt1", "event_type": "SIGNAL_REJECTED", "symbol": "EURUSD", "severity": "INFO", "module": "test", "message": "reject", "payload": {"reason": "COOLDOWN_BLOCK"}})
        before_db = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
        summary = run_micro_frequency_proposal(database=db, reports_root=tmp_path / "reports", base_profile_config=base, frequency_dir=freq, v2_review_dir=tmp_path / "review", output_dir=tmp_path / "out")
        after_db = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
    finally:
        db.close()

    assert base.read_text(encoding="utf-8") == before_profile
    assert before_db == after_db
    assert summary["sqlite_unchanged"] is True
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_mode_generates_proposal(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    db = TelemetryDatabase(sqlite)
    db.close()
    base = _profile(tmp_path / "base.ini")
    freq = _frequency_dir(tmp_path)

    assert cli.main(["--mode", "micro-frequency-proposal", "--sqlite", str(sqlite), "--reports-root", str(tmp_path / "reports"), "--base-profile-config", str(base), "--frequency-dir", str(freq), "--v2-review-dir", str(tmp_path / "review"), "--output-dir", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["mode"] == "micro-frequency-proposal"
    assert summary["proposal_status"] == "MICRO_FREQUENCY_PROPOSAL_CREATED"
    assert summary["execution_attempted"] is False


def _profile(path: Path, *, include_cooldown: bool = True, include_daily_limit: bool = True, extra: dict[str, str] | None = None) -> Path:
    values = {
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO",
        "NOT_FOR_DEMO_LIVE": "true",
        "PAPER_ONLY": "true",
        "PAPER_RISK_MULTIPLIER": "0.1",
        "MAX_OPEN_PAPER_TRADES": "1",
        "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES": "1440",
        "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT": "true",
    }
    if include_cooldown:
        values["COOLDOWN_AFTER_LOSS_MINUTES"] = "120"
    if include_daily_limit:
        values["MAX_PAPER_TRADES_PER_DAY"] = "2"
    values.update(extra or {})
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path


def _frequency_dir(tmp_path: Path) -> Path:
    path = tmp_path / "frequency"
    path.mkdir()
    (path / "micro_frequency_summary.json").write_text(
        json.dumps(
            {
                "trade_shortfall": 2,
                "top_frequency_bottlenecks": [
                    {"bottleneck": "REGIME_BLOCK", "count": 31},
                    {"bottleneck": "LIQUIDITY_BLOCK", "count": 24},
                    {"bottleneck": "STALE_SIGNAL_BLOCK", "count": 11},
                    {"bottleneck": "COOLDOWN_BLOCK", "count": 5},
                    {"bottleneck": "SPREAD_BLOCK", "count": 4},
                    {"bottleneck": "SCORE_THRESHOLD_BLOCK", "count": 2},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path

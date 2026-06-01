from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_consolidated_audit import run_micro_v2_consolidated_audit


def test_market_closed_dominates_not_stable(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.75)
    _exposure(paths["v2_sqlite"], actual=1.0)

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_MARKET_NOT_STABLE_ENOUGH"


def test_exposure_zero_with_open_trades_zero_double_counting(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, open_trades=0)
    _exposure(paths["v2_sqlite"], actual=0.0)

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_EXPOSURE_POSSIBLE_DOUBLE_COUNTING"
    assert summary["double_counting_detected"] is True


def test_exposure_data_missing(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1)
    _exposure(paths["v2_sqlite"], actual=None)

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_EXPOSURE_DATA_MISSING"
    assert summary["data_missing_detected"] is True


def test_profile_parse_error(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nMAX_OPEN_RISK_PCT=not-a-number\n", encoding="utf-8")
    _exposure(paths["v2_sqlite"], actual=1.0)

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_EXPOSURE_PROFILE_PARSE_ERROR"


def test_expected_exposure_and_stable_market_continue(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1)
    _exposure(paths["v2_sqlite"], actual=1.0)

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_CONTINUE_COLLECTING_MARKET_DATA"


def test_real_filters_with_fresh_ticks_ready_for_tuning_review(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, risk_reason="REGIME_BLOCK", risk_status="MICRO_V2_RISK_BLOCK_REQUIRES_MANUAL_REVIEW")

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_READY_FOR_FILTER_TUNING_REVIEW"


def test_closed_trades_ready_for_frequency_reevaluation(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, closed_trades=1)
    _exposure(paths["v2_sqlite"], actual=1.0)

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_READY_FOR_TRADE_FREQUENCY_REEVALUATION"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1)
    _exposure(paths["v2_sqlite"], actual=1.0, extra={"execution_attempted": True})

    summary = _run(paths)

    assert summary["consolidated_v2_audit_status"] == "MICRO_V2_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False


def test_cli_does_not_modify_sqlite_logs_or_profile(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1)
    _exposure(paths["v2_sqlite"], actual=1.0)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8")
    profile_before = paths["profile"].read_text(encoding="utf-8")

    result = cli.main(
        [
            "--mode",
            "micro-v2-consolidated-risk-market-audit",
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
            "--filter-analysis-dir",
            str(paths["filter_analysis_dir"]),
            "--risk-block-dir",
            str(paths["risk_block_dir"]),
            "--checkpoint-dir",
            str(paths["checkpoint_dir"]),
            "--readiness-dir",
            str(paths["readiness_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["execution_attempted"] is False
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8") == log_before
    assert paths["profile"].read_text(encoding="utf-8") == profile_before


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_consolidated_audit(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        filter_analysis_dir=paths["filter_analysis_dir"],
        risk_block_dir=paths["risk_block_dir"],
        checkpoint_dir=paths["checkpoint_dir"],
        readiness_dir=paths["readiness_dir"],
        output_dir=paths["out"],
    )


def _fixture(
    tmp_path: Path,
    *,
    market_ratio: float,
    open_trades: int = 0,
    closed_trades: int = 0,
    risk_reason: str = "EXPOSURE_BLOCK",
    risk_status: str = "MICRO_V2_RISK_BLOCK_EXPECTED_SAFETY_GUARD",
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "filter_analysis_dir": tmp_path / "data" / "reports" / "micro_v2_filter_analysis",
        "risk_block_dir": tmp_path / "data" / "reports" / "micro_v2_risk_block_audit",
        "checkpoint_dir": tmp_path / "data" / "reports" / "micro_v2_observation_checkpoint",
        "readiness_dir": tmp_path / "data" / "reports" / "micro_v2_market_open_readiness",
        "out": tmp_path / "data" / "reports" / "micro_v2_consolidated_audit",
    }
    for key in ("v2_log_dir", "base_log_dir", "reports_root", "filter_analysis_dir", "risk_block_dir", "checkpoint_dir", "readiness_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nMAX_OPEN_RISK_PCT=5\n", encoding="utf-8")
    total = 100
    market = int(total * market_ratio)
    _write_json(paths["filter_analysis_dir"] / "micro_v2_filter_analysis_summary.json", {"total_v2_rejections": total, "market_closed_rejection_count": market, "stale_tick_rejection_count": 0, "total_v2_signals": 120, "fresh_tick_symbols": ["EURUSD"], "dominant_v2_filter": "RISK_BLOCK"})
    _write_json(paths["risk_block_dir"] / "micro_v2_risk_block_summary.json", {"micro_v2_risk_block_status": risk_status, "dominant_risk_block_reason": risk_reason, "dominant_risk_block_share": 0.9, "risk_rejected_count": 42, "affected_symbols": ["EURUSD"]})
    _write_json(paths["checkpoint_dir"] / "micro_v2_observation_checkpoint_summary.json", {"micro_v2_checkpoint_status": "MICRO_V2_CHECKPOINT_READY_FOR_FILTER_ANALYSIS", "v2_paper_trades_open": open_trades, "v2_paper_trades_closed": closed_trades, "fresh_tick_symbols": ["EURUSD"]})
    _write_json(paths["readiness_dir"] / "micro_v2_market_open_readiness_summary.json", {"fresh_tick_symbols": ["EURUSD"], "stale_tick_symbols": []})
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)")
        conn.commit()
    finally:
        conn.close()


def _exposure(path: Path, *, actual: float | None, extra: dict[str, object] | None = None) -> None:
    payload: dict[str, object] = {"reason": "EXPOSURE_BLOCK", "blocking_reasons": ["EXPOSURE_BLOCK"], "session": "LONDON"}
    if actual is not None:
        payload["current_exposure"] = actual
    payload.update(extra or {})
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("RISK_REJECTED", "EURUSD", datetime.now(timezone.utc).isoformat(), "INFO", "EXPOSURE_BLOCK", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")

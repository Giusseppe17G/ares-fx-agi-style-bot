from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.research_candidate_ranking import run_research_candidate_ranking
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_cli_mode_exists_and_generates_reports(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    db = TelemetryDatabase(sqlite)
    try:
        _insert_event(db, "SIGNAL_REJECTED", "EURUSD", {"strategy_name": "strategy_ensemble", "reject_reason": "ENSEMBLE_SCORE_LOW"})
    finally:
        db.close()

    assert cli.main(["--mode", "research-candidate-ranking", "--sqlite", str(sqlite), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["mode"] == "research-candidate-ranking"
    assert (tmp_path / "out" / "candidate_ranking_summary.json").exists()
    assert summary["execution_attempted"] is False


def test_generates_ranking_with_minimal_data(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        _insert_event(db, "FORWARD_CANDIDATE_EVALUATED", "EURUSD", {"strategy_name": "strategy_ensemble", "ensemble_score": 61})
        summary = run_research_candidate_ranking(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["symbols_analyzed"] >= 1
    assert summary["strategies_analyzed"] >= 1
    assert summary["research_candidate_status"] in {"NEEDS_MORE_FORWARD_DATA", "DATA_INSUFFICIENT"}


def test_no_failure_with_few_trades(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_paper_trade(_trade("ptr1", "EURUSD", "strategy_ensemble", status="CLOSED", pnl=0.1))
        summary = run_research_candidate_ranking(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["paper_trade_count"] == 1
    assert summary["execution_attempted"] is False


def test_data_insufficient_classification(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        summary = run_research_candidate_ranking(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["research_candidate_status"] == "DATA_INSUFFICIENT"


def test_high_rejection_rate_classification(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        for idx in range(5):
            _insert_event(db, "SIGNAL_REJECTED", "GBPUSD", {"strategy_name": "strategy_ensemble", "reject_reason": "SPREAD_BLOCK", "ensemble_score": 20 + idx})
        summary = run_research_candidate_ranking(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
        rows = list((tmp_path / "out" / "candidate_ranking_by_symbol.csv").read_text(encoding="utf-8").splitlines())
    finally:
        db.close()

    assert summary["research_candidate_status"] == "HIGH_REJECTION_RATE"
    assert any("HIGH_REJECTION_RATE" in row for row in rows)


def test_does_not_modify_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        _insert_event(db, "SIGNAL_REJECTED", "USDJPY", {"strategy_name": "strategy_ensemble", "reject_reason": "STALE_SIGNAL"})
        before = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
        summary = run_research_candidate_ranking(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
        after = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
    finally:
        db.close()

    assert before == after
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def _insert_event(db: TelemetryDatabase, event_type: str, symbol: str, payload: dict[str, object]) -> None:
    event_id = f"evt_{event_type}_{symbol}_{db.count_rows('events')}"
    db.insert_event(
        {
            "event_id": event_id,
            "idempotency_key": event_id,
            "event_type": event_type,
            "symbol": symbol,
            "severity": "INFO",
            "module": "test",
            "message": event_type.lower(),
            "payload": payload,
        }
    )


def _trade(trade_id: str, symbol: str, strategy: str, *, status: str, pnl: float) -> dict[str, object]:
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig-{trade_id}",
        "idempotency_key": f"idem-{trade_id}",
        "symbol": symbol,
        "broker_symbol": symbol,
        "direction": "BUY",
        "entry_time_utc": "2026-05-28T00:00:00+00:00",
        "exit_time_utc": "2026-05-28T00:05:00+00:00" if status == "CLOSED" else None,
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
        "lot": 0.01,
        "risk_pct": 0.1,
        "risk_amount": 1.0,
        "strategy_name": strategy,
        "strategy_version": "1",
        "regime": "RANGE",
        "session": "LONDON",
        "score": 70,
        "reasons": [],
        "status": status,
        "scaled_paper_pnl": pnl,
    }

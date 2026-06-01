from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_lifecycle_risk_comparison import run_micro_v2_lifecycle_risk_comparison


def test_open_trades_healthy_collecting_exits(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=[_trade("ptr1")], closed_trades=0)
    summary = _run(paths)
    assert summary["micro_v2_lifecycle_risk_comparison_status"] == "MICRO_V2_OPEN_TRADES_HEALTHY_COLLECTING_EXITS"
    assert summary["acceptance_ready"] is False


def test_closed_ten_and_24h_ready_final_pack(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=[], closed_trades=10, hours=25)
    summary = _run(paths)
    assert summary["micro_v2_lifecycle_risk_comparison_status"] == "MICRO_V2_READY_FOR_FINAL_ACCEPTANCE_EVIDENCE_PACK"
    assert summary["acceptance_ready"] is True


def test_invalid_risk_distance_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=[_trade("ptr_bad", entry=1.1, sl=1.1)])
    summary = _run(paths)
    assert summary["micro_v2_lifecycle_risk_comparison_status"] == "MICRO_V2_OPEN_TRADES_INVALID_RISK_DISTANCE"
    assert summary["risk_distance_issues"] == 1


def test_invalid_sl_tp_blocks(tmp_path: Path) -> None:
    trade = _trade("ptr_sl", entry=1.1, sl=None, tp=1.102)
    paths = _fixture(tmp_path, open_trades=[trade])
    summary = _run(paths)
    assert summary["micro_v2_lifecycle_risk_comparison_status"] == "MICRO_V2_OPEN_TRADES_INVALID_SL_TP"
    assert summary["sl_tp_issues"] == 1


def test_pnl_issue_blocks(tmp_path: Path) -> None:
    trade = _trade("ptr_pnl", raw_pnl=10.0, scaled_paper_pnl=10.0)
    paths = _fixture(tmp_path, open_trades=[trade])
    summary = _run(paths)
    assert summary["micro_v2_lifecycle_risk_comparison_status"] == "MICRO_V2_OPEN_TRADES_PNL_ISSUE"
    assert summary["pnl_issues"] >= 1


def test_drawdown_active_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=[_trade("ptr1")], drawdown_event=True)
    summary = _run(paths)
    assert summary["micro_v2_lifecycle_risk_comparison_status"] == "MICRO_V2_RISK_HEALTH_BLOCKED"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=[_trade("ptr1")], safety=True)
    summary = _run(paths)
    assert summary["micro_v2_lifecycle_risk_comparison_status"] == "MICRO_V2_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False


def test_cli_does_not_modify_sqlite_logs_or_profile(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path, open_trades=[_trade("ptr1")])
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8")
    profile_before = paths["profile"].read_text(encoding="utf-8")
    result = cli.main(
        [
            "--mode",
            "micro-v2-lifecycle-risk-comparison",
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
            "--stable-window-dir",
            str(paths["stable_window_dir"]),
            "--checkpoint-dir",
            str(paths["checkpoint_dir"]),
            "--filter-analysis-dir",
            str(paths["filter_analysis_dir"]),
            "--consolidated-dir",
            str(paths["consolidated_dir"]),
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
    return run_micro_v2_lifecycle_risk_comparison(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        stable_window_dir=paths["stable_window_dir"],
        checkpoint_dir=paths["checkpoint_dir"],
        filter_analysis_dir=paths["filter_analysis_dir"],
        consolidated_dir=paths["consolidated_dir"],
        output_dir=paths["out"],
    )


def _fixture(
    tmp_path: Path,
    *,
    open_trades: list[dict[str, object]],
    closed_trades: int = 0,
    hours: float = 3.0,
    drawdown_event: bool = False,
    safety: bool = False,
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "stable_window_dir": tmp_path / "data" / "reports" / "micro_v2_stable_market_window",
        "checkpoint_dir": tmp_path / "data" / "reports" / "micro_v2_observation_checkpoint",
        "filter_analysis_dir": tmp_path / "data" / "reports" / "micro_v2_filter_analysis",
        "consolidated_dir": tmp_path / "data" / "reports" / "micro_v2_consolidated_audit",
        "out": tmp_path / "data" / "reports" / "micro_v2_lifecycle_risk_comparison",
    }
    for key in ("v2_log_dir", "base_log_dir", "reports_root", "stable_window_dir", "checkpoint_dir", "filter_analysis_dir", "consolidated_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    for trade in open_trades:
        _insert_trade(paths["v2_sqlite"], trade, "OPEN")
    for idx in range(closed_trades):
        _insert_trade(paths["v2_sqlite"], _trade(f"closed{idx}"), "CLOSED")
    if drawdown_event:
        _event(paths["v2_sqlite"], "ACTIVE_SCALED_DRAWDOWN_BLOCK", {"reason": "ACTIVE_SCALED_DRAWDOWN_BLOCK"})
    if safety:
        _event(paths["v2_sqlite"], "SIGNAL_REJECTED", {"execution_attempted": True})
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text(
        "PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_RISK_MULTIPLIER=0.1\nMAX_OPEN_TRADES=5\nMAX_PAPER_TRADES_PER_DAY=3\n",
        encoding="utf-8",
    )
    _write_json(paths["stable_window_dir"] / "micro_v2_stable_market_window_summary.json", {"paper_trades_open": len(open_trades), "paper_trades_closed": closed_trades, "observed_market_open_hours": hours, "fresh_tick_coverage_ratio": 1.0, "market_closed_dominance_ratio": 0.1, "stale_tick_symbols": []})
    _write_json(paths["checkpoint_dir"] / "micro_v2_observation_checkpoint_summary.json", {"v2_paper_trades_open": len(open_trades), "v2_paper_trades_closed": closed_trades, "v2_paper_trades_closed_today": min(closed_trades, 3)})
    _write_json(paths["filter_analysis_dir"] / "micro_v2_filter_analysis_summary.json", {"market_closed_dominance_ratio": 0.1})
    _write_json(paths["consolidated_dir"] / "micro_v2_consolidated_audit_summary.json", {"active_scaled_drawdown_count": 0, "daily_drawdown_status": "OK"})
    return paths


def _trade(
    trade_id: str,
    *,
    entry: float = 1.1,
    sl: float | None = 1.099,
    tp: float | None = 1.102,
    current: float = 1.1005,
    raw_pnl: float | None = None,
    scaled_paper_pnl: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "paper_trade_id": trade_id,
        "symbol": "EURUSD",
        "side": "BUY",
        "direction": "BUY",
        "entry_price": entry,
        "current_price": current,
        "volume": 1.0,
        "opened_at_utc": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
    }
    if sl is not None:
        payload["sl_price"] = sl
    if tp is not None:
        payload["tp_price"] = tp
    if raw_pnl is not None:
        payload["raw_pnl"] = raw_pnl
    if scaled_paper_pnl is not None:
        payload["scaled_paper_pnl"] = scaled_paper_pnl
    return payload


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, payload: dict[str, object], status: str) -> None:
    conn = sqlite3.connect(path)
    try:
        opened = str(payload.get("opened_at_utc") or datetime.now(timezone.utc).isoformat())
        closed = datetime.now(timezone.utc).isoformat() if status == "CLOSED" else ""
        saved = {**payload, "status": status}
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, symbol, status, payload_json, opened_at_utc, closed_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (payload["paper_trade_id"], payload.get("symbol", "EURUSD"), status, json.dumps(saved), opened, closed),
        )
        conn.commit()
    finally:
        conn.close()


def _event(path: Path, event_type: str, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, "EURUSD", datetime.now(timezone.utc).isoformat(), "INFO", event_type, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")

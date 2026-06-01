from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_invalid_trade_forensics import run_micro_v2_invalid_trade_forensics


def test_sl_equals_entry_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="SELL", entry=1.16542, sl=1.16542, tp=1.16363)])
    summary = _run(paths)
    assert summary["root_cause"] == "SL_EQUALS_ENTRY"
    assert summary["repair_plan_applied"] is False


def test_tp_equals_entry_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="BUY", entry=1.1, sl=1.099, tp=1.1)])
    assert _run(paths)["root_cause"] == "TP_EQUALS_ENTRY"


def test_sl_missing_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="BUY", entry=1.1, sl=None, tp=1.102)])
    assert _run(paths)["root_cause"] == "SL_MISSING"


def test_tp_missing_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="BUY", entry=1.1, sl=1.099, tp=None)])
    assert _run(paths)["root_cause"] == "TP_MISSING"


def test_wrong_side_long_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="BUY", entry=1.1, sl=1.101, tp=1.102)])
    assert _run(paths)["root_cause"] == "SL_WRONG_SIDE_FOR_LONG"


def test_wrong_side_short_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="SELL", entry=1.1, sl=1.099, tp=1.098)])
    assert _run(paths)["root_cause"] == "SL_WRONG_SIDE_FOR_SHORT"


def test_zero_atr_or_zero_stop_distance_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="BUY", entry=1.1, sl=1.1, tp=1.102)], event_payload={"atr": 0, "stop_distance": 0})
    assert _run(paths)["root_cause"] == "ZERO_ATR_OR_ZERO_STOP_DISTANCE"


def test_precision_rounding_collapse_detected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="BUY", entry=1.1, sl=1.1, tp=1.102, digits=5)])
    assert _run(paths)["root_cause"] == "SYMBOL_PRECISION_ROUNDING_COLLAPSE"


def test_no_invalid_trades(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="BUY", entry=1.1, sl=1.099, tp=1.102, invalid=False)])
    summary = _run(paths)
    assert summary["invalid_trade_forensics_status"] == "MICRO_V2_INVALID_TRADE_NO_INVALID_TRADES_FOUND"


def test_data_missing(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [{"trade_id": "", "symbol": "EURUSD", "entry_price": None, "sl_price": None, "tp_price": 1.1, "side": "BUY", "invalid_sl_tp": True}])
    assert _run(paths)["invalid_trade_forensics_status"] == "MICRO_V2_INVALID_TRADE_DATA_MISSING"


def test_safety_flags_true(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="SELL", entry=1.1, sl=1.1, tp=1.098)], safety=True)
    summary = _run(paths)
    assert summary["invalid_trade_forensics_status"] == "MICRO_V2_INVALID_TRADE_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False


def test_cli_read_only_and_repair_plan_not_applied(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path, [_trade("ptr1", side="SELL", entry=1.16542, sl=1.16542, tp=1.16363)])
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8")
    profile_before = paths["profile"].read_text(encoding="utf-8")
    result = cli.main(
        [
            "--mode",
            "micro-v2-invalid-trade-forensics",
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
            "--lifecycle-dir",
            str(paths["lifecycle_dir"]),
            "--stable-window-dir",
            str(paths["stable_window_dir"]),
            "--checkpoint-dir",
            str(paths["checkpoint_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    plan = json.loads((paths["out"] / "repair_plan.json").read_text(encoding="utf-8"))
    assert summary["repair_plan_applied"] is False
    assert plan["NOT_APPLIED"] is True
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8") == log_before
    assert paths["profile"].read_text(encoding="utf-8") == profile_before


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_invalid_trade_forensics(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        lifecycle_dir=paths["lifecycle_dir"],
        stable_window_dir=paths["stable_window_dir"],
        checkpoint_dir=paths["checkpoint_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path, trades: list[dict[str, object]], *, event_payload: dict[str, object] | None = None, safety: bool = False) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "lifecycle_dir": tmp_path / "data" / "reports" / "micro_v2_lifecycle_risk_comparison",
        "stable_window_dir": tmp_path / "data" / "reports" / "micro_v2_stable_market_window",
        "checkpoint_dir": tmp_path / "data" / "reports" / "micro_v2_observation_checkpoint",
        "out": tmp_path / "data" / "reports" / "micro_v2_invalid_trade_forensics",
    }
    for key in ("v2_log_dir", "base_log_dir", "reports_root", "lifecycle_dir", "stable_window_dir", "checkpoint_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    for trade in trades:
        _insert_trade(paths["v2_sqlite"], trade)
    if event_payload:
        _event(paths["v2_sqlite"], event_payload)
    if safety:
        _event(paths["v2_sqlite"], {"execution_attempted": True})
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    invalid_rows = [trade for trade in trades if trade.get("invalid", True)]
    _write_json(paths["lifecycle_dir"] / "open_trade_lifecycle_audit.json", {"open_trades": invalid_rows, "invalid_open_trade_count": len(invalid_rows)})
    _write_json(paths["lifecycle_dir"] / "micro_v2_lifecycle_risk_comparison_summary.json", {"invalid_open_trade_count": len(invalid_rows)})
    _write_json(paths["stable_window_dir"] / "micro_v2_stable_market_window_summary.json", {})
    _write_json(paths["checkpoint_dir"] / "micro_v2_observation_checkpoint_summary.json", {})
    return paths


def _trade(trade_id: str, *, side: str, entry: float, sl: float | None, tp: float | None, digits: int | None = None, invalid: bool = True) -> dict[str, object]:
    trade: dict[str, object] = {
        "trade_id": trade_id,
        "symbol": "EURUSD",
        "side": side,
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": tp,
        "current_price": entry,
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        "risk_distance": abs(entry - sl) if sl is not None else None,
        "reward_distance": abs(tp - entry) if tp is not None else None,
        "invalid_risk_distance": sl is not None and abs(entry - sl) <= 1e-12,
        "invalid_sl_tp": sl is None or tp is None or (sl is not None and abs(entry - sl) <= 1e-12) or (tp is not None and abs(tp - entry) <= 1e-12),
        "invalid": invalid,
    }
    if digits is not None:
        trade["digits"] = digits
    return trade


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, symbol, status, payload_json, opened_at_utc, closed_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (payload.get("trade_id"), payload.get("symbol", "EURUSD"), "OPEN", json.dumps(payload), payload.get("opened_at_utc", ""), ""),
        )
        conn.commit()
    finally:
        conn.close()


def _event(path: Path, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("SIGNAL_REJECTED", "EURUSD", datetime.now(timezone.utc).isoformat(), "INFO", "event", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")

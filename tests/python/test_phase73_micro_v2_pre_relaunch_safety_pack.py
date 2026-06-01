from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.contracts import Direction, EntryType, MarketSnapshot, RiskDecision, TradeSignal
from agi_style_forex_bot_mt5.micro_v2_pre_relaunch_safety_pack import PaperTradeGuardInput, validate_paper_trade_creation
from agi_style_forex_bot_mt5.micro_v2_pre_relaunch_safety_pack.pre_relaunch_safety_report import run_micro_v2_pre_relaunch_safety_pack
from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel
from agi_style_forex_bot_mt5.paper_trading.paper_position_manager import PaperPositionManager
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_guard_rejects_invalid_setups_with_specific_reasons() -> None:
    cases = [
        (PaperTradeGuardInput(1.1, 1.1, 1.2, "BUY", 5, {}), "PAPER_TRADE_REJECTED_SL_EQUALS_ENTRY"),
        (PaperTradeGuardInput(1.1, 1.1, 1.0, "SELL", 5, {}), "PAPER_TRADE_REJECTED_SL_EQUALS_ENTRY"),
        (PaperTradeGuardInput(1.1, 1.2, 1.3, "BUY", 5, {}), "PAPER_TRADE_REJECTED_INVALID_LONG_SL_TP"),
        (PaperTradeGuardInput(1.1, 1.0, 0.9, "SELL", 5, {}), "PAPER_TRADE_REJECTED_INVALID_SHORT_SL_TP"),
        (PaperTradeGuardInput(1.1, 1.0, 1.1, "BUY", 5, {}), "PAPER_TRADE_REJECTED_TP_EQUALS_ENTRY"),
        (PaperTradeGuardInput(1.1, 1.0, 1.1, "SELL", 5, {}), "PAPER_TRADE_REJECTED_TP_EQUALS_ENTRY"),
        (PaperTradeGuardInput(1.1, 1.0, 1.2, "BUY", 5, {"atr_stop_distance": 0}), "PAPER_TRADE_REJECTED_ZERO_ATR_STOP_DISTANCE"),
        (PaperTradeGuardInput(1.100004, 1.100003, 1.10002, "BUY", 5, {}), "PAPER_TRADE_REJECTED_PRECISION_ROUNDING_COLLAPSE"),
        (PaperTradeGuardInput(1.1, 1.0, 1.2, "SIDEWAYS", 5, {}), "PAPER_TRADE_REJECTED_INVALID_SIDE"),
    ]

    for candidate, reason in cases:
        result = validate_paper_trade_creation(candidate)
        assert result["paper_trade_creation_allowed"] is False
        assert result["rejection_reason"] == reason
        assert result["execution_attempted"] is False


def test_guard_allows_valid_long_and_short() -> None:
    assert validate_paper_trade_creation(PaperTradeGuardInput(1.1, 1.0, 1.2, "BUY", 5, {}))["paper_trade_creation_allowed"] is True
    assert validate_paper_trade_creation(PaperTradeGuardInput(1.1, 1.2, 1.0, "SELL", 5, {}))["paper_trade_creation_allowed"] is True


def test_guard_integrated_before_paper_trade_creation(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "v2.sqlite3")
    try:
        manager = PaperPositionManager(database=db, fill_model=PaperFillModel(slippage_points=0))
        signal = _signal(direction=Direction.BUY, sl=1.1001, tp=1.1010)
        try:
            manager.open_trade(
                signal=signal,
                risk_decision=_risk(signal.signal_id),
                snapshot=_snapshot(),
                broker_symbol="EURUSD",
                score=80,
                reasons=("test",),
                strategy_name="test",
                strategy_version="1",
                regime="TREND_UP",
                session="LONDON",
            )
        except ValueError as exc:
            assert "PAPER_TRADE_REJECTED_SL_EQUALS_ENTRY" in str(exc)
        assert db.count_rows("paper_trades") == 0
        events = db.fetch_all("events")
        assert any("PAPER_TRADE_REJECTED_SL_EQUALS_ENTRY" in row["payload_json"] for row in events)
    finally:
        db.close()


def test_relaunch_gate_keep_halted_and_ready(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, relaunch_allowed=False, daily_halt_active=True)
    summary = _run(paths)
    assert summary["micro_v2_pre_relaunch_safety_pack_status"] == "MICRO_V2_PRE_RELAUNCH_SAFETY_PACK_READY_KEEP_HALTED"
    assert summary["relaunch_allowed"] is False

    ready_paths = _fixture(tmp_path / "ready", relaunch_allowed=True, daily_halt_active=False, daily_reset_occurred=True)
    ready = _run(ready_paths)
    assert ready["micro_v2_pre_relaunch_safety_pack_status"] == "MICRO_V2_PRE_RELAUNCH_SAFETY_PACK_READY_FOR_RELAUNCH"
    assert ready["relaunch_allowed"] is True


def test_no_sqlite_or_ledger_mutation_and_cli_mode(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, relaunch_allowed=False, daily_halt_active=True)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    ledger_before = paths["daily_ledger"].read_text(encoding="utf-8")
    code = main(
        [
            "--mode",
            "micro-v2-pre-relaunch-safety-pack",
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--daily-risk-ledger",
            str(paths["daily_ledger"]),
            "--daily-reset-readiness-dir",
            str(paths["reset_dir"]),
            "--daily-risk-scope-repair-dir",
            str(paths["scope_repair_dir"]),
            "--closed-loss-scope-dir",
            str(paths["closed_loss_dir"]),
            "--open-trade-repair-dir",
            str(paths["open_repair_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert code == 0
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert paths["daily_ledger"].read_text(encoding="utf-8") == ledger_before
    assert (paths["out"] / "micro_v2_pre_relaunch_safety_pack_summary.json").exists()


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_pre_relaunch_safety_pack(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_ledger"],
        daily_reset_readiness_dir=paths["reset_dir"],
        daily_risk_scope_repair_dir=paths["scope_repair_dir"],
        closed_loss_scope_dir=paths["closed_loss_dir"],
        open_trade_repair_dir=paths["open_repair_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path, *, relaunch_allowed: bool, daily_halt_active: bool, daily_reset_occurred: bool = False) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "reset_dir": tmp_path / "data" / "reports" / "micro_v2_daily_reset_readiness",
        "scope_repair_dir": tmp_path / "data" / "reports" / "micro_v2_daily_risk_scope_repair",
        "closed_loss_dir": tmp_path / "data" / "reports" / "micro_v2_closed_loss_scope_decision",
        "open_repair_dir": tmp_path / "data" / "reports" / "micro_v2_guarded_open_trade_integrity_repair",
        "out": tmp_path / "data" / "reports" / "micro_v2_pre_relaunch_safety_pack",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    paths["v2_sqlite"].write_bytes(b"sqlite-placeholder")
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    paths["daily_ledger"].write_text(json.dumps({"daily_risk_clearances": []}), encoding="utf-8")
    (paths["reset_dir"] / "micro_v2_daily_reset_readiness_summary.json").write_text(
        json.dumps(
            {
                "daily_halt_active": daily_halt_active,
                "daily_reset_occurred": daily_reset_occurred,
                "daily_risk_scope_status": "DAILY_RISK_SCOPE_OK_FOR_V2",
                "open_trade_count": 0,
                "invalid_open_trade_count": 0,
                "quarantined_trade_count": 3,
                "paper_state_clean_for_relaunch": True,
                "relaunch_allowed": relaunch_allowed,
            }
        ),
        encoding="utf-8",
    )
    return paths


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EURUSD",
        timeframe="M5",
        timestamp_utc=datetime.now(timezone.utc),
        bid=1.1000,
        ask=1.1001,
        spread_points=10,
        digits=5,
        point=0.00001,
        tick_value=1.0,
        tick_size=0.00001,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        stops_level_points=10,
        freeze_level_points=5,
    )


def _signal(*, direction: Direction, sl: float, tp: float) -> TradeSignal:
    return TradeSignal(
        signal_id=TradeSignal.new_id("sig"),
        created_at_utc=datetime.now(timezone.utc),
        symbol="EURUSD",
        timeframe="M5",
        direction=direction,
        entry_type=EntryType.MARKET,
        sl_price=sl,
        tp_price=tp,
        risk_pct=0.1,
        confidence=0.8,
    )


def _risk(signal_id: str) -> RiskDecision:
    return RiskDecision(signal_id=signal_id, accepted=True, approved_lot=0.01, risk_amount_account_currency=1.0)

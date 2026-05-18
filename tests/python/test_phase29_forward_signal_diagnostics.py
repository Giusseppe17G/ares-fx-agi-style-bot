from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import MarketSnapshot, SignalAction, utc_now
from agi_style_forex_bot_mt5.execution import MT5Connector
from agi_style_forex_bot_mt5.forward_diagnostics.forward_candidate_audit import audit_forward_candidate
from agi_style_forex_bot_mt5.forward_diagnostics.forward_diagnostics_report import audit_stable_filter, run_forward_signal_diagnose
from agi_style_forex_bot_mt5.forward_diagnostics.forward_near_miss_report import summarize_near_misses
from agi_style_forex_bot_mt5.forward_diagnostics.live_feature_probe import probe_live_features
from agi_style_forex_bot_mt5.forward_diagnostics.live_strategy_probe import probe_live_strategies
from agi_style_forex_bot_mt5.forward_diagnostics.runtime_data_quality import probe_runtime_data_quality
from agi_style_forex_bot_mt5.forward_evidence import run_forward_evidence
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter


def _rates(count: int = 260) -> list[dict[str, float]]:
    now = int(utc_now().timestamp())
    price = 1.1000
    rows: list[dict[str, float]] = []
    for idx in range(count):
        price += 0.00003
        rows.append({"time": now - (count - idx) * 300, "open": price, "high": price + 0.0001, "low": price - 0.0001, "close": price + 0.00002, "tick_volume": 1000, "spread": 10})
    return rows


class EmptyRatesMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    SYMBOL_TRADE_MODE_DISABLED = 0
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __init__(self, *, empty_rates: bool = True) -> None:
        self.empty_rates = empty_rates
        self.calls: list[str] = []

    def initialize(self):
        self.calls.append("initialize")
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(login=100, trade_mode=0, trade_allowed=True, balance=10000, equity=10000, margin_free=9000, currency="USD")

    def symbol_info(self, symbol: str):
        return SimpleNamespace(name=symbol, visible=True, trade_mode=1, filling_mode=0, digits=5, point=0.00001, trade_tick_value=1, trade_tick_size=0.00001, trade_contract_size=100000, volume_min=0.01, volume_max=100, volume_step=0.01, trade_stops_level=10, trade_freeze_level=5)

    def symbol_info_tick(self, symbol: str):
        now = int(utc_now().timestamp())
        return SimpleNamespace(bid=1.1000, ask=1.1001, time=now, time_msc=now * 1000)

    def copy_rates_from_pos(self, symbol: str, timeframe, start_pos: int, count: int):
        self.calls.append(f"copy_rates_from_pos:{timeframe}")
        return [] if self.empty_rates else _rates(count)

    def copy_rates_range(self, symbol: str, timeframe, date_from, date_to):
        return []

    def symbols_get(self, group: str = "*"):
        return (SimpleNamespace(name="EURUSD"),)

    def last_error(self):
        return (0, "")

    def order_send(self, request):
        self.calls.append("order_send")
        raise AssertionError("order_send must not be called")

    def order_check(self, request):
        self.calls.append("order_check")
        raise AssertionError("order_check must not be called")


def _stable_config(tmp_path: Path, text: str = "APPLY_STABILITY_FILTERS=true\nPROFILE_TYPE=RESEARCH_BACKTEST_ONLY\n") -> BotConfig:
    path = tmp_path / "balanced_stable.ini"
    path.write_text(text, encoding="utf-8")
    return BotConfig(signal_profile="BALANCED_STABLE", profile_config=str(path), stability_filters_applied=True, profile_type="RESEARCH_BACKTEST_ONLY")


def test_forward_signal_diagnose_runs_with_empty_sqlite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        summary = run_forward_signal_diagnose(
            config=BotConfig(),
            symbols=("EURUSD",),
            database=db,
            log_dir=tmp_path / "logs",
            reports_root=tmp_path / "reports",
            output_dir=tmp_path / "out",
            mt5_client=EmptyRatesMT5(empty_rates=True),
        )
        assert summary["mode"] == "forward-signal-diagnose"
        assert summary["execution_attempted"] is False
        assert summary["candidate_count"] == 0
    finally:
        db.close()


def test_live_data_quality_detects_live_m5_empty() -> None:
    client = EmptyRatesMT5(empty_rates=True)
    connector = MT5Connector(config=BotConfig(), mt5_client=client)
    rows, payloads = probe_runtime_data_quality(config=BotConfig(), connector=connector, symbols=("EURUSD",))
    assert payloads == {}
    assert "LIVE_M5_EMPTY" in rows[0]["blockers"]
    assert "order_send" not in client.calls
    assert "order_check" not in client.calls


def test_live_feature_probe_detects_missing_features() -> None:
    snapshot = MarketSnapshot(symbol="EURUSD", timeframe="M5", timestamp_utc=datetime.now(timezone.utc), bid=1.1, ask=1.1001, spread_points=10, digits=5, point=0.00001, tick_value=1, tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, stops_level_points=10, freeze_level_points=5)
    rows, features = probe_live_features(config=BotConfig(), runtime_payloads={"EURUSD": {"snapshot": snapshot, "rates": {"M5": _rates(20)}}})
    assert features == {}
    assert rows[0]["features_generated"] is False
    assert "INSUFFICIENT_STRUCTURE_DATA" in rows[0]["blockers"]


def test_live_strategy_probe_reports_threshold_failures(monkeypatch) -> None:
    import agi_style_forex_bot_mt5.forward_diagnostics.live_strategy_probe as module

    def fake_evaluate(*_args, **_kwargs):
        return SimpleNamespace(action=SignalAction.NONE, score=55.0, reasons=("ensemble score below threshold",), strategy_name="strategy_ensemble", metadata={"blocking_reasons": ("ensemble score below threshold",), "component_scores": {"cost_fit": 40.0}})

    monkeypatch.setattr(module, "evaluate_ensemble", fake_evaluate)
    snapshot = MarketSnapshot(symbol="EURUSD", timeframe="M5", timestamp_utc=datetime.now(timezone.utc), bid=1.1, ask=1.1001, spread_points=10, digits=5, point=0.00001, tick_value=1, tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, stops_level_points=10, freeze_level_points=5)
    rows, near = probe_live_strategies(config=BotConfig(signal_profile="BALANCED"), runtime_payloads={"EURUSD": {"snapshot": snapshot}}, features_by_symbol={"EURUSD": {"session": "LONDON", "regime": "RANGE"}})
    assert rows[0]["passed_thresholds"] is False
    assert "ENSEMBLE_SCORE_LOW" in rows[0]["threshold_failures"]
    assert near


def test_near_miss_report_detects_candidate_close_to_threshold() -> None:
    summary = summarize_near_misses([{"symbol": "EURUSD", "strategy_name": "strategy_ensemble", "threshold_failures": ("ENSEMBLE_SCORE_LOW",)}])
    assert summary["near_miss_count"] == 1
    assert summary["near_misses_by_symbol"][0]["symbol"] == "EURUSD"


def test_stable_filter_audit_detects_filter_that_blocks_everything(tmp_path: Path) -> None:
    cfg = _stable_config(tmp_path, "APPLY_STABILITY_FILTERS=true\nPROFILE_TYPE=RESEARCH_BACKTEST_ONLY\nDISABLED_SYMBOLS=EURUSD,GBPUSD\n")
    audit = audit_stable_filter(config=cfg, symbols=("EURUSD", "GBPUSD"), strategy_rows=[])
    assert audit["classification"] == "STABLE_FILTER_TOO_RESTRICTIVE"


def test_forward_candidate_audit_writes_events_without_trades(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "events.sqlite3")
    try:
        audit_forward_candidate(database=db, audit_logger=JsonlAuditLogger(tmp_path / "logs"), run_id="test", event_type="FORWARD_CANDIDATE_EVALUATED", payload={"symbol": "EURUSD"}, symbol="EURUSD")
        assert db.count_rows("events") == 1
        assert db.count_rows("paper_trades") == 0
    finally:
        db.close()


def test_forward_evidence_integrates_top_forward_blockers(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    reports = tmp_path / "reports"
    diagnostics = reports / "forward_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "signal_scarcity_summary.json").write_text(json.dumps({"classification": "STRATEGY_TOO_SELECTIVE", "top_blockers": [{"blocking_reason": "ENSEMBLE_SCORE_LOW", "count": 3}], "candidate_count": 3, "near_miss_count": 1, "feature_ready_symbols": ["EURUSD"], "recommended_action": "research only"}), encoding="utf-8")
    try:
        summary = run_forward_evidence(database=db, log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "evidence")
        assert summary["forward_diagnostics_status"] == "STRATEGY_TOO_SELECTIVE"
        assert summary["top_forward_blockers"][0]["blocking_reason"] == "ENSEMBLE_SCORE_LOW"
    finally:
        db.close()


def test_cli_accepts_forward_signal_diagnose(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_run(**_kwargs):
        return {"mode": "forward-signal-diagnose", "execution_attempted": False, "order_send_called": False, "order_check_called": False}

    monkeypatch.setattr(cli, "run_forward_signal_diagnose", fake_run)
    code = cli.main(["--mode", "forward-signal-diagnose", "--sqlite", str(tmp_path / "f.sqlite3"), "--symbols", "EURUSD"])
    assert code == 0
    output = capsys.readouterr().out
    assert '"mode": "forward-signal-diagnose"' in output
    assert '"execution_attempted": false' in output


def test_telegram_signal_diag_returns_read_only_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report_dir = tmp_path / "data/reports/forward_diagnostics"
    report_dir.mkdir(parents=True)
    (report_dir / "signal_scarcity_summary.json").write_text('{"classification":"STRATEGY_TOO_SELECTIVE","execution_attempted":false}', encoding="utf-8")
    db = TelemetryDatabase(tmp_path / "telegram.sqlite3")
    try:
        result = TelegramCommandCenter(database=db, allowed_chat_id="123").process_update({"message": {"chat": {"id": "123"}, "text": "/signal_diag"}})
        assert result.accepted is True
        assert "STRATEGY_TOO_SELECTIVE" in result.response_text
        assert result.execution_attempted is False
    finally:
        db.close()

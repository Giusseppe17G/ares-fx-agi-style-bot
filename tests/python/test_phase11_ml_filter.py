from __future__ import annotations

import csv
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import SignalAction, StrategySignal, utc_now
from agi_style_forex_bot_mt5.ml import MLFilter, build_ml_dataset, build_ml_report, train_ml_filter
from agi_style_forex_bot_mt5.ml.feature_store import FEATURE_COLUMNS, build_feature_store
from agi_style_forex_bot_mt5.ml.label_builder import build_labels
from agi_style_forex_bot_mt5.ml.ml_filter import MLFilterDecision
from agi_style_forex_bot_mt5.ml.model_registry import save_model_bundle
from agi_style_forex_bot_mt5.ml.model_trainer import LogisticBaseline, NUMERIC_FEATURES
from agi_style_forex_bot_mt5.ml.probability_calibrator import SigmoidCalibrator, brier_score
from agi_style_forex_bot_mt5.paper_trading import ForwardShadowBot
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _db_with_trades(tmp_path: Path) -> TelemetryDatabase:
    db = TelemetryDatabase(tmp_path / "ml.sqlite3")
    base = utc_now()
    for index in range(12):
        status = "CLOSED" if index < 10 else "OPEN"
        r = 1.0 if index % 2 == 0 else -1.0
        trade = {
            "paper_trade_id": f"ptr_{index}",
            "signal_id": f"sig_{index}",
            "idempotency_key": f"paper:{index}",
            "symbol": "EURUSD",
            "broker_symbol": "EURUSD",
            "direction": "BUY",
            "entry_time_utc": (base + timedelta(minutes=index)).isoformat(),
            "entry_price": 1.1,
            "sl_price": 1.09,
            "tp_price": 1.12,
            "lot": 0.1,
            "risk_pct": 0.5,
            "risk_amount": 10,
            "strategy_name": "strategy_ensemble",
            "strategy_version": "0.1",
            "regime": "TREND_UP",
            "session": "LONDON",
            "score": 60 + index,
            "reasons": ("test",),
            "status": status,
            "exit_time_utc": (base + timedelta(minutes=index + 5)).isoformat() if status == "CLOSED" else None,
            "exit_price": 1.12 if r > 0 else 1.09,
            "exit_reason": "TP" if r > 0 else "SL",
            "profit": r * 10,
            "r_multiple": r,
            "mae": -0.2,
            "mfe": 1.1,
            "spread_at_entry": 10,
            "spread_at_exit": 12,
        }
        db.insert_paper_trade(trade)
    return db


def test_feature_store_and_labels_generate_minimum_columns(tmp_path: Path) -> None:
    db = _db_with_trades(tmp_path)
    try:
        features = build_feature_store(db, tmp_path / "ml")
        labels = build_labels(db, tmp_path / "ml")
        assert features["samples"] >= 10
        assert labels["labels"] == 10
        with (tmp_path / "ml" / "feature_store.csv").open("r", encoding="utf-8") as handle:
            columns = next(csv.reader(handle))
        for column in ("symbol_encoded", "session_encoded", "regime_encoded", "score", "spread_points"):
            assert column in columns
        assert set(FEATURE_COLUMNS).issubset(set(columns))
    finally:
        db.close()


def test_dataset_builder_splits_temporally_and_no_open_labels(tmp_path: Path) -> None:
    db = _db_with_trades(tmp_path)
    try:
        summary = build_ml_dataset(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "ml")
        assert summary["samples"] == 10
        rows = list(csv.DictReader((tmp_path / "ml" / "ml_dataset.csv").open("r", encoding="utf-8")))
        assert {row["split"] for row in rows} == {"train", "validation", "test"}
        assert all(row["label_time_utc"] > row["timestamp_utc"] for row in rows)
    finally:
        db.close()


def test_trainer_registry_and_report(tmp_path: Path) -> None:
    db = _db_with_trades(tmp_path)
    try:
        build_ml_dataset(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "ml")
    finally:
        db.close()
    summary = train_ml_filter(dataset_path=tmp_path / "ml" / "ml_dataset.csv", model_dir=tmp_path / "models", report_dir=tmp_path / "ml")
    assert summary["samples"] == 10
    assert (tmp_path / "models" / "metadata.json").exists()
    report = build_ml_report(model_dir=tmp_path / "models", report_dir=tmp_path / "ml_report")
    assert report["execution_attempted"] is False


def test_calibrator_reports_brier_score() -> None:
    labels = np.array([0, 0, 1, 1], dtype=float)
    raw = np.array([0.2, 0.4, 0.6, 0.8], dtype=float)
    calibrator = SigmoidCalibrator.fit(raw, labels)
    calibrated = calibrator.predict(raw)
    assert brier_score(labels, calibrated) >= 0


def test_ml_filter_disabled_without_model(tmp_path: Path) -> None:
    decision = MLFilter(tmp_path / "missing").approve_or_reject(SimpleNamespace(signal_id="s", symbol="EURUSD", created_at_utc=utc_now(), strategy_name="x"), {})
    assert decision.ml_status == "ML_DISABLED"
    assert decision.execution_attempted is False


def test_ml_filter_rejects_low_probability_and_never_changes_risk(tmp_path: Path) -> None:
    feature_count = len(NUMERIC_FEATURES)
    model = LogisticBaseline(weights=np.zeros(feature_count), bias=-4.0, feature_names=NUMERIC_FEATURES)
    calibrator = SigmoidCalibrator(a=1.0, b=0.0)
    save_model_bundle(
        model_dir=tmp_path / "model",
        model=model,
        calibrator=calibrator,
        metadata={"features": list(NUMERIC_FEATURES), "labels": ["label_win"], "approved_for_shadow_filtering": True},
        metrics={"brier_after_calibration": 0.1},
        training_manifest={"samples": 20},
    )
    decision = MLFilter(tmp_path / "model").approve_or_reject(SimpleNamespace(signal_id="s", symbol="EURUSD", created_at_utc=utc_now(), strategy_name="x"), {})
    assert decision.ml_status == "ML_REJECTED"
    assert "risk" not in decision.to_dict()


def test_forward_shadow_audits_ml_prediction(monkeypatch, tmp_path: Path) -> None:
    import agi_style_forex_bot_mt5.paper_trading.forward_shadow_bot as fsb

    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO = 0

        def initialize(self):
            return True

        def account_info(self):
            return SimpleNamespace(login=1, trade_mode=0, balance=10000, equity=10000, margin_free=9000, currency="USD", trade_allowed=True)

        def symbol_info(self, symbol):
            return SimpleNamespace(name=symbol, visible=True, trade_mode=1, digits=5, point=0.00001, trade_tick_value=1, trade_tick_size=0.00001, volume_min=0.01, volume_max=100, volume_step=0.01, trade_stops_level=10, trade_freeze_level=5)

        def symbol_info_tick(self, symbol):
            now = int(utc_now().timestamp())
            return SimpleNamespace(bid=1.1000, ask=1.1001, time=now, time_msc=now * 1000)

        def last_error(self):
            return (0, "")

        def order_send(self, request):
            raise AssertionError("order_send must not be called")

    monkeypatch.setattr(fsb.MT5DataOnlyBot, "_read_timeframes", lambda self, *args, **kwargs: {"M5": object()})
    monkeypatch.setattr(fsb.MT5DataOnlyBot, "_features_from_bars", lambda self, *args, **kwargs: {"regime": "TREND_UP", "session": "LONDON", "atr": 0.001, "score": 80})
    monkeypatch.setattr(fsb, "evaluate_ensemble", lambda *_args, **_kwargs: StrategySignal(SignalAction.BUY, 80, ("ok",), "strategy_ensemble", {"atr": 0.001, "version": "test"}))
    monkeypatch.setattr(fsb.MLFilter, "load_latest_model", staticmethod(lambda: SimpleNamespace(approve_or_reject=lambda signal, features: MLFilterDecision("ML_DISABLED", None, None, None, None, None, 0.58, ("no model",)))))
    db = TelemetryDatabase(tmp_path / "fwd.sqlite3")
    try:
        bot = ForwardShadowBot(config=BotConfig(), symbols=("EURUSD",), audit_logger=JsonlAuditLogger(tmp_path / "logs"), database=db, mt5_client=FakeMT5(), max_cycles=1, cycle_seconds=0)
        summary = bot.run()
        assert summary.execution_attempted is False
        assert db.count_rows("model_predictions") >= 1
        assert any(row["event_type"] == "ML_PREDICTION" for row in db.fetch_all("events"))
    finally:
        db.close()


def test_cli_ml_modes_and_telegram_status(monkeypatch, tmp_path: Path, capsys) -> None:
    sqlite_path = tmp_path / "cli.sqlite3"
    db = _db_with_trades(tmp_path)
    db.close()
    monkeypatch.setattr(cli, "build_ml_dataset", lambda **_kwargs: {"mode": "build-ml-dataset", "samples": 1, "model_status": "ML_DISABLED", "approved_for_shadow_filtering": False, "reports_created": [], "execution_attempted": False})
    monkeypatch.setattr(cli, "train_ml_filter", lambda **_kwargs: {"mode": "train-ml-filter", "samples": 1, "model_status": "WATCHLIST", "approved_for_shadow_filtering": False, "reports_created": [], "execution_attempted": False})
    monkeypatch.setattr(cli, "build_ml_report", lambda **_kwargs: {"mode": "ml-report", "samples": 0, "model_status": "ML_DISABLED", "approved_for_shadow_filtering": False, "reports_created": [], "execution_attempted": False})
    assert cli.main(["--mode", "build-ml-dataset", "--sqlite", str(sqlite_path), "--output-dir", str(tmp_path / "ml")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "train-ml-filter", "--dataset", str(tmp_path / "ml.csv"), "--model-dir", str(tmp_path / "model"), "--report-dir", str(tmp_path / "ml")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "ml-report", "--model-dir", str(tmp_path / "model"), "--report-dir", str(tmp_path / "ml")]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

    from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter

    db2 = TelemetryDatabase(tmp_path / "tg.sqlite3")
    try:
        center = TelegramCommandCenter(database=db2, allowed_chat_id="123")
        result = center.process_update({"message": {"chat": {"id": "123"}, "text": "/ml_status"}})
        assert result.accepted is True
        assert "ML_DISABLED" in result.response_text
    finally:
        db2.close()


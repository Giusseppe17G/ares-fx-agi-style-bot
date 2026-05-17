from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.backtesting import run_monte_carlo_report, run_stress_report
from agi_style_forex_bot_mt5.real_data_research import RealDataResearchConfig, RealDataResearchRunner, load_latest_run_summary


def test_stress_accepts_trade_dict_with_regime_and_session(tmp_path: Path) -> None:
    trade = _trade("t1") | {"regime": "TREND_UP", "session": "LONDON", "strategy_name": "strategy_ensemble"}

    summary = run_stress_report(trades=[trade], report_dir=tmp_path / "stress")

    assert summary["classification"] == "LOW_SAMPLE_WARNING"
    assert summary["sample_status"] == "LOW_SAMPLE"
    assert summary["execution_attempted"] is False


def test_monte_carlo_low_sample_warning(tmp_path: Path) -> None:
    summary = run_monte_carlo_report(trades=[10.0, -5.0, 7.0], report_dir=tmp_path / "mc", seed=42, iterations=20)

    assert summary["classification"] == "LOW_SAMPLE_WARNING"
    assert summary["sample_status"] == "LOW_SAMPLE"
    assert summary["execution_attempted"] is False


def test_walk_forward_needs_more_trades_for_low_sample(tmp_path: Path) -> None:
    runner = RealDataResearchRunner(RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="low-sample"))
    runner._prepare_dirs()
    trades = pd.DataFrame([_trade(f"t{i}") for i in range(8)])
    backtests = runner.reports_dir / "backtests"
    backtests.mkdir(parents=True)
    trades.to_csv(backtests / "trades.csv", index=False)

    summary = runner._walk_forward()

    assert summary["classification"] == "NEEDS_MORE_TRADES"
    assert summary["total_trades"] == 8
    assert summary["execution_attempted"] is False


def test_real_data_research_quick_skips_heavy_stages(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="quick", quick=True)
    runner = RealDataResearchRunner(config)

    stage_names = [name for name, _fn in runner._stages()]

    assert stage_names == ["MT5_DIAGNOSE", "EXPORT_HISTORY", "HISTORICAL_DATA_AUDIT", "DATA_CONTRACT_AUDIT", "STRATEGY_DIAGNOSE", "BACKTEST"]


def test_cli_accepts_quick(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_run(config: RealDataResearchConfig, **_kwargs):
        return {"mode": "real-data-research", "quick": config.quick, "execution_attempted": False, "order_send_called": False, "order_check_called": False}

    monkeypatch.setattr(cli, "run_real_data_research", fake_run)

    assert cli.main(["--mode", "real-data-research", "--symbols", "EURUSD", "--output-root", str(tmp_path), "--quick"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["quick"] is True
    assert output["execution_attempted"] is False


def test_skip_stress_test_removes_stage(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="skip-stress", skip_stress_test=True)
    runner = RealDataResearchRunner(config)

    assert "STRESS_TEST" not in [name for name, _fn in runner._stages()]


def test_latest_run_summary_includes_low_sample_fields(tmp_path: Path) -> None:
    run = tmp_path / "20260101-000000-real-data-research"
    run.mkdir()
    (run / "final_summary_compact.json").write_text(
        json.dumps(
            {
                "run_id": "latest",
                "sample_status": "LOW_SAMPLE",
                "next_best_command": "py -m agi_style_forex_bot_mt5.cli --mode real-data-research --quick",
                "execution_attempted": False,
            }
        ),
        encoding="utf-8",
    )

    summary = load_latest_run_summary(tmp_path)

    assert summary["sample_status"] == "LOW_SAMPLE"
    assert "--quick" in summary["next_best_command"]
    assert summary["execution_attempted"] is False


def test_profile_comparison_run_cli(monkeypatch, tmp_path: Path, capsys) -> None:
    from agi_style_forex_bot_mt5.calibration import profile_application

    def fake_compare(**_kwargs):
        return {"mode": "profile-comparison-run", "execution_attempted": False}

    monkeypatch.setattr(profile_application, "run_profile_comparison", fake_compare)

    assert cli.main(["--mode", "profile-comparison-run", "--symbols", "EURUSD", "--data-dir", str(tmp_path), "--output-dir", str(tmp_path / "profiles")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "profile-comparison-run"
    assert output["execution_attempted"] is False


def _trade(signal_id: str) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_time": "2024-01-01T00:00:00Z",
        "exit_time": "2024-01-01T00:10:00Z",
        "entry_price": 1.1,
        "exit_price": 1.101,
        "initial_sl_price": 1.099,
        "final_sl_price": 1.099,
        "tp_price": 1.102,
        "lot": 1.0,
        "profit": 10.0,
        "r_multiple": 1.0,
        "exit_reason": "TP",
        "duration_bars": 2,
        "duration_seconds": 600,
        "mae": -0.0002,
        "mfe": 0.001,
        "spread_points": 10.0,
        "slippage_points": 1.0,
        "commission": 0.0,
        "point": 0.00001,
        "tick_value": 1.0,
        "tick_size": 0.00001,
        "metadata": {},
    }

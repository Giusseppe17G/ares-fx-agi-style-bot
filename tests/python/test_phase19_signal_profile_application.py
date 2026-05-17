from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.backtesting import run_backtest_for_symbols
from agi_style_forex_bot_mt5.calibration import apply_signal_profile, profile_allowed_for_shadow, write_profile_comparison
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.real_data_research import RealDataResearchConfig, RealDataResearchRunner
from agi_style_forex_bot_mt5.validation_pipeline import MasterDecisionEngine


STAGES = (
    "MT5_DIAGNOSE",
    "EXPORT_HISTORY",
    "HISTORICAL_DATA_AUDIT",
    "DATA_CONTRACT_AUDIT",
    "DATA_QUALITY",
    "BROKER_COST_PROFILE",
    "STRUCTURE_REPORT",
    "STRATEGY_DIAGNOSE",
    "BACKTEST",
    "WALK_FORWARD",
    "MONTE_CARLO",
    "STRESS_TEST",
    "RESEARCH",
    "BENCHMARK",
    "COMPETITIVE_SCORECARD",
    "FULL_VALIDATION",
)


def test_apply_signal_profile_loads_balanced_ini(tmp_path: Path) -> None:
    suggestions = tmp_path / "run" / "reports" / "calibration" / "config_suggestions"
    suggestions.mkdir(parents=True)
    (suggestions / "balanced.ini").write_text("SIGNAL_PROFILE=BALANCED\nENSEMBLE_MIN_SCORE=60\n", encoding="utf-8")

    summary = apply_signal_profile(profile_name="BALANCED", runs_root=tmp_path, output_dir=tmp_path / "applied")

    assert summary["profile_name"] == "BALANCED"
    assert summary["thresholds"]["ENSEMBLE_MIN_SCORE"] == 60
    assert summary["not_for_demo_live"] is False
    assert (tmp_path / "applied" / "applied_profile.json").exists()
    assert (tmp_path / "applied" / "applied_profile.ini").exists()
    assert (tmp_path / "applied" / "profile_diff.json").exists()


def test_active_and_research_only_are_not_for_demo_live(tmp_path: Path) -> None:
    active = apply_signal_profile(profile_name="ACTIVE", runs_root=tmp_path, output_dir=tmp_path / "active")

    assert active["not_for_demo_live"] is True
    assert active["profile_allowed_for_shadow"] is False
    assert profile_allowed_for_shadow("RESEARCH_ONLY") is False


def test_forward_shadow_rejects_research_only_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "research_only.ini"
    config_path.write_text("DEMO_ONLY=True\nLIVE_TRADING_APPROVED=False\nSIGNAL_PROFILE=RESEARCH_ONLY\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli.main(["--config", str(config_path), "--mode", "forward-shadow", "--sqlite", str(tmp_path / "paper.sqlite3")])


def test_real_data_research_accepts_signal_profile_balanced(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_run(config: RealDataResearchConfig, **_kwargs):
        return {
            "mode": "real-data-research",
            "signal_profile_used": config.signal_profile,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }

    monkeypatch.setattr(cli, "run_real_data_research", fake_run)

    assert cli.main(["--mode", "real-data-research", "--symbols", "EURUSD", "--output-root", str(tmp_path), "--signal-profile", "BALANCED"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signal_profile_used"] == "BALANCED"
    assert output["execution_attempted"] is False


def test_signal_profile_used_appears_in_final_summary_compact(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="profile-compact", signal_profile="BALANCED")
    overrides = {name: _stage(name) for name in STAGES}
    overrides["DATA_QUALITY"] = lambda: {"classification": "OK", "execution_attempted": False}
    overrides["BACKTEST"] = lambda: {"classification": "OK", "signals_generated": 12, "trades_generated": 5, "total_trades": 5, "execution_attempted": False}

    summary = RealDataResearchRunner(config, stage_overrides=overrides).run()
    compact = summary["compact_summary"]

    assert compact["signal_profile_used"] == "BALANCED"
    assert compact["thresholds_used"]["ensemble_min_score"] == 60
    assert compact["signals_generated"] == 12
    assert compact["trades_generated"] == 5
    assert compact["trade_frequency_status"] == "LOW_SAMPLE"


def test_backtest_reports_selected_profile_thresholds(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _write_history(data_dir / "EURUSD_M5.csv", rows=260)

    result = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",), config=BotConfig(signal_profile="BALANCED"))

    assert result.summary["signal_profile_used"] == "BALANCED"
    assert result.summary["thresholds_used"]["ensemble_min_score"] == 60
    assert result.summary["execution_attempted"] is False


def test_profile_comparison_generates_csv(tmp_path: Path) -> None:
    paths = write_profile_comparison(
        tmp_path / "profile_runs",
        {"BALANCED": {"signals_generated": 10, "trades_generated": 3, "validation_decision": "NEEDS_STRATEGY_RESEARCH"}},
    )

    assert any(path.endswith("profile_comparison.csv") for path in paths)
    frame = pd.read_csv(tmp_path / "profile_runs" / "profile_comparison.csv")
    assert "BALANCED" in set(frame["profile"])


def test_full_validation_blocks_active_profile_from_shadow_promotion(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    for name in ("data_quality", "broker_costs", "backtests", "walk_forward", "monte_carlo", "stress", "benchmarks", "competitive_scorecard"):
        (root / name).mkdir(parents=True)
    (root / "data_quality" / "summary.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "broker_costs" / "broker_cost_profile.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "backtests" / "summary.json").write_text('{"signal_profile_used":"ACTIVE","total_trades":300}', encoding="utf-8")
    (root / "walk_forward" / "summary.json").write_text('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', encoding="utf-8")
    (root / "monte_carlo" / "summary.json").write_text('{"probability_of_ruin":0.01}', encoding="utf-8")
    (root / "stress" / "summary.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "benchmarks" / "summary.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "competitive_scorecard" / "competitive_scorecard.json").write_text('{"classification":"COMPETITIVE_CANDIDATE"}', encoding="utf-8")

    decision = MasterDecisionEngine().decide(reports_root=root, output_dir=tmp_path / "full", symbols=("EURUSD",))

    assert decision.final_decision == "NEEDS_STRATEGY_RESEARCH"
    assert any("ACTIVE" in reason for reason in decision.reasons)
    assert decision.execution_attempted is False


def test_apply_signal_profile_cli(capsys, tmp_path: Path) -> None:
    assert cli.main(["--mode", "apply-signal-profile", "--profile", "BALANCED", "--runs-root", str(tmp_path), "--output-dir", str(tmp_path / "applied")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "apply-signal-profile"
    assert output["profile_name"] == "BALANCED"
    assert output["execution_attempted"] is False


def _stage(name: str):
    def run() -> dict[str, object]:
        payload: dict[str, object] = {"mode": name.lower(), "classification": "OK", "execution_attempted": False}
        if name in {"MT5_DIAGNOSE", "EXPORT_HISTORY"}:
            payload["mt5_connected"] = True
        if name == "FULL_VALIDATION":
            payload["final_decision"] = "CONTINUE_FORWARD_SHADOW"
        return payload

    return run


def _write_history(path: Path, *, rows: int) -> None:
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    data = []
    for index in range(rows):
        price = 1.1000 + index * 0.00001
        data.append(
            {
                "time": (start + pd.Timedelta(minutes=5 * index)).isoformat(),
                "open": price,
                "high": price + 0.0001,
                "low": price - 0.0001,
                "close": price,
                "tick_volume": 100,
                "spread": 10,
            }
        )
    pd.DataFrame(data).to_csv(path, index=False)

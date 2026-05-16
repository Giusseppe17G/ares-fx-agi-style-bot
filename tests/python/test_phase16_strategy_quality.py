from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.contracts import MarketSnapshot, SignalAction, utc_now
from agi_style_forex_bot_mt5.market_structure import (
    analyze_market_structure,
    calculate_session_levels,
    detect_liquidity_zones,
    detect_swing_points,
)
from agi_style_forex_bot_mt5.research.candidate_registry import CandidateRegistry
from agi_style_forex_bot_mt5.research.research_report import write_research_reports
from agi_style_forex_bot_mt5.strategy import (
    strategy_breakout_compression,
    strategy_liquidity_sweep,
    strategy_mean_reversion,
    strategy_session_momentum,
    strategy_trend_pullback,
)


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot("EURUSD", "M5", utc_now(), 1.1000, 1.1001, 10, 5, 0.00001, 1.0, 0.00001, 0.01, 100, 0.01, 10, 5)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.date_range("2026-01-01", periods=12, freq="h", tz="UTC").astype(str),
            "open": [1.10, 1.11, 1.105, 1.12, 1.115, 1.13, 1.12, 1.135, 1.125, 1.14, 1.13, 1.145],
            "high": [1.11, 1.115, 1.112, 1.125, 1.121, 1.135, 1.127, 1.14, 1.132, 1.145, 1.136, 1.15],
            "low": [1.095, 1.10, 1.10, 1.11, 1.108, 1.12, 1.115, 1.125, 1.12, 1.13, 1.125, 1.135],
            "close": [1.108, 1.104, 1.11, 1.114, 1.12, 1.122, 1.126, 1.128, 1.131, 1.133, 1.136, 1.148],
            "tick_volume": [100] * 12,
            "spread": [10] * 12,
        }
    )


def test_swing_points_and_structure_detect_bos() -> None:
    frame = _frame()
    swings = detect_swing_points(frame, lookback=1)
    structure = analyze_market_structure(frame, lookback=1)

    assert any(swing.kind == "HIGH" for swing in swings)
    assert structure.break_of_structure in {"BULLISH", "NONE"}
    assert structure.execution_attempted is False


def test_liquidity_sweep_detects_sweep_and_reclaim() -> None:
    frame = _frame().copy()
    recent_low = frame["low"].iloc[-11:-1].min()
    frame.loc[len(frame) - 1, "low"] = recent_low - 0.0005
    frame.loc[len(frame) - 1, "close"] = recent_low + 0.0002
    frame.loc[len(frame) - 1, "high"] = frame["high"].iloc[:-1].max() - 0.0002

    context = detect_liquidity_zones(frame, lookback=10)

    assert context.swept_recent_low is True
    assert context.reclaimed_low is True
    assert context.sweep_direction == "BUY_SWEEP"


def test_session_levels_calculate_ranges() -> None:
    levels = calculate_session_levels(_frame())

    assert levels.asian_high is not None
    assert levels.london_high is not None
    assert levels.current_session in {"ASIA", "LONDON", "LONDON_NY_OVERLAP", "NEW_YORK", "ROLLOVER"}


def test_strategy_context_blocks_and_explainability() -> None:
    snapshot = _snapshot()
    trend = strategy_trend_pullback.evaluate(
        snapshot,
        {
            "regime": "TREND_UP",
            "close": 1.1300,
            "previous_close": 1.1290,
            "ema_fast": 1.1000,
            "ema_slow": 1.0900,
            "trend_slope": 0.001,
            "trend_strength": 1.0,
            "atr_points": 20,
            "rsi": 50,
            "spread_points": 10,
        },
    )
    assert trend.action == SignalAction.NONE
    assert "blocking_reasons" in trend.metadata

    mean = strategy_mean_reversion.evaluate(snapshot, {"regime": "TREND_UP", "spread_points": 10})
    assert mean.action == SignalAction.NONE
    assert "RANGE" in mean.reasons[0]

    breakout = strategy_breakout_compression.evaluate(snapshot, {"compression_ratio": 1.0, "body_ratio": 0.6, "spread_points": 10})
    assert breakout.action == SignalAction.NONE
    assert "compression" in breakout.reasons[0]

    sweep = strategy_liquidity_sweep.evaluate(snapshot, {"high": 1.1010, "low": 1.0990, "prev_high": 1.1010, "prev_low": 1.0990, "spread_points": 10})
    assert sweep.action == SignalAction.NONE
    assert "liquidity sweep" in sweep.reasons[0]

    session = strategy_session_momentum.evaluate(snapshot, {"session": "ASIA", "momentum_points": 10, "range_points": 20, "body_ratio": 0.7, "spread_points": 10})
    assert session.action == SignalAction.NONE
    assert "session" in session.reasons[0]


def test_scoring_component_scores_present_on_valid_strategy() -> None:
    signal = strategy_mean_reversion.evaluate(
        _snapshot(),
        {
            "regime": "RANGE",
            "support": 1.0990,
            "resistance": 1.1100,
            "close": 1.1000,
            "rsi": 25,
            "zscore": -2,
            "trend_strength": 0.1,
            "spread_points": 5,
        },
    )

    assert "component_scores" in signal.metadata
    assert signal.metadata["setup_quality"] in {"A", "B", "C", "D"}
    assert "blocking_reasons" in signal.metadata


def test_research_ablation_report_and_cli_modes(monkeypatch, tmp_path: Path, capsys) -> None:
    registry = CandidateRegistry()
    reports = write_research_reports(output_dir=tmp_path / "research", registry=registry, recommended_mix=[], summary={"mode": "research", "execution_attempted": False})
    assert any(path.endswith("ablation_results.csv") for path in reports)
    assert any(path.endswith("strategy_version_comparison.csv") for path in reports)

    monkeypatch.setattr(cli, "run_strategy_diagnose", lambda **_kwargs: {"mode": "strategy-diagnose", "reports_created": [], "execution_attempted": False})
    monkeypatch.setattr(cli, "write_structure_report", lambda **_kwargs: {"mode": "structure-report", "reports_created": [], "execution_attempted": False})
    assert cli.main(["--mode", "strategy-diagnose", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out
    assert cli.main(["--mode", "structure-report", "--symbols", "EURUSD,GBPUSD", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.calibration import get_signal_profile
from agi_style_forex_bot_mt5.real_data_research import RealDataResearchConfig, load_latest_run_summary
from agi_style_forex_bot_mt5.stability_repair import build_fold_diagnostics, run_stability_repair, run_walk_forward_failure_analysis
from agi_style_forex_bot_mt5.stability_repair.stability_filter_builder import build_balanced_stable_profile
from agi_style_forex_bot_mt5.stability_repair.strategy_stability_selector import select_stable_strategies
from agi_style_forex_bot_mt5.stability_repair.symbol_stability_selector import select_stable_symbols
from agi_style_forex_bot_mt5.stability_repair.temporal_edge_decay import analyze_temporal_edge_decay


def test_walk_forward_failure_analyzer_detects_negative_fold(tmp_path: Path) -> None:
    _write_artifacts(tmp_path, _mixed_trades())

    summary = run_walk_forward_failure_analysis(
        runs_root=tmp_path / "runs",
        robustness_dir=tmp_path / "robustness",
        profile_runs_dir=tmp_path / "profile_runs",
        output_dir=tmp_path / "stability",
    )

    assert summary["folds_negative"] >= 1
    assert summary["execution_attempted"] is False


def test_fold_diagnostics_classifies_pf_below_one() -> None:
    diagnostics = build_fold_diagnostics(_negative_trades(), folds=3, min_trades_per_fold=5)

    assert any("PF_BELOW_1" in reason for reason in diagnostics["failure_reason"].astype(str))


def test_temporal_edge_decay_detects_last_folds_bad() -> None:
    trades = _mixed_trades()
    diagnostics = build_fold_diagnostics(trades, folds=3, min_trades_per_fold=5)

    decay = analyze_temporal_edge_decay(diagnostics, trades)

    assert decay["latest_folds_negative"] is True
    assert decay["classification"] == "TEMPORAL_EDGE_DECAY"


def test_symbol_stability_selector_disables_negative_symbol() -> None:
    trades = pd.concat([_symbol_trades("EURUSD", 30, 0.4), _symbol_trades("GBPUSD", 30, -0.4)], ignore_index=True)

    selected = select_stable_symbols(trades, fold_count=3)

    assert selected.loc[selected["symbol"] == "GBPUSD", "decision"].iloc[0] == "DISABLE_FOR_NOW"


def test_strategy_stability_selector_disables_unstable_strategy() -> None:
    trades = _strategy_trades("mean_reversion", 30, -0.4)

    selected = select_stable_strategies(trades, fold_count=3)

    assert selected.loc[selected["strategy_name"] == "mean_reversion", "decision"].iloc[0] == "DISABLE_IN_BALANCED"


def test_balanced_stable_ini_is_generated_and_not_demo_live(tmp_path: Path) -> None:
    summary = build_balanced_stable_profile(
        output_dir=tmp_path,
        disabled_symbols=["GBPUSD"],
        disabled_strategies=["mean_reversion"],
        blocked_sessions=["ROLLOVER"],
        blocked_regimes=["HIGH_VOLATILITY"],
        stability_summary={"fold_stability_score": 50},
    )

    text = (tmp_path / "balanced_stable.ini").read_text(encoding="utf-8")
    assert "SIGNAL_PROFILE=BALANCED_STABLE" in text
    assert "NOT_FOR_DEMO_LIVE=true" in text
    assert summary["execution_attempted"] is False


def test_balanced_stable_profile_is_research_only() -> None:
    profile = get_signal_profile("BALANCED_STABLE")

    assert profile.not_for_demo_live is True
    assert profile.research_only is True


def test_stability_repair_creates_reports(tmp_path: Path) -> None:
    _write_artifacts(tmp_path, _mixed_trades())

    summary = run_stability_repair(
        runs_root=tmp_path / "runs",
        robustness_dir=tmp_path / "robustness",
        profile_runs_dir=tmp_path / "profile_runs",
        output_dir=tmp_path / "stability",
    )

    assert (tmp_path / "stability" / "balanced_stable.ini").exists()
    assert (tmp_path / "stability" / "fold_diagnostics.csv").exists()
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_real_data_research_accepts_balanced_stable_with_profile_config(tmp_path: Path) -> None:
    ini = tmp_path / "balanced_stable.ini"
    ini.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE",
                "PROFILE_TYPE=RESEARCH_BACKTEST_ONLY",
                "NOT_FOR_DEMO_LIVE=true",
                "REQUIRES_ROBUSTNESS_RERUN=true",
                "APPLY_STABILITY_FILTERS=true",
                "DISABLED_SYMBOLS=GBPUSD",
                "DISABLED_STRATEGIES=mean_reversion",
                "BLOCKED_SESSIONS=ROLLOVER",
                "BLOCKED_REGIMES=HIGH_VOLATILITY",
            ]
        ),
        encoding="utf-8",
    )

    config = RealDataResearchConfig(symbols=("EURUSD",), signal_profile="BALANCED_STABLE", profile_config=str(ini), quick=True)

    assert config.signal_profile == "BALANCED_STABLE"


def test_cli_accepts_stability_modes(tmp_path: Path, capsys) -> None:
    _write_artifacts(tmp_path, _mixed_trades())

    assert cli.main(["--mode", "walk-forward-failure-analysis", "--runs-root", str(tmp_path / "runs"), "--robustness-dir", str(tmp_path / "robustness"), "--profile-runs-dir", str(tmp_path / "profile_runs"), "--output-dir", str(tmp_path / "stability")]) == 0
    failure = json.loads(capsys.readouterr().out)
    assert failure["mode"] == "walk-forward-failure-analysis"

    assert cli.main(["--mode", "stability-repair", "--runs-root", str(tmp_path / "runs"), "--robustness-dir", str(tmp_path / "robustness"), "--profile-runs-dir", str(tmp_path / "profile_runs"), "--output-dir", str(tmp_path / "stability")]) == 0
    repair = json.loads(capsys.readouterr().out)
    assert repair["mode"] == "stability-repair"

    assert cli.main(["--mode", "build-stable-profile", "--runs-root", str(tmp_path / "runs"), "--stability-dir", str(tmp_path / "stability"), "--output-dir", str(tmp_path / "stability")]) == 0
    build = json.loads(capsys.readouterr().out)
    assert build["mode"] == "build-stable-profile"
    assert build["execution_attempted"] is False


def test_latest_run_summary_includes_stability_repair(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "20260101-000000-real-data-research"
    stability = run / "reports" / "stability_repair"
    stability.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    (stability / "walk_forward_failure_summary.json").write_text(
        json.dumps(
            {
                "stability_repair_decision": "STABILITY_REPAIR_REQUIRED",
                "fold_stability_score": 33.3,
                "overfit_risk_score": 75.0,
                "disabled_symbols_stable": ["GBPUSD"],
                "disabled_strategies_stable": ["mean_reversion"],
                "blocked_sessions_stable": ["ROLLOVER"],
                "blocked_regimes_stable": ["HIGH_VOLATILITY"],
            }
        ),
        encoding="utf-8",
    )

    summary = load_latest_run_summary(tmp_path / "runs")

    assert summary["stability_repair_decision"] == "STABILITY_REPAIR_REQUIRED"
    assert "recommended_stable_rerun_command" in summary


def _write_artifacts(root: Path, trades: pd.DataFrame) -> None:
    run = root / "runs" / "20260101-000000-real-data-research"
    backtests = run / "reports" / "backtests"
    profile = root / "profile_runs" / "balanced"
    robustness = root / "robustness"
    backtests.mkdir(parents=True)
    profile.mkdir(parents=True)
    robustness.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    trades.to_csv(backtests / "trades.csv", index=False)
    trades.to_csv(profile / "trades.csv", index=False)
    (robustness / "walk_forward_fast.json").write_text(json.dumps({"classification": "WALK_FORWARD_WARNING", "fold_count": 3}), encoding="utf-8")
    pd.DataFrame([{"fold": 0, "expectancy_r": 0.3}, {"fold": 1, "expectancy_r": 0.2}, {"fold": 2, "expectancy_r": -0.4}]).to_csv(robustness / "walk_forward_fast.csv", index=False)


def _mixed_trades() -> pd.DataFrame:
    rows = []
    for index in range(90):
        value = 0.4 if index < 60 else -0.5
        symbol = "EURUSD" if index < 45 else "GBPUSD"
        rows.append(_row(index, value, symbol=symbol, strategy="trend_pullback", session="LONDON", regime="TREND_UP"))
    return pd.DataFrame(rows)


def _negative_trades() -> pd.DataFrame:
    return pd.DataFrame([_row(index, -0.3, symbol="GBPUSD", strategy="mean_reversion", session="ROLLOVER", regime="RANGE") for index in range(30)])


def _symbol_trades(symbol: str, count: int, value: float) -> pd.DataFrame:
    return pd.DataFrame([_row(index, value, symbol=symbol, strategy="trend_pullback", session="LONDON", regime="TREND_UP") for index in range(count)])


def _strategy_trades(strategy: str, count: int, value: float) -> pd.DataFrame:
    return pd.DataFrame([_row(index, value, symbol="EURUSD", strategy=strategy, session="LONDON", regime="TREND_UP") for index in range(count)])


def _row(index: int, r_multiple: float, *, symbol: str, strategy: str, session: str, regime: str) -> dict[str, object]:
    entry = pd.Timestamp("2024-01-01T00:00:00Z") + pd.Timedelta(hours=index * 2)
    exit_time = entry + pd.Timedelta(hours=1)
    return {
        "signal_id": f"s{index}",
        "symbol": symbol,
        "strategy_name": strategy,
        "session": session,
        "regime": regime,
        "entry_time": entry.isoformat(),
        "exit_time": exit_time.isoformat(),
        "profit": r_multiple * 100.0,
        "r_multiple": r_multiple,
    }

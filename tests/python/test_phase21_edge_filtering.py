from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.edge_filtering import build_filtered_profile, filter_sessions, filter_strategies, filter_symbols
from agi_style_forex_bot_mt5.real_data_research import RealDataResearchConfig, load_latest_run_summary, run_real_data_research


def test_edge_filtering_reads_edge_summary_and_generates_profile(tmp_path: Path) -> None:
    edge_dir = _write_edge_reports(tmp_path)
    output = tmp_path / "edge_filtering"

    summary = build_filtered_profile(runs_root=tmp_path / "runs", edge_dir=edge_dir, output_dir=output)

    assert summary["filtered_profile"] == "BALANCED_FILTERED"
    assert summary["filtering_decision"] == "ACTIONABLE_FILTER_CREATED"
    assert summary["symbols_keep"] == ["EURUSD"]
    assert "GBPUSD" in summary["symbols_disable"]
    assert (output / "balanced_filtered.ini").exists()
    assert (output / "balanced_filtered.json").exists()
    assert summary["execution_attempted"] is False


def test_edge_filtering_produces_no_actionable_filter_when_all_watchlist(tmp_path: Path) -> None:
    edge = tmp_path / "edge"
    edge.mkdir()
    (edge / "edge_summary.json").write_text(
        json.dumps({"run_id": "edge-run", "decision": "CONTINUE_BALANCED_RESEARCH", "metrics_status": "FULL_EDGE_METRICS", "total_trades": 120}),
        encoding="utf-8",
    )
    pd.DataFrame([{"symbol": "EURUSD", "total_trades": 50, "profit_factor": 1.02, "expectancy_r": 0.0}]).to_csv(edge / "by_symbol.csv", index=False)
    pd.DataFrame([{"strategy_name": "trend_pullback", "total_trades": 50, "profit_factor": 1.02, "expectancy_r": 0.0}]).to_csv(edge / "by_strategy.csv", index=False)
    pd.DataFrame(columns=["session", "total_trades"]).to_csv(edge / "by_session.csv", index=False)
    pd.DataFrame(columns=["regime", "total_trades"]).to_csv(edge / "by_regime.csv", index=False)
    pd.DataFrame(columns=["blocking_reason", "count"]).to_csv(edge / "blockers.csv", index=False)

    summary = build_filtered_profile(runs_root=tmp_path / "runs", edge_dir=edge, output_dir=tmp_path / "filtered")

    assert summary["filtering_decision"] == "NO_ACTIONABLE_FILTER"
    assert summary["apply_filters"] is False
    assert "APPLY_FILTERS=false" in (tmp_path / "filtered" / "balanced_filtered.ini").read_text(encoding="utf-8")


def test_edge_filtering_recommends_active_research_for_test_active_with_no_filters(tmp_path: Path) -> None:
    edge = tmp_path / "edge"
    edge.mkdir()
    (edge / "edge_summary.json").write_text(
        json.dumps({"run_id": "edge-run", "decision": "TEST_ACTIVE_RESEARCH_ONLY", "metrics_status": "FULL_EDGE_METRICS", "total_trades": 213}),
        encoding="utf-8",
    )
    pd.DataFrame([{"symbol": "EURUSD", "total_trades": 79, "profit_factor": 1.0, "expectancy_r": 0.0}]).to_csv(edge / "by_symbol.csv", index=False)
    pd.DataFrame([{"strategy_name": "trend_pullback", "total_trades": 79, "profit_factor": 1.0, "expectancy_r": 0.0}]).to_csv(edge / "by_strategy.csv", index=False)
    pd.DataFrame(columns=["session", "total_trades"]).to_csv(edge / "by_session.csv", index=False)
    pd.DataFrame(columns=["regime", "total_trades"]).to_csv(edge / "by_regime.csv", index=False)
    pd.DataFrame(columns=["blocking_reason", "count"]).to_csv(edge / "blockers.csv", index=False)

    summary = build_filtered_profile(runs_root=tmp_path / "runs", edge_dir=edge, output_dir=tmp_path / "filtered")

    assert summary["filtering_decision"] == "ACTIVE_RESEARCH_EXPERIMENT_RECOMMENDED"
    assert (tmp_path / "filtered" / "research_active_experiment.ini").exists()


def test_edge_filtering_falls_back_to_summary_counts(tmp_path: Path) -> None:
    edge = tmp_path / "edge"
    edge.mkdir()
    (edge / "edge_summary.json").write_text(
        json.dumps({"run_id": "edge-run", "decision": "CONTINUE_BALANCED_RESEARCH", "metrics_status": "FULL_EDGE_METRICS", "trades_by_symbol": {"EURUSD": 79}, "trades_by_strategy": {"trend_pullback": 79}}),
        encoding="utf-8",
    )
    pd.DataFrame(columns=["symbol", "total_trades"]).to_csv(edge / "by_symbol.csv", index=False)
    pd.DataFrame(columns=["strategy_name", "total_trades"]).to_csv(edge / "by_strategy.csv", index=False)
    pd.DataFrame(columns=["session", "total_trades"]).to_csv(edge / "by_session.csv", index=False)
    pd.DataFrame(columns=["regime", "total_trades"]).to_csv(edge / "by_regime.csv", index=False)
    pd.DataFrame(columns=["blocking_reason", "count"]).to_csv(edge / "blockers.csv", index=False)

    summary = build_filtered_profile(runs_root=tmp_path / "runs", edge_dir=edge, output_dir=tmp_path / "filtered")
    symbols = pd.read_csv(tmp_path / "filtered" / "by_symbol_filter.csv")

    assert symbols["symbol"].tolist() == ["EURUSD"]
    assert symbols["filter_decision"].iloc[0] == "WATCHLIST_COUNTS_ONLY"
    assert summary["filtering_decision"] in {"NO_ACTIONABLE_FILTER", "ACTIVE_RESEARCH_EXPERIMENT_RECOMMENDED"}


def test_symbol_filter_keep_and_disable() -> None:
    frame = pd.DataFrame(
        [
            {"symbol": "EURUSD", "total_trades": 79, "profit_factor": 1.2, "expectancy_r": 0.08},
            {"symbol": "GBPUSD", "total_trades": 68, "profit_factor": 0.8, "expectancy_r": -0.05},
        ]
    )

    result = filter_symbols(frame)

    assert result.loc[result["symbol"] == "EURUSD", "filter_decision"].iloc[0] == "KEEP"
    assert result.loc[result["symbol"] == "GBPUSD", "filter_decision"].iloc[0] == "DISABLE"


def test_strategy_filter_disables_low_profit_factor() -> None:
    frame = pd.DataFrame([{"strategy_name": "mean_reversion", "total_trades": 40, "profit_factor": 0.9, "expectancy_r": -0.03}])

    result = filter_strategies(frame)

    assert result["filter_decision"].iloc[0] == "DISABLE_IN_BALANCED"


def test_session_filter_blocks_negative_rollover() -> None:
    frame = pd.DataFrame([{"session": "ROLLOVER", "total_trades": 25, "profit_factor": 0.8, "expectancy_r": -0.05}])

    result = filter_sessions(frame)

    assert result["filter_decision"].iloc[0] == "BLOCK"


def test_cli_accepts_edge_filtering_modes(tmp_path: Path, capsys) -> None:
    edge_dir = _write_edge_reports(tmp_path)
    output = tmp_path / "filtered"

    assert cli.main(["--mode", "edge-filtering", "--runs-root", str(tmp_path / "runs"), "--edge-dir", str(edge_dir), "--output-dir", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "edge-filtering"
    assert payload["execution_attempted"] is False

    assert cli.main(["--mode", "build-filtered-profile", "--runs-root", str(tmp_path / "runs"), "--edge-dir", str(edge_dir), "--output-dir", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "build-filtered-profile"


def test_profile_comparison_run_includes_active_research_only(tmp_path: Path, capsys) -> None:
    output = tmp_path / "profiles"

    assert cli.main(["--mode", "profile-comparison-run", "--symbols", "EURUSD", "--data-dir", str(tmp_path / "historical"), "--output-dir", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    comparison = json.loads((output / "profile_comparison.json").read_text(encoding="utf-8"))
    active = next(row for row in comparison["profiles"] if row["profile"] == "ACTIVE")

    assert "ACTIVE" in payload["profiles_compared"]
    assert active["not_for_demo_live"] is True
    assert active["recommendation"].startswith("research-only")


def test_real_data_research_accepts_balanced_filtered_with_profile_config(tmp_path: Path) -> None:
    profile = tmp_path / "balanced_filtered.ini"
    profile.write_text("DEMO_ONLY=True\nLIVE_TRADING_APPROVED=False\nSIGNAL_PROFILE=BALANCED_FILTERED\nAPPLY_FILTERS=true\nFILTERING_DECISION=ACTIONABLE_FILTER_CREATED\n", encoding="utf-8")
    config = RealDataResearchConfig(
        symbols=("EURUSD",),
        output_root=str(tmp_path / "runs"),
        run_id="filtered-run",
        signal_profile="BALANCED_FILTERED",
        profile_config=str(profile),
        quick=True,
    )

    summary = run_real_data_research(
        config,
        stage_overrides={
            "MT5_DIAGNOSE": lambda: {"classification": "OK", "mt5_connected": True},
            "EXPORT_HISTORY": lambda: {"classification": "OK", "symbols_exported": ["EURUSD"]},
            "HISTORICAL_DATA_AUDIT": lambda: {"classification": "OK"},
            "DATA_CONTRACT_AUDIT": lambda: {"classification": "OK", "data_contract_status": "OK"},
            "STRATEGY_DIAGNOSE": lambda: {"classification": "OK"},
            "BACKTEST": lambda: {"classification": "WARNING_NO_TRADES", "total_trades": 0, "signals_generated": 0, "trades_generated": 0},
        },
    )

    assert summary["signal_profile_used"] == "BALANCED_FILTERED"
    assert summary["filters_applied"]["enabled"] is True
    assert summary["execution_attempted"] is False


def test_balanced_filtered_apply_false_is_not_normal_profile(tmp_path: Path) -> None:
    profile = tmp_path / "balanced_filtered.ini"
    profile.write_text("SIGNAL_PROFILE=BALANCED_FILTERED\nAPPLY_FILTERS=false\nFILTERING_DECISION=NO_ACTIONABLE_FILTER\n", encoding="utf-8")
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path / "runs"), run_id="filtered-run", signal_profile="BALANCED_FILTERED", profile_config=str(profile), quick=True)

    summary = run_real_data_research(
        config,
        stage_overrides={
            "MT5_DIAGNOSE": lambda: {"classification": "OK", "mt5_connected": True},
            "EXPORT_HISTORY": lambda: {"classification": "OK"},
            "HISTORICAL_DATA_AUDIT": lambda: {"classification": "OK"},
            "DATA_CONTRACT_AUDIT": lambda: {"classification": "OK"},
            "STRATEGY_DIAGNOSE": lambda: {"classification": "OK"},
            "BACKTEST": lambda: {"classification": "WARNING_NO_TRADES", "total_trades": 0, "signals_generated": 0, "trades_generated": 0},
        },
    )

    assert summary["filters_applied"]["enabled"] is False
    assert summary["filters_applied"]["status"] == "FILTERED_PROFILE_NOT_ACTIONABLE"


def test_latest_run_summary_includes_filtered_profile_path(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run = runs / "20260517-160651-real-data-research"
    run.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "total_trades": 213, "execution_attempted": False}), encoding="utf-8")
    edge_dir = _write_edge_reports(tmp_path)
    build_filtered_profile(runs_root=runs, edge_dir=edge_dir, output_dir=run / "reports" / "edge_filtering")

    summary = load_latest_run_summary(runs)

    assert summary["filtered_profile_available"] is True
    assert summary["filtering_decision"] == "ACTIONABLE_FILTER_CREATED"
    assert summary["filtered_profile_path"].endswith("balanced_filtered.ini")
    assert summary["execution_attempted"] is False


def _write_edge_reports(tmp_path: Path) -> Path:
    edge = tmp_path / "edge"
    edge.mkdir(parents=True)
    (edge / "edge_summary.json").write_text(
        json.dumps({"run_id": "edge-run", "decision": "TEST_ACTIVE_RESEARCH_ONLY", "metrics_status": "FULL_EDGE_METRICS", "total_trades": 213}),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"symbol": "EURUSD", "total_trades": 79, "profit_factor": 1.2, "expectancy_r": 0.08, "max_drawdown_pct": 4},
            {"symbol": "GBPUSD", "total_trades": 68, "profit_factor": 0.8, "expectancy_r": -0.05, "max_drawdown_pct": 6},
        ]
    ).to_csv(edge / "by_symbol.csv", index=False)
    pd.DataFrame(
        [
            {"strategy_name": "trend_pullback", "total_trades": 60, "profit_factor": 1.2, "expectancy_r": 0.06, "winrate": 48},
            {"strategy_name": "mean_reversion", "total_trades": 40, "profit_factor": 0.9, "expectancy_r": -0.03, "winrate": 38},
        ]
    ).to_csv(edge / "by_strategy.csv", index=False)
    pd.DataFrame(
        [
            {"session": "LONDON", "total_trades": 80, "profit_factor": 1.15, "expectancy_r": 0.04},
            {"session": "ROLLOVER", "total_trades": 25, "profit_factor": 0.7, "expectancy_r": -0.08},
        ]
    ).to_csv(edge / "by_session.csv", index=False)
    pd.DataFrame(
        [
            {"regime": "TREND_UP", "total_trades": 70, "profit_factor": 1.2, "expectancy_r": 0.05},
            {"regime": "HIGH_VOLATILITY", "total_trades": 30, "profit_factor": 0.9, "expectancy_r": -0.02},
        ]
    ).to_csv(edge / "by_regime.csv", index=False)
    pd.DataFrame([{"blocking_reason": "SPREAD_BLOCK", "count": 4}, {"blocking_reason": "ENSEMBLE_SCORE_LOW", "count": 8}]).to_csv(edge / "blockers.csv", index=False)
    return edge

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.edge_evaluation import (
    analyze_blockers,
    analyze_sessions_regimes,
    decide_fast,
    load_edge_metrics,
    run_edge_evaluation,
    select_strategies,
    select_symbols,
)
from agi_style_forex_bot_mt5.real_data_research import load_latest_run_summary


def test_edge_evaluation_loads_trades_csv(tmp_path: Path) -> None:
    run = _make_run(tmp_path, _profitable_trades("EURUSD", 35))

    bundle = load_edge_metrics(runs_root=tmp_path)

    assert bundle.run_id == run.name
    assert bundle.global_metrics["total_trades"] == 35
    assert bundle.classification == "OK"


def test_edge_evaluation_tolerates_missing_trades(tmp_path: Path) -> None:
    run = tmp_path / "20260101-000000-real-data-research"
    (run / "reports" / "backtests").mkdir(parents=True)
    (run / "final_summary_compact.json").write_text('{"run_id":"missing"}', encoding="utf-8")

    bundle = load_edge_metrics(runs_root=tmp_path)

    assert bundle.classification == "NEEDS_TRADES"
    assert bundle.global_metrics["total_trades"] == 0


def test_edge_evaluation_uses_compact_summary_when_trades_csv_is_missing(tmp_path: Path) -> None:
    run = tmp_path / "20260517-160651-real-data-research"
    (run / "reports" / "backtests").mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(
        json.dumps(
            {
                "run_id": run.name,
                "total_trades": 213,
                "sample_status": "USABLE_SAMPLE",
                "trade_frequency_status": "USABLE_SAMPLE",
                "trades_by_symbol": {"EURUSD": 79, "GBPUSD": 68, "USDJPY": 66},
                "trades_by_strategy": {"strategy_ensemble": 213},
                "execution_attempted": False,
            }
        ),
        encoding="utf-8",
    )

    summary = run_edge_evaluation(runs_root=tmp_path, output_dir=tmp_path / "edge")

    assert summary["run_id"] == run.name
    assert summary["total_trades"] == 213
    assert summary["sample_status"] == "USABLE_SAMPLE"
    assert summary["metrics_status"] == "COUNTS_ONLY"
    assert summary["decision"] == "NEEDS_FULL_EDGE_METRICS"
    assert summary["trades_by_symbol"]["EURUSD"] == 79
    assert summary["execution_attempted"] is False


def test_edge_evaluation_total_trades_matches_latest_run_summary_counts_only(tmp_path: Path) -> None:
    run = tmp_path / "20260517-160651-real-data-research"
    (run / "reports").mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(
        json.dumps({"run_id": run.name, "total_trades": 213, "sample_status": "USABLE_SAMPLE", "trades_by_symbol": {"EURUSD": 79}, "execution_attempted": False}),
        encoding="utf-8",
    )

    edge = run_edge_evaluation(runs_root=tmp_path, output_dir=run / "reports" / "edge")
    latest = load_latest_run_summary(tmp_path)

    assert edge["total_trades"] == latest["total_trades"] == 213
    assert latest["edge_metrics_status"] == "COUNTS_ONLY"
    assert latest["edge_decision"] == "NEEDS_FULL_EDGE_METRICS"


def test_symbol_selector_keep_and_reject() -> None:
    frame = pd.DataFrame(
        [
            {"symbol": "EURUSD", "total_trades": 35, "expectancy_r": 0.2, "profit_factor": 1.4, "winrate": 52},
            {"symbol": "GBPUSD", "total_trades": 35, "expectancy_r": -0.2, "profit_factor": 0.8, "winrate": 35},
        ]
    )

    selected = select_symbols(frame)

    assert selected.loc[selected["symbol"] == "EURUSD", "decision"].iloc[0] == "KEEP"
    assert selected.loc[selected["symbol"] == "GBPUSD", "decision"].iloc[0] == "REJECT"


def test_symbol_selector_counts_only_is_watchlist_counts_only() -> None:
    frame = pd.DataFrame([{"symbol": "EURUSD", "total_trades": 79, "metrics_status": "COUNTS_ONLY"}])

    selected = select_symbols(frame)

    assert selected["decision"].iloc[0] == "WATCHLIST_COUNTS_ONLY"


def test_strategy_selector_disable_in_balanced() -> None:
    frame = pd.DataFrame([{"strategy_name": "mean_reversion", "total_trades": 40, "expectancy_r": -0.05, "profit_factor": 0.92}])

    selected = select_strategies(frame)

    assert selected["decision"].iloc[0] == "DISABLE_IN_BALANCED"


def test_strategy_selector_counts_only_stays_watchlist() -> None:
    frame = pd.DataFrame([{"strategy_name": "strategy_ensemble", "total_trades": 213, "metrics_status": "COUNTS_ONLY"}])

    selected = select_strategies(frame)

    assert selected["decision"].iloc[0] == "WATCHLIST_COUNTS_ONLY"


def test_session_analyzer_blocks_negative_rollover() -> None:
    sessions = pd.DataFrame([{"session": "ROLLOVER", "total_trades": 25, "expectancy_r": -0.1, "profit_factor": 0.7}])
    regimes = pd.DataFrame()

    result = analyze_sessions_regimes(sessions, regimes)

    assert "ROLLOVER" in result["blocked_sessions"]


def test_blocker_analyzer_does_not_relax_spread() -> None:
    blockers = pd.DataFrame([{"blocking_reason": "SPREAD_BLOCK", "count": 10}])

    result = analyze_blockers(blockers)

    assert "maintain strict" in result["recommendation"].iloc[0]


def test_fast_decision_needs_more_trades() -> None:
    decision = decide_fast(global_metrics={"total_trades": 8, "profit_factor": 2.0, "expectancy_r": 0.2}, symbol_selection=pd.DataFrame(), strategy_selection=pd.DataFrame(), blocker_summary={})

    assert decision["decision"] == "NEEDS_MORE_TRADES"


def test_fast_decision_forward_shadow_candidate() -> None:
    symbols = pd.DataFrame([{"symbol": "EURUSD", "decision": "KEEP"}])
    strategies = pd.DataFrame([{"strategy_name": "strategy_ensemble", "decision": "KEEP"}])

    decision = decide_fast(global_metrics={"total_trades": 120, "profit_factor": 1.3, "expectancy_r": 0.12}, symbol_selection=symbols, strategy_selection=strategies, blocker_summary={})

    assert decision["decision"] == "FORWARD_SHADOW_CANDIDATE"
    assert decision["execution_attempted"] is False


def test_fast_decision_needs_full_edge_metrics_for_usable_counts_only() -> None:
    symbols = pd.DataFrame([{"symbol": "EURUSD", "decision": "WATCHLIST_COUNTS_ONLY"}])
    strategies = pd.DataFrame([{"strategy_name": "strategy_ensemble", "decision": "WATCHLIST"}])

    decision = decide_fast(global_metrics={"total_trades": 213, "sample_status": "USABLE_SAMPLE", "metrics_status": "COUNTS_ONLY"}, symbol_selection=symbols, strategy_selection=strategies, blocker_summary={})

    assert decision["decision"] == "NEEDS_FULL_EDGE_METRICS"
    assert decision["execution_attempted"] is False


def test_edge_evaluation_reports_are_created(tmp_path: Path) -> None:
    _make_run(tmp_path, _profitable_trades("EURUSD", 35))

    summary = run_edge_evaluation(runs_root=tmp_path, output_dir=tmp_path / "edge")

    assert summary["mode"] == "edge-evaluation"
    assert (tmp_path / "edge" / "edge_summary.json").exists()
    assert (tmp_path / "edge" / "by_symbol.csv").exists()
    assert (tmp_path / "edge" / "config_suggestions" / "balanced_filtered.ini").exists()
    assert summary["execution_attempted"] is False


def test_cli_accepts_edge_modes(tmp_path: Path, capsys) -> None:
    _make_run(tmp_path, _profitable_trades("EURUSD", 35))

    assert cli.main(["--mode", "edge-evaluation", "--runs-root", str(tmp_path), "--output-dir", str(tmp_path / "edge")]) == 0
    edge = json.loads(capsys.readouterr().out)
    assert edge["mode"] == "edge-evaluation"
    assert edge["execution_attempted"] is False

    assert cli.main(["--mode", "symbol-selection", "--runs-root", str(tmp_path), "--output-dir", str(tmp_path / "edge")]) == 0
    symbol = json.loads(capsys.readouterr().out)
    assert symbol["mode"] == "symbol-selection"

    assert cli.main(["--mode", "strategy-selection", "--runs-root", str(tmp_path), "--output-dir", str(tmp_path / "edge")]) == 0
    strategy = json.loads(capsys.readouterr().out)
    assert strategy["mode"] == "strategy-selection"


def test_cli_run_id_selects_exact_run(tmp_path: Path, capsys) -> None:
    old = tmp_path / "20260101-000000-real-data-research"
    new = tmp_path / "20260517-160651-real-data-research"
    for run, total in ((old, 10), (new, 213)):
        (run / "reports").mkdir(parents=True)
        (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "total_trades": total, "sample_status": "USABLE_SAMPLE"}), encoding="utf-8")

    assert cli.main(["--mode", "edge-evaluation", "--runs-root", str(tmp_path), "--run-id", old.name, "--output-dir", str(tmp_path / "edge")]) == 0
    edge = json.loads(capsys.readouterr().out)

    assert edge["run_id"] == old.name
    assert edge["total_trades"] == 10


def test_latest_run_summary_includes_edge_decision(tmp_path: Path) -> None:
    run = _make_run(tmp_path, _profitable_trades("EURUSD", 35))
    edge_dir = run / "reports" / "edge"
    run_edge_evaluation(runs_root=tmp_path, output_dir=edge_dir)

    summary = load_latest_run_summary(tmp_path)

    assert "edge_decision" in summary
    assert summary["execution_attempted"] is False


def _make_run(root: Path, trades: pd.DataFrame) -> Path:
    run = root / "20260101-000000-real-data-research"
    reports = run / "reports" / "backtests"
    reports.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    trades.to_csv(reports / "trades.csv", index=False)
    (reports / "summary.json").write_text(json.dumps({"total_trades": len(trades), "top_blocking_reasons": [{"blocking_reason": "ENSEMBLE_SCORE_LOW", "count": 3}]}), encoding="utf-8")
    return run


def _profitable_trades(symbol: str, count: int) -> pd.DataFrame:
    rows = []
    for index in range(count):
        profit = 12.0 if index % 2 == 0 else -5.0
        rows.append(
            {
                "signal_id": f"s{index}",
                "symbol": symbol,
                "strategy_name": "strategy_ensemble",
                "session": "LONDON",
                "regime": "TREND_UP",
                "entry_time": f"2024-01-01T00:{index % 60:02d}:00Z",
                "exit_time": f"2024-01-01T01:{index % 60:02d}:00Z",
                "profit": profit,
                "r_multiple": profit / 10.0,
                "duration_seconds": 3600,
            }
        )
    return pd.DataFrame(rows)

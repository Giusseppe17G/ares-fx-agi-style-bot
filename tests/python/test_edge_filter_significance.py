"""Edge filtering KEEP needs the edge selectors' Holm-adjusted significance.

Decision: docs/decisions/2026-10-22-deflated-promotion-gate.md. The selectors
write ``holm_adjusted_p_value`` to by_symbol.csv and by_strategy.csv; the
BALANCED_FILTERED symbol and strategy filters keep a row only when that value
is a finite number in [0, 0.05], on top of their old metric rule. A missing
column or a blank, malformed or larger value fails closed to WATCHLIST. Every
other filter decision is unchanged. Research only: no filter decision enables
any execution.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.edge_evaluation import run_edge_evaluation, select_strategies, select_symbols
from agi_style_forex_bot_mt5.edge_filtering import build_filtered_profile, filter_strategies, filter_symbols

# Rows that pass each filter's old metric KEEP rule.
SYMBOL_ROW = {"symbol": "EURUSD", "total_trades": 79, "profit_factor": 1.2, "expectancy_r": 0.08, "max_drawdown_pct": 4.0}
STRATEGY_ROW = {
    "strategy_name": "trend_pullback",
    "total_trades": 60,
    "profit_factor": 1.2,
    "expectancy_r": 0.06,
    "winrate": 48.0,
    "net_profit": 120.0,
    "max_drawdown_pct": 4.0,
}
FILTERS = [
    pytest.param(filter_symbols, SYMBOL_ROW, "symbol", id="symbols"),
    pytest.param(filter_strategies, STRATEGY_ROW, "strategy_name", id="strategies"),
]


def _decision(filter_function, row: dict) -> pd.Series:
    return filter_function(pd.DataFrame([row])).iloc[0]


@pytest.mark.parametrize(("filter_function", "row", "column"), FILTERS)
@pytest.mark.parametrize(
    ("adjusted_p", "expected"),
    [
        (0.0, "KEEP"),
        (0.01, "KEEP"),
        (0.05, "KEEP"),
        # Between 0.05 and 0.10: only the 0.05 level keeps these out of KEEP.
        (0.0501, "WATCHLIST"),
        (0.07, "WATCHLIST"),
        (1.0, "WATCHLIST"),
        (float("nan"), "WATCHLIST"),
        (float("inf"), "WATCHLIST"),
        (-0.01, "WATCHLIST"),
        ("", "WATCHLIST"),
        ("significant", "WATCHLIST"),
        (None, "WATCHLIST"),
    ],
)
def test_filter_keep_needs_a_significant_adjusted_p_value(filter_function, row: dict, column: str, adjusted_p: object, expected: str) -> None:
    result = _decision(filter_function, {**row, "holm_adjusted_p_value": adjusted_p})

    assert result["filter_decision"] == expected
    if expected == "WATCHLIST":
        assert "Holm" in result["filter_reason"]


@pytest.mark.parametrize(("filter_function", "row", "column"), FILTERS)
def test_filter_keep_fails_closed_without_the_column(filter_function, row: dict, column: str) -> None:
    result = _decision(filter_function, row)

    assert result["filter_decision"] == "WATCHLIST"
    assert "holm_adjusted_p_value is missing" in result["filter_reason"]


@pytest.mark.parametrize(("filter_function", "row", "column"), FILTERS)
def test_not_significant_reason_names_the_adjusted_p_value(filter_function, row: dict, column: str) -> None:
    result = _decision(filter_function, {**row, "holm_adjusted_p_value": 0.07})

    assert "adjusted p=0.07 > 0.05" in result["filter_reason"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"symbol": "GBPUSD", "total_trades": 68, "profit_factor": 0.8, "expectancy_r": -0.05}, "DISABLE"),
        ({"symbol": "USDJPY", "total_trades": 40, "profit_factor": 1.0, "expectancy_r": 0.0}, "WATCHLIST"),
        ({"symbol": "AUDUSD", "total_trades": 10, "profit_factor": 1.5, "expectancy_r": 0.2}, "RESEARCH_ONLY"),
        ({**SYMBOL_ROW, "max_drawdown_pct": 15.0}, "DISABLE"),
        ({"symbol": "USDCAD", "total_trades": 50}, "WATCHLIST_COUNTS_ONLY"),
    ],
)
@pytest.mark.parametrize("adjusted_p", [0.001, 1.0, None])
def test_symbol_filter_other_decisions_are_unchanged(row: dict, expected: str, adjusted_p: object) -> None:
    with_p = row if adjusted_p is None else {**row, "holm_adjusted_p_value": adjusted_p}

    assert _decision(filter_symbols, with_p)["filter_decision"] == expected


@pytest.mark.parametrize(
    ("row", "expected", "reason"),
    [
        ({"strategy_name": "mean_reversion", "total_trades": 40, "profit_factor": 0.9, "expectancy_r": -0.03}, "DISABLE_IN_BALANCED", None),
        ({"strategy_name": "breakout", "total_trades": 25, "profit_factor": 1.0, "expectancy_r": 0.0}, "WATCHLIST", None),
        ({"strategy_name": "sweep", "total_trades": 10, "profit_factor": 1.5, "expectancy_r": 0.2}, "RESEARCH_ONLY", None),
        ({**STRATEGY_ROW, "net_profit": -5.0}, "WATCHLIST", "positive R metrics but negative net profit"),
        ({**STRATEGY_ROW, "max_drawdown_pct": 15.0}, "DISABLE_IN_BALANCED", "drawdown exceeds filter threshold"),
        ({"strategy_name": "momentum", "total_trades": 50}, "WATCHLIST_COUNTS_ONLY", None),
    ],
)
def test_strategy_filter_other_decisions_are_unchanged(row: dict, expected: str, reason: str | None) -> None:
    result = _decision(filter_strategies, {**row, "holm_adjusted_p_value": 0.001})

    assert result["filter_decision"] == expected
    if reason is not None:
        assert result["filter_reason"] == reason


def _zero_edge_rows(rng: np.random.Generator, slices: int, column: str) -> list[dict]:
    rows = []
    for index in range(slices):
        trades = int(rng.integers(30, 81))
        values = np.where(rng.random(trades) < 0.4, 1.5, -1.0)  # expectancy exactly 0 R
        wins, losses = values[values > 0], values[values < 0]
        rows.append(
            {
                column: f"slice_{index}",
                "total_trades": trades,
                "expectancy_r": float(values.mean()),
                "r_multiple_std": float(values.std(ddof=1)),
                "profit_factor": float(wins.sum() / -losses.sum()) if losses.size else float("inf"),
                "winrate": float(wins.size / trades * 100.0),
                "max_drawdown_pct": 5.0,
            }
        )
    return rows


def _through_csv(frame: pd.DataFrame) -> pd.DataFrame:
    """The filters read the selectors' output back from CSV."""

    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    buffer.seek(0)
    return pd.read_csv(buffer)


@pytest.mark.parametrize(
    ("selector", "filter_function", "column"),
    [(select_symbols, filter_symbols, "symbol"), (select_strategies, filter_strategies, "strategy_name")],
)
def test_zero_edge_slices_rarely_reach_filter_keep(selector, filter_function, column: str) -> None:
    universes, slices = 200, 20
    universes_with_keep = old_keep_rows = new_keep_rows = 0
    for seed in range(universes):
        rows = _zero_edge_rows(np.random.default_rng(6000 + seed), slices, column)
        filtered = filter_function(_through_csv(selector(pd.DataFrame(rows))))
        keeps = int((filtered["filter_decision"] == "KEEP").sum())
        universes_with_keep += keeps > 0
        new_keep_rows += keeps
        # The filters' old rule, without the selectors' significance.
        old_keep_rows += int((filter_function(pd.DataFrame(rows).assign(holm_adjusted_p_value=0.0))["filter_decision"] == "KEEP").sum())

    assert universes_with_keep / universes <= 0.05
    assert old_keep_rows / (universes * slices) >= 0.15
    assert new_keep_rows < old_keep_rows / 20


def _make_run(root: Path, trades: pd.DataFrame) -> None:
    run = root / "20260101-000000-real-data-research"
    reports = run / "reports" / "backtests"
    reports.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    trades.to_csv(reports / "trades.csv", index=False)
    (reports / "summary.json").write_text(json.dumps({"total_trades": len(trades)}), encoding="utf-8")


def _trade(index: int, symbol: str, strategy: str, r_multiple: float) -> dict:
    return {
        "signal_id": f"{symbol}-{index}",
        "symbol": symbol,
        "strategy_name": strategy,
        "session": "LONDON",
        "regime": "TREND_UP",
        "entry_time": f"2024-01-{1 + index // 60:02d}T00:{index % 60:02d}:00Z",
        "exit_time": f"2024-01-{1 + index // 60:02d}T01:{index % 60:02d}:00Z",
        "profit": r_multiple * 10.0,
        "r_multiple": r_multiple,
        "duration_seconds": 3600,
    }


def test_edge_filtering_keeps_only_significant_rows_end_to_end(tmp_path: Path) -> None:
    rows = []
    # GBPUSD / strong: +1.2 R or -0.5 R alternately, clearly significant.
    for index in range(60):
        rows.append(_trade(index, "GBPUSD", "strong", 1.2 if index % 2 == 0 else -0.5))
    # EURUSD / marginal: +1.2 R or -1.0 R alternately. PF 1.2 and mean R 0.1
    # pass the old filter rule, but t is about 0.6, far from significant.
    for index in range(40):
        rows.append(_trade(60 + index, "EURUSD", "marginal", 1.2 if index % 2 == 0 else -1.0))
    _make_run(tmp_path / "runs", pd.DataFrame(rows))

    run_edge_evaluation(runs_root=tmp_path / "runs", output_dir=tmp_path / "edge")
    summary = build_filtered_profile(runs_root=tmp_path / "runs", edge_dir=tmp_path / "edge", output_dir=tmp_path / "filtered")

    assert summary["symbols_keep"] == ["GBPUSD"]
    assert summary["strategies_keep"] == ["strong"]
    symbols = pd.read_csv(tmp_path / "filtered" / "by_symbol_filter.csv").set_index("symbol")
    strategies = pd.read_csv(tmp_path / "filtered" / "by_strategy_filter.csv").set_index("strategy_name")
    assert symbols.loc["EURUSD", "filter_decision"] == "WATCHLIST"
    assert "Holm" in symbols.loc["EURUSD", "filter_reason"]
    assert strategies.loc["marginal", "filter_decision"] == "WATCHLIST"
    assert "Holm" in strategies.loc["marginal", "filter_reason"]
    assert summary["execution_attempted"] is False
    assert summary["profile_allowed_for_demo_live"] is False

"""KEEP in the edge selectors needs a Holm-adjusted one-sided t-test of mean R.

Decision: docs/decisions/2026-10-22-deflated-promotion-gate.md. The old KEEP
rule (PF > 1.10 on 30 trades) is still required; a row that passes it but whose
Holm-adjusted p-value, across every row evaluated in the same call, exceeds
0.05 becomes WATCHLIST with an explicit reason. COUNTS_ONLY rows keep their
decision. Research only: no row decision enables any execution.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.edge_evaluation import (
    load_edge_metrics,
    run_edge_evaluation,
    select_strategies,
    select_symbols,
)
from agi_style_forex_bot_mt5.edge_evaluation.significance import (
    SIGNIFICANCE_ALPHA,
    mean_r_significance,
    student_t_sf,
)


@pytest.mark.parametrize(
    ("t_value", "df", "expected"),
    [
        (0.0, 10, 0.5),
        (1.0, 1, 0.25),
        (1.6973, 30, 0.05),
        (2.0423, 30, 0.025),
        (2.4573, 30, 0.01),
        (3.1693, 10, 0.005),
        (1.6449, 1_000_000, 0.05),
        (-2.0423, 30, 0.975),
    ],
)
def test_student_t_upper_tail_matches_reference_tables(t_value: float, df: float, expected: float) -> None:
    assert student_t_sf(t_value, df) == pytest.approx(expected, abs=2e-5)


def test_row_p_value_is_the_one_sided_upper_tail() -> None:
    # 31 trades, t = 2.0423 with 30 degrees of freedom: one-sided p = 0.025
    # (a two-sided test would report 0.05); a negative mean gives p = 0.975.
    std = 0.2 * np.sqrt(31) / 2.0423
    frame = pd.DataFrame(
        [
            {"strategy_name": "up", "total_trades": 31, "expectancy_r": 0.2, "r_multiple_std": std},
            {"strategy_name": "down", "total_trades": 31, "expectancy_r": -0.2, "r_multiple_std": std},
        ]
    )

    up, down = mean_r_significance(frame)

    assert up["mean_r_t_stat"] == pytest.approx(2.0423)
    assert up["mean_r_p_value"] == pytest.approx(0.025, abs=2e-5)
    assert down["mean_r_p_value"] == pytest.approx(0.975, abs=2e-5)
    # Holm over the two rows: the smaller p is doubled, the larger kept.
    assert up["holm_adjusted_p_value"] == pytest.approx(0.05, abs=4e-5)
    assert down["holm_adjusted_p_value"] == pytest.approx(0.975, abs=2e-5)


def test_student_t_upper_tail_rejects_bad_inputs() -> None:
    for t_value, df in ((float("nan"), 10), (1.0, 0), (1.0, float("nan"))):
        with pytest.raises(ValueError):
            student_t_sf(t_value, df)


def _row(name: str, *, trades: int, mean_r: float, std_r: float | None, pf: float, winrate: float = 50.0, column: str = "strategy_name") -> dict:
    row = {column: name, "total_trades": trades, "expectancy_r": mean_r, "profit_factor": pf, "winrate": winrate}
    if std_r is not None:
        row["r_multiple_std"] = std_r
    return row


def _std_for_p(mean_r: float, trades: int, t_value: float) -> float:
    return mean_r * np.sqrt(trades) / t_value


def test_old_keep_without_dispersion_becomes_watchlist() -> None:
    frame = pd.DataFrame([_row("trend_pullback", trades=40, mean_r=0.2, std_r=None, pf=1.3)])

    selected = select_strategies(frame)

    row = selected.iloc[0]
    assert row["decision"] == "WATCHLIST"
    assert "not significant" in row["reasons"]
    assert row["holm_adjusted_p_value"] == 1.0
    assert row["significance_status"] == "UNAVAILABLE_NO_DISPERSION"


def test_keep_requires_holm_adjusted_significance_across_the_call() -> None:
    # One-sided p of about 0.02 on its own...
    strong = _row("trend_pullback", trades=40, mean_r=0.2, std_r=_std_for_p(0.2, 40, 2.12), pf=1.3)
    alone = select_strategies(pd.DataFrame([strong]))
    assert alone["decision"].iloc[0] == "KEEP"
    assert alone["holm_adjusted_p_value"].iloc[0] == pytest.approx(alone["mean_r_p_value"].iloc[0])
    assert alone["holm_adjusted_p_value"].iloc[0] <= SIGNIFICANCE_ALPHA

    # ...but not once four more strategies were evaluated in the same call.
    others = [_row(f"other_{index}", trades=40, mean_r=-0.05, std_r=1.0, pf=0.9) for index in range(4)]
    together = select_strategies(pd.DataFrame([strong, *others]))
    row = together.loc[together["strategy_name"] == "trend_pullback"].iloc[0]
    assert row["decision"] == "WATCHLIST"
    assert row["holm_family_size"] == 5
    assert row["holm_adjusted_p_value"] > SIGNIFICANCE_ALPHA
    assert "Holm" in row["reasons"]


def test_symbol_selector_applies_the_same_rule() -> None:
    strong = _row("EURUSD", trades=40, mean_r=0.2, std_r=_std_for_p(0.2, 40, 2.12), pf=1.3, column="symbol")
    others = [_row(name, trades=40, mean_r=-0.05, std_r=1.0, pf=0.9, column="symbol") for name in ("GBPUSD", "USDJPY", "AUDUSD", "USDCAD")]

    alone = select_symbols(pd.DataFrame([strong]))
    together = select_symbols(pd.DataFrame([strong, *others]))

    assert alone["decision"].iloc[0] == "KEEP"
    row = together.loc[together["symbol"] == "EURUSD"].iloc[0]
    assert row["decision"] == "WATCHLIST"
    assert "Holm" in row["reasons"]
    assert "holm_adjusted_p_value" in together.columns


def test_counts_only_rows_keep_their_decision_and_count_in_the_family() -> None:
    strong = _row("trend_pullback", trades=40, mean_r=0.2, std_r=_std_for_p(0.2, 40, 2.12), pf=1.3)
    counts = [{"strategy_name": f"counted_{index}", "total_trades": 50, "metrics_status": "COUNTS_ONLY"} for index in range(4)]

    selected = select_strategies(pd.DataFrame([strong, *counts]))

    counted = selected.loc[selected["metrics_status"] == "COUNTS_ONLY"]
    assert set(counted["decision"]) == {"WATCHLIST_COUNTS_ONLY"}
    assert set(counted["reasons"]) == {"strategy has trade count but no profit/expectancy metrics"}
    assert set(counted["significance_status"]) == {"UNAVAILABLE_COUNTS_ONLY"}
    assert selected.loc[selected["strategy_name"] == "trend_pullback", "decision"].iloc[0] == "WATCHLIST"
    assert set(selected["holm_family_size"]) == {5}


def test_empty_frames_report_the_adjusted_p_value_column() -> None:
    assert "holm_adjusted_p_value" in select_strategies(pd.DataFrame()).columns
    assert "holm_adjusted_p_value" in select_symbols(pd.DataFrame()).columns


def test_non_keep_decisions_are_unchanged() -> None:
    frame = pd.DataFrame(
        [
            _row("near", trades=25, mean_r=0.0, std_r=1.0, pf=1.0),
            _row("bad", trades=40, mean_r=-0.05, std_r=1.0, pf=0.92),
            _row("tiny", trades=10, mean_r=0.5, std_r=1.0, pf=2.0),
        ]
    )

    selected = select_strategies(frame).set_index("strategy_name")

    assert selected.loc["near", "decision"] == "WATCHLIST"
    assert selected.loc["bad", "decision"] == "DISABLE_IN_BALANCED"
    assert selected.loc["tiny", "decision"] == "RESEARCH_ONLY"


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
            }
        )
    return rows


def _old_keep(row: dict) -> bool:
    return row["total_trades"] >= 30 and row["expectancy_r"] > 0 and row["profit_factor"] > 1.10


@pytest.mark.parametrize(("selector", "column"), [(select_strategies, "strategy_name"), (select_symbols, "symbol")])
def test_zero_edge_slices_rarely_reach_keep(selector, column: str) -> None:
    universes, slices = 200, 20
    universes_with_keep = old_keep_rows = new_keep_rows = 0
    for seed in range(universes):
        rows = _zero_edge_rows(np.random.default_rng(3000 + seed), slices, column)
        selected = selector(pd.DataFrame(rows))
        keeps = int((selected["decision"] == "KEEP").sum())
        universes_with_keep += keeps > 0
        new_keep_rows += keeps
        old_keep_rows += sum(_old_keep(row) for row in rows)

    # Family-wise: at most 5% of universes show any KEEP at all.
    assert universes_with_keep / universes <= 0.05
    # The old rule labels a large share of zero-edge slices KEEP.
    assert old_keep_rows / (universes * slices) >= 0.15
    assert new_keep_rows < old_keep_rows / 20


def test_planted_edge_among_zero_edge_slices_stays_keep() -> None:
    rng = np.random.default_rng(4242)
    rows = _zero_edge_rows(rng, 19, "strategy_name")
    values = np.where(rng.random(200) < 0.56, 1.5, -1.0)  # expectancy 0.4 R
    rows.append(
        {
            "strategy_name": "planted",
            "total_trades": 200,
            "expectancy_r": float(values.mean()),
            "r_multiple_std": float(values.std(ddof=1)),
            "profit_factor": float(values[values > 0].sum() / -values[values < 0].sum()),
            "winrate": float((values > 0).mean() * 100.0),
        }
    )

    selected = select_strategies(pd.DataFrame(rows)).set_index("strategy_name")

    assert selected.loc["planted", "decision"] == "KEEP"
    assert selected.loc["planted", "holm_adjusted_p_value"] <= SIGNIFICANCE_ALPHA


def test_significance_rows_align_with_the_frame() -> None:
    frame = pd.DataFrame(
        [
            _row("a", trades=40, mean_r=0.3, std_r=1.0, pf=1.4),
            {"strategy_name": "b", "total_trades": 40, "metrics_status": "COUNTS_ONLY"},
            _row("c", trades=2, mean_r=0.3, std_r=1.0, pf=1.4),
            _row("d", trades=40, mean_r=0.3, std_r=0.0, pf=1.4),
        ],
        index=[7, 7, 3, 1],
    )

    rows = mean_r_significance(frame)

    assert [row["significance_status"] for row in rows] == [
        "COMPUTED",
        "UNAVAILABLE_COUNTS_ONLY",
        "UNAVAILABLE_SMALL_SAMPLE",
        "UNAVAILABLE_ZERO_DISPERSION",
    ]
    assert rows[0]["holm_adjusted_p_value"] == pytest.approx(min(1.0, 4 * rows[0]["mean_r_p_value"]))
    assert all(row["holm_family_size"] == 4 for row in rows)


def _make_run(root: Path, trades: pd.DataFrame) -> Path:
    run = root / "20260101-000000-real-data-research"
    reports = run / "reports" / "backtests"
    reports.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    trades.to_csv(reports / "trades.csv", index=False)
    (reports / "summary.json").write_text(json.dumps({"total_trades": len(trades)}), encoding="utf-8")
    return run


def _trades_frame() -> pd.DataFrame:
    rows = []
    for index in range(60):
        r_multiple = 1.2 if index % 2 == 0 else -0.5
        rows.append(
            {
                "signal_id": f"s{index}",
                "symbol": "EURUSD" if index % 3 else "GBPUSD",
                "strategy_name": "strategy_ensemble",
                "session": "LONDON",
                "regime": "TREND_UP",
                "entry_time": f"2024-01-01T00:{index % 60:02d}:00Z",
                "exit_time": f"2024-01-01T01:{index % 60:02d}:00Z",
                "profit": r_multiple * 10.0,
                "r_multiple": r_multiple,
                "duration_seconds": 3600,
            }
        )
    return pd.DataFrame(rows)


def test_edge_metrics_report_r_dispersion(tmp_path: Path) -> None:
    trades = _trades_frame()
    _make_run(tmp_path, trades)

    bundle = load_edge_metrics(runs_root=tmp_path)

    by_strategy = bundle.by_strategy.set_index("strategy_name")
    assert by_strategy.loc["strategy_ensemble", "r_multiple_std"] == pytest.approx(trades["r_multiple"].std(ddof=1))
    by_symbol = bundle.by_symbol.set_index("symbol")
    eurusd = trades.loc[trades["symbol"] == "EURUSD", "r_multiple"]
    assert by_symbol.loc["EURUSD", "r_multiple_std"] == pytest.approx(eurusd.std(ddof=1))


def test_edge_report_writes_the_adjusted_p_value(tmp_path: Path) -> None:
    _make_run(tmp_path, _trades_frame())

    summary = run_edge_evaluation(runs_root=tmp_path, output_dir=tmp_path / "edge")

    for name in ("by_symbol.csv", "by_strategy.csv"):
        frame = pd.read_csv(tmp_path / "edge" / name)
        assert "holm_adjusted_p_value" in frame.columns
        assert "significance_status" in frame.columns
    # A clearly positive, significant strategy is still kept end to end.
    assert summary["strategies_keep"] == ["strategy_ensemble"]
    assert summary["execution_attempted"] is False

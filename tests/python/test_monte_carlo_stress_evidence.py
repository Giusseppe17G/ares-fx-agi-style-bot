"""Independent sequence/cost oracles; no market data or strategy optimization."""

from dataclasses import asdict, replace
import json

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting.monte_carlo import (
    MonteCarloSimulator, run_monte_carlo_report, shuffled_metrics, sequence_metrics,
)
from agi_style_forex_bot_mt5.backtesting.stress_tester import StressTester, run_stress_report
from test_backtesting import _trade


def chronological_trades(profits=(-100.0, 200.0, -100.0, -100.0, 200.0)):
    return [replace(
        _trade(profit, signal_id=str(index)),
        entry_time=f"2026-01-{index + 1:02d}T00:00:00Z",
        exit_time=f"2026-01-{index + 1:02d}T01:00:00Z",
    ) for index, profit in enumerate(profits)]


def test_shuffle_preserves_synthetic_order_instead_of_sorting_historical_dates():
    source = chronological_trades()
    metrics = shuffled_metrics(source, seed=1, initial_balance=1000)
    # PCG64 seed1 permutes [4, 0, 1, 2, 3]: 1000,1200,1100,1300,1200,1100.
    assert metrics.max_drawdown_pct == pytest.approx(-200 / 1300 * 100)
    assert metrics.sequence_axis == "SYNTHETIC_TRADE_INDEX"
    assert metrics.source_indices == (4, 0, 1, 2, 3)
    assert metrics.equity_sequence == (1000, 1200, 1100, 1300, 1200, 1100)
    assert metrics.worst_month_return_pct is None
    assert metrics.sharpe is None
    assert metrics.monthly_returns == {}


@pytest.mark.parametrize("kwargs", [
    {"initial_balance": 0}, {"initial_balance": -1}, {"initial_balance": True},
    {"initial_balance": float("nan")}, {"initial_balance": float("inf")},
    {"ruin_threshold_pct": 0}, {"ruin_threshold_pct": -1},
    {"ruin_threshold_pct": 101}, {"ruin_threshold_pct": True},
    {"ruin_threshold_pct": float("nan")}, {"ruin_threshold_pct": float("inf")},
    {"iterations": True}, {"iterations": 1.5}, {"iterations": 0},
])
def test_monte_carlo_rejects_invalid_config_before_simulation(kwargs):
    with pytest.raises(ValueError):
        MonteCarloSimulator().run([10, -5], **({"iterations": 2} | kwargs))


@pytest.mark.parametrize("seed", [True, -1, 1.5, float("nan"), None])
def test_monte_carlo_requires_reproducible_integer_seed(seed):
    with pytest.raises(ValueError):
        MonteCarloSimulator(seed=seed).run([1, -1], iterations=2)


@pytest.mark.parametrize("profit", [True, float("nan"), float("inf"), -float("inf"), "10"])
def test_monte_carlo_rejects_invalid_pnl(profit):
    with pytest.raises(ValueError):
        MonteCarloSimulator().run([{"profit": profit}], iterations=2)


def test_monte_carlo_rejects_numeric_overflow():
    with pytest.raises(ValueError):
        MonteCarloSimulator().run([1e308, 1e308], iterations=2)


def test_artificial_loss_streak_appends_to_synthetic_sequence():
    rows = StressTester(initial_balance=1000).comprehensive(chronological_trades())
    result = next(r for r in rows if r.scenario == "artificial_loss_streak" and r.parameters["losses_added"] == 3)
    # Last original equity1100/peak1100, then1000,900,800 (not inserted on Jan1).
    assert result.metrics.max_drawdown_pct == pytest.approx(-300 / 1100 * 100)
    assert result.metrics.max_consecutive_losses == 3
    assert result.metrics.sequence_axis == "SYNTHETIC_TRADE_INDEX"
    assert result.metrics.monthly_returns == {}


def test_operational_scenarios_are_unmodeled_not_fake_executed_checks():
    rows = StressTester().comprehensive(chronological_trades())
    for name in ("entry_delay_one_bar", "session_shift", "fill_rate", "missing_bars"):
        result = next(r for r in rows if r.scenario == name)
        assert result.status == "NOT_MODELED"
        assert result.metrics is None
        assert result.evidence_scope == "REQUIRES_EXPLICIT_QUOTE_REPLAY"
    haircut = next(r for r in rows if r.scenario == "fixed_profit_haircut")
    assert haircut.status == "COMPLETED"
    assert haircut.metrics.net_profit == 65
    assert haircut.evidence_scope == "POST_TRADE_APPROXIMATION"


def test_removing_one_trade_counts_occurrences_not_object_identity():
    best = _trade(100)
    result = StressTester().remove_best_trades([best, best, _trade(-10)], counts=(1,))[0]
    assert result.metrics.trades_total == 2
    assert result.metrics.net_profit == 90


def test_cost_grid_accepts_generators_without_dropping_scenarios():
    results = StressTester().spread_slippage_sensitivity(
        [_trade(10)], spread_multipliers=iter([1, 2]), extra_slippage_points=iter([0, 1]),
    )
    assert len(results) == 4


@pytest.mark.parametrize("field,value", [
    ("commission", float("nan")), ("commission", -1), ("lot", 0),
    ("point", float("inf")), ("tick_size", 0), ("tick_value", -1),
    ("spread_points", float("nan")), ("slippage_points", True),
    ("profit", float("inf")), ("r_multiple", float("nan")),
])
def test_stress_rejects_invalid_inputs(field, value):
    with pytest.raises(ValueError):
        StressTester().comprehensive([replace(_trade(10), **{field: value})])


def test_commission_and_haircut_recompute_r_from_original_risk():
    trade = replace(_trade(100), commission=10, r_multiple=2)
    rows = StressTester().comprehensive([trade])
    commission = next(r for r in rows if r.scenario == "commission_multiplier" and r.parameters["commission_multiplier"] == 2)
    haircut = next(r for r in rows if r.scenario == "fixed_profit_haircut")
    assert commission.metrics.average_r == pytest.approx(90 / 50)
    assert haircut.metrics.average_r == pytest.approx(95 / 50)


def test_report_config_inputs_and_ruin_threshold_are_reproducible(tmp_path):
    kwargs = dict(trades=[100, -50, 80, -30], seed=3, iterations=10, initial_balance=200, ruin_threshold_pct=25)
    a = run_monte_carlo_report(report_dir=tmp_path / "a", **kwargs)
    b = run_monte_carlo_report(report_dir=tmp_path / "b", **kwargs)
    changed = run_monte_carlo_report(report_dir=tmp_path / "c", **(kwargs | {"ruin_threshold_pct": 30}))
    assert a["effective_config"]["ruin_threshold_pct"] == 25
    assert a["result"]["ruin_threshold_pct"] == 25
    assert a["run_manifest"] == b["run_manifest"]
    assert a["run_manifest"]["run_id"] != changed["run_manifest"]["run_id"]
    assert a["upstream_provenance_status"] == "UNKNOWN"
    assert a["operational_scenarios_tested"] is False
    assert a["promotion_eligible"] is False
    assert a["order_send_called"] is False
    assert json.loads((tmp_path / "a" / "inputs.json").read_text())["profits"] == kwargs["trades"]
    assert (tmp_path / "a" / "simulations.csv").read_bytes() == (tmp_path / "b" / "simulations.csv").read_bytes()


def test_stress_report_distinguishes_completion_from_unsupported(tmp_path):
    report = run_stress_report(trades=chronological_trades(), report_dir=tmp_path)
    rows = pd.read_csv(tmp_path / "scenarios.csv")
    unsupported = rows.loc[rows.status == "NOT_MODELED"]
    assert set(unsupported.scenario) == {"entry_delay_one_bar", "session_shift", "fill_rate", "missing_bars"}
    assert unsupported.net_profit.isna().all()
    assert report["completed_scenario_count"] + report["not_modeled_scenario_count"] == report["scenario_count"]
    assert report["operational_scenarios_tested"] is False
    assert report["promotion_eligible"] is False
    assert report["run_manifest"]["dataset_hash"]


@pytest.mark.parametrize("method", ["permutation", "bootstrap"])
def test_sampling_uses_actual_permuted_or_resampled_sequence(method):
    profits = [40.0, -20.0, -30.0]
    result = MonteCarloSimulator(seed=8).run(profits, method=method, iterations=8, initial_balance=100)
    rng = np.random.default_rng(8)
    for row in result.simulations:
        sampled = rng.permutation(profits) if method == "permutation" else rng.choice(profits, size=3, replace=True)
        capital = peak = 100
        worst = 0
        for profit in sampled:
            capital += profit
            peak = max(peak, capital)
            worst = min(worst, 100 * (capital / peak - 1))
        assert row["final_equity"] == capital
        assert row["max_drawdown_pct"] == pytest.approx(worst)
    if method == "permutation":
        assert {row["final_equity"] for row in result.simulations} == {90}
    else:
        assert len({row["final_equity"] for row in result.simulations}) > 1


def test_ruin_compatibility_field_means_peak_drawdown_not_insolvency():
    hit = MonteCarloSimulator().run([-30], initial_balance=100, iterations=2, ruin_threshold_pct=30)
    miss = MonteCarloSimulator().run([-30], initial_balance=100, iterations=2, ruin_threshold_pct=31)
    assert hit.risk_of_ruin_pct == 100
    assert miss.risk_of_ruin_pct == 0
    assert hit.final_equity_percentiles["p5"] == 70  # Solvent in every path.
    assert hit.ruin_event == "MAX_PEAK_DRAWDOWN_AT_LEAST_THRESHOLD"


def test_sequence_metrics_baseline_drawdown_recovery_and_unknown_r():
    metrics = sequence_metrics([100, -40, -30], initial_balance=100)
    assert metrics.equity_sequence == (100, 200, 160, 130)
    assert metrics.max_drawdown_pct == -35
    assert metrics.recovery_factor == pytest.approx(30 / 70)
    assert metrics.average_r is None
    assert sequence_metrics([-10], initial_balance=100).max_drawdown_pct == -10


def test_stress_cost_units_and_round_trip_are_not_double_counted():
    trade = replace(_trade(100), lot=0.2, spread_points=10, slippage_points=1,
        point=0.00001, tick_size=0.00005, tick_value=2, r_multiple=2)
    result = StressTester().spread_slippage_sensitivity([trade], spread_multipliers=(2,), extra_slippage_points=(3,))[0]
    # Additional10 spreadpoints once +3 slip eachside =>16points*point/tick*value*lot=1.28.
    assert result.metrics.net_profit == pytest.approx(98.72)
    assert result.metrics.average_r == pytest.approx(98.72 / 50)


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), -1])
def test_cost_grid_rejects_invalid_values(invalid):
    with pytest.raises(ValueError):
        StressTester().spread_slippage_sensitivity([_trade(10)], spread_multipliers=(invalid,))
    with pytest.raises(ValueError):
        StressTester().spread_slippage_sensitivity([_trade(10)], extra_slippage_points=(invalid,))


@pytest.mark.parametrize("invalid", [True, 1.5, -1])
def test_remove_counts_reject_ambiguous_values(invalid):
    with pytest.raises(ValueError):
        StressTester().remove_best_trades([_trade(10)], counts=(invalid,))


@pytest.mark.parametrize("timestamp", ["invalid", "2026-01-01", pd.NaT, None])
def test_stress_rejects_ambiguous_calendar_data(timestamp):
    with pytest.raises(ValueError):
        StressTester().comprehensive([replace(_trade(10), exit_time=timestamp)])


def test_stress_empty_data_does_not_count_checks_or_invent_losses(tmp_path):
    empty = run_stress_report(trades=[], report_dir=tmp_path / "empty")
    assert empty["completed_scenario_count"] == 0
    assert empty["classification"] == "REJECTED"
    zero = run_stress_report(trades=[_trade(0)], report_dir=tmp_path / "zero")
    assert zero["insufficient_input_scenario_count"] == 3
    details = json.loads((tmp_path / "zero" / "scenarios.json").read_text())
    streaks = [row for row in details if row["scenario"] == "artificial_loss_streak"]
    assert all(row["metrics"] is None and row["parameters"]["losses_added"] == 0 for row in streaks)


def test_stress_inputs_replay_without_private_metadata_and_hash_costs(tmp_path):
    source = [replace(trade, metadata={"token": "do-not-export"}) for trade in chronological_trades()]
    a = run_stress_report(trades=source, report_dir=tmp_path / "a")
    inputs = json.loads((tmp_path / "a" / "inputs.json").read_text())
    b = run_stress_report(trades=inputs["trades"], report_dir=tmp_path / "b")
    changed = [replace(trade, commission=1) for trade in source]
    c = run_stress_report(trades=changed, report_dir=tmp_path / "c")
    assert a["run_manifest"] == b["run_manifest"]
    assert a["run_manifest"]["dataset_hash"] != c["run_manifest"]["dataset_hash"]
    assert (tmp_path / "a" / "scenarios.csv").read_bytes() == (tmp_path / "b" / "scenarios.csv").read_bytes()
    assert "do-not-export" not in (tmp_path / "a" / "inputs.json").read_text()


def test_monte_carlo_file_and_selected_inputs_are_distinct_provenance(tmp_path):
    path = tmp_path / "source.csv"
    pd.DataFrame({"profit": [999]}).to_csv(path, index=False)
    a = run_monte_carlo_report(trades=[1, -1], trades_path=path, report_dir=tmp_path / "a", iterations=2)
    inputs = json.loads((tmp_path / "a" / "inputs.json").read_text())
    assert inputs["profits"] == [1, -1]
    assert len(inputs["source_file_sha256"]) == 64
    assert a["effective_config"]["input_selection"] == "SUPPLIED_TRADES"
    assert a["upstream_provenance_status"] == "UNKNOWN"


def test_stress_does_not_mutate_original_trade_records():
    source = chronological_trades()
    before = [asdict(trade) for trade in source]
    StressTester().comprehensive(source)
    assert [asdict(trade) for trade in source] == before


def test_artificial_loss_ignores_zero_when_nonzero_magnitude_is_available():
    rows = StressTester(initial_balance=1000).comprehensive(chronological_trades((0, 100)))
    streak = next(row for row in rows if row.scenario == "artificial_loss_streak" and row.parameters["losses_added"] == 3)
    assert streak.status == "COMPLETED"
    assert streak.metrics.profit_sequence == (0, 100, -100, -100, -100)
    assert streak.metrics.max_consecutive_losses == 3

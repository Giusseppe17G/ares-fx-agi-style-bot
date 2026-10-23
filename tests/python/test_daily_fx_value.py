"""Cross-sectional real-value signal, equal-risk sizing and the v2 study protocol on synthetic data only."""
from dataclasses import replace
import json
import math

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.research.daily_fx import runner
from agi_style_forex_bot_mt5.research.daily_fx.data import PricePanel, load_fred_daily, load_worldbank_inflation
from agi_style_forex_bot_mt5.research.daily_fx.plans import (REAL_VALUE_CURRENCIES, REAL_VALUE_PRICE_START,
    real_value_v2)
from agi_style_forex_bot_mt5.research.daily_fx.portfolio import (CostModel, PortfolioConfig, RiskLimits, backtest,
    currency_permutation, inflation_differentials, target_weights, xsvalue_signal)
from agi_style_forex_bot_mt5.research.daily_fx.study import (Acceptance, DataBinding, Hypothesis, StudyPlan,
    run_development, run_holdout)
from agi_style_forex_bot_mt5.research.edge_statistics import expected_max_sharpe
from agi_style_forex_bot_mt5.research.trial_registry import TrialLedger

CURRENCIES = ("AUD", "CAD", "CHF", "DKK", "GBP", "JPY", "NOK", "NZD", "SEK")
DIGEST = "a" * 64
INFLATION_DIGEST = "e" * 64
ZERO = CostModel({code: 0.0 for code in CURRENCIES})
FAST = PortfolioConfig(signal="xsvalue", lookbacks=(200,), average_rows=40, inflation_years=1, xs_top=3,
                       sizing="equal_risk", rebalance_days=10)
EASY = Acceptance(max_currency_share=1.0, max_development_drawdown=0.5, max_holdout_drawdown=0.5)


def _inflation(first=1990, last=2030, values=None):
    years = range(first, last + 1)
    values = values or {}
    return pd.DataFrame({code: [values.get(code, 0.0)] * len(years) for code in ("USD", *CURRENCIES)},
                        index=pd.Index(list(years)))


def _drifting(drifts, days=600, vol=0.0, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2001-01-01", periods=days, tz="UTC")
    steps = np.asarray(drifts, dtype=float) + rng.normal(0.0, vol, size=(days, len(CURRENCIES)))
    return pd.DataFrame(np.exp(np.cumsum(steps, axis=0)), index=index, columns=list(CURRENCIES))


def _mean_reverting(days=3000, speed=0.01, vol=0.006, seed=0):
    # Real exchange rates pulled back to a constant level: cheap currencies tend to rise.
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, vol, size=(days, len(CURRENCIES)))
    level = np.zeros((days, len(CURRENCIES)))
    for t in range(1, days):
        level[t] = level[t - 1] * (1.0 - speed) + noise[t]
    index = pd.bdate_range("2000-01-03", periods=days, tz="UTC")
    return PricePanel(pd.DataFrame(np.exp(level), index=index, columns=list(CURRENCIES)), "synthetic", DIGEST)


def _plan(**overrides):
    hypothesis = Hypothesis("H1_VALUE", "synthetic value", FAST,
                            subperiods=(("2001-07-01", "2004-12-31"), ("2005-01-01", "2008-12-31")))
    values = dict(name="synthetic_value", currencies=CURRENCIES, development=("2001-07-01", "2008-12-31"),
                  holdout=("2009-01-01", "2011-06-30"), hypotheses=(hypothesis,), costs=ZERO,
                  data=DataBinding("synthetic", DIGEST, inflation_sha256=INFLATION_DIGEST), random_replicas=19,
                  spa_bootstraps=200, acceptance=EASY)
    values.update(overrides)
    return StudyPlan(**values)


def _develop(plan, panel, ledger):
    return run_development(plan, panel, None, None, ledger, inflation=_inflation(),
                           inflation_sha256=INFLATION_DIGEST)


def _inflation_csv(path, overrides=None):
    rows = ["Country,Country Code,Year,CPI"]
    anchors = {("USA", 1974): 11.05, ("USA", 1980): 13.55, ("USA", 2009): -0.36, ("USA", 2022): 8.0,
               ("JPN", 1974): 23.22}
    anchors.update(overrides or {})
    for iso in ("USA", "AUS", "CAN", "CHE", "DNK", "GBR", "JPN", "NOR", "NZL", "SWE", "ABW"):
        for year in range(1970, 2025):
            if (iso, year) in anchors and anchors[(iso, year)] is None:
                continue
            rows.append(f"Name,{iso},{year},{anchors.get((iso, year), 2.0)}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_inflation_loader_reads_annual_percent_and_checks_anchor_values(tmp_path):
    table, digest = load_worldbank_inflation(_inflation_csv(tmp_path / "cpi.csv"), CURRENCIES)
    assert list(table.columns) == ["USD", *CURRENCIES] and len(digest) == 64
    assert table.index[0] == 1970 and table.index[-1] == 2024 and table.at[1974, "USD"] == pytest.approx(11.05)
    # A CPI index (US 1974 near 49) or the GDP deflator (US 1974 = 9.0) is not annual CPI inflation.
    for wrong in ({("USA", 1974): 49.3}, {("USA", 1974): 9.0}, {("JPN", 1974): None}):
        with pytest.raises(ValueError, match="anchor"):
            load_worldbank_inflation(_inflation_csv(tmp_path / "bad.csv", wrong), CURRENCIES)
    with pytest.raises(ValueError, match="missing years"):
        load_worldbank_inflation(_inflation_csv(tmp_path / "gap.csv", {("SWE", 1990): None}), CURRENCIES)
    with pytest.raises(ValueError, match="no inflation"):
        load_worldbank_inflation(_inflation_csv(tmp_path / "cpi.csv"), ("EUR",))


def test_inflation_of_a_year_is_used_from_july_of_the_next_year_only():
    days = pd.DatetimeIndex(["2025-06-30", "2025-07-01", "2026-06-30", "2026-07-01"], tz="UTC")
    table = _inflation(2015, 2024, {"JPY": 3.0})
    gap = inflation_differentials(table, days, CURRENCIES, years=5)
    expected = 5 * math.log(1.03)
    # 2025-06-30 uses 2019-2023, 2025-07-01 and 2026-06-30 use 2020-2024, 2026-07-01 would need 2025.
    assert gap["JPY"].iloc[:3].tolist() == pytest.approx([expected] * 3)
    assert gap.iloc[3].isna().all() and gap["CHF"].iloc[0] == 0.0
    later = table.copy()
    later.loc[2024, "JPY"] = 50.0
    changed = inflation_differentials(later, days, CURRENCIES, years=5)
    assert changed["JPY"].iloc[0] == gap["JPY"].iloc[0] and changed["JPY"].iloc[1] != gap["JPY"].iloc[1]
    with pytest.raises(ValueError, match="no inflation"):
        inflation_differentials(table.drop(columns="USD"), days, CURRENCIES, years=5)


def test_value_buys_real_depreciation_and_sells_real_appreciation():
    # Distinct drifts: falling currencies are cheap. USD's score is zero and ranks fifth here.
    prices = _drifting([-4e-4, -3e-4, -2e-4, -1e-4, 1e-4, 2e-4, 3e-4, 4e-4, 5e-4])
    gap = inflation_differentials(_inflation(), prices.index, CURRENCIES, years=1)
    signal = xsvalue_signal(np.log(prices), gap, lookback=200, average_rows=40, top=3)
    # The oldest row averaged is 200 rows back, so the first complete signal is on row 200.
    assert signal.iloc[:200].isna().all().all() and signal.iloc[200:].notna().all().all()
    assert signal.iloc[-1].tolist() == [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, -1.0, -1.0, -1.0]
    # High inflation with a flat price is a real appreciation: expensive, so sold.
    flat = _drifting([0.0] * 9)
    hot = inflation_differentials(_inflation(values={"AUD": 30.0, "SEK": -20.0, "NZD": 10.0, "NOK": 5.0,
                                                     "JPY": -10.0, "GBP": -5.0}),
                                  flat.index, CURRENCIES, years=1)
    signal = xsvalue_signal(np.log(flat), hot, lookback=200, average_rows=40, top=3)
    assert signal.iloc[-1].to_dict() == {"AUD": -1.0, "CAD": 0.0, "CHF": 0.0, "DKK": 0.0, "GBP": 1.0, "JPY": 1.0,
                                         "NOK": -1.0, "NZD": -1.0, "SEK": 1.0}


def test_usd_is_ranked_and_ties_break_by_iso_code():
    # Every currency appreciated: USD (score 0) is the cheapest, so only two currencies are bought.
    prices = _drifting([4e-4, 3e-4, 2e-4, 1e-4, 1e-4, 2e-4, 3e-4, 4e-4, 5e-4])
    gap = inflation_differentials(_inflation(), prices.index, CURRENCIES, years=1)
    row = xsvalue_signal(np.log(prices), gap, lookback=200, average_rows=40, top=3).iloc[-1]
    assert row[row > 0].index.tolist() == ["DKK", "GBP"] and row[row < 0].index.tolist() == ["AUD", "NZD", "SEK"]
    # All scores equal: the alphabetical order decides (AUD, CAD first; USD last), never at random.
    flat = _drifting([0.0] * 9)
    tied = xsvalue_signal(np.log(flat), inflation_differentials(_inflation(), flat.index, CURRENCIES, 1),
                          lookback=200, average_rows=40, top=3).iloc[-1]
    assert tied[tied > 0].index.tolist() == ["AUD", "CAD", "CHF"]
    assert tied[tied < 0].index.tolist() == ["NZD", "SEK"]


def test_value_signal_ignores_future_prices_and_unpublished_inflation():
    prices = _drifting([0.0] * 9, vol=0.006, seed=4)
    cut = 450
    altered = prices.copy()
    altered.iloc[cut + 1:] *= 1.3
    table = _inflation(values={"CHF": 1.0})
    later = table.copy()
    later.loc[2003:, "CHF"] = 40.0  # 2003 is first used on 2004-07-01, after the cut
    assert prices.index[cut] < pd.Timestamp("2004-07-01", tz="UTC")
    first = xsvalue_signal(np.log(prices), inflation_differentials(table, prices.index, CURRENCIES, 1), 200, 40, 3)
    second = xsvalue_signal(np.log(altered), inflation_differentials(later, prices.index, CURRENCIES, 1), 200, 40, 3)
    pd.testing.assert_frame_equal(first.iloc[:cut + 1], second.iloc[:cut + 1])


def test_permuted_control_moves_the_same_ranking_to_other_currencies():
    prices = _drifting([0.0] * 9, vol=0.006, seed=5)
    gap = inflation_differentials(_inflation(), prices.index, CURRENCIES, years=1)
    order = currency_permutation(10, seed=3)
    assert sorted(order) == list(range(10)) and order != tuple(range(10))
    assert order == currency_permutation(10, seed=3)
    assert all(currency_permutation(10, seed) != tuple(range(10)) for seed in range(200))
    base = xsvalue_signal(np.log(prices), gap, 200, 40, 3).iloc[200:]
    moved = xsvalue_signal(np.log(prices), gap, 200, 40, 3, permutation=order).iloc[200:]
    labels = sorted((*CURRENCIES, "USD"))
    full = base.assign(USD=-(base.sum(axis=1)))[labels]  # USD's own membership: the books are balanced
    moved_full = moved.assign(USD=-(moved.sum(axis=1)))[labels]
    for source, target in enumerate(order):
        np.testing.assert_array_equal(moved_full[labels[target]].to_numpy(), full[labels[source]].to_numpy())


def test_equal_risk_sizing_puts_each_position_at_the_risk_cap():
    prices = _drifting([0.0] * 9, days=900, vol=0.006, seed=6)
    inflation = _inflation()
    limits = RiskLimits()
    result = backtest(prices, FAST, ZERO, limits, inflation=inflation)
    _, vol = target_weights(prices, FAST, inflation_gap=inflation_differentials(inflation, prices.index,
                                                                                CURRENCIES, 1))
    # The first complete signal is on row 200; rebalances execute one row later, every 10 rows.
    rebalances = prices.index[201::10]
    assert len(rebalances) > 60 and (result.turnover.loc[rebalances] > 0).all()
    for day in rebalances:
        decision = prices.index[prices.index.get_loc(day) - 1]
        stop = limits.stop_sigmas * vol.loc[decision].to_numpy() * math.sqrt(10 / 252)
        weights = result.positions.loc[day].to_numpy()
        live = weights != 0
        assert 5 <= live.sum() <= 6
        np.testing.assert_allclose(np.abs(weights[live]) * stop[live], 0.005, rtol=1e-9)
        assert abs(float(np.sum(weights * stop))) <= 0.005 + 1e-12  # net USD risk: at most one position
    with pytest.raises(ValueError, match="risk_per_position"):
        backtest(prices, FAST, ZERO, RiskLimits(risk_per_position=None), inflation=inflation)
    with pytest.raises(ValueError, match="needs inflation"):
        backtest(prices, FAST, ZERO, limits)


def test_the_book_is_flat_once_inflation_is_no_longer_published():
    prices = _drifting([0.0] * 9, days=1200, vol=0.006, seed=7)
    result = backtest(prices, FAST, ZERO, RiskLimits(), inflation=_inflation(1990, 2002))
    # 2002 inflation is the last year: usable until 2004-06-30, then the signal is incomplete and
    # the next rebalance (at most 11 rows later) flattens the book.
    positions = result.positions
    assert positions.loc[:"2004-06-28"].abs().sum(axis=1).iloc[-1] > 0
    assert (positions.loc["2004-07-16":].abs().sum(axis=1) == 0).all()


def test_fred_loader_can_start_after_a_peg(tmp_path):
    days = pd.bdate_range("1974-01-01", periods=60)
    rows = ["Date,Country,Exchange rate"]
    for number, day in enumerate(days):
        pegged = 1.5 if number < 20 else 1.5 + 0.001 * number
        rows.append(f"{day.date()},Australia,{pegged}")
        rows.append(f"{day.date()},Japan,{300 + number}")
    path = tmp_path / "daily.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        load_fred_daily(path, ("AUD", "JPY"))
    panel = load_fred_daily(path, ("AUD", "JPY"), start=str(days[25].date()))
    assert panel.prices.index[0] == pd.Timestamp(days[25], tz="UTC")


def test_real_value_plan_v2_is_one_spot_only_trial_deflated_over_v1():
    plan = real_value_v2(DIGEST, INFLATION_DIGEST)
    plan.validate()
    assert plan.currencies == REAL_VALUE_CURRENCIES == CURRENCIES and plan.price_start == REAL_VALUE_PRICE_START
    assert [len(item.configs()) for item in plan.hypotheses] == [1] and plan.program_trials == 7
    hypothesis = plan.hypotheses[0]
    assert hypothesis.primary.signal == "xsvalue" and hypothesis.primary.sizing == "equal_risk"
    assert not hypothesis.carry_accrual and hypothesis.timing_claim and len(hypothesis.subperiods) == 2
    assert plan.development == ("1985-04-01", "2016-12-31") and plan.holdout == ("2017-01-01", "2026-06-30")
    assert plan.limits == RiskLimits() and plan.acceptance.min_development_dsr == 0.95
    assert plan.costs.one_way_bps["DKK"] == 3.0 and plan.costs.financing_bps_per_year == 75.0
    assert plan.data.inflation_sha256 == INFLATION_DIGEST and plan.data.rates_sha256 is None
    assert "price_start" in plan.to_dict() and plan.to_dict()["program_trials"] == 7


def test_plan_refuses_unbound_inflation_other_inflation_and_another_start():
    with pytest.raises(ValueError, match="inflation"):
        _plan(data=DataBinding("synthetic", DIGEST)).validate()
    with pytest.raises(ValueError, match="controls"):
        _plan(hypotheses=(Hypothesis("H0", "control", replace(FAST, permute=True)),)).validate()
    with pytest.raises(ValueError, match="subperiod"):
        _plan(hypotheses=(Hypothesis("H1", "value", FAST, subperiods=(("2000-01-01", "2003-12-31"),)),)).validate()
    panel = _mean_reverting()
    ledger = TrialLedger("/nonexistent/never-written.jsonl")
    with pytest.raises(ValueError, match="inflation data"):
        run_development(_plan(), panel, None, None, ledger, inflation=_inflation(), inflation_sha256="f" * 64)
    with pytest.raises(ValueError, match="price_start"):
        _develop(_plan(price_start="2000-06-01"), panel, ledger)


def test_planted_value_edge_passes_development_and_holdout_and_random_walks_do_not(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    plan = _plan()
    panel = _mean_reverting(seed=11)
    development = _develop(plan, panel, ledger)
    result = development["hypotheses"][0]
    assert result["proceed_to_holdout"] is True, result["checks"]
    assert development["pbo"] is None and result["checks"]["probability_of_backtest_overfitting"] is True
    assert result["random_control"]["kind"] == "permuted_currencies"
    assert len(set(result["random_control"]["seeds"])) == plan.random_replicas
    assert set(result["subperiod_sharpes"]) == {"2001-07-01..2004-12-31", "2005-01-01..2008-12-31"}
    assert result["carry_credited"] is False and "hac_t_stat_21d" in result["primary"]
    holdout = run_holdout(plan, panel, None, None, json.loads(json.dumps(development, default=float)), ledger,
                          tmp_path / "holdout.json", inflation=_inflation(), inflation_sha256=INFLATION_DIGEST)
    assert holdout["hypotheses"][0]["verdict"] in {"PASSED_RESEARCH", "WATCHLIST"}
    assert holdout["hypotheses"][0]["checks"]["development_pbo_promotion_grade"] is True
    # A random walk passes these gates about 2% of the time (t >= 2 alone: 2.5% of 40 seeds); seed 0 does not.
    null = _develop(_plan(name="null"), _mean_reverting(speed=0.0, seed=0), TrialLedger(tmp_path / "n.jsonl"))
    assert null["hypotheses"][0]["proceed_to_holdout"] is False


def test_deflation_counts_other_plans_trials_with_a_null_variance_floor(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    panel = _mean_reverting(seed=13)
    _develop(_plan(name="earlier"), panel, ledger)
    with pytest.raises(ValueError, match="development trials of other plans"):
        _develop(_plan(name="later", program_trials=2), panel, ledger)
    development = _develop(_plan(name="later", program_trials=1), panel, ledger)
    deflated = development["hypotheses"][0]["deflated_sharpe"]
    assert deflated["trials"] == 2 and development["program_trials"] == 2
    floor = 1.0 / (deflated["observations"] - 1)
    assert deflated["benchmark_sharpe"] >= expected_max_sharpe(2, floor) - 1e-15
    # Without program trials a single trial is not deflated at all (v1 convention).
    alone = _develop(_plan(name="alone"), panel, TrialLedger(tmp_path / "alone.jsonl"))
    assert alone["hypotheses"][0]["deflated_sharpe"]["trials"] == 1


def test_subperiod_gate_needs_every_subperiod_above_its_threshold(tmp_path):
    panel = _mean_reverting(seed=11)
    strict = _develop(_plan(acceptance=Acceptance(min_subperiod_sharpe=50.0)), panel,
                      TrialLedger(tmp_path / "a.jsonl"))
    assert strict["hypotheses"][0]["checks"]["positive_in_subperiods"] is False
    loose = _develop(_plan(acceptance=Acceptance(min_subperiod_sharpe=-50.0)), panel,
                     TrialLedger(tmp_path / "b.jsonl"))
    assert loose["hypotheses"][0]["checks"]["positive_in_subperiods"] is True


def test_runner_uses_the_inflation_file_for_the_value_plan(tmp_path, monkeypatch):
    calls = {}

    def fake_fred(path, currencies, start=None):
        calls["fred"] = (tuple(currencies), start)
        return PricePanel(_mean_reverting().prices, "fred_h10_daily", DIGEST)

    def fake_inflation(path, currencies):
        calls["inflation"] = tuple(currencies)
        return _inflation(), INFLATION_DIGEST

    monkeypatch.setattr(runner, "load_fred_daily", fake_fred)
    monkeypatch.setattr(runner, "load_worldbank_inflation", fake_inflation)
    plan_file = tmp_path / "plan.json"
    args = ["--plan", "real_value_v2", "--prices", "p.csv", "--plan-file", str(plan_file)]
    assert runner.main(["freeze", *args]) == 2  # --inflation is required by this plan
    assert runner.main(["freeze", *args, "--inflation", "cpi.csv"]) == 0
    assert calls == {"fred": (CURRENCIES, REAL_VALUE_PRICE_START), "inflation": CURRENCIES}
    frozen = json.loads(plan_file.read_text(encoding="utf-8"))
    assert frozen["plan_hash"] == real_value_v2(DIGEST, INFLATION_DIGEST).plan_hash()

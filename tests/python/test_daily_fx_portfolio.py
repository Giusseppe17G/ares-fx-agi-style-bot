"""Daily FX portfolio research engine on synthetic data only (no real prices)."""
import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.research.daily_fx.data import load_fred_daily, load_mt5_daily, load_oecd_rates
from agi_style_forex_bot_mt5.research.daily_fx.portfolio import (UNCONSTRAINED, CostModel, PortfolioConfig, RiskLimits,
    backtest, performance, rate_differentials, target_weights, tsmom_signal, xsmom_signal)

CURRENCIES = ("EUR", "JPY", "GBP", "CHF", "AUD")
ZERO = CostModel({code: 0.0 for code in CURRENCIES})


def _prices(days=1500, drift=None, vol=0.006, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2001-01-01", periods=days, tz="UTC")
    steps = rng.normal(0.0, vol, size=(days, len(CURRENCIES)))
    if drift is not None:
        steps += np.asarray(drift)
    return pd.DataFrame(np.exp(np.cumsum(steps, axis=0)), index=index, columns=list(CURRENCIES))


def _rates(index, values):
    months = pd.period_range(index[0].tz_convert(None).to_period("M") - 2, index[-1].tz_convert(None).to_period("M"),
                             freq="M")
    return pd.DataFrame({code: [values.get(code, 1.0)] * len(months) for code in (*CURRENCIES, "USD")}, index=months)


def test_no_look_ahead_targets_and_returns_ignore_the_future():
    prices = _prices()
    config = PortfolioConfig(execution_lag_days=1, rebalance_days=1)
    cut = 900
    altered = prices.copy()
    altered.iloc[cut + 1:] *= np.exp(np.random.default_rng(9).normal(0, 0.05, size=altered.iloc[cut + 1:].shape))
    full_target, _ = target_weights(prices, config)
    other_target, _ = target_weights(altered, config)
    pd.testing.assert_frame_equal(full_target.iloc[:cut + 1], other_target.iloc[:cut + 1])
    full, other = backtest(prices, config, ZERO), backtest(altered, config, ZERO)
    last_safe = prices.index[cut]
    pd.testing.assert_series_equal(full.net_returns.loc[:last_safe], other.net_returns.loc[:last_safe])
    pd.testing.assert_frame_equal(full.positions.loc[:last_safe], other.positions.loc[:last_safe])
    assert not full.net_returns.loc[prices.index[cut + 1]:].equals(other.net_returns.loc[prices.index[cut + 1]:])


def test_planted_trends_are_captured_and_random_walks_are_not():
    trending = _prices(drift=[0.0006, -0.0006, 0.0004, -0.0004, 0.0005], seed=1)
    assert performance(backtest(trending, PortfolioConfig(), ZERO).net_returns)["sharpe"] > 1.0
    sharpes = [performance(backtest(_prices(days=2500, seed=seed), PortfolioConfig(), ZERO).net_returns)["sharpe"]
               for seed in range(10, 20)]
    assert abs(np.mean(sharpes)) < 0.35


def test_flipping_the_signal_negates_gross_returns_of_a_daily_book():
    prices = _prices(seed=3)
    config = PortfolioConfig(rebalance_days=1)
    base = backtest(prices, config, ZERO, UNCONSTRAINED).gross_returns
    flipped = backtest(prices, PortfolioConfig(rebalance_days=1, flip=True), ZERO, UNCONSTRAINED).gross_returns
    np.testing.assert_allclose(np.expm1(base.to_numpy()), -np.expm1(flipped.to_numpy()), atol=1e-15)


def test_volatility_target_and_leverage_cap_without_invariants():
    prices = _prices(days=3000, seed=4)
    result = backtest(prices, PortfolioConfig(target_annual_vol=0.10, max_gross_leverage=10.0), ZERO, UNCONSTRAINED)
    realised = performance(result.gross_returns.iloc[300:])["annual_vol"]
    assert 0.07 < realised < 0.13
    capped = backtest(prices, PortfolioConfig(max_gross_leverage=1.0, rebalance_days=1), ZERO, UNCONSTRAINED)
    assert capped.positions.abs().sum(axis=1).max() <= 1.0 + 1e-12


def test_invariants_bound_risk_per_position_open_risk_usd_leg_and_count():
    prices = _prices(days=2500, drift=[0.0004] * 5, seed=11)
    limits = RiskLimits(risk_per_position=0.005, max_open_risk=0.012, max_net_usd_risk=0.01, max_positions=3)
    config = PortfolioConfig(rebalance_days=21)
    result = backtest(prices, config, ZERO, limits)
    _, vol = target_weights(prices, config)
    stop = limits.stop_sigmas * vol * np.sqrt(21 / 252)
    rebalances = result.turnover[result.turnover > 0].index
    # Right after each rebalance (weights not drifted yet) the limits hold exactly.
    decided = stop.shift(1).loc[rebalances]
    risk = result.positions.loc[rebalances].abs() * decided
    assert (risk.max(axis=1) <= 0.005 + 1e-9).all()
    assert (risk.sum(axis=1) <= 0.012 + 1e-9).all()
    assert ((result.positions.loc[rebalances] * decided).sum(axis=1).abs() <= 0.01 + 1e-9).all()
    assert ((result.positions.loc[rebalances] != 0).sum(axis=1) <= 3).all()
    assert performance(result.net_returns)["annual_vol"] < 0.05


def test_stops_take_profits_and_loss_halts_are_simulated():
    prices = _prices(days=2000, vol=0.004, seed=12)
    crash = prices.index[1200]
    prices.loc[crash:, "EUR"] *= 0.85  # one-day 15% gap against any long EUR position
    result = backtest(prices, PortfolioConfig(rebalance_days=21), ZERO, RiskLimits(stop_sigmas=1.0))
    assert result.stops > 0
    tp = backtest(_prices(days=2000, drift=[0.002] * 5, seed=13), PortfolioConfig(), ZERO,
                  RiskLimits(stop_sigmas=1.0, take_profit_multiple=1.0))
    assert tp.take_profits > 0
    halted = backtest(prices, PortfolioConfig(rebalance_days=1), ZERO,
                      RiskLimits(daily_loss_halt=1e-9, floating_loss_halt=1e-9))
    assert halted.blocked_rebalances > 0


def test_costs_are_charged_on_turnover_and_financing_on_exposure():
    prices = _prices(seed=5)
    costs = CostModel({code: 1.0 for code in CURRENCIES}, financing_bps_per_year=100.0)
    result = backtest(prices, PortfolioConfig(), costs, UNCONSTRAINED)
    held = result.positions.shift(1).fillna(0.0).abs().sum(axis=1)
    expected = result.turnover * 1e-4 + held * 0.01 / 252
    np.testing.assert_allclose(result.costs.to_numpy(), expected.to_numpy(), rtol=1e-12, atol=1e-15)
    np.testing.assert_allclose((np.expm1(result.gross_returns) - np.expm1(result.net_returns)).to_numpy(),
                               result.costs.to_numpy(), atol=1e-15)
    free = backtest(prices, PortfolioConfig(), ZERO, UNCONSTRAINED)
    pd.testing.assert_series_equal(free.net_returns, free.gross_returns)
    np.testing.assert_allclose(free.contributions.sum(axis=1).to_numpy(), np.expm1(free.gross_returns).to_numpy(),
                               atol=1e-15)


def test_trades_only_happen_on_rebalance_days_without_stops():
    prices = _prices(seed=6)
    result = backtest(prices, PortfolioConfig(rebalance_days=5), ZERO, UNCONSTRAINED)
    trades = np.flatnonzero(result.turnover.to_numpy() > 0)
    assert trades.size > 10 and (np.diff(trades) % 5 == 0).all()


def test_carry_accrues_the_previous_month_rate_differential_and_stops_with_the_rates():
    prices = _prices(days=1200, seed=7)
    rates = _rates(prices.index, {"EUR": 5.0, "USD": 1.0})
    carry = rate_differentials(rates, prices.index, CURRENCIES)
    assert carry["EUR"].dropna().unique().tolist() == pytest.approx([0.04])
    assert carry["JPY"].dropna().unique().tolist() == pytest.approx([0.0])
    # A month without rates is NaN, never a stale value.
    holed = rates.drop(rates.index[-2:])  # the last days use the second-to-last month
    assert rate_differentials(holed, prices.index, CURRENCIES).iloc[-1].isna().all()
    result = backtest(prices, PortfolioConfig(signal="tscarry"), ZERO, UNCONSTRAINED, rates=holed)
    assert result.net_returns.index[-1] < prices.index[-1]
    assert (result.positions["EUR"].iloc[-1] > 0) and (result.positions["JPY"].abs().iloc[-1] == 0)
    flat_prices = pd.DataFrame(1.0, index=prices.index, columns=list(CURRENCIES))
    accrued = backtest(flat_prices * np.exp(np.linspace(0, 1e-9, len(prices)))[:, None],
                       PortfolioConfig(signal="tscarry", vol_span=5), ZERO, UNCONSTRAINED, rates=rates)
    assert accrued.contributions["EUR"].sum() > 0
    with pytest.raises(ValueError):
        backtest(prices, PortfolioConfig(signal="blend"), ZERO)


def test_time_shift_keeps_the_signal_but_moves_it():
    prices = _prices(days=1500, seed=8)
    config = PortfolioConfig(rebalance_days=1)
    base = target_weights(prices, config)[0]
    shifted = target_weights(prices, PortfolioConfig(rebalance_days=1, shift_days=300))[0]
    assert base.notna().all(axis=1).sum() == shifted.notna().all(axis=1).sum()
    assert not base.dropna().equals(shifted.dropna())
    signs = np.sign(tsmom_signal(np.log(prices), (252,)).dropna())
    assert (signs.to_numpy() != 0).mean() > 0.99
    with pytest.raises(ValueError):
        target_weights(prices, PortfolioConfig(shift_days=10_000))


def test_signals_are_bounded_and_cross_sectional_is_balanced():
    log_prices = np.log(_prices(seed=7))
    ts = tsmom_signal(log_prices, (21, 63)).dropna()
    assert ts.abs().max().max() <= 1.0 and set(np.unique(ts.to_numpy())) <= {-1.0, 0.0, 1.0, -0.5, 0.5}
    xs = xsmom_signal(log_prices, 63, 2).dropna()
    assert (xs.sum(axis=1) == 0).all() and (xs.abs().sum(axis=1) == 4).all()
    with pytest.raises(ValueError):
        xsmom_signal(log_prices, 63, 3)


def test_rejects_invalid_configurations_and_short_history():
    prices = _prices(days=100)
    with pytest.raises(ValueError):
        backtest(prices, PortfolioConfig(), ZERO)
    with pytest.raises(ValueError):
        backtest(_prices(), PortfolioConfig(signal="martingale"), ZERO)
    with pytest.raises(ValueError):
        backtest(_prices(), PortfolioConfig(), CostModel({"EUR": 1.0}))
    with pytest.raises(ValueError):
        backtest(_prices(), PortfolioConfig(shift_days=-1), ZERO)


def test_fred_loader_inverts_every_series_to_usd_per_unit(tmp_path):
    rows = ["Date,Country,Exchange rate"]
    values = (("2020-01-02", 0.90, 100.0), ("2020-01-03", 0.80, ""), ("2020-01-06", 0.75, 125.0))
    for day, eur, jpy in values:
        rows += [f"{day},Euro,{eur}", f"{day},Japan,{jpy}", f"{day},Brazil,5.0"]
    path = tmp_path / "daily.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    panel = load_fred_daily(path, ("EUR", "JPY"))
    assert panel.currencies == ("EUR", "JPY") and len(panel.source_sha256) == 64
    # Every H.10 series is currency per USD: the Euro reads 0.90 when EURUSD is 1.111.
    assert panel.prices["EUR"].tolist() == pytest.approx([1 / 0.90, 1 / 0.80, 1 / 0.75])
    # The missing day carries the last price.
    assert panel.prices["JPY"].tolist() == pytest.approx([0.01, 0.01, 0.008])
    with pytest.raises(ValueError):
        load_fred_daily(path, ("EUR", "XAU"))


def test_fred_loader_rejects_a_stale_feed(tmp_path):
    days = pd.bdate_range("2020-01-01", periods=12)
    rows = ["Date,Country,Exchange rate"] + [f"{day.date()},Euro,{0.9 if 3 <= i < 9 else 0.9 + i / 1000}"
                                             for i, day in enumerate(days)]
    path = tmp_path / "daily.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        load_fred_daily(path, ("EUR",))


def test_mt5_loader_inverts_usd_base_pairs_and_dates_bars_by_their_close(tmp_path):
    # A New York close broker opens Monday's D1 bar on Sunday at 21:00 UTC.
    opens = pd.DatetimeIndex(["2021-02-28 22:00", "2021-03-01 22:00", "2021-03-02 22:00", "2021-03-03 22:00"],
                             tz="UTC")
    for symbol, closes in (("EURUSD", [1.2, 1.21, 1.22, 1.23]), ("USDJPY", [100.0, 101.0, 102.0, 103.0])):
        pd.DataFrame({"timestamp_utc": opens.strftime("%Y-%m-%dT%H:%M:%SZ"), "close": closes}).to_csv(
            tmp_path / f"{symbol}_D1.csv", index=False)
    panel = load_mt5_daily(tmp_path, ("EUR", "JPY"))
    assert panel.prices.index[0] == pd.Timestamp("2021-03-01", tz="UTC")
    assert panel.prices["JPY"].iloc[0] == pytest.approx(0.01) and panel.prices["EUR"].iloc[-1] == pytest.approx(1.23)
    utc_opens = pd.DatetimeIndex(["2021-03-01", "2021-03-02", "2021-03-03", "2021-03-04"], tz="UTC")
    for symbol in ("EURUSD", "USDJPY"):
        frame = pd.read_csv(tmp_path / f"{symbol}_D1.csv")
        frame["timestamp_utc"] = utc_opens.strftime("%Y-%m-%dT%H:%M:%SZ")
        frame.to_csv(tmp_path / f"{symbol}_D1.csv", index=False)
    assert load_mt5_daily(tmp_path, ("EUR", "JPY")).prices.index.equals(panel.prices.index)


def test_oecd_rates_loader(tmp_path):
    rows = ['"LOCATION","INDICATOR","SUBJECT","MEASURE","FREQUENCY","TIME","Value","Flag Codes"']
    for location, value in (("USA", 1.5), ("EA19", -0.3), ("JPN", 0.0)):
        rows += [f'"{location}","STINT","TOT","PC_PA","M","2020-0{month}",{value + month / 10},'
                 for month in (1, 2, 3)]
        rows.append(f'"{location}","STINT","TOT","PC_PA","Q","2020-Q1",{value},')
    path = tmp_path / "short-term-interest.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    rates, digest = load_oecd_rates(path, ("EUR", "JPY"))
    assert list(rates.columns) == ["USD", "EUR", "JPY"] and len(digest) == 64
    assert rates.loc[pd.Period("2020-02", "M"), "EUR"] == pytest.approx(-0.1)
    with pytest.raises(ValueError):
        load_oecd_rates(path, ("GBP",))

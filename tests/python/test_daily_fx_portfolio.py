"""Daily FX portfolio research engine on synthetic data only (no real prices)."""
import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.research.daily_fx.data import load_fred_daily, load_mt5_daily
from agi_style_forex_bot_mt5.research.daily_fx.portfolio import (CostModel, PortfolioConfig, backtest, performance,
    tsmom_signal, xsmom_signal)

CURRENCIES = ("EUR", "JPY", "GBP", "CHF", "AUD")
ZERO = CostModel({code: 0.0 for code in CURRENCIES})


def _prices(days=1500, drift=None, vol=0.006, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2001-01-01", periods=days, tz="UTC")
    steps = rng.normal(0.0, vol, size=(days, len(CURRENCIES)))
    if drift is not None:
        steps += np.asarray(drift)
    return pd.DataFrame(np.exp(np.cumsum(steps, axis=0)), index=index, columns=list(CURRENCIES))


def test_no_look_ahead_positions_ignore_the_future():
    prices = _prices()
    config = PortfolioConfig(execution_lag_days=1, rebalance_days=1)
    cut = 900
    altered = prices.copy()
    altered.iloc[cut + 1:] *= np.exp(np.random.default_rng(9).normal(0, 0.05, size=altered.iloc[cut + 1:].shape))
    full = backtest(prices, config, ZERO).positions
    other = backtest(altered, config, ZERO).positions
    # Positions held up to day cut+2 (target of day cut, lag 1) cannot depend on later prices.
    last_safe = prices.index[cut + 2]
    pd.testing.assert_frame_equal(full.loc[:last_safe], other.loc[:last_safe])
    assert not full.loc[prices.index[cut + 3]:].equals(other.loc[prices.index[cut + 3]:])


def test_planted_trends_are_captured_and_random_walks_are_not():
    trending = _prices(drift=[0.0006, -0.0006, 0.0004, -0.0004, 0.0005], seed=1)
    assert performance(backtest(trending, PortfolioConfig(), ZERO).net_returns)["sharpe"] > 1.0
    sharpes = [performance(backtest(_prices(seed=seed), PortfolioConfig(), ZERO).net_returns)["sharpe"]
               for seed in range(10, 20)]
    assert abs(np.mean(sharpes)) < 0.35


def test_flipping_the_signal_negates_gross_returns():
    prices = _prices(seed=3)
    base = backtest(prices, PortfolioConfig(), ZERO).gross_returns
    flipped = backtest(prices, PortfolioConfig(flip=True), ZERO).gross_returns
    np.testing.assert_allclose(base.to_numpy(), -flipped.to_numpy(), atol=1e-15)


def test_volatility_target_and_leverage_cap():
    prices = _prices(days=3000, seed=4)
    result = backtest(prices, PortfolioConfig(target_annual_vol=0.10, max_gross_leverage=10.0), ZERO)
    realised = performance(result.gross_returns.iloc[300:])["annual_vol"]
    assert 0.07 < realised < 0.13
    capped = backtest(prices, PortfolioConfig(target_annual_vol=0.10, max_gross_leverage=1.0), ZERO)
    assert capped.positions.abs().sum(axis=1).max() <= 1.0 + 1e-12


def test_costs_are_charged_on_turnover_and_financing_on_exposure():
    prices = _prices(seed=5)
    costs = CostModel({code: 1.0 for code in CURRENCIES}, financing_bps_per_year=100.0)
    result = backtest(prices, PortfolioConfig(), costs)
    expected = result.turnover * 1e-4 + result.positions.abs().sum(axis=1) * 0.01 / 252
    np.testing.assert_allclose(result.costs.to_numpy(), expected.to_numpy(), rtol=1e-12, atol=1e-15)
    np.testing.assert_allclose((result.gross_returns - result.net_returns).to_numpy(), result.costs.to_numpy())
    free = backtest(prices, PortfolioConfig(), ZERO)
    pd.testing.assert_series_equal(free.net_returns, free.gross_returns)


def test_positions_only_change_on_rebalance_days():
    prices = _prices(seed=6)
    result = backtest(prices, PortfolioConfig(rebalance_days=5), ZERO)
    changes = result.positions.diff().abs().sum(axis=1).iloc[1:] > 0
    gaps = np.diff(np.flatnonzero(changes.to_numpy()))
    assert gaps.size and (gaps % 5 == 0).all()


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


def test_fred_loader_converts_every_series_to_usd_per_unit(tmp_path):
    rows = ["Date,Country,Exchange rate"]
    for day, (eur, jpy) in zip(("2020-01-02", "2020-01-03", "2020-01-06"), ((1.10, 100.0), (1.20, ""), (1.30, 125.0))):
        rows += [f"{day},Euro,{eur}", f"{day},Japan,{jpy}", f"{day},Brazil,5.0"]
    path = tmp_path / "daily.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    panel = load_fred_daily(path, ("EUR", "JPY"))
    assert panel.currencies == ("EUR", "JPY") and len(panel.source_sha256) == 64
    assert panel.prices["EUR"].tolist() == pytest.approx([1.10, 1.20, 1.30])
    # JPY is quoted per USD: inverted, and the missing day carries the last price.
    assert panel.prices["JPY"].tolist() == pytest.approx([0.01, 0.01, 0.008])
    with pytest.raises(ValueError):
        load_fred_daily(path, ("EUR", "XAU"))


def test_mt5_loader_inverts_usd_base_pairs(tmp_path):
    days = pd.bdate_range("2021-03-01", periods=4, tz="UTC")
    for symbol, closes in (("EURUSD", [1.2, 1.21, 1.22, 1.23]), ("USDJPY", [100.0, 101.0, 102.0, 103.0])):
        pd.DataFrame({"timestamp_utc": days.strftime("%Y-%m-%dT%H:%M:%SZ"), "close": closes}).to_csv(
            tmp_path / f"{symbol}_D1.csv", index=False)
    panel = load_mt5_daily(tmp_path, ("EUR", "JPY"))
    assert panel.prices["JPY"].iloc[0] == pytest.approx(0.01) and panel.prices["EUR"].iloc[-1] == pytest.approx(1.23)

"""Edge statistics: PSR/DSR/MinTRL, PBO by CSCV, SPA and Holm, on synthetic data."""
import math

import numpy as np
import pytest

from agi_style_forex_bot_mt5.research.edge_statistics import (deflated_sharpe_ratio, expected_max_sharpe,
    holm_adjusted, min_track_record_length, moments, probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting, sharpe_ratio, stationary_bootstrap_indices, superior_predictive_ability)


def test_psr_is_one_half_at_the_benchmark_and_monotone():
    assert probabilistic_sharpe_ratio(0.1, 0.1, 250) == pytest.approx(0.5)
    assert probabilistic_sharpe_ratio(0.1, 0.0, 250) > probabilistic_sharpe_ratio(0.1, 0.0, 50) > 0.5
    # Negative skew and fat tails make the same Sharpe less convincing.
    assert probabilistic_sharpe_ratio(0.1, 0.0, 250, skew=-1.0, kurtosis=8.0) < probabilistic_sharpe_ratio(0.1, 0.0, 250)


def test_min_track_record_length_reaches_the_requested_confidence():
    n = min_track_record_length(0.08, 0.0, skew=-0.3, kurtosis=5.0, confidence=0.95)
    assert probabilistic_sharpe_ratio(0.08, 0.0, math.ceil(n), skew=-0.3, kurtosis=5.0) >= 0.95
    assert probabilistic_sharpe_ratio(0.08, 0.0, math.floor(n) - 1, skew=-0.3, kurtosis=5.0) < 0.95
    assert min_track_record_length(0.0, 0.1) == math.inf


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 0.01) == 0.0
    values = [expected_max_sharpe(n, 0.01) for n in (2, 10, 100, 1000)]
    assert values == sorted(values) and values[-1] < 0.1 * 4


def test_expected_max_sharpe_matches_simulation():
    rng = np.random.default_rng(3)
    sd = 0.05
    maxima = rng.normal(0.0, sd, size=(20000, 50)).max(axis=1)
    assert expected_max_sharpe(50, sd**2) == pytest.approx(maxima.mean(), rel=0.03)


def test_dsr_penalises_the_best_of_many_noise_strategies():
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 0.01, size=(1000, 200))
    sharpes = noise.mean(axis=0) / noise.std(axis=0, ddof=1)
    best = noise[:, int(np.argmax(sharpes))]
    # The luckiest of 200 noise strategies looks good on its own...
    assert probabilistic_sharpe_ratio(sharpe_ratio(best), 0.0, 1000, *moments(best)) > 0.9
    # ...but not once the 200 trials are accounted for.
    assert deflated_sharpe_ratio(best, sharpes).deflated_sharpe_ratio < 0.5
    edge = rng.normal(0.002, 0.01, size=1000)  # per-period Sharpe 0.2, twice the luck benchmark
    assert deflated_sharpe_ratio(edge, np.r_[sharpes[:199], sharpe_ratio(edge)]).deflated_sharpe_ratio > 0.95


def test_pbo_is_high_for_noise_and_low_for_a_real_edge():
    rng = np.random.default_rng(11)
    noise = rng.normal(0.0, 0.01, size=(1600, 30))
    assert 0.3 < probability_of_backtest_overfitting(noise, blocks=10).pbo < 0.75
    edge = noise.copy()
    edge[:, 0] += 0.004
    result = probability_of_backtest_overfitting(edge, blocks=10)
    assert result.pbo < 0.05 and result.combinations == math.comb(10, 5)


def test_pbo_rejects_bad_shapes():
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting(np.zeros((100, 1)))
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting(np.zeros((100, 3)), blocks=5)


def test_stationary_bootstrap_resamples_in_blocks():
    rng = np.random.default_rng(1)
    indices = stationary_bootstrap_indices(1000, 20.0, rng)
    assert indices.shape == (1000,) and indices.min() >= 0 and indices.max() < 1000
    continuations = np.mean(np.diff(indices) % 1000 == 1)
    assert 0.9 < continuations < 0.99  # about 1 - 1/20


def test_spa_rejects_a_real_edge_but_not_noise_or_losers():
    rng = np.random.default_rng(5)
    noise = rng.normal(0.0, 0.01, size=(1500, 20))
    assert superior_predictive_ability(noise, bootstraps=500).p_value > 0.05
    losers = noise - 0.002
    assert superior_predictive_ability(losers, bootstraps=500).p_value > 0.5
    edge = noise.copy()
    edge[:, 3] += 0.0015
    result = superior_predictive_ability(edge, bootstraps=500)
    assert result.p_value < 0.05 and result.best_strategy == 3


def test_holm_controls_the_family():
    assert holm_adjusted([0.01, 0.04, 0.03, 0.2]) == pytest.approx([0.04, 0.09, 0.09, 0.2])
    assert holm_adjusted([]) == []

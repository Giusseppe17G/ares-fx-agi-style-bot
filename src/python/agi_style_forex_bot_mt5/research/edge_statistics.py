"""Statistics that separate a real edge from luck and backtest overfitting.

Every function works on per-period returns (one value per bar or per day) and
uses numpy plus the standard library only. Sharpe ratios are per period unless
a name says annualised; annualise with ``annualised_sharpe``.

- Probabilistic Sharpe Ratio (PSR) and Minimum Track Record Length:
  Bailey & Lopez de Prado, "The Sharpe Ratio Efficient Frontier", Journal of
  Risk 15(2), 2012.
- Deflated Sharpe Ratio (DSR) and the expected maximum Sharpe of N trials:
  Bailey & Lopez de Prado, "The Deflated Sharpe Ratio", Journal of Portfolio
  Management 40(5), 2014.
- Probability of Backtest Overfitting (PBO) by combinatorially symmetric
  cross-validation (CSCV): Bailey, Borwein, Lopez de Prado & Zhu, Journal of
  Computational Finance 20(4), 2017.
- Superior Predictive Ability test with the stationary bootstrap: Hansen,
  Journal of Business & Economic Statistics 23(4), 2005; White, Econometrica
  68(5), 2000; Politis & Romano, JASA 89(428), 1994.
- Holm step-down adjustment for multiple hypotheses: Holm, Scandinavian
  Journal of Statistics 6(2), 1979.
- t-statistic of the mean with the Newey-West (Bartlett kernel) long-run
  variance: Newey & West, Econometrica 55(3), 1987; automatic lag
  floor(4 (n/100)^(2/9)).

Nothing here builds, checks or sends an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
from statistics import NormalDist
from typing import Sequence

import numpy as np

EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


def _clean(returns: Sequence[float] | np.ndarray) -> np.ndarray:
    values = np.asarray(returns, dtype=float).ravel()
    if values.size < 3 or not np.isfinite(values).all():
        raise ValueError("returns must hold at least 3 finite values")
    return values


def sharpe_ratio(returns: Sequence[float] | np.ndarray) -> float:
    """Per-period Sharpe ratio (mean / sample standard deviation, ddof=1)."""

    values = _clean(returns)
    std = float(np.std(values, ddof=1))
    if std == 0.0:
        raise ValueError("returns have zero variance")
    return float(np.mean(values)) / std


def annualised_sharpe(per_period_sharpe: float, periods_per_year: float) -> float:
    return float(per_period_sharpe) * math.sqrt(periods_per_year)


def moments(returns: Sequence[float] | np.ndarray) -> tuple[float, float]:
    """Sample skewness and (non-excess) kurtosis, as PSR expects."""

    values = _clean(returns)
    centred = values - values.mean()
    std = float(np.sqrt(np.mean(centred**2)))
    if std == 0.0:
        raise ValueError("returns have zero variance")
    skew = float(np.mean(centred**3)) / std**3
    kurtosis = float(np.mean(centred**4)) / std**4
    return skew, kurtosis


def _sharpe_std(sharpe: float, skew: float, kurtosis: float) -> float:
    variance = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if variance <= 0.0:
        raise ValueError("Sharpe ratio variance is not positive for these moments")
    return math.sqrt(variance)


def probabilistic_sharpe_ratio(sharpe: float, benchmark_sharpe: float, observations: int,
                               skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """Probability that the true per-period Sharpe exceeds ``benchmark_sharpe``."""

    if observations < 2:
        raise ValueError("observations must be at least 2")
    z = (sharpe - benchmark_sharpe) * math.sqrt(observations - 1) / _sharpe_std(sharpe, skew, kurtosis)
    return _NORMAL.cdf(z)


def min_track_record_length(sharpe: float, benchmark_sharpe: float, skew: float = 0.0,
                            kurtosis: float = 3.0, confidence: float = 0.95) -> float:
    """Observations needed for PSR(benchmark) to reach ``confidence``."""

    if sharpe <= benchmark_sharpe:
        return math.inf
    z = _NORMAL.inv_cdf(confidence)
    return 1.0 + _sharpe_std(sharpe, skew, kurtosis) ** 2 * (z / (sharpe - benchmark_sharpe)) ** 2


def expected_max_sharpe(trials: int, sharpe_variance: float) -> float:
    """Expected maximum per-period Sharpe among ``trials`` unskilled strategies."""

    if trials < 1 or sharpe_variance < 0:
        raise ValueError("trials must be >= 1 and the variance non-negative")
    if trials == 1:
        return 0.0
    return math.sqrt(sharpe_variance) * (
        (1.0 - EULER_GAMMA) * _NORMAL.inv_cdf(1.0 - 1.0 / trials)
        + EULER_GAMMA * _NORMAL.inv_cdf(1.0 - 1.0 / (trials * math.e))
    )


@dataclass(frozen=True)
class DeflatedSharpe:
    sharpe: float
    benchmark_sharpe: float
    deflated_sharpe_ratio: float
    observations: int
    trials: int
    skew: float
    kurtosis: float

    def to_dict(self) -> dict[str, float | int]:
        return {"sharpe": self.sharpe, "benchmark_sharpe": self.benchmark_sharpe,
                "deflated_sharpe_ratio": self.deflated_sharpe_ratio, "observations": self.observations,
                "trials": self.trials, "skew": self.skew, "kurtosis": self.kurtosis}


def deflated_sharpe_ratio(returns: Sequence[float] | np.ndarray, trial_sharpes: Sequence[float]) -> DeflatedSharpe:
    """DSR of the selected strategy given the per-period Sharpes of every trial tried.

    ``trial_sharpes`` must include every configuration evaluated during the
    search (the selected one too); their dispersion sets the luck benchmark.
    """

    values = _clean(returns)
    trials = np.asarray(trial_sharpes, dtype=float).ravel()
    if trials.size < 1 or not np.isfinite(trials).all():
        raise ValueError("trial_sharpes must hold finite values")
    sharpe = sharpe_ratio(values)
    skew, kurtosis = moments(values)
    variance = float(np.var(trials, ddof=1)) if trials.size > 1 else 0.0
    benchmark = expected_max_sharpe(int(trials.size), variance)
    dsr = probabilistic_sharpe_ratio(sharpe, benchmark, values.size, skew, kurtosis)
    return DeflatedSharpe(sharpe, benchmark, dsr, int(values.size), int(trials.size), skew, kurtosis)


@dataclass(frozen=True)
class OverfitProbability:
    pbo: float
    combinations: int
    logits: tuple[float, ...]
    in_sample_sharpe_of_selected: tuple[float, ...]
    out_of_sample_sharpe_of_selected: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return {"pbo": self.pbo, "combinations": self.combinations,
                "median_logit": float(np.median(self.logits)) if self.logits else None,
                "median_oos_sharpe_of_selected": float(np.median(self.out_of_sample_sharpe_of_selected))
                if self.out_of_sample_sharpe_of_selected else None}


def _block_sharpes(matrix: np.ndarray) -> np.ndarray:
    std = matrix.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpes = matrix.mean(axis=0) / std
    return np.where(std > 0, sharpes, 0.0)


def probability_of_backtest_overfitting(performance: np.ndarray, blocks: int = 16) -> OverfitProbability:
    """PBO by CSCV over a (periods x strategies) matrix of per-period returns.

    The rows are split into ``blocks`` contiguous groups; every half of the
    groups serves once as in-sample. The best in-sample strategy's out-of-sample
    rank gives a logit; PBO is the share of logits at or below zero, i.e. how
    often the in-sample winner is no better than the median out of sample.
    """

    matrix = np.asarray(performance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2 or not np.isfinite(matrix).all():
        raise ValueError("performance must be a finite (periods x strategies) matrix with 2+ strategies")
    if blocks < 2 or blocks % 2 or matrix.shape[0] < blocks * 2:
        raise ValueError("blocks must be even, >= 2, and leave at least 2 rows per block")
    groups = np.array_split(np.arange(matrix.shape[0]), blocks)
    strategies = matrix.shape[1]
    logits, is_best, oos_best = [], [], []
    for chosen in combinations(range(blocks), blocks // 2):
        in_rows = np.concatenate([groups[i] for i in chosen])
        out_rows = np.concatenate([groups[i] for i in range(blocks) if i not in chosen])
        in_sharpe = _block_sharpes(matrix[in_rows])
        out_sharpe = _block_sharpes(matrix[out_rows])
        best = int(np.argmax(in_sharpe))
        # Relative rank of the in-sample winner out of sample, in (0, 1).
        rank = (np.sum(out_sharpe < out_sharpe[best]) + 0.5 * (np.sum(out_sharpe == out_sharpe[best]) - 1) + 1)
        omega = rank / (strategies + 1)
        logits.append(math.log(omega / (1.0 - omega)))
        is_best.append(float(in_sharpe[best]))
        oos_best.append(float(out_sharpe[best]))
    pbo = float(np.mean(np.asarray(logits) <= 0.0))
    return OverfitProbability(pbo, len(logits), tuple(logits), tuple(is_best), tuple(oos_best))


def stationary_bootstrap_indices(length: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """One stationary-bootstrap resample of ``range(length)`` (Politis & Romano)."""

    if length < 1 or mean_block < 1:
        raise ValueError("length and mean_block must be >= 1")
    restart = rng.random(length) < 1.0 / mean_block
    restart[0] = True
    starts = rng.integers(0, length, size=length)
    positions = np.arange(length)
    # Position where the current block began; blocks wrap around the series.
    block_start = np.maximum.accumulate(np.where(restart, positions, 0))
    return (starts[block_start] + positions - block_start) % length


@dataclass(frozen=True)
class SuperiorAbility:
    p_value: float
    statistic: float
    best_strategy: int
    bootstraps: int

    def to_dict(self) -> dict[str, float | int]:
        return {"p_value": self.p_value, "statistic": self.statistic,
                "best_strategy": self.best_strategy, "bootstraps": self.bootstraps}


def superior_predictive_ability(excess_returns: np.ndarray, *, bootstraps: int = 2000,
                                mean_block: float = 10.0, seed: int = 0) -> SuperiorAbility:
    """Hansen's consistent SPA test that no strategy beats the benchmark.

    ``excess_returns`` is (periods x strategies): each strategy's per-period
    return minus the benchmark's (for "beats doing nothing", the returns
    themselves). A small p-value means the best strategy's edge is unlikely
    to be data-snooping luck across all the strategies tried.
    """

    matrix = np.asarray(excess_returns, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix[:, None]
    if matrix.ndim != 2 or matrix.shape[0] < 10 or not np.isfinite(matrix).all():
        raise ValueError("excess_returns must be a finite (periods x strategies) matrix with 10+ periods")
    periods = matrix.shape[0]
    rng = np.random.default_rng(seed)
    means = matrix.mean(axis=0)
    resampled = np.empty((bootstraps, matrix.shape[1]))
    for b in range(bootstraps):
        resampled[b] = matrix[stationary_bootstrap_indices(periods, mean_block, rng)].mean(axis=0)
    # omega_k: bootstrap standard deviation of sqrt(n) * mean excess return.
    omega = np.sqrt(periods) * resampled.std(axis=0, ddof=1)
    omega = np.where(omega > 0, omega, np.inf)
    t_values = np.sqrt(periods) * means / omega
    statistic = max(0.0, float(np.max(t_values)))
    # SPA_c recentring: a strategy clearly worse than the benchmark keeps its own
    # (negative) mean under the null, so poor strategies cannot inflate it; the
    # rest are held at the least favourable mean, zero.
    clearly_worse = t_values <= -np.sqrt(2.0 * np.log(np.log(periods)))
    null_mean = np.where(clearly_worse, means, 0.0)
    null = np.sqrt(periods) * (resampled - means + null_mean) / omega
    null_max = np.maximum(null.max(axis=1), 0.0)
    p_value = float((np.sum(null_max >= statistic) + 1) / (bootstraps + 1))
    return SuperiorAbility(p_value, statistic, int(np.argmax(means / omega)), bootstraps)


def holm_adjusted(p_values: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values (family-wise error control)."""

    values = np.asarray(p_values, dtype=float)
    if values.size == 0:
        return []
    order = np.argsort(values)
    adjusted = np.empty_like(values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (values.size - rank) * values[index]))
        adjusted[index] = running
    return adjusted.tolist()


def newey_west_t_stat(returns: Sequence[float] | np.ndarray, lags: int | None = None) -> float:
    """t-statistic of the mean return robust to autocorrelation and heteroskedasticity."""

    values = _clean(returns)
    count = values.size
    if lags is None:
        lags = int(math.floor(4.0 * (count / 100.0) ** (2.0 / 9.0)))
    if lags < 0 or lags >= count:
        raise ValueError("lags must be in [0, observations)")
    centred = values - values.mean()
    variance = float(np.dot(centred, centred)) / count
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        variance += 2.0 * weight * float(np.dot(centred[lag:], centred[:-lag])) / count
    if variance <= 0.0:
        raise ValueError("returns have no long-run variance")
    return float(values.mean()) / math.sqrt(variance / count)

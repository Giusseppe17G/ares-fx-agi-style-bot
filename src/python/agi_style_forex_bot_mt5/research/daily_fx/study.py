"""Predeclared daily FX portfolio study: development first, holdout once.

The plan (hypotheses, variants, periods, costs, risk limits, controls,
acceptance thresholds, the sha256 of the data files and of the engine code)
is frozen as canonical JSON and hashed before any result exists. A run refuses
data or engine code that differ from the plan.

Development only ever sees data up to the development end. It evaluates every
configuration of every hypothesis; all of them count as trials for the
deflated Sharpe ratio, the probability of backtest overfitting and the
superior-predictive-ability test, and every one is written to the trial
ledger. Each primary configuration is also compared with random-sign signals
and with its own signal shifted in time (same turnover, no alignment with
returns), its flipped signal and doubled costs. The time-shift control gates
only hypotheses that claim timing: a nearly static signal such as the sign of
a rate differential keeps its exposure when shifted, so for it the shift
measures nothing and is only reported.

Only hypotheses whose primary configuration passes every development gate are
scored on the holdout, and the holdout of a plan is scored once. The ledger,
not the development JSON, decides which hypotheses proceed (the JSON must
match the digest the ledger recorded), and it refuses any run whose windows
overlap a holdout already scored, or a holdout whose window another plan's
development already used, on the same price data. Verdicts are research
labels (PASSED_RESEARCH, WATCHLIST, REJECTED); none of them authorises
execution.
Nothing here builds, checks or sends an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from pathlib import Path
import platform
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..edge_statistics import (deflated_sharpe_ratio, holm_adjusted, moments, newey_west_t_stat,
    probabilistic_sharpe_ratio, probability_of_backtest_overfitting, sharpe_ratio, superior_predictive_ability)
from ..trial_registry import TrialLedger
from .data import PricePanel
from .portfolio import BacktestResult, CostModel, PortfolioConfig, RiskLimits, backtest, performance, signal_flip_rate

STUDY_VERSION = "daily_fx_study_v2"
RATE_SIGNALS = {"tscarry", "blend"}
# Files whose code decides every number of a study; their sha256 is part of the plan.
ENGINE_FILES = ("daily_fx/data.py", "daily_fx/portfolio.py", "daily_fx/study.py", "daily_fx/plans.py",
                "daily_fx/runner.py", "edge_statistics.py", "trial_registry.py")
STRESS_WINDOWS = {
    "2008-10_crisis": ("2008-10-01", "2008-10-31"),
    "2009-03_to_2010-06_recovery": ("2009-03-01", "2010-06-30"),
    "2015-01_chf_floor": ("2015-01-01", "2015-01-31"),
    "2020-03_covid": ("2020-03-01", "2020-03-31"),
    "2022_usd_rally": ("2022-01-01", "2022-12-31"),
    "2024-08_yen_unwind": ("2024-07-15", "2024-08-31"),
}


def environment() -> dict[str, str]:
    """Interpreter and numerical library versions a plan's numbers depend on."""

    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}


def digest(payload: Mapping[str, Any]) -> str:
    """sha256 of a JSON payload in canonical form (stable across a write and read)."""

    canonical = json.loads(json.dumps(payload, sort_keys=True, default=float))
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def engine_sha256() -> str:
    """sha256 of the engine sources (line endings normalised)."""

    root = Path(__file__).resolve().parent.parent
    digest = sha256()
    for name in ENGINE_FILES:
        text = (root / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        digest.update(name.encode("utf-8") + b"\0" + text.encode("utf-8") + b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    description: str
    primary: PortfolioConfig
    variants: tuple[PortfolioConfig, ...] = ()
    carry_accrual: bool = False  # returns include the interest differential (needs rates)
    timing_claim: bool = True  # gate on the time-shifted control (False for static premia)

    def configs(self) -> tuple[PortfolioConfig, ...]:
        return (self.primary, *self.variants)

    @property
    def needs_rates(self) -> bool:
        return self.carry_accrual or any(config.signal in RATE_SIGNALS for config in self.configs())

    def to_dict(self) -> dict[str, Any]:
        return {"hypothesis_id": self.hypothesis_id, "description": self.description,
                "primary": self.primary.to_dict(), "variants": [config.to_dict() for config in self.variants],
                "carry_accrual": self.carry_accrual, "timing_claim": self.timing_claim}


@dataclass(frozen=True)
class Acceptance:
    # Development gates (all must hold).
    min_development_sharpe: float = 0.3
    min_development_hac_t: float = 2.0
    max_holm_p_value: float = 0.05
    min_development_dsr: float = 0.95
    max_development_pbo: float = 0.30
    max_spa_p_value: float = 0.05
    max_random_quota: float = 0.05
    max_shift_quota: float = 0.05
    min_stressed_sharpe: float = 0.0
    max_development_drawdown: float = 0.12
    max_currency_share: float = 0.5
    # Holdout: REJECTED unless all three hold; PASSED_RESEARCH also needs the last two.
    min_holdout_sharpe: float = 0.0
    max_holdout_drawdown: float = 0.12
    min_holdout_stressed_sharpe: float = 0.0
    min_holdout_hac_t: float = 2.0
    max_promotion_pbo: float = 0.10

    def to_dict(self) -> dict[str, float]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class DataBinding:
    price_source: str
    price_sha256: str
    rates_sha256: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class StudyPlan:
    name: str
    currencies: tuple[str, ...]
    development: tuple[str, str]
    holdout: tuple[str, str]
    hypotheses: tuple[Hypothesis, ...]
    costs: CostModel
    data: DataBinding
    limits: RiskLimits = field(default_factory=RiskLimits)
    cost_stress_factor: float = 2.0
    random_replicas: int = 200
    pbo_blocks: int = 16
    spa_bootstraps: int = 2000
    acceptance: Acceptance = field(default_factory=Acceptance)
    engine: str = field(default_factory=engine_sha256)
    runtime: Mapping[str, str] = field(default_factory=environment)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"study_version": STUDY_VERSION, "name": self.name, "currencies": list(self.currencies),
                "development": list(self.development), "holdout": list(self.holdout),
                "hypotheses": [item.to_dict() for item in self.hypotheses],
                "costs": {"one_way_bps": dict(sorted(self.costs.one_way_bps.items())),
                          "financing_bps_per_year": self.costs.financing_bps_per_year},
                "data": self.data.to_dict(), "limits": self.limits.to_dict(),
                "cost_stress_factor": self.cost_stress_factor, "random_replicas": self.random_replicas,
                "pbo_blocks": self.pbo_blocks, "spa_bootstraps": self.spa_bootstraps,
                "acceptance": self.acceptance.to_dict(), "engine_sha256": self.engine,
                "environment": dict(sorted(self.runtime.items())),
                "stress_windows": {key: list(value) for key, value in STRESS_WINDOWS.items()},
                "notes": list(self.notes)}

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def plan_hash(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def validate(self) -> None:
        if not self.hypotheses or len({item.hypothesis_id for item in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("hypotheses must be non-empty with unique ids")
        if pd.Timestamp(self.development[1]) >= pd.Timestamp(self.holdout[0]):
            raise ValueError("the holdout must start after development ends")
        if self.random_replicas < 19 or self.cost_stress_factor < 1.0:
            raise ValueError("at least 19 random replicas and a cost stress factor >= 1 are required")
        for hypothesis in self.hypotheses:
            for config in hypothesis.configs():
                config.validate()
                if config.signal == "random" or config.flip or config.shift_days:
                    raise ValueError("controls are generated by the study, not declared as hypotheses")
            if hypothesis.needs_rates and self.data.rates_sha256 is None:
                raise ValueError(f"{hypothesis.hypothesis_id} needs rates bound to the plan")
            if any(config.signal in RATE_SIGNALS for config in hypothesis.configs()) and not hypothesis.carry_accrual:
                raise ValueError("a carry signal must earn the carry it bets on (carry_accrual)")
            if not hypothesis.timing_claim and any(config.signal != "tscarry" for config in hypothesis.configs()):
                raise ValueError("only static carry hypotheses may skip the time-shifted control")

    def check_inputs(self, panel: PricePanel, rates_sha256: str | None) -> None:
        """Fail closed when the data or the engine differ from what the plan froze."""

        self.validate()
        if tuple(panel.currencies) != tuple(self.currencies):
            raise ValueError("the price panel currencies differ from the plan")
        if panel.source != self.data.price_source or panel.source_sha256 != self.data.price_sha256:
            raise ValueError("the price data differ from the data bound to the plan")
        if self.data.rates_sha256 is not None and rates_sha256 != self.data.rates_sha256:
            raise ValueError("the rate data differ from the data bound to the plan")
        if self.engine != engine_sha256():
            raise ValueError("the engine code changed since the plan was frozen")
        if dict(self.runtime) != environment():
            raise ValueError("the Python, numpy or pandas version differs from the frozen plan")


def _overlaps(first: Sequence[str], second: Sequence[str]) -> bool:
    return pd.Timestamp(first[0]) <= pd.Timestamp(second[1]) and pd.Timestamp(second[0]) <= pd.Timestamp(first[1])


def _refuse_seen_data(plan: StudyPlan, ledger: TrialLedger, windows: Sequence[Sequence[str]]) -> None:
    """Refuse windows that overlap a holdout already scored on the same prices, by any plan."""

    for record in ledger.records():
        payload = record["payload"]
        if record["kind"] != "holdout" or payload.get("price_sha256") != plan.data.price_sha256:
            continue
        if any(_overlaps(window, payload["holdout_window"]) for window in windows):
            raise ValueError(f"these dates overlap a holdout already scored by plan {record['plan_hash'][:12]}")


def _window(series: pd.Series, period: tuple[str, str]) -> pd.Series:
    start, end = (pd.Timestamp(value, tz="UTC") for value in period)
    return series.loc[start:end]


def _sharpe_or_zero(values: pd.Series) -> float:
    try:
        return sharpe_ratio(values.to_numpy())
    except ValueError:
        return 0.0


def _stats(values: pd.Series) -> dict[str, float]:
    stats = performance(values)
    try:
        stats["hac_t_stat"] = newey_west_t_stat(values.to_numpy())
    except ValueError:
        stats["hac_t_stat"] = 0.0
    return stats


def _simulate(prices: pd.DataFrame, rates: pd.DataFrame | None, hypothesis: Hypothesis, config: PortfolioConfig,
              costs: CostModel, limits: RiskLimits) -> BacktestResult:
    return backtest(prices, config, costs, limits, rates if hypothesis.needs_rates else None)


def _currency_share(result: BacktestResult, period: tuple[str, str]) -> float:
    contributions = result.contributions.loc[pd.Timestamp(period[0], tz="UTC"):pd.Timestamp(period[1], tz="UTC")]
    by_currency = contributions.sum()
    total = float(by_currency.sum())
    return float(by_currency.max() / total) if total > 0 else 1.0


def _yearly(values: pd.Series) -> dict[str, float]:
    return {str(year): float(value) for year, value in values.groupby(values.index.year).sum().items()}


def _stress(values: pd.Series) -> dict[str, float | None]:
    report: dict[str, float | None] = {}
    for key, period in STRESS_WINDOWS.items():
        inside = _window(values, period)
        report[key] = float(np.expm1(inside.sum())) if len(inside) else None
    return report


def _development_inputs(plan: StudyPlan, panel: PricePanel,
                        rates: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    # Development never sees a price or a rate after the development end.
    end = pd.Timestamp(plan.development[1], tz="UTC")
    prices = panel.prices.loc[:end]
    if rates is None:
        return prices, None
    last_month = end.tz_convert(None).to_period("M")
    return prices, rates.loc[rates.index <= last_month]


def _shift_offsets(length: int, config: PortfolioConfig, replicas: int, seed: int) -> list[int]:
    # Distinct shifts that keep every shifted signal at least a look-back plus a
    # holding period away from the returns it is scored on, in both directions.
    margin = max(config.lookbacks) + config.rebalance_days + config.execution_lag_days
    if length - 2 * margin < replicas:
        raise ValueError("development history too short for time-shifted controls")
    rng = np.random.default_rng(seed)
    return sorted(int(value) for value in rng.choice(np.arange(margin, length - margin), size=replicas, replace=False))


def run_development(plan: StudyPlan, panel: PricePanel, rates: pd.DataFrame | None, rates_sha256: str | None,
                    ledger: TrialLedger) -> dict[str, Any]:
    """Evaluate every predeclared configuration on the development period."""

    plan.check_inputs(panel, rates_sha256)
    plan_hash = plan.plan_hash()
    if ledger.has("development_summary", plan_hash):
        raise ValueError("the development of this plan was already run; its trials are in the ledger")
    _refuse_seen_data(plan, ledger, [plan.development, plan.holdout])
    prices, dev_rates = _development_inputs(plan, panel, rates)
    if any(item.needs_rates for item in plan.hypotheses) and dev_rates is None:
        raise ValueError("the plan needs rates")
    limits, costs = plan.limits, plan.costs
    trial_returns: dict[str, pd.Series] = {}
    primaries: dict[str, BacktestResult] = {}
    for hypothesis in plan.hypotheses:
        for index, config in enumerate(hypothesis.configs()):
            key = f"{hypothesis.hypothesis_id}:{index}"
            result = _simulate(prices, dev_rates, hypothesis, config, costs, limits)
            returns = _window(result.net_returns, plan.development)
            trial_returns[key] = returns
            if index == 0:
                primaries[hypothesis.hypothesis_id] = result
            stats = _stats(returns)
            ledger.append("development_trial", plan_hash, {
                "trial": key, "config": config.to_dict(), "carry_accrual": hypothesis.carry_accrual,
                "config_sha256": sha256(json.dumps(config.to_dict(), sort_keys=True).encode()).hexdigest(),
                "first_day": str(returns.index.min().date()), "last_day": str(returns.index.max().date()),
                "metrics": stats})
    matrix = pd.DataFrame(trial_returns).dropna()
    # Each trial's Sharpe on its own window, like the primary it deflates.
    trial_sharpes = [_sharpe_or_zero(values) for values in trial_returns.values()]
    pbo = probability_of_backtest_overfitting(matrix.to_numpy(), blocks=plan.pbo_blocks)
    spa = superior_predictive_ability(matrix.to_numpy(), bootstraps=plan.spa_bootstraps)
    results, p_values = [], []
    for number, hypothesis in enumerate(plan.hypotheses):
        result = primaries[hypothesis.hypothesis_id]
        primary = trial_returns[f"{hypothesis.hypothesis_id}:0"]
        stats = _stats(primary)
        gross = _window(result.gross_returns, plan.development)
        dsr = deflated_sharpe_ratio(primary.to_numpy(), trial_sharpes)
        skew, kurtosis = moments(primary.to_numpy())
        psr_zero = probabilistic_sharpe_ratio(dsr.sharpe, 0.0, len(primary), skew, kurtosis)
        p_values.append(1.0 - psr_zero)

        def control_sharpe(config: PortfolioConfig) -> float:
            simulated = _simulate(prices, dev_rates, hypothesis, config, costs, limits)
            return _sharpe_or_zero(_window(simulated.net_returns, plan.development))

        # Random signs as persistent as the primary signal (same turnover).
        flip_rate = signal_flip_rate(prices, hypothesis.primary, dev_rates if hypothesis.needs_rates else None)
        random_sharpes = np.array([control_sharpe(replace(hypothesis.primary, signal="random", seed=seed,
                                                          random_flip_probability=flip_rate))
                                   for seed in range(plan.random_replicas)])
        valid_rows = int(result.positions.shape[0])
        shifts = _shift_offsets(valid_rows, hypothesis.primary, plan.random_replicas, seed=1000 + number)
        shift_sharpes = np.array([control_sharpe(replace(hypothesis.primary, shift_days=shift)) for shift in shifts])
        random_quota = float((np.sum(random_sharpes >= dsr.sharpe) + 1) / (plan.random_replicas + 1))
        shift_quota = float((np.sum(shift_sharpes >= dsr.sharpe) + 1) / (plan.random_replicas + 1))
        flipped = _window(_simulate(prices, dev_rates, hypothesis, replace(hypothesis.primary, flip=True),
                                    costs, limits).net_returns, plan.development)
        stressed = _window(_simulate(prices, dev_rates, hypothesis, hypothesis.primary,
                                     costs.scaled(plan.cost_stress_factor), limits).net_returns, plan.development)
        variants = {key: _stats(values) for key, values in trial_returns.items()
                    if key.startswith(f"{hypothesis.hypothesis_id}:") and key != f"{hypothesis.hypothesis_id}:0"}
        ledger.append("development_controls", plan_hash, {
            "hypothesis_id": hypothesis.hypothesis_id, "random_sharpes": random_sharpes.tolist(),
            "shift_days": shifts, "shift_sharpes": shift_sharpes.tolist()})
        results.append({
            "hypothesis_id": hypothesis.hypothesis_id,
            "primary": stats,
            "gross_primary": _stats(gross),
            "stops": result.stops, "take_profits": result.take_profits,
            "blocked_rebalances": result.blocked_rebalances,
            "mean_gross_exposure": float(result.positions.abs().sum(axis=1).mean()),
            "currency_share": _currency_share(result, plan.development),
            "yearly_returns": _yearly(primary),
            "stress_windows": _stress(primary),
            "psr_vs_zero": psr_zero,
            "deflated_sharpe": dsr.to_dict(),
            "random_control": {"replicas": plan.random_replicas, "median_sharpe": float(np.median(random_sharpes)),
                               "quota": random_quota, "flip_probability": flip_rate},
            "shift_control": {"replicas": plan.random_replicas, "median_sharpe": float(np.median(shift_sharpes)),
                              "quota": shift_quota, "gated": hypothesis.timing_claim},
            "flipped_sharpe": _stats(flipped)["sharpe"],
            "cost_stress": {"factor": plan.cost_stress_factor, "sharpe": _stats(stressed)["sharpe"]},
            "variants": variants,
        })
    adjusted = holm_adjusted(p_values)
    acceptance = plan.acceptance
    for result, holm_p in zip(results, adjusted):
        result["holm_adjusted_p"] = holm_p
        checks = {key: bool(value) for key, value in {
            "development_sharpe": result["primary"]["sharpe"] >= acceptance.min_development_sharpe,
            "hac_t_stat": result["primary"]["hac_t_stat"] >= acceptance.min_development_hac_t,
            "holm_adjusted_p": holm_p <= acceptance.max_holm_p_value,
            "deflated_sharpe": result["deflated_sharpe"]["deflated_sharpe_ratio"] >= acceptance.min_development_dsr,
            "probability_of_backtest_overfitting": pbo.pbo <= acceptance.max_development_pbo,
            "superior_predictive_ability": spa.p_value <= acceptance.max_spa_p_value,
            "beats_random_signals": result["random_control"]["quota"] <= acceptance.max_random_quota,
            "beats_time_shifted_signals": (not result["shift_control"]["gated"]
                                           or result["shift_control"]["quota"] <= acceptance.max_shift_quota),
            "survives_stressed_costs": result["cost_stress"]["sharpe"] > acceptance.min_stressed_sharpe,
            "development_drawdown": result["primary"]["max_drawdown"] < acceptance.max_development_drawdown,
            "no_dominant_currency": result["currency_share"] <= acceptance.max_currency_share,
        }.items()}
        result["checks"] = checks
        result["proceed_to_holdout"] = all(checks.values())
    summary = {"study_version": STUDY_VERSION, "phase": "development", "plan_hash": plan_hash,
               "engine_sha256": plan.engine,
               "data": {"source": panel.source, "sha256": panel.source_sha256, "rates_sha256": rates_sha256,
                        "first_day": str(matrix.index.min().date()), "last_day": str(matrix.index.max().date()),
                        "common_days": int(len(matrix))},
               "trials": len(trial_sharpes), "pbo": pbo.to_dict(), "spa": spa.to_dict(), "hypotheses": results,
               "execution_authorized": False}
    ledger.append("development_summary", plan_hash, {
        "trials": len(trial_sharpes), "pbo": pbo.pbo, "spa_p_value": spa.p_value,
        "price_sha256": plan.data.price_sha256, "development_window": list(plan.development),
        "proceed_to_holdout": {item["hypothesis_id"]: item["proceed_to_holdout"] for item in results},
        "summary_sha256": digest(summary)})
    return summary


def run_holdout(plan: StudyPlan, panel: PricePanel, rates: pd.DataFrame | None, rates_sha256: str | None,
                development: Mapping[str, Any], ledger: TrialLedger, output: str | Path) -> dict[str, Any]:
    """Score the holdout once for hypotheses that passed development."""

    plan.check_inputs(panel, rates_sha256)
    plan_hash = plan.plan_hash()
    if ledger.has("holdout", plan_hash):
        raise ValueError("the holdout of this plan was already scored; it is scored exactly once")
    if development.get("plan_hash") != plan_hash or development.get("phase") != "development":
        raise ValueError("development results do not belong to this plan")
    summaries = [record for record in ledger.records()
                 if record["kind"] == "development_summary" and record["plan_hash"] == plan_hash]
    if len(summaries) != 1:
        raise ValueError("the ledger has no single development run of this plan")
    recorded = summaries[0]["payload"]
    if digest(development) != recorded["summary_sha256"]:
        raise ValueError("the development results differ from what the ledger recorded")
    ids = [item.hypothesis_id for item in plan.hypotheses]
    if sorted(recorded["proceed_to_holdout"]) != sorted(ids):
        raise ValueError("the ledgered development does not cover exactly this plan's hypotheses")
    _refuse_seen_data(plan, ledger, [plan.holdout])
    for record in ledger.records():
        payload = record["payload"]
        if (record["kind"] == "development_summary" and record["plan_hash"] != plan_hash
                and payload.get("price_sha256") == plan.data.price_sha256
                and _overlaps(payload["development_window"], plan.holdout)):
            raise ValueError(f"plan {record['plan_hash'][:12]} already developed on these holdout dates")
    target = Path(output)
    if target.exists():
        raise FileExistsError("refusing to overwrite an existing holdout result")
    acceptance = plan.acceptance
    pbo_ok = float(recorded["pbo"]) <= acceptance.max_promotion_pbo
    results = []
    for hypothesis in plan.hypotheses:
        if not recorded["proceed_to_holdout"][hypothesis.hypothesis_id]:
            results.append({"hypothesis_id": hypothesis.hypothesis_id, "evaluated": False,
                            "verdict": "REJECTED", "reason": "failed development gates"})
            continue
        result = _simulate(panel.prices, rates, hypothesis, hypothesis.primary, plan.costs, plan.limits)
        returns = _window(result.net_returns, plan.holdout)
        stressed = _window(_simulate(panel.prices, rates, hypothesis, hypothesis.primary,
                                     plan.costs.scaled(plan.cost_stress_factor), plan.limits).net_returns,
                           plan.holdout)
        stats = _stats(returns)
        skew, kurtosis = moments(returns.to_numpy())
        psr = probabilistic_sharpe_ratio(_sharpe_or_zero(returns), 0.0, len(returns), skew, kurtosis)
        survives = {"holdout_sharpe": bool(stats["sharpe"] > acceptance.min_holdout_sharpe),
                    "holdout_drawdown": bool(stats["max_drawdown"] < acceptance.max_holdout_drawdown),
                    "holdout_stressed_costs": bool(_stats(stressed)["sharpe"] > acceptance.min_holdout_stressed_sharpe)}
        promotes = {"holdout_hac_t_stat": bool(stats["hac_t_stat"] >= acceptance.min_holdout_hac_t),
                    "development_pbo_promotion_grade": bool(pbo_ok)}
        verdict = ("REJECTED" if not all(survives.values())
                   else "PASSED_RESEARCH" if all(promotes.values()) else "WATCHLIST")
        results.append({"hypothesis_id": hypothesis.hypothesis_id, "evaluated": True, "holdout": stats,
                        "first_day": str(returns.index.min().date()), "last_day": str(returns.index.max().date()),
                        "psr_vs_zero": psr, "currency_share": _currency_share(result, plan.holdout),
                        "stressed_sharpe": _stats(stressed)["sharpe"], "checks": {**survives, **promotes},
                        "verdict": verdict, "yearly_returns": _yearly(returns), "stress_windows": _stress(returns)})
    summary = {"study_version": STUDY_VERSION, "phase": "holdout", "plan_hash": plan_hash,
               "engine_sha256": plan.engine,
               "data": {"source": panel.source, "sha256": panel.source_sha256, "rates_sha256": rates_sha256},
               "hypotheses": results, "execution_authorized": False}
    # Record first, with the full result: a crash after this line can never lead to a second scoring.
    ledger.append("holdout", plan_hash, {**summary, "price_sha256": plan.data.price_sha256,
                                         "holdout_window": list(plan.holdout)})
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, default=float)
        handle.write("\n")
    return summary


def hypotheses_from_grid(hypothesis_id: str, description: str, primary: PortfolioConfig,
                         grid: Mapping[str, Sequence[Any]], carry_accrual: bool = False,
                         timing_claim: bool = True) -> Hypothesis:
    """Primary configuration plus every single-parameter variation in ``grid``."""

    variants = []
    for key, values in grid.items():
        for value in values:
            value = tuple(int(item) for item in value) if key == "lookbacks" else value
            if getattr(primary, key) != value:
                variants.append(replace(primary, **{key: value}))
    return Hypothesis(hypothesis_id, description, primary, tuple(variants), carry_accrual, timing_claim)

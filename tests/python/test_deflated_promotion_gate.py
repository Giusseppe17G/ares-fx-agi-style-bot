"""Deflated Strategy Promotion Gate (PROJECT_SPEC.md 12.1).

Decision: docs/decisions/2026-10-22-deflated-promotion-gate.md. Demo mode now
needs the shadow-approval minimums, the Phase 8 forward-shadow evidence and
deflated statistics (PSR/MinTRL, DSR given the trials tried, Newey-West t,
PBO). Shadow mode is unchanged. Zero-edge universes built with fixed seeds
must be rejected at least 95% of the time, while a planted strong edge with a
single trial and complete forward evidence passes. Nothing here can execute:
the broker release lock holds regardless of the gate.
"""

from __future__ import annotations

from dataclasses import fields, replace
import json
import math

import numpy as np
import pytest

from agi_style_forex_bot_mt5.research.edge_statistics import probability_of_backtest_overfitting
from agi_style_forex_bot_mt5.strategy import PromotionEvidence, evaluate_promotion_gate

# The checks the gate ran before this change, with their thresholds unchanged.
LEGACY_CHECKS = (
    "sample_size",
    "profit_factor",
    "expected_payoff",
    "drawdown",
    "profit_concentration",
    "spread_slippage_sensitivity",
    "walk_forward",
    "shadow_forward",
)
STATISTICAL_CHECKS = ("psr_zero", "min_track_record_length", "deflated_sharpe", "newey_west_t", "pbo")

LEGACY_DEFAULTS = {
    "historical_trades": 0,
    "statistical_justification": "",
    "oos_profit_factor": 0.0,
    "oos_expected_payoff": 0.0,
    "oos_max_drawdown_pct": 100.0,
    "max_drawdown_limit_pct": 0.0,
    "max_profit_concentration_pct": 100.0,
    "spread_slippage_sensitivity_passed": False,
    "walk_forward_passed": False,
    "optimization_used": False,
    "shadow_signals": 0,
    "shadow_days": 0,
    "shadow_audit_complete": False,
}


def _trades(rng: np.random.Generator, count: int, mean_r: float, payoff: float = 1.5) -> np.ndarray:
    """Fixed-target trades in R: +payoff or -1, with the requested expectancy."""

    win_probability = (mean_r + 1.0) / (payoff + 1.0)
    return np.where(rng.random(count) < win_probability, payoff, -1.0)


def _profit_factor(values: np.ndarray) -> float:
    return float(values[values > 0].sum() / -values[values < 0].sum())


def _sharpes(matrix: np.ndarray) -> np.ndarray:
    return matrix.mean(axis=0) / matrix.std(axis=0, ddof=1)


def _complete_evidence(returns: np.ndarray, **overrides: object) -> PromotionEvidence:
    """Evidence on which every non-statistical item passes.

    That is the worst case for the statistical checks: only they stand between
    the return sequence and demo approval.
    """

    values = np.asarray(returns, dtype=float)
    base: dict[str, object] = {
        "historical_trades": max(int(values.size), 300),
        "oos_profit_factor": 1.40,
        "oos_expected_payoff": 3.0,
        "oos_expectancy_r": 0.20,
        "oos_max_drawdown_pct": 8.0,
        "max_drawdown_limit_pct": 10.0,
        "max_profit_concentration_pct": 30.0,
        "spread_slippage_sensitivity_passed": True,
        "walk_forward_passed": True,
        "optimization_used": True,
        "shadow_signals": 260,
        "shadow_days": 21,
        "shadow_audit_complete": True,
        "shadow_approval_classification": "APPROVED_FOR_SHADOW_OBSERVATION",
        "forward_paper_trades": 220,
        "forward_profit_factor": 1.30,
        "forward_expectancy_r": 0.12,
        "forward_controls_passed": True,
        "return_sequence": tuple(float(value) for value in values),
        "trials": 1,
        "pbo": 0.0,
    }
    base.update(overrides)
    return PromotionEvidence(**base)


def _planted_edge(seed: int = 20261022, count: int = 500, mean_r: float = 0.35) -> np.ndarray:
    return _trades(np.random.default_rng(seed), count, mean_r)


def _demo(evidence: object):
    return evaluate_promotion_gate(evidence, requested_mode="demo")


def test_existing_fields_keep_their_defaults() -> None:
    defaults = {item.name: item.default for item in fields(PromotionEvidence)}

    for name, value in LEGACY_DEFAULTS.items():
        assert defaults[name] == value


def test_default_evidence_fails_every_new_check() -> None:
    decision = _demo(PromotionEvidence())

    assert decision.approved is False
    assert decision.effective_mode == "shadow"
    for name in (
        "shadow_approval_classification",
        "shadow_approval_sample_size",
        "shadow_approval_profit_factor",
        "shadow_approval_expectancy_r",
        "forward_shadow_duration",
        "forward_shadow_trades",
        "forward_profit_factor",
        "forward_expectancy_r",
        "forward_controls",
        "trials_declared",
        *STATISTICAL_CHECKS,
    ):
        assert decision.checks[name] is False, name
        assert f"promotion gate failed: {name}" in decision.reasons


def test_missing_evidence_is_rejected_in_demo_mode() -> None:
    for evidence in (None, {}):
        decision = _demo(evidence)
        assert decision.approved is False
        assert decision.effective_mode == "shadow"


def test_shadow_mode_is_unchanged() -> None:
    for evidence in (None, PromotionEvidence(), _complete_evidence(_planted_edge())):
        decision = evaluate_promotion_gate(evidence, requested_mode="shadow")
        assert decision.approved is True
        assert decision.effective_mode == "shadow"
        assert decision.reasons == ("shadow mode only; signals are for audit, not execution",)
        assert dict(decision.checks) == {"shadow_mode_allowed": True}


def test_unsupported_mode_is_unchanged() -> None:
    decision = evaluate_promotion_gate(_complete_evidence(_planted_edge()), requested_mode="live")

    assert decision.approved is False
    assert decision.reasons == ("unsupported strategy mode",)


def test_planted_strong_edge_with_one_trial_and_forward_evidence_passes() -> None:
    returns = _planted_edge()
    decision = _demo(_complete_evidence(returns))

    assert decision.approved is True, decision.reasons
    assert decision.effective_mode == "demo"
    assert all(decision.checks.values())
    stats = decision.statistics
    assert stats["observations"] == returns.size
    assert stats["psr_zero"] >= 0.95
    assert stats["observations"] >= stats["min_track_record_length"]
    assert stats["deflated_sharpe"] >= 0.95
    assert stats["newey_west_t"] >= 3.0
    assert stats["newey_west_t_threshold"] == 3.0
    assert stats["trials"] == 1
    # The audit payload must serialise without NaN or infinity.
    json.dumps(stats, allow_nan=False)


def test_planted_strong_edge_has_power_across_seeds() -> None:
    approved = sum(_demo(_complete_evidence(_planted_edge(seed=9000 + seed))).approved for seed in range(100))

    assert approved >= 95


@pytest.mark.parametrize(
    ("field_name", "failing_value", "check"),
    [
        ("shadow_approval_classification", "", "shadow_approval_classification"),
        ("shadow_approval_classification", "WATCHLIST", "shadow_approval_classification"),
        ("oos_expectancy_r", 0.0, "shadow_approval_expectancy_r"),
        ("forward_paper_trades", 0, "forward_shadow_trades"),
        ("forward_profit_factor", 0.0, "forward_profit_factor"),
        ("forward_expectancy_r", 0.0, "forward_expectancy_r"),
        ("forward_controls_passed", False, "forward_controls"),
        ("trials", 0, "trials_declared"),
        ("trials", 0, "deflated_sharpe"),
        ("pbo", None, "pbo"),
        ("return_sequence", (), "psr_zero"),
        ("return_sequence", (), "min_track_record_length"),
        ("return_sequence", (), "deflated_sharpe"),
        ("return_sequence", (), "newey_west_t"),
    ],
)
def test_each_new_field_at_its_default_fails_its_check(field_name: str, failing_value: object, check: str) -> None:
    evidence = replace(_complete_evidence(_planted_edge()), **{field_name: failing_value})

    decision = _demo(evidence)

    assert decision.approved is False
    assert decision.checks[check] is False


@pytest.mark.parametrize(
    ("overrides", "check", "expected"),
    [
        ({"historical_trades": 299}, "shadow_approval_sample_size", False),
        ({"historical_trades": 299, "statistical_justification": "   "}, "shadow_approval_sample_size", False),
        ({"historical_trades": 299, "statistical_justification": "power analysis in the study plan"}, "shadow_approval_sample_size", True),
        ({"historical_trades": 300}, "shadow_approval_sample_size", True),
        ({"oos_profit_factor": 1.25}, "shadow_approval_profit_factor", False),
        ({"oos_profit_factor": 1.2501}, "shadow_approval_profit_factor", True),
        ({"oos_max_drawdown_pct": 12.0, "max_drawdown_limit_pct": 20.0}, "shadow_approval_drawdown", False),
        ({"oos_max_drawdown_pct": 11.9, "max_drawdown_limit_pct": 20.0}, "shadow_approval_drawdown", True),
        ({"shadow_days": 13}, "forward_shadow_duration", False),
        ({"shadow_days": 14}, "forward_shadow_duration", True),
        ({"forward_paper_trades": 199}, "forward_shadow_trades", False),
        ({"forward_paper_trades": 200}, "forward_shadow_trades", True),
        ({"forward_profit_factor": 1.15}, "forward_profit_factor", False),
        ({"forward_profit_factor": 1.1501}, "forward_profit_factor", True),
        ({"pbo": 0.10}, "pbo", True),
        ({"pbo": 0.1001}, "pbo", False),
        ({"pbo": float("nan")}, "pbo", False),
        ({"pbo": -0.01}, "pbo", False),
    ],
)
def test_thresholds_are_the_strictest_of_the_overlapping_rules(overrides: dict, check: str, expected: bool) -> None:
    decision = _demo(_complete_evidence(_planted_edge(), **overrides))

    assert decision.checks[check] is expected
    assert decision.approved is all(decision.checks.values())


def test_legacy_thresholds_still_apply() -> None:
    decision = _demo(_complete_evidence(_planted_edge(), oos_max_drawdown_pct=9.0, max_drawdown_limit_pct=8.0))

    assert decision.checks["drawdown"] is False
    assert decision.approved is False


def _caller_statistics(**overrides: object) -> PromotionEvidence:
    values: dict[str, object] = {
        "return_sequence": (),
        "psr_zero": 0.999,
        "min_track_record_length": 120.0,
        "sharpe_observations": 400,
        "deflated_sharpe": 0.99,
        "newey_west_t": 2.5,
        "trials": 1,
        "pbo": 0.0,
    }
    values.update(overrides)
    return _complete_evidence(_planted_edge(), **values)


def test_caller_computed_statistics_are_accepted_without_a_sequence() -> None:
    decision = _demo(_caller_statistics(newey_west_t=3.2))

    assert decision.approved is True, decision.reasons


def test_newey_west_threshold_relaxes_only_for_one_preregistered_trial() -> None:
    strict = _demo(_caller_statistics())
    relaxed = _demo(_caller_statistics(single_preregistered_hypothesis=True))
    contradictory = _demo(_caller_statistics(single_preregistered_hypothesis=True, trials=3))
    text_flag = _demo(_caller_statistics(single_preregistered_hypothesis="yes"))

    assert strict.checks["newey_west_t"] is False
    assert relaxed.checks["newey_west_t"] is True and relaxed.approved is True
    assert relaxed.statistics["newey_west_t_threshold"] == 2.0
    assert contradictory.checks["newey_west_t"] is False
    assert text_flag.checks["newey_west_t"] is False


def test_min_track_record_length_must_be_reached() -> None:
    decision = _demo(_caller_statistics(newey_west_t=3.2, min_track_record_length=401.0))

    assert decision.checks["min_track_record_length"] is False


def test_the_less_favourable_source_wins() -> None:
    evidence = _complete_evidence(_planted_edge(), psr_zero=0.50, newey_west_t=1.0)

    decision = _demo(evidence)

    assert decision.checks["psr_zero"] is False
    assert decision.checks["newey_west_t"] is False
    assert decision.statistics["psr_zero"] == 0.50


def test_trials_raise_the_deflated_sharpe_benchmark() -> None:
    returns = _planted_edge(count=300, mean_r=0.12)
    one = _demo(_complete_evidence(returns, trials=1))
    many = _demo(_complete_evidence(returns, trials=1000))

    assert many.statistics["deflated_sharpe"] < one.statistics["deflated_sharpe"]
    assert many.statistics["dsr_benchmark_sharpe"] > 0.0 == one.statistics["dsr_benchmark_sharpe"]


def test_trial_sharpes_never_lower_the_benchmark_below_the_null() -> None:
    returns = _planted_edge(count=400, mean_r=0.2)
    count_only = _demo(_complete_evidence(returns, trials=20))
    tight = _demo(_complete_evidence(returns, trials=20, trial_sharpes=tuple([0.001] * 20)))
    wide = _demo(_complete_evidence(returns, trials=20, trial_sharpes=tuple(np.linspace(-0.5, 0.5, 20))))

    assert tight.statistics["dsr_benchmark_sharpe"] == pytest.approx(count_only.statistics["dsr_benchmark_sharpe"])
    assert wide.statistics["dsr_benchmark_sharpe"] > count_only.statistics["dsr_benchmark_sharpe"]
    # More trial Sharpes than declared trials: the larger count is used.
    more = _demo(_complete_evidence(returns, trials=2, trial_sharpes=tuple([0.01] * 50)))
    assert more.statistics["trials"] == 50


@pytest.mark.parametrize(
    "sequence",
    [
        (0.1, 0.2),
        (0.1, float("nan"), 0.3, 0.4),
        (1.0,) * 50,
        ("a", "b", "c"),
    ],
)
def test_unusable_return_sequence_fails_closed(sequence: tuple) -> None:
    decision = _demo(_complete_evidence(_planted_edge(), return_sequence=sequence))

    assert decision.approved is False
    assert decision.checks["deflated_inputs_valid"] is False
    for name in ("psr_zero", "min_track_record_length", "deflated_sharpe", "newey_west_t"):
        assert decision.checks[name] is False


def test_unusable_trial_sharpes_fail_closed() -> None:
    decision = _demo(_complete_evidence(_planted_edge(), trials=3, trial_sharpes=(0.1, float("inf"), 0.2)))

    assert decision.checks["deflated_inputs_valid"] is False
    assert decision.approved is False


def test_mapping_evidence_reaches_the_new_checks() -> None:
    evidence = _complete_evidence(_planted_edge())
    mapping = {item.name: getattr(evidence, item.name) for item in fields(PromotionEvidence)}
    mapping["return_sequence"] = list(mapping["return_sequence"])

    assert _demo(mapping).approved is True
    for key, value in (
        ("forward_controls_passed", "false"),
        ("spread_slippage_sensitivity_passed", "false"),
        ("walk_forward_passed", "no"),
        ("shadow_audit_complete", "0"),
        ("trials", "many"),
        ("trials", 2.5),
        ("pbo", "low"),
        ("return_sequence", "not a sequence"),
        ("forward_paper_trades", None),
        ("oos_expectancy_r", float("nan")),
    ):
        decision = _demo({**mapping, key: value})
        assert decision.approved is False, (key, value)


def test_textual_true_is_accepted_for_pass_flags() -> None:
    evidence = _complete_evidence(_planted_edge())
    mapping = {item.name: getattr(evidence, item.name) for item in fields(PromotionEvidence)}

    assert _demo({**mapping, "forward_controls_passed": "true", "walk_forward_passed": "True"}).approved is True


def _zero_edge_universe(seed: int, strategies: int, count: int) -> tuple[np.ndarray, np.ndarray, int]:
    rng = np.random.default_rng(seed)
    matrix = np.column_stack([_trades(rng, count, 0.0) for _ in range(strategies)])
    sharpes = _sharpes(matrix)
    return matrix, sharpes, int(np.argmax(sharpes))


@pytest.mark.parametrize(
    ("strategies", "count", "pbo_source", "trial_sharpes_supplied"),
    [
        (20, 400, "cscv", True),
        (20, 400, "favourable", True),
        (50, 300, "favourable", True),
        # Only the number of trials is known: the null Sharpe variance sets the benchmark.
        (20, 400, "favourable", False),
        (50, 300, "favourable", False),
    ],
)
def test_best_of_many_zero_edge_strategies_is_rejected(
    strategies: int, count: int, pbo_source: str, trial_sharpes_supplied: bool
) -> None:
    universes = 200
    approved = legacy_approved = legacy_profit_factor = 0
    for seed in range(universes):
        matrix, sharpes, best = _zero_edge_universe(1000 + seed, strategies, count)
        pbo = probability_of_backtest_overfitting(matrix, blocks=8).pbo if pbo_source == "cscv" else 0.0
        trial_sharpes = tuple(sharpes) if trial_sharpes_supplied else ()
        evidence = _complete_evidence(matrix[:, best], trials=strategies, trial_sharpes=trial_sharpes, pbo=pbo)
        decision = _demo(evidence)
        approved += decision.approved
        legacy_approved += all(decision.checks[name] for name in LEGACY_CHECKS)
        legacy_profit_factor += _profit_factor(matrix[:, best]) > 1.15

    assert approved / universes <= 0.05
    # The summary fields are the passing worst case, so the checks the gate ran
    # before this change approve every universe. Those summaries are realistic:
    # the selected zero-edge slice's own PF clears the old 1.15 bar most of the time.
    assert legacy_approved == universes
    assert legacy_profit_factor / universes >= 0.5


def test_single_preregistered_zero_edge_strategy_is_rejected() -> None:
    universes = 400
    approved = 0
    for seed in range(universes):
        returns = _trades(np.random.default_rng(5000 + seed), 300, 0.0)
        evidence = _complete_evidence(returns, trials=1, single_preregistered_hypothesis=True)
        approved += _demo(evidence).approved

    assert approved / universes <= 0.05


def test_rejections_name_the_failed_statistics() -> None:
    matrix, sharpes, best = _zero_edge_universe(1000, 20, 400)
    decision = _demo(_complete_evidence(matrix[:, best], trials=20, trial_sharpes=tuple(sharpes)))

    assert decision.approved is False
    assert "promotion gate failed: deflated_sharpe" in decision.reasons
    assert math.isfinite(decision.statistics["deflated_sharpe"])
    json.dumps(decision.statistics, allow_nan=False)


@pytest.mark.parametrize(
    "overrides",
    [
        {"psr_zero": float("nan")},
        {"psr_zero": 1.5},
        {"deflated_sharpe": -0.1},
        {"deflated_sharpe": "high"},
        {"newey_west_t": float("inf")},
        {"min_track_record_length": -1.0},
        {"sharpe_observations": -5},
        {"sharpe_observations": 400.5},
    ],
)
def test_malformed_caller_statistics_fail_closed(overrides: dict) -> None:
    decision = _demo(_caller_statistics(**{"newey_west_t": 3.2, **overrides}))

    assert decision.approved is False
    assert decision.checks["deflated_inputs_valid"] is False


def test_caller_statistics_cannot_raise_a_computed_value() -> None:
    returns = _planted_edge(count=300, mean_r=0.12)
    computed = _demo(_complete_evidence(returns)).statistics
    optimistic = _demo(
        _complete_evidence(
            returns,
            psr_zero=1.0,
            deflated_sharpe=1.0,
            newey_west_t=50.0,
            min_track_record_length=2.0,
            sharpe_observations=10_000,
        )
    ).statistics

    for name in ("psr_zero", "deflated_sharpe", "newey_west_t", "min_track_record_length", "observations"):
        assert optimistic[name] == computed[name], name
    assert optimistic["source"] == "return_sequence+caller"


def test_mapping_edge_cases_never_relax_a_check() -> None:
    evidence = _complete_evidence(_planted_edge())
    mapping = {item.name: getattr(evidence, item.name) for item in fields(PromotionEvidence)}

    # A textual "false" is not an explicit boolean, so walk-forward stays required.
    walk = _demo({**mapping, "optimization_used": "false", "walk_forward_passed": False})
    assert walk.checks["walk_forward"] is False
    # None is not a written justification.
    small = _demo({**mapping, "historical_trades": 150, "statistical_justification": None})
    assert small.checks["sample_size"] is False
    assert small.checks["shadow_approval_sample_size"] is False
    # A relaxing flag must be a real boolean True.
    flag = _demo({**mapping, "single_preregistered_hypothesis": "true"})
    assert flag.statistics["newey_west_t_threshold"] == 3.0
    # Not a mapping at all.
    assert _demo(["not", "evidence"]).approved is False


def test_ensemble_audit_payload_carries_demo_statistics_only() -> None:
    from agi_style_forex_bot_mt5.contracts import MarketSnapshot, utc_now
    from agi_style_forex_bot_mt5.strategy import evaluate_ensemble

    snapshot = MarketSnapshot(
        symbol="EURUSD", timeframe="M5", timestamp_utc=utc_now(), bid=1.1, ask=1.1001, spread_points=10,
        digits=5, point=0.00001, tick_value=1.0, tick_size=0.00001, volume_min=0.01, volume_max=100,
        volume_step=0.01, stops_level_points=10, freeze_level_points=0,
    )
    demo = evaluate_ensemble(snapshot, {}, mode="demo", promotion_evidence=PromotionEvidence())
    shadow = evaluate_ensemble(snapshot, {}, mode="shadow")

    assert demo.metadata["promotion_gate"]["approved"] is False
    assert demo.metadata["promotion_gate"]["statistics"]["source"] == "none"
    json.dumps(demo.metadata["promotion_gate"]["statistics"], allow_nan=False)
    assert shadow.metadata["promotion_gate"] == {
        "requested_mode": "shadow",
        "approved": True,
        "effective_mode": "shadow",
        "reasons": ("shadow mode only; signals are for audit, not execution",),
        "checks": {"shadow_mode_allowed": True},
    }

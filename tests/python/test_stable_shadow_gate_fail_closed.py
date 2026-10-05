"""Invalid or absent evidence cannot authorize paper/shadow readiness."""

import json

import pytest

from agi_style_forex_bot_mt5.robustness_validation.stable_shadow_gate import (
    decide_stable_shadow_readiness,
    run_stable_robustness_gate,
)


def _valid(**changes):
    return {
        "profile": "BALANCED_STABLE",
        "stable_filters_applied": True,
        "not_for_demo_live": True,
        "execution_attempted": False,
        "total_trades": 124,
        "sample_status": "USABLE_SAMPLE",
        "profit_factor": 2.64,
        "expectancy_r": 0.373,
        "winrate": 41.94,
        "monte_carlo_classification": "MONTE_CARLO_OK",
        "stress_classification": "STRESS_WARNING",
        "walk_forward_classification": "WALK_FORWARD_WARNING",
        "cost_sensitivity_classification": "COST_SENSITIVITY_OK",
        **changes,
    }


def _decision(payload):
    return decide_stable_shadow_readiness(profile="BALANCED_STABLE", robustness=payload)


@pytest.mark.parametrize("field", ("total_trades", "profit_factor", "expectancy_r", "winrate"))
@pytest.mark.parametrize("value", (float("nan"), float("inf"), -float("inf"), True, False, "NaN", "Infinity", "124", None, [], {}))
def test_nonfinite_or_untyped_metric_never_approves(field, value):
    assert _decision(_valid(**{field: value}))["stable_gate_decision"] != "PAPER_SHADOW_READY"


@pytest.mark.parametrize("value", (-1, 124.5, 10**400))
def test_trade_count_must_be_nonnegative_finite_integral(value):
    assert _decision(_valid(total_trades=value))["stable_gate_decision"] == "NEEDS_MORE_STABLE_DATA"


@pytest.mark.parametrize("field", (
    "monte_carlo_classification", "stress_classification", "walk_forward_classification", "cost_sensitivity_classification",
))
@pytest.mark.parametrize("value", (None, "", "UNKNOWN", "NEEDS_MORE_ROBUSTNESS_DATA", True, [], {}))
def test_unknown_missing_or_insufficient_status_never_approves(field, value):
    payload = _valid(**{field: value})
    assert _decision(payload)["stable_gate_decision"] != "PAPER_SHADOW_READY"
    payload.pop(field)
    assert _decision(payload)["stable_gate_decision"] != "PAPER_SHADOW_READY"


@pytest.mark.parametrize("field", ("stable_filters_applied", "not_for_demo_live", "execution_attempted"))
@pytest.mark.parametrize("value", (None, "False", "True", 0, 1, [], {}))
def test_required_safety_flags_are_explicit_booleans(field, value):
    payload = _valid(**{field: value})
    assert _decision(payload)["stable_gate_decision"] != "PAPER_SHADOW_READY"
    payload.pop(field)
    assert _decision(payload)["stable_gate_decision"] != "PAPER_SHADOW_READY"


@pytest.mark.parametrize("field", ("order_send_called", "order_check_called"))
@pytest.mark.parametrize("value", (True, None, "False", 0))
def test_optional_legacy_execution_flags_when_present_must_be_false(field, value):
    assert _decision(_valid(**{field: value}))["stable_gate_decision"] == "REJECT_STABLE_PROFILE"


@pytest.mark.parametrize("value", (None, "", "BALANCED", [], {}))
def test_evidence_profile_must_match_requested_stable_profile(value):
    assert _decision(_valid(profile=value))["stable_gate_decision"] == "REJECT_STABLE_PROFILE"


@pytest.mark.parametrize("field, value, decision", (
    ("stress_classification", "STRESS_FAILED", "NEEDS_COST_RECALIBRATION"),
    ("walk_forward_classification", "WALK_FORWARD_CRITICAL", "NEEDS_STABILITY_REWORK"),
    ("walk_forward_classification", "NEEDS_MORE_WALK_FORWARD_DATA", "NEEDS_STABILITY_REWORK"),
    ("cost_sensitivity_classification", "COST_FRAGILE", "NEEDS_COST_RECALIBRATION"),
    ("cost_sensitivity_classification", "NEEDS_COST_RECALIBRATION", "NEEDS_COST_RECALIBRATION"),
))
def test_known_negative_classifications_keep_existing_remediation(field, value, decision):
    assert _decision(_valid(**{field: value}))["stable_gate_decision"] == decision


@pytest.mark.parametrize("monte_carlo", ("MONTE_CARLO_OK", "MONTE_CARLO_WARNING"))
@pytest.mark.parametrize("stress", ("STRESS_OK", "STRESS_WARNING"))
@pytest.mark.parametrize("walk_forward", ("WALK_FORWARD_OK", "WALK_FORWARD_WARNING"))
def test_complete_legacy_valid_evidence_keeps_paper_only_compatibility(monte_carlo, stress, walk_forward):
    # Legacy v1 had no source hashes or individual order flags. No fake hashes
    # are generated to preserve this documented paper-observation contract.
    payload = _valid(monte_carlo_classification=monte_carlo, stress_classification=stress,
                     walk_forward_classification=walk_forward)
    decision = _decision(payload)
    assert decision["stable_gate_decision"] == "PAPER_SHADOW_READY"
    assert decision["execution_attempted"] is False


@pytest.mark.parametrize("changes", (
    {"total_trades": 99}, {"profit_factor": 1.19}, {"expectancy_r": 0},
))
def test_existing_numeric_thresholds_are_not_weakened(changes):
    assert _decision(_valid(**changes))["stable_gate_decision"] != "PAPER_SHADOW_READY"
    assert _decision(_valid(total_trades=100, profit_factor=1.2, expectancy_r=0.01))["stable_gate_decision"] == "PAPER_SHADOW_READY"


@pytest.mark.parametrize("raw", ("[]", "null", "true", "1", "{}", "{", '{"profit_factor":NaN}'))
def test_invalid_preferred_artifact_cannot_borrow_valid_fallback(tmp_path, raw):
    preferred = tmp_path / "preferred"
    preferred.mkdir()
    (preferred / "robustness_summary.json").write_text(raw)
    fallback = tmp_path / "runs" / "robustness"
    fallback.mkdir(parents=True)
    (fallback / "robustness_summary.json").write_text(json.dumps(_valid()))
    result = run_stable_robustness_gate(robustness_dir=preferred, runs_root=tmp_path / "runs",
                                      stability_dir=tmp_path / "absent", output_dir=tmp_path / "gate")
    assert result["paper_shadow_ready"] is False
    assert result["total_trades"] is None
    assert result["gate_contract_version"] == "stable_shadow_gate_v2"
    json.dumps(result, allow_nan=False)


def test_missing_preferred_path_keeps_documented_valid_fallback(tmp_path):
    fallback = tmp_path / "runs" / "robustness"
    fallback.mkdir(parents=True)
    (fallback / "robustness_summary.json").write_text(json.dumps(_valid()))
    result = run_stable_robustness_gate(robustness_dir=tmp_path / "absent", runs_root=tmp_path / "runs",
                                      stability_dir=tmp_path / "absent", output_dir=tmp_path / "gate")
    assert result["paper_shadow_ready"] is True


def test_invalid_metric_report_uses_null_without_crashing_or_fabricating_zero(tmp_path):
    robustness = tmp_path / "robustness"
    robustness.mkdir()
    (robustness / "robustness_summary.json").write_text(json.dumps(_valid(total_trades="not-an-int", profit_factor="Infinity")))
    result = run_stable_robustness_gate(robustness_dir=robustness, runs_root=tmp_path / "runs",
                                      stability_dir=tmp_path / "absent", output_dir=tmp_path / "gate")
    assert result["paper_shadow_ready"] is False
    assert result["total_trades"] is None
    assert result["profit_factor"] is None
    persisted = json.loads((tmp_path / "gate" / "stable_gate_summary.json").read_text())
    assert persisted["total_trades"] is None
    assert persisted["profit_factor"] is None


@pytest.mark.parametrize("payload", (None, [], True))
def test_nonobject_programmatic_evidence_rejects_without_exception(payload):
    assert _decision(payload)["stable_gate_decision"] == "REJECT_STABLE_PROFILE"

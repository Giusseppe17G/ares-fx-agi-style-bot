"""Consolidation never promotes missing, malformed or unrecognized evidence."""

import csv
import json
from pathlib import Path

import pytest

from agi_style_forex_bot_mt5.backtesting.validation_report import (
    APPROVED, SECTION_PATHS, _final_decision, _section_classification,
    build_master_validation_report,
)


def reports():
    return {
        "data_quality": {"classification": "OK"},
        "broker_cost_profile": {"classification": "OK"},
        "backtest": {"classification": "OK", "total_trades": 300, "profit_factor": 1.5, "expectancy_r": 0.1, "max_drawdown_pct": 0},
        "walk_forward": {"classification": APPROVED},
        "monte_carlo": {"classification": APPROVED},
        "stress": {"classification": APPROVED},
        "benchmark": {"classification": APPROVED},
        "competitive_scorecard": {"classification": "COMPETITIVE_CANDIDATE"},
        "broker_quality": {"classification": "EXECUTION_READY_SHADOW_ONLY"},
        "readiness": {"classification": "CONTINUE_FORWARD_SHADOW", "decision": "CONTINUE_FORWARD_SHADOW"},
        "forward_shadow": {"mode": "forward-shadow", "paper_total_trades": 4, "open_trades": 1, "closed_trades": 3},
        "research": {"classification": APPROVED},
        "recommended_strategy_mix": [{"symbol": "EURUSD"}],
        "candidate_registry": [{"candidate_id": "fixture-candidate"}],
        "execution_simulation": {"classification": "CALIBRATED_OK"},
        "paper_vs_backtest": {"classification": "CALIBRATED_OK"},
    }


def write_reports(tmp_path, payloads):
    root = tmp_path / "sources"
    for section, payload in payloads.items():
        path = root / SECTION_PATHS[section]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return root


def consolidate(tmp_path, payloads):
    root = write_reports(tmp_path, payloads)
    return build_master_validation_report(reports_root=root, output_dir=tmp_path / "out")


@pytest.mark.parametrize("section", tuple(SECTION_PATHS))
def test_every_missing_section_is_explicit_and_never_implicitly_approved(tmp_path, section):
    payloads = reports()
    payloads.pop(section)
    report = consolidate(tmp_path, payloads)
    assert report["classification"] == "NEEDS_MORE_DATA"
    assert report["missing_sections"] == [section]
    assert report["evidence_quality"][section]["classification"] == "REJECTED"
    assert report["evidence_quality"][section]["reason"] == "FILE_MISSING"
    assert report["promotion_authorized"] is False


@pytest.mark.parametrize("section", ("walk_forward", "monte_carlo", "stress", "benchmark", "data_quality", "broker_cost_profile", "readiness", "research", "competitive_scorecard", "broker_quality", "execution_simulation", "paper_vs_backtest"))
@pytest.mark.parametrize("label", ("UNKNOWN_SUCCESS", "PASS", True, {"approved": True}))
def test_unrecognized_labels_do_not_pass_through_to_approval(tmp_path, section, label):
    payloads = reports()
    payloads[section] = {"classification": label}
    report = consolidate(tmp_path, payloads)
    assert report["classification"] == "NEEDS_MORE_DATA"
    assert report["unknown_classification_sections"] == [section]
    assert report["summaries"][section] == {}
    assert _section_classification(section, payloads[section]) == "REJECTED"


@pytest.mark.parametrize("document,reason", (
    ('["APPROVED_FOR_SHADOW_OBSERVATION"]', "JSON_OBJECT_REQUIRED"),
    ('"APPROVED_FOR_SHADOW_OBSERVATION"', "JSON_OBJECT_REQUIRED"),
    ('42', "JSON_OBJECT_REQUIRED"), ('true', "JSON_OBJECT_REQUIRED"), ('null', "JSON_OBJECT_REQUIRED"),
    ('{"classification":"REJECTED","classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', "JSON_DUPLICATE_KEY"),
    ('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION","nested":{"x":0,"x":1}}', "JSON_DUPLICATE_KEY"),
    ('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION","x":NaN}', "JSON_NONFINITE_NUMBER"),
    ('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION","x":Infinity}', "JSON_NONFINITE_NUMBER"),
    ('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION","x":1e400}', "JSON_NONFINITE_NUMBER"),
    ('{', "JSON_INVALID"),
))
def test_invalid_json_is_a_reported_block_without_crashing_or_serializing_nan(tmp_path, document, reason):
    root = write_reports(tmp_path, reports())
    (root / SECTION_PATHS["monte_carlo"]).write_text(document, encoding="utf-8")
    report = build_master_validation_report(reports_root=root, output_dir=tmp_path / "out")
    assert report["classification"] == "NEEDS_MORE_DATA"
    assert report["invalid_sections"] == ["monte_carlo"]
    assert report["evidence_quality"]["monte_carlo"]["reason"] == reason
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("field", ("profit_factor", "expectancy_r", "max_drawdown_pct", "total_trades"))
@pytest.mark.parametrize("value", (None, True, "Infinity", "1.5", float("nan"), float("inf")))
def test_backtest_invalid_numbers_never_become_approved(tmp_path, field, value):
    payloads = reports()
    payloads["backtest"][field] = value
    assert _section_classification("backtest", payloads["backtest"]) == "REJECTED"
    report = consolidate(tmp_path, payloads)
    assert report["classification"] == "NEEDS_MORE_DATA"
    assert report["evidence_quality"]["backtest"]["status"] == "INVALID"


@pytest.mark.parametrize("field", ("profit_factor", "expectancy_r", "max_drawdown_pct", "total_trades"))
def test_missing_backtest_metric_has_field_specific_reason(tmp_path, field):
    payloads = reports()
    del payloads["backtest"][field]
    report = consolidate(tmp_path, payloads)
    assert report["evidence_quality"]["backtest"]["reason"] == f"METRIC_MISSING:{field}"
    assert report["classification"] == "NEEDS_MORE_DATA"


@pytest.mark.parametrize("drawdown", (0, -0.0, 5, -5, 11.999))
def test_zero_and_signed_finite_drawdown_preserve_existing_thresholds(drawdown):
    summary = reports()["backtest"]
    summary["max_drawdown_pct"] = drawdown
    assert _section_classification("backtest", summary) == APPROVED


@pytest.mark.parametrize("changes,expected", (({"total_trades": 299}, "WATCHLIST"),
    ({"profit_factor": 1.25}, "WATCHLIST"), ({"profit_factor": 1.0}, "REJECTED"),
    ({"expectancy_r": 0}, "WATCHLIST"), ({"max_drawdown_pct": 12}, "WATCHLIST")))
def test_numeric_threshold_boundaries_are_unchanged(changes, expected):
    assert _section_classification("backtest", {**reports()["backtest"], **changes}) == expected


@pytest.mark.parametrize("section", ("monte_carlo", "stress"))
def test_low_sample_warning_is_recognized_as_watchlist_not_approval(tmp_path, section):
    payloads = reports()
    payloads[section]["classification"] = "LOW_SAMPLE_WARNING"
    report = consolidate(tmp_path, payloads)
    detail = report["evidence_quality"][section]
    assert detail["status"] == "AVAILABLE" and detail["classification"] == "WATCHLIST"
    assert report["classification"] == "NEEDS_OPTIMIZATION"


@pytest.mark.parametrize("section", ("recommended_strategy_mix", "candidate_registry"))
@pytest.mark.parametrize("payload", ([], {}, [{"classification": APPROVED}], {"classification": APPROVED}, [True]))
def test_research_indexes_require_actual_nonempty_rows_without_promoting(tmp_path, section, payload):
    payloads = reports()
    payloads[section] = payload
    report = consolidate(tmp_path, payloads)
    assert report["classification"] == "NEEDS_MORE_DATA"
    assert report["evidence_quality"][section]["status"] in {"MISSING", "INVALID"}


def test_real_research_array_contract_is_information_not_approval(tmp_path):
    report = consolidate(tmp_path, reports())
    for section in ("recommended_strategy_mix", "candidate_registry"):
        assert isinstance(report["summaries"][section], list)
        assert report["evidence_quality"][section]["classification"] == "INFORMATIONAL"


@pytest.mark.parametrize("counts", ({"paper_total_trades": 0, "open_trades": 0, "closed_trades": 0},
    {"paper_total_trades": 4, "open_trades": 0, "closed_trades": 3}, {"unrelated": "nonempty"}))
def test_empty_or_inconsistent_forward_evidence_cannot_count_as_available(tmp_path, counts):
    payloads = reports()
    payloads["forward_shadow"] = counts
    report = consolidate(tmp_path, payloads)
    assert report["classification"] == "NEEDS_MORE_DATA"
    assert report["evidence_quality"]["forward_shadow"]["status"] != "AVAILABLE"


def test_conflicting_readiness_labels_are_invalid(tmp_path):
    payloads = reports()
    payloads["readiness"]["decision"] = "NEEDS_BROKER_FIX"
    report = consolidate(tmp_path, payloads)
    assert report["evidence_quality"]["readiness"]["reason"] == "CLASSIFICATION_CONFLICT"
    assert report["classification"] == "NEEDS_MORE_DATA"


def test_explicit_broker_failure_is_retained_despite_other_missing_evidence(tmp_path):
    report = consolidate(tmp_path, {"broker_quality": {"classification": "NOT_READY"}})
    assert report["classification"] == "NEEDS_BROKER_FIX"
    assert "backtest" in report["missing_sections"]


def test_empty_direct_consolidation_cannot_be_approved():
    classification, reasons = _final_decision({})
    assert classification == "NEEDS_MORE_DATA" and len(reasons) == len(SECTION_PATHS)


def test_unreadable_source_is_explicit_invalid_evidence(tmp_path):
    root = write_reports(tmp_path, reports())
    path = root / SECTION_PATHS["stress"]
    path.unlink()
    path.mkdir()
    report = build_master_validation_report(reports_root=root, output_dir=tmp_path / "out")
    assert report["evidence_quality"]["stress"]["reason"] == "FILE_UNREADABLE"
    assert report["classification"] == "NEEDS_MORE_DATA"


def test_json_csv_html_consistently_declare_observational_scope(tmp_path):
    report = consolidate(tmp_path, reports())
    saved = json.loads(Path(report["reports_created"][0]).read_text(encoding="utf-8"))
    assert saved == report
    assert saved["report_version"] == "2.0"
    assert saved["scope"] == "OBSERVATIONAL_REPORT_CONSOLIDATION"
    assert saved["execution_enabled"] is saved["full_pipeline_verified"] is saved["promotion_authorized"] is False
    rows = list(csv.DictReader(Path(report["reports_created"][1]).open(encoding="utf-8", newline="")))
    assert len(rows) == len(SECTION_PATHS)
    for row in rows:
        detail = report["evidence_quality"][row["section"]]
        assert row["classification"] == detail["classification"]
        assert row["reason"] == detail["reason"]
    assert "No real or demo execution is authorized" in Path(report["reports_created"][2]).read_text(encoding="utf-8")


def test_actual_monte_carlo_and_empty_forward_producers_keep_their_contracts(tmp_path):
    from agi_style_forex_bot_mt5.backtesting.monte_carlo import run_monte_carlo_report
    from agi_style_forex_bot_mt5.paper_trading.paper_report import write_forward_shadow_report

    root = write_reports(tmp_path, reports())
    produced = run_monte_carlo_report(trades=[2.0, -1.0] * 20, report_dir=root / "monte_carlo", iterations=10, seed=3)
    write_forward_shadow_report([], root / "forward_shadow")
    report = build_master_validation_report(reports_root=root, output_dir=tmp_path / "out")
    assert report["evidence_quality"]["monte_carlo"]["source_classification"] == produced["classification"]
    assert report["evidence_quality"]["monte_carlo"]["status"] == "AVAILABLE"
    assert report["evidence_quality"]["forward_shadow"]["reason"] == "FORWARD_OBSERVATIONS_EMPTY"
    assert report["classification"] == "NEEDS_MORE_DATA"

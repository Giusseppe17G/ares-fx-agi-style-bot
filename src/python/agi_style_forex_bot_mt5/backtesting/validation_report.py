"""Fail-closed consolidation of observational research reports."""

from __future__ import annotations

import csv
from html import escape
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


REPORT_VERSION = "2.0"
APPROVED = "APPROVED_FOR_SHADOW_OBSERVATION"
CLASSIFICATION_ORDER = {APPROVED: 2, "WATCHLIST": 1, "REJECTED": 0}
SECTION_PATHS = {
    "data_quality": "data_quality/summary.json",
    "broker_cost_profile": "broker_costs/broker_cost_profile.json",
    "backtest": "backtests/summary.json",
    "walk_forward": "walk_forward/summary.json",
    "monte_carlo": "monte_carlo/summary.json",
    "stress": "stress/summary.json",
    "benchmark": "benchmarks/summary.json",
    "competitive_scorecard": "competitive_scorecard/competitive_scorecard.json",
    "broker_quality": "broker_quality/summary.json",
    "readiness": "readiness/execution_readiness_report.json",
    "forward_shadow": "forward_shadow/summary.json",
    "research": "research/research_summary.json",
    "recommended_strategy_mix": "research/recommended_strategy_mix.json",
    "candidate_registry": "research/candidate_registry.json",
    "execution_simulation": "execution_simulation/simulation_calibration.json",
    "paper_vs_backtest": "paper_vs_backtest/summary.json",
}
RESEARCH_LISTS = {"recommended_strategy_mix": "symbol", "candidate_registry": "candidate_id"}
_BASE_LABELS = {label: label for label in CLASSIFICATION_ORDER}
SECTION_LABELS = {
    "data_quality": {"OK": APPROVED, "WATCHLIST": "WATCHLIST", "REJECTED": "REJECTED"},
    "broker_cost_profile": {"OK": APPROVED, "WATCHLIST": "WATCHLIST", "REJECTED": "REJECTED"},
    "walk_forward": dict(_BASE_LABELS),
    "monte_carlo": {**_BASE_LABELS, "LOW_SAMPLE_WARNING": "WATCHLIST"},
    "stress": {**_BASE_LABELS, "LOW_SAMPLE_WARNING": "WATCHLIST"},
    "benchmark": {**_BASE_LABELS, "NEEDS_MORE_DATA": "WATCHLIST"},
    "competitive_scorecard": {"COMPETITIVE_CANDIDATE": APPROVED, "NEEDS_OPTIMIZATION": "WATCHLIST",
        "WEAK_EDGE": "WATCHLIST", "REJECTED": "REJECTED", "NEEDS_MORE_DATA": "WATCHLIST"},
    "broker_quality": {"EXECUTION_READY_SHADOW_ONLY": APPROVED, "WATCHLIST": "WATCHLIST", "NOT_READY": "REJECTED"},
    "readiness": {"CONTINUE_FORWARD_SHADOW": APPROVED, "NEEDS_MORE_DATA": "WATCHLIST", "NEEDS_BROKER_FIX": "WATCHLIST"},
    "research": dict(_BASE_LABELS),
    "execution_simulation": {"CALIBRATED_OK": APPROVED, "NEEDS_MORE_FORWARD_DATA": "WATCHLIST", "COST_ASSUMPTION_TOO_LOW": "WATCHLIST"},
    "paper_vs_backtest": {"CALIBRATED_OK": APPROVED, "NEEDS_MORE_FORWARD_DATA": "WATCHLIST",
        "BACKTEST_TOO_OPTIMISTIC": "WATCHLIST", "COST_ASSUMPTION_TOO_LOW": "WATCHLIST", "STRATEGY_BEHAVIOR_DRIFT": "WATCHLIST"},
}


class _EvidenceError(ValueError):
    """A controlled diagnostic code, without raw source text or exception data."""


def build_master_validation_report(*, reports_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Summarize supplied claims; never authorize execution or verify promotion."""
    root, output = Path(reports_root), Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, Any] = {}
    quality: dict[str, dict[str, Any]] = {}
    for section, relative in SECTION_PATHS.items():
        path = root / relative
        try:
            summary = _read_json(path)
            detail = _assess_section(section, summary)
            if not path.exists():
                detail = _quality("MISSING", "FILE_MISSING")
        except (OSError, UnicodeError):
            summary, detail = {}, _quality("INVALID", "FILE_UNREADABLE")
        except _EvidenceError as exc:
            summary, detail = {}, _quality("INVALID", str(exc))
        summaries[section] = summary if detail["status"] not in {"INVALID", "UNKNOWN_CLASSIFICATION"} else {}
        quality[section] = {**detail, "path": str(path)}
    final_decision, reasons = _consolidate(summaries, quality)
    report = {
        "mode": "validation-report", "report_version": REPORT_VERSION,
        "scope": "OBSERVATIONAL_REPORT_CONSOLIDATION",
        "input_files": [str(path) for path in _existing_summary_paths(root)],
        "classification": final_decision, "reasons": reasons, "summaries": summaries,
        "evidence_quality": quality,
        "missing_sections": [key for key, value in quality.items() if value["status"] == "MISSING"],
        "invalid_sections": [key for key, value in quality.items() if value["status"] == "INVALID"],
        "unknown_classification_sections": [key for key, value in quality.items() if value["status"] == "UNKNOWN_CLASSIFICATION"],
        "execution_enabled": False, "full_pipeline_verified": False,
        "promotion_authorized": False, "execution_attempted": False,
        "limitations": ["Source classifications are observations, not independently authenticated evidence.",
            "This report does not verify cross-run provenance, full decision parity or the Strategy Promotion Gate."],
        "reports_created": [],
    }
    json_path, csv_path, html_path = (output / name for name in
        ("master_validation_report.json", "master_validation_report.csv", "master_validation_report.html"))
    report["reports_created"] = [str(json_path), str(csv_path), str(html_path)]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["section", "classification", "available", "evidence_status", "reason"])
        writer.writeheader()
        for section, detail in quality.items():
            writer.writerow({"section": section, "classification": detail["classification"],
                "available": detail["status"] == "AVAILABLE", "evidence_status": detail["status"], "reason": detail["reason"]})
    html_path.write_text(_html(report), encoding="utf-8")
    json_path.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return report


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys,
            parse_constant=_invalid_constant)
    except _EvidenceError:
        raise
    except (ValueError, RecursionError) as exc:
        raise _EvidenceError("JSON_INVALID") from exc
    _finite_tree(result)
    return result


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _EvidenceError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise _EvidenceError("JSON_NONFINITE_NUMBER")


def _finite_tree(value: Any) -> None:
    if isinstance(value, float) and not isfinite(value):
        raise _EvidenceError("JSON_NONFINITE_NUMBER")
    if isinstance(value, Mapping):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite_tree(item)


def _existing_summary_paths(root: Path) -> list[Path]:
    return [root / relative for relative in SECTION_PATHS.values() if (root / relative).exists()]


def _quality(status: str, reason: str, classification: str = "REJECTED", *, source_classification: str | None = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "classification": classification,
            "source_classification": source_classification}


def _number(summary: Mapping[str, Any], field: str, *, count: bool = False) -> float | int:
    if field not in summary:
        raise _EvidenceError(f"METRIC_MISSING:{field}")
    value = summary[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _EvidenceError(f"METRIC_INVALID:{field}")
    try:
        finite = isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (count and (type(value) is not int or value < 0)):
        raise _EvidenceError(f"METRIC_INVALID:{field}")
    return value


def _assess_section(section: str, summary: Any) -> dict[str, Any]:
    if section not in SECTION_PATHS:
        return _quality("INVALID", "SECTION_UNKNOWN")
    if summary == {} or summary == []:
        return _quality("MISSING", "EVIDENCE_EMPTY")
    try:
        _finite_tree(summary)
        if section in RESEARCH_LISTS:
            if not isinstance(summary, list):
                raise _EvidenceError("JSON_OBJECT_ARRAY_REQUIRED")
            key = RESEARCH_LISTS[section]
            if not all(isinstance(item, Mapping) and isinstance(item.get(key), str) and item[key].strip() for item in summary):
                raise _EvidenceError(f"RESEARCH_ITEM_INVALID:{key}")
            return _quality("AVAILABLE", "RESEARCH_INDEX_INFORMATION_ONLY", "INFORMATIONAL")
        if not isinstance(summary, Mapping):
            raise _EvidenceError("JSON_OBJECT_REQUIRED")
        if section == "backtest":
            source = summary.get("classification")
            if source is not None and (not isinstance(source, str) or source not in {"OK", "WARNING_NO_SIGNALS", "WARNING_NO_TRADES", "WARNING_SIGNALS_NO_TRADES"}):
                return _quality("UNKNOWN_CLASSIFICATION", "CLASSIFICATION_UNKNOWN")
            pf = _number(summary, "profit_factor")
            expectancy = _number(summary, "expectancy_r")
            drawdown = abs(_number(summary, "max_drawdown_pct"))
            trades = _number(summary, "total_trades", count=True)
            if pf < 0:
                raise _EvidenceError("METRIC_INVALID:profit_factor")
            if trades >= 300 and pf > 1.25 and expectancy > 0 and drawdown < 12:
                classification = APPROVED
            elif pf > 1.0 and expectancy >= 0:
                classification = "WATCHLIST"
            else:
                classification = "REJECTED"
            if source is not None and source != "OK":
                classification = "REJECTED"
            return _quality("AVAILABLE", "BACKTEST_THRESHOLDS_EVALUATED", classification, source_classification=source)
        if section == "forward_shadow":
            total = _number(summary, "paper_total_trades", count=True)
            opened = _number(summary, "open_trades", count=True)
            closed = _number(summary, "closed_trades", count=True)
            if total != opened + closed:
                raise _EvidenceError("PAPER_TRADE_COUNTS_INCONSISTENT")
            if total == 0:
                return _quality("MISSING", "FORWARD_OBSERVATIONS_EMPTY")
            return _quality("AVAILABLE", "FORWARD_OBSERVATION_ONLY", "WATCHLIST")
        source = summary.get("classification")
        if section == "readiness":
            decision = summary.get("decision")
            if source is not None and decision is not None and source != decision:
                raise _EvidenceError("CLASSIFICATION_CONFLICT")
            source = source if source is not None else decision
        if source is None:
            return _quality("MISSING", "CLASSIFICATION_MISSING")
        if not isinstance(source, str) or source not in SECTION_LABELS[section]:
            return _quality("UNKNOWN_CLASSIFICATION", "CLASSIFICATION_UNKNOWN")
        return _quality("AVAILABLE", "SOURCE_CLASSIFICATION_RECOGNIZED", SECTION_LABELS[section][source], source_classification=source)
    except _EvidenceError as exc:
        return _quality("INVALID", str(exc))


def _section_classification(section: str, summary: Mapping[str, Any]) -> str:
    return _assess_section(section, summary)["classification"]


def _final_decision(summaries: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]:
    quality = {section: _assess_section(section, summaries.get(section, {})) for section in SECTION_PATHS}
    return _consolidate(summaries, quality)


def _consolidate(summaries: Mapping[str, Any], quality: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]:
    reasons = [f"{section}: {item['classification']} [{item['status']}:{item['reason']}]" for section, item in quality.items()]
    available = {section: item["classification"] for section, item in quality.items() if item["status"] == "AVAILABLE"}
    sources = {section: item.get("source_classification") for section, item in quality.items() if item["status"] == "AVAILABLE"}
    if available.get("data_quality") == "REJECTED":
        return "NEEDS_MORE_DATA", reasons
    if available.get("broker_quality") == "REJECTED" or sources.get("readiness") == "NEEDS_BROKER_FIX":
        return "NEEDS_BROKER_FIX", reasons
    if any(available.get(key) in {"REJECTED", "WATCHLIST"} for key in ("benchmark", "competitive_scorecard")):
        return "NEEDS_STRATEGY_FIX", reasons
    if sources.get("paper_vs_backtest") in {"BACKTEST_TOO_OPTIMISTIC", "COST_ASSUMPTION_TOO_LOW"} or sources.get("execution_simulation") == "COST_ASSUMPTION_TOO_LOW":
        return "NEEDS_STRATEGY_FIX", reasons
    if "REJECTED" in available.values():
        return "REJECTED", reasons
    if any(item["status"] != "AVAILABLE" for item in quality.values()):
        return "NEEDS_MORE_DATA", reasons
    if "WATCHLIST" in available.values():
        return "NEEDS_OPTIMIZATION", reasons
    if any(summaries.get(section) for section in ("broker_quality", "readiness", "forward_shadow")):
        return "CONTINUE_FORWARD_SHADOW", reasons
    return APPROVED, reasons


def _html(report: Mapping[str, Any]) -> str:
    rows = "\n".join(f"<tr><th>{escape(str(key))}</th><td>{escape(str(_jsonable(value)))}</td></tr>"
        for key, value in report.items() if key != "summaries")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Master Validation Report</title></head>
<body><h1>Master Validation Report</h1>
<p>Observational research consolidation. No real or demo execution is authorized.
Full pipeline and Strategy Promotion Gate are not verified.</p><table>{rows}</table></body></html>
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

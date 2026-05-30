"""Offline micro frequency calibration report orchestration."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.observation_window import calculate_observation_window
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .exit_latency_audit import audit_exit_latency
from .frequency_dataset import load_frequency_dataset
from .micro_profile_candidate import build_micro_profile_candidate
from .rejection_pressure_audit import audit_rejection_pressure
from .session_opportunity_audit import audit_session_opportunity
from .symbol_frequency_audit import audit_symbol_frequency
from .threshold_sensitivity_audit import audit_threshold_sensitivity


def run_micro_frequency_calibration(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/micro_frequency_calibration",
) -> dict[str, Any]:
    """Build read-only frequency calibration diagnostics and a non-active candidate INI."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    dataset = load_frequency_dataset(database=database, log_dir=log_dir, reports_root=reports_root, profile_config=profile_config)
    events = list(dataset.get("events", []))
    heartbeats = list(dataset.get("heartbeats", []))
    paper_trades = list(dataset.get("paper_trades", []))
    sufficiency = dataset.get("forward_sufficiency", {}) if isinstance(dataset.get("forward_sufficiency"), Mapping) else {}
    window = _window(sufficiency, events, heartbeats, paper_trades)
    rejection = audit_rejection_pressure(events)
    threshold_rows, threshold = audit_threshold_sensitivity(events)
    symbol_rows, symbol_summary = audit_symbol_frequency(events, paper_trades)
    session_rows, session = audit_session_opportunity(events, paper_trades)
    exit_latency = audit_exit_latency(paper_trades)
    closed = int(sufficiency.get("closed_paper_trades", _closed_trades(paper_trades)) or 0)
    open_trades = int(sufficiency.get("open_paper_trades", _open_trades(paper_trades)) or 0)
    hours = float(window.get("hours_observed", 0.0) or 0.0)
    rate = closed / hours * 24.0 if hours > 0 else 0.0
    required_rate = 10.0 / 24.0
    shortfall = max(10 - closed, 0)
    current_estimate = sufficiency.get("estimated_hours_to_10_closed_trades")
    if current_estimate is None:
        current_estimate = shortfall / (closed / hours) if closed and hours > 0 and shortfall else (0.0 if shortfall == 0 else None)
    bottlenecks = _bottlenecks(rejection, threshold, session, sufficiency, exit_latency)
    status = _classify(hours=hours, closed=closed, rejection=rejection, threshold=threshold, session=session, sufficiency=sufficiency, exit_latency=exit_latency)
    candidate_gain = _candidate_gain_score(bottlenecks)
    safety_penalty = _safety_penalty_score(dataset, sufficiency)
    candidate_estimate = _candidate_estimate(current_estimate, candidate_gain, safety_penalty)
    final_score = max(0.0, min(100.0, candidate_gain - safety_penalty + 50.0))
    summary = {
        "mode": "micro-frequency-calibration",
        "micro_frequency_status": status,
        "hours_observed": round(hours, 4),
        "paper_trades_closed": closed,
        "paper_trades_open": open_trades,
        "required_closed_paper_trades": 10,
        "closed_trade_rate_per_24h": round(rate, 4),
        "required_trade_rate_per_24h": round(required_rate, 4),
        "trade_shortfall": shortfall,
        "signals_to_closed_trade_conversion": _conversion(closed, int(rejection.get("signals_detected", 0) or 0)),
        "accepted_signal_to_closed_trade_conversion": _conversion(closed, int(rejection.get("signals_accepted", 0) or 0)),
        "rejection_rate": rejection.get("rejection_rate", 0.0),
        "top_frequency_bottlenecks": bottlenecks,
        "estimated_hours_to_10_trades_current_profile": None if current_estimate is None else round(float(current_estimate), 4),
        "estimated_hours_to_10_trades_candidate_profile": candidate_estimate,
        "safety_penalty_score": round(safety_penalty, 4),
        "frequency_gain_score": round(candidate_gain, 4),
        "final_candidate_profile_score": round(final_score, 4),
        "recommended_next_action": _recommended_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    candidate = build_micro_profile_candidate(
        profile_config=dataset.get("profile_config", {}),
        profile_lines=list(dataset.get("profile_config_lines", [])),
        summary={**summary, **sufficiency, "active_scaled_drawdown_count": _active_scaled_drawdown_count(dataset), "drawdown_active": _drawdown_active(dataset)},
        output_dir=output,
    )
    summary = {**summary, **candidate}
    paths = _write_reports(output, summary, bottlenecks, threshold_rows, symbol_rows, session_rows, exit_latency)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _window(sufficiency: Mapping[str, Any], events: list[Mapping[str, Any]], heartbeats: list[Mapping[str, Any]], paper_trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    if sufficiency.get("hours_observed") is not None:
        return {
            "observation_start_utc": sufficiency.get("observation_start_utc"),
            "observation_end_utc": sufficiency.get("observation_end_utc"),
            "hours_observed": float(sufficiency.get("hours_observed", 0.0) or 0.0),
        }
    return calculate_observation_window([*events, *heartbeats, *paper_trades])


def _closed_trades(paper_trades: list[Mapping[str, Any]]) -> int:
    return sum(1 for trade in paper_trades if str(trade.get("status", "")).upper() == "CLOSED")


def _open_trades(paper_trades: list[Mapping[str, Any]]) -> int:
    return sum(1 for trade in paper_trades if str(trade.get("status", "")).upper() == "OPEN")


def _bottlenecks(
    rejection: Mapping[str, Any],
    threshold: Mapping[str, Any],
    session: Mapping[str, Any],
    sufficiency: Mapping[str, Any],
    exit_latency: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        ("REGIME_BLOCK", int(sufficiency.get("regime_block_count", session.get("regime_block_count", 0)) or 0)),
        ("LIQUIDITY_BLOCK", int(sufficiency.get("liquidity_block_count", 0) or 0)),
        ("STALE_SIGNAL_BLOCK", int(sufficiency.get("stale_signal_count", 0) or 0)),
        ("COOLDOWN_BLOCK", int(sufficiency.get("cooldown_block_count", 0) or 0)),
        ("SCORE_THRESHOLD_BLOCK", int(sufficiency.get("score_threshold_block_count", threshold.get("score_threshold_block_count", 0)) or 0)),
        ("SESSION_BLOCK", int(sufficiency.get("session_block_count", session.get("session_block_count", 0)) or 0)),
        ("SPREAD_BLOCK", int(sufficiency.get("spread_block_count", 0) or 0)),
        ("PAPER_RISK_BLOCK", int(sufficiency.get("paper_risk_block_count", 0) or 0)),
    ]
    rows = [{"bottleneck": name, "count": count} for name, count in sorted(candidates, key=lambda item: item[1], reverse=True) if count > 0]
    if float(rejection.get("rejection_rate", 0.0) or 0.0) >= 0.8:
        rows.insert(0, {"bottleneck": "HIGH_REJECTION_RATE", "count": int(rejection.get("signals_rejected", 0) or 0)})
    if exit_latency.get("exit_latency_status") == "EXIT_LATENCY_TOO_HIGH":
        rows.append({"bottleneck": "EXIT_LATENCY_TOO_HIGH", "count": int(exit_latency.get("closed_trade_duration_count", 0) or 0)})
    return rows[:10]


def _classify(
    *,
    hours: float,
    closed: int,
    rejection: Mapping[str, Any],
    threshold: Mapping[str, Any],
    session: Mapping[str, Any],
    sufficiency: Mapping[str, Any],
    exit_latency: Mapping[str, Any],
) -> str:
    rejection_rate = float(rejection.get("rejection_rate", 0.0) or 0.0)
    if int(sufficiency.get("data_quality_block_count", 0) or 0) > max(3, int(rejection.get("signals_detected", 0) or 0) // 2):
        return "DATA_QUALITY_LIMITING"
    if rejection_rate >= 0.8 and int(rejection.get("signals_detected", 0) or 0) >= 5:
        return "FILTERS_TOO_RESTRICTIVE"
    if int(sufficiency.get("cooldown_block_count", 0) or 0) >= 10:
        return "COOLDOWN_TOO_RESTRICTIVE"
    if int(session.get("session_block_count", 0) or 0) >= 10:
        return "SESSION_TOO_RESTRICTIVE"
    if int(threshold.get("score_threshold_block_count", 0) or 0) >= 10:
        return "SCORE_THRESHOLD_TOO_RESTRICTIVE"
    if exit_latency.get("exit_latency_status") == "EXIT_LATENCY_TOO_HIGH":
        return "EXIT_LATENCY_TOO_HIGH"
    if hours > 48 and closed < 10:
        return "LOW_TRADE_FREQUENCY_CONFIRMED"
    if closed >= 10:
        return "FREQUENCY_ACCEPTABLE_WAIT"
    return "DO_NOT_RELAX_PROFILE"


def _candidate_gain_score(bottlenecks: list[Mapping[str, Any]]) -> float:
    if not bottlenecks:
        return 0.0
    weighted = 0.0
    for row in bottlenecks:
        name = str(row.get("bottleneck", ""))
        count = float(row.get("count", 0) or 0)
        weight = 0.8 if name in {"COOLDOWN_BLOCK", "SCORE_THRESHOLD_BLOCK", "SESSION_BLOCK"} else 0.35
        weighted += min(count * weight, 20.0)
    return min(weighted, 45.0)


def _safety_penalty_score(dataset: Mapping[str, Any], sufficiency: Mapping[str, Any]) -> float:
    penalty = 0.0
    paper_risk = dataset.get("paper_risk", {}) if isinstance(dataset.get("paper_risk"), Mapping) else {}
    if str(paper_risk.get("daily_drawdown_status", "")).upper() in {"HALTED", "ACTIVE_DRAWDOWN_HALT"}:
        penalty += 35.0
    penalty += min(float(sufficiency.get("paper_risk_block_count", 0) or 0) * 3.0, 20.0)
    return penalty


def _candidate_estimate(current_estimate: Any, gain: float, penalty: float) -> float | None:
    if current_estimate is None:
        return None
    factor = max(0.7, min(1.0, 1.0 - (gain - penalty) / 200.0))
    return round(float(current_estimate) * factor, 4)


def _active_scaled_drawdown_count(dataset: Mapping[str, Any]) -> int:
    evidence = dataset.get("forward_evidence", {}) if isinstance(dataset.get("forward_evidence"), Mapping) else {}
    paper_risk = dataset.get("paper_risk", {}) if isinstance(dataset.get("paper_risk"), Mapping) else {}
    return int(evidence.get("active_scaled_drawdown_count", paper_risk.get("active_scaled_drawdown_count", 0)) or 0)


def _conversion(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(min(numerator / denominator, 1.0), 4)


def _drawdown_active(dataset: Mapping[str, Any]) -> bool:
    paper_risk = dataset.get("paper_risk", {}) if isinstance(dataset.get("paper_risk"), Mapping) else {}
    status = str(paper_risk.get("daily_drawdown_status") or paper_risk.get("paper_daily_risk_status") or "").upper()
    return status in {"HALTED", "ACTIVE_DRAWDOWN_HALT", "ACTIVE_SCALED_DRAWDOWN_BLOCK"}


def _recommended_action(status: str) -> str:
    return {
        "FREQUENCY_ACCEPTABLE_WAIT": "WAIT_FOR_MORE_CLOSED_TRADES",
        "LOW_TRADE_FREQUENCY_CONFIRMED": "REVIEW_MICRO_V2_CANDIDATE_OFFLINE",
        "FILTERS_TOO_RESTRICTIVE": "REVIEW_FILTER_STRICTNESS_OFFLINE",
        "COOLDOWN_TOO_RESTRICTIVE": "REVIEW_COOLDOWN_OFFLINE",
        "SESSION_TOO_RESTRICTIVE": "REVIEW_SESSION_WINDOWS_OFFLINE",
        "SCORE_THRESHOLD_TOO_RESTRICTIVE": "REVIEW_SIGNAL_SCORE_THRESHOLDS_OFFLINE",
        "SYMBOL_UNIVERSE_TOO_NARROW": "REVIEW_SYMBOL_UNIVERSE_OFFLINE",
        "EXIT_LATENCY_TOO_HIGH": "REVIEW_EXIT_RULES_OFFLINE",
        "DATA_QUALITY_LIMITING": "REVIEW_DATA_QUALITY_FEEDS",
        "DO_NOT_RELAX_PROFILE": "DO_NOT_CHANGE_RUNTIME_YET",
    }.get(status, "DO_NOT_CHANGE_RUNTIME_YET")


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    bottlenecks: list[Mapping[str, Any]],
    threshold_rows: list[Mapping[str, Any]],
    symbol_rows: list[Mapping[str, Any]],
    session_rows: list[Mapping[str, Any]],
    exit_latency: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_frequency_summary.json",
        output / "frequency_bottlenecks.csv",
        output / "threshold_sensitivity.csv",
        output / "symbol_frequency.csv",
        output / "session_opportunity.csv",
        output / "exit_latency_audit.json",
        output / "balanced_stable_micro_v2_candidate.ini",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], bottlenecks)
    _write_csv(paths[2], threshold_rows)
    _write_csv(paths[3], symbol_rows)
    _write_csv(paths[4], session_rows)
    _write_json(paths[5], exit_latency)
    paths[7].write_text(_recommendations_markdown(summary), encoding="utf-8")
    paths[8].write_text(
        f"<html><body><h1>Micro Frequency Calibration</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>",
        encoding="utf-8",
    )
    return paths


def _recommendations_markdown(summary: Mapping[str, Any]) -> str:
    return f"""# Micro Frequency Calibration

Status: `{summary.get('micro_frequency_status')}`

Closed paper trades: `{summary.get('paper_trades_closed')}` of `10`

Closed trade rate per 24h: `{summary.get('closed_trade_rate_per_24h')}`

Estimated hours to 10 trades, current profile: `{summary.get('estimated_hours_to_10_trades_current_profile')}`

Candidate profile: `{summary.get('candidate_profile_path')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This is offline research only. The candidate profile is not active, does not replace `balanced_stable_micro.ini`, and does not authorize demo/live execution.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

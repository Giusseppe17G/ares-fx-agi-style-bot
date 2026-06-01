"""Report orchestration for Micro V2 stable market window."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.heartbeat_audit import audit_heartbeat
from agi_style_forex_bot_mt5.micro_v2_market_open_readiness.mt5_connection_audit import audit_mt5_connection

from .fresh_tick_coverage_audit import audit_fresh_tick_coverage
from .market_closed_trend_audit import audit_market_closed_trend
from .next_decision_gate import decide_stable_market_window
from .stable_window_loader import configured_symbols, load_stable_window_inputs
from .symbol_readiness_audit import build_symbol_readiness
from .trade_readiness_audit import audit_trade_readiness


def run_micro_v2_stable_market_window(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    checkpoint_dir: str | Path = "data/reports/micro_v2_observation_checkpoint",
    readiness_dir: str | Path = "data/reports/micro_v2_market_open_readiness",
    filter_analysis_dir: str | Path = "data/reports/micro_v2_filter_analysis",
    consolidated_dir: str | Path = "data/reports/micro_v2_consolidated_audit",
    output_dir: str | Path = "data/reports/micro_v2_stable_market_window",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_stable_window_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        checkpoint_dir=checkpoint_dir,
        readiness_dir=readiness_dir,
        filter_analysis_dir=filter_analysis_dir,
        consolidated_dir=consolidated_dir,
    )
    expected_symbols = configured_symbols(inputs["profile_values"])
    heartbeat_raw = audit_heartbeat(inputs["v2_dataset"])
    mt5 = audit_mt5_connection(inputs["v2_dataset"])
    heartbeat = {
        "v2_runtime_active": heartbeat_raw.get("process_appears_active", False),
        "last_heartbeat_utc": heartbeat_raw.get("latest_heartbeat_utc"),
        "observed_market_open_hours": heartbeat_raw.get("hours_observed", 0.0),
        "mt5_connected": mt5.get("mt5_connected", False),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    coverage = audit_fresh_tick_coverage(
        inputs["v2_dataset"],
        expected_symbols=expected_symbols,
        checkpoint=inputs["checkpoint"],
        readiness=inputs["readiness"],
        filter_analysis=inputs["filter_analysis"],
    )
    market = audit_market_closed_trend(inputs["filter_analysis"], inputs["checkpoint"], inputs["consolidated"])
    symbols = build_symbol_readiness(expected_symbols, coverage["fresh_tick_symbols"], coverage["stale_tick_symbols"])
    trade = audit_trade_readiness(inputs["v2_dataset"], inputs["checkpoint"], inputs["filter_analysis"])
    decision = decide_stable_market_window(
        dataset=inputs["v2_dataset"],
        heartbeat=heartbeat,
        coverage=coverage,
        market=market,
        trade=trade,
        filter_analysis=inputs["filter_analysis"],
    )
    summary = {
        "mode": "micro-v2-stable-market-window",
        **decision,
        "v2_runtime_active": heartbeat.get("v2_runtime_active", False),
        "mt5_connected": heartbeat.get("mt5_connected", False),
        "last_heartbeat_utc": heartbeat.get("last_heartbeat_utc"),
        "fresh_tick_symbols": coverage.get("fresh_tick_symbols", []),
        "stale_tick_symbols": coverage.get("stale_tick_symbols", []),
        "fresh_tick_coverage_ratio": coverage.get("fresh_tick_coverage_ratio", 0.0),
        "market_closed_rejection_count": market.get("market_closed_rejection_count", 0),
        "stale_tick_rejection_count": market.get("stale_tick_rejection_count", 0),
        "market_closed_dominance_ratio": market.get("market_closed_dominance_ratio", 0.0),
        "signals_detected": trade.get("signals_detected", 0),
        "signals_rejected": trade.get("signals_rejected", 0),
        "rejection_rate": trade.get("rejection_rate", 0.0),
        "paper_trades_open": trade.get("paper_trades_open", 0),
        "paper_trades_closed": trade.get("paper_trades_closed", 0),
        "paper_trades_closed_today": trade.get("paper_trades_closed_today", 0),
        "accepted_signals": trade.get("accepted_signals", 0),
        "trade_readiness_status": trade.get("trade_readiness_status", ""),
        "observed_market_open_hours": heartbeat.get("observed_market_open_hours", 0.0),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, coverage, symbols, market, trade, decision)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    coverage: Mapping[str, Any],
    symbols: list[Mapping[str, Any]],
    market: Mapping[str, Any],
    trade: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_stable_market_window_summary.json",
        output / "fresh_tick_coverage_audit.json",
        output / "symbol_readiness.csv",
        output / "market_closed_trend_audit.json",
        output / "trade_readiness_audit.json",
        output / "next_decision_gate.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], coverage)
    _write_csv(paths[2], symbols)
    _write_json(paths[3], market)
    _write_json(paths[4], trade)
    _write_json(paths[5], decision)
    paths[6].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[7].write_text(_recommendations(summary), encoding="utf-8")
    paths[8].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    status = str(summary.get("micro_v2_stable_market_window_status", ""))
    mapping = {
        "MICRO_V2_MARKET_WINDOW_NOT_STABLE": "Continue V2 and rerun micro-v2-observation-checkpoint plus micro-v2-market-open-readiness later.",
        "MICRO_V2_MARKET_WINDOW_PARTIALLY_STABLE": "Wait for more symbols with fresh ticks, then rerun this stable window pack.",
        "MICRO_V2_MARKET_WINDOW_STABLE_NO_TRADES_YET": "Run micro-v2-filter-analysis to explain why fresh-tick signals are not becoming paper trades.",
        "MICRO_V2_MARKET_WINDOW_STABLE_COLLECTING_TRADES": "Run micro-v2-dry-run-monitor at regular checkpoints while trades close.",
        "MICRO_V2_READY_FOR_TRADE_FREQUENCY_LIFECYCLE_AUDIT": "Prepare a combined frequency/lifecycle/PnL audit phase.",
        "MICRO_V2_READY_FOR_ACCEPTANCE_EVIDENCE_PACK": "Prepare a V2 acceptance evidence pack phase.",
    }
    return f"""# Recommended Commands

Status: `{status}`

Recommended next action: `{summary.get('recommended_next_action')}`

{mapping.get(status, 'Review the generated stable market window reports before proceeding.')}

This pack is offline/read-only and does not approve demo/live execution.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Stable Market Window

Status: `{summary.get('micro_v2_stable_market_window_status')}`

Fresh tick coverage ratio: `{summary.get('fresh_tick_coverage_ratio')}`

Market closed dominance ratio: `{summary.get('market_closed_dominance_ratio')}`

Trade readiness: `{summary.get('trade_readiness_status')}`

Recommended next action: `{summary.get('recommended_next_action')}`
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Stable Market Window</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


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

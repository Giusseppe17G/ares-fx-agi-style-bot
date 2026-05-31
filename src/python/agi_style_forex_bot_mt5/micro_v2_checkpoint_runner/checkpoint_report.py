"""Report orchestration for Micro V2 observation checkpoints."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .acceptance_snapshot import build_acceptance_snapshot
from .checkpoint_decision import decide_checkpoint
from .checkpoint_loader import load_checkpoint_inputs
from .monitor_snapshot import build_monitor_snapshot
from .readiness_snapshot import build_readiness_snapshot
from .rejection_snapshot import build_rejection_snapshot
from .status_snapshot import build_status_snapshot


def run_micro_v2_observation_checkpoint(
    *,
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    output_dir: str | Path = "data/reports/micro_v2_observation_checkpoint",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_checkpoint_inputs(
        base_sqlite=base_sqlite,
        base_log_dir=base_log_dir,
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
    )
    status = build_status_snapshot(inputs["base_dataset"], inputs["v2_dataset"])
    readiness = build_readiness_snapshot(inputs["v2_dataset"], inputs["existing_readiness"])
    monitor = build_monitor_snapshot(inputs["base_dataset"], inputs["v2_dataset"], inputs["existing_monitor"])
    rejection = build_rejection_snapshot(inputs["v2_dataset"], inputs["existing_rejection"])
    acceptance = build_acceptance_snapshot(inputs["existing_acceptance"])
    decision = decide_checkpoint(status=status, readiness=readiness, monitor=monitor)
    summary = {
        "mode": "micro-v2-observation-checkpoint",
        **decision,
        "v2_runtime_active": status.get("v2_runtime_active", False),
        "last_heartbeat_utc": status.get("last_heartbeat_utc"),
        "mt5_connected": readiness.get("mt5_connected", False),
        "fresh_tick_symbols": readiness.get("fresh_tick_symbols", []),
        "stale_tick_symbols": readiness.get("stale_tick_symbols", []),
        "market_closed_rejection_count": readiness.get("market_closed_rejection_count", rejection.get("market_closed_rejection_count", 0)),
        "stale_tick_rejection_count": readiness.get("stale_tick_rejection_count", rejection.get("stale_tick_rejection_count", 0)),
        "invalid_market_snapshot_rejection_count": readiness.get("invalid_market_snapshot_rejection_count", rejection.get("invalid_market_snapshot_rejection_count", 0)),
        "v2_signals_detected": monitor.get("v2_signals_detected", 0),
        "v2_signals_rejected": monitor.get("v2_signals_rejected", 0),
        "v2_rejection_rate": monitor.get("v2_rejection_rate", 0.0),
        "v2_paper_trades_open": monitor.get("v2_paper_trades_open", 0),
        "v2_paper_trades_closed": monitor.get("v2_paper_trades_closed", 0),
        "v2_closed_trade_rate_per_24h": monitor.get("v2_closed_trade_rate_per_24h", 0.0),
        "base_closed_trade_rate_per_24h": monitor.get("base_closed_trade_rate_per_24h", 0.0),
        "paper_state_recovery_status": monitor.get("paper_state_recovery_status", ""),
        "config_error_root_cause": monitor.get("config_error_root_cause", ""),
        "forward_acceptance_v2_decision": acceptance.get("forward_acceptance_v2_decision", ""),
        "readiness_status": readiness.get("readiness_status", ""),
        "monitor_status": monitor.get("monitor_status", ""),
        "rejection_labeling_status": rejection.get("rejection_labeling_status", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, status, readiness, monitor, rejection, acceptance, decision)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    status: Mapping[str, Any],
    readiness: Mapping[str, Any],
    monitor: Mapping[str, Any],
    rejection: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "micro_v2_observation_checkpoint_summary.json",
        output / "status_snapshot.json",
        output / "readiness_snapshot.json",
        output / "monitor_snapshot.json",
        output / "rejection_snapshot.json",
        output / "acceptance_snapshot.json",
        output / "checkpoint_decision.json",
        output / "recommended_commands.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], status)
    _write_json(paths[2], readiness)
    _write_json(paths[3], monitor)
    _write_json(paths[4], rejection)
    _write_json(paths[5], acceptance)
    _write_json(paths[6], decision)
    paths[7].write_text(_recommended_commands(summary), encoding="utf-8")
    paths[8].write_text(_recommendations(summary), encoding="utf-8")
    paths[9].write_text(_html(summary), encoding="utf-8")
    return paths


def _recommended_commands(summary: Mapping[str, Any]) -> str:
    status = str(summary.get("micro_v2_checkpoint_status", ""))
    if status == "MICRO_V2_CHECKPOINT_WAITING_FOR_MARKET_OPEN":
        command = "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-market-open-readiness --v2-sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --v2-log-dir data\\logs\\forward-shadow-v2-dryrun --reports-root data\\reports --v2-profile-config data\\reports\\paper_risk\\balanced_stable_micro_v2.ini --rejection-labeling-dir data\\reports\\rejection_labeling_audit --monitor-dir data\\reports\\micro_v2_dry_run_monitor --output-dir data\\reports\\micro_v2_market_open_readiness"
        note = "Market is still closed or fresh ticks are unavailable. Re-run readiness when the market opens."
    elif status in {"MICRO_V2_CHECKPOINT_COLLECTING_FRESH_TICK_DATA", "MICRO_V2_CHECKPOINT_NEEDS_MORE_TRADES"}:
        command = "py -m agi_style_forex_bot_mt5.cli --mode micro-v2-dry-run-monitor --base-sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --base-log-dir data\\logs\\forward-shadow-stable --v2-sqlite data\\sqlite\\forward-shadow-v2-dryrun.sqlite3 --v2-log-dir data\\logs\\forward-shadow-v2-dryrun --reports-root data\\reports --output-dir data\\reports\\micro_v2_dry_run_monitor"
        note = "Keep monitoring V2 and rerun rejection-labeling audit at checkpoints."
    elif status == "MICRO_V2_CHECKPOINT_READY_FOR_FILTER_ANALYSIS":
        command = "# Future phase: run a V2 filter-analysis audit; do not change runtime from this checkpoint."
        note = "Fresh ticks exist but filters/rejections appear to dominate."
    elif status == "MICRO_V2_CHECKPOINT_SAFETY_BLOCKED":
        command = "# Run the FASE 57 stop/rollback checklist and preserve V2 evidence."
        note = "Safety evidence requires immediate manual review."
    elif status == "MICRO_V2_CHECKPOINT_READY_FOR_ACCEPTANCE_REVIEW":
        command = "# Future phase: run explicit V2 acceptance review using the V2 evidence pack."
        note = "Minimum observation and closed paper trades are met for review."
    else:
        command = "# Review status_snapshot.json, readiness_snapshot.json, monitor_snapshot.json, and rejection_snapshot.json."
        note = "Manual review is required before deciding next steps."
    return f"""# Recommended Commands

Checkpoint status: `{status}`

Recommended next action: `{summary.get('recommended_next_action')}`

{note}

```powershell
{command}
```

This checkpoint is offline/read-only and does not approve demo/live execution.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Observation Checkpoint

Status: `{summary.get('micro_v2_checkpoint_status')}`

V2 runtime active: `{summary.get('v2_runtime_active')}`

MT5 connected: `{summary.get('mt5_connected')}`

Fresh tick symbols: `{', '.join(summary.get('fresh_tick_symbols', []))}`

Closed paper trades: `{summary.get('v2_paper_trades_closed')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This runner does not open/close trades, pause/resume shadow, modify SQLite/logs/profiles, or authorize demo/live execution.
"""


def _html(summary: Mapping[str, Any]) -> str:
    return f"<html><body><h1>Micro V2 Observation Checkpoint</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

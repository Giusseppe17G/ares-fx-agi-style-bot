"""Weekend clean-state validation for BALANCED_STABLE paper shadow."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"


def run_weekend_readiness(
    *,
    sqlite_path: str | Path,
    log_dir: str | Path,
    reports_root: str | Path,
    output_dir: str | Path,
    config: BotConfig,
) -> dict[str, Any]:
    """Validate the paused weekend state without touching MT5."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    sqlite = Path(sqlite_path)
    logs = Path(log_dir)
    reports = Path(reports_root)
    checks: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    open_paper_trades = 0
    paper_drawdown = 0.0

    database: TelemetryDatabase | None = None
    if not sqlite.exists():
        _check(checks, "sqlite_exists", FAIL, "NEEDS_PAPER_STATE_REVIEW", f"SQLite file not found: {sqlite}")
    else:
        try:
            with sqlite3.connect(sqlite) as conn:
                conn.execute("SELECT 1").fetchone()
            _check(checks, "sqlite_opens", PASS, "", f"SQLite opens: {sqlite}")
            database = TelemetryDatabase(sqlite)
        except Exception as exc:
            _check(checks, "sqlite_opens", FAIL, "NEEDS_PAPER_STATE_REVIEW", f"SQLite open failed: {exc}")

    if database is not None:
        try:
            open_paper_trades = len(database.fetch_open_paper_trades())
            state = database.get_operational_state()
            _check(
                checks,
                "no_open_paper_trades",
                PASS if open_paper_trades == 0 else FAIL,
                "" if open_paper_trades == 0 else "NEEDS_PAPER_STATE_REVIEW",
                f"open_paper_trades={open_paper_trades}",
            )
            _check(
                checks,
                "shadow_paused",
                PASS if bool(state.get("shadow_paused")) else FAIL,
                "" if bool(state.get("shadow_paused")) else "NOT_READY_FOR_MARKET_OPEN",
                f"paper_shadow_paused={bool(state.get('shadow_paused'))}; reason={state.get('paused_reason') or state.get('halt_reason') or ''}",
            )
            critical = _recent_critical_alerts(database)
            unexplained = [
                item
                for item in critical
                if str(item.get("alert_code") or item.get("event_type") or "") not in {"PAPER_DAILY_DRAWDOWN", "SHADOW_MANUALLY_PAUSED"}
            ]
            _check(
                checks,
                "critical_events_explained",
                PASS if not unexplained else WARNING,
                "" if not unexplained else "NEEDS_PAPER_STATE_REVIEW",
                f"critical_recent={len(critical)} unexplained={len(unexplained)}",
            )
            paper_drawdown = _latest_paper_drawdown(reports)
        except Exception as exc:
            _check(checks, "paper_state_readable", FAIL, "NEEDS_PAPER_STATE_REVIEW", f"paper state failed: {exc}")
        finally:
            database.close()

    _check(checks, "stable_gate_exists", PASS if (reports / "stable_gate" / "stable_gate_summary.json").exists() else FAIL, "" if (reports / "stable_gate" / "stable_gate_summary.json").exists() else "NEEDS_STABLE_GATE", str(reports / "stable_gate" / "stable_gate_summary.json"))
    _check(checks, "balanced_stable_config_exists", PASS if (reports / "stability_repair" / "balanced_stable.ini").exists() else FAIL, "" if (reports / "stability_repair" / "balanced_stable.ini").exists() else "NEEDS_STABLE_GATE", str(reports / "stability_repair" / "balanced_stable.ini"))

    offset_path = Path("data/runtime/broker_time_offset.json")
    _check(
        checks,
        "broker_time_offset_optional",
        PASS if offset_path.exists() else WARNING,
        "",
        "broker_time_offset.json present" if offset_path.exists() else "broker_time_offset.json has not been created yet; OK if no MT5 offset has been detected",
    )

    for name in ("forward_evidence", "paper_state", "forward_diagnostics", "stable_gate", "stability_repair"):
        path = reports / name
        _check(checks, f"report_dir_{name}", PASS if path.exists() else WARNING, "" if path.exists() else "NEEDS_EVIDENCE_REPAIR", str(path))

    jsonl_status = _parse_jsonl_logs(logs)
    _check(
        checks,
        "jsonl_logs_parseable",
        PASS if jsonl_status["invalid_lines"] == 0 else FAIL,
        "" if jsonl_status["invalid_lines"] == 0 else "NEEDS_EVIDENCE_REPAIR",
        f"files={jsonl_status['files']} lines={jsonl_status['lines']} invalid_lines={jsonl_status['invalid_lines']}",
        metadata=jsonl_status,
    )
    _check(
        checks,
        "no_real_execution_flags",
        PASS if not jsonl_status["real_execution_flags"] else FAIL,
        "" if not jsonl_status["real_execution_flags"] else "NEEDS_CONFIG_REVIEW",
        f"real_execution_flags={jsonl_status['real_execution_flags']}",
    )

    _check(
        checks,
        "safety_config",
        PASS if config.demo_only and not config.live_trading_approved else FAIL,
        "" if config.demo_only and not config.live_trading_approved else "NEEDS_CONFIG_REVIEW",
        f"DEMO_ONLY={config.demo_only}; LIVE_TRADING_APPROVED={config.live_trading_approved}",
    )

    classification = _classify(checks)
    paper_clean_state = open_paper_trades == 0 and paper_drawdown >= 0
    summary = {
        "mode": "weekend-readiness",
        "weekend_readiness_status": classification,
        "classification": classification,
        "paper_clean_state": paper_clean_state,
        "paper_trades_open": open_paper_trades,
        "paper_drawdown": paper_drawdown,
        "paper_shadow_paused": bool(state.get("shadow_paused", False)),
        "shadow_paused_reason": state.get("paused_reason") or state.get("halt_reason") or "",
        "checks_passed": sum(1 for item in checks if item["status"] == PASS),
        "checks_warning": sum(1 for item in checks if item["status"] == WARNING),
        "checks_failed": sum(1 for item in checks if item["status"] == FAIL),
        "market_open_next_action": _next_action(classification),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "checks": checks,
    }
    summary_path = output / "weekend_readiness_summary.json"
    checks_path = output / "checks.csv"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(checks_path, checks, fieldnames=("check_name", "status", "classification", "detail", "execution_attempted"))
    summary["reports_created"] = [str(summary_path), str(checks_path)]
    return summary


def _check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    classification: str,
    detail: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "check_name": name,
            "status": status,
            "classification": classification,
            "detail": detail,
            "metadata": dict(metadata or {}),
            "execution_attempted": False,
        }
    )


def _recent_critical_alerts(database: TelemetryDatabase) -> list[dict[str, Any]]:
    rows = database.fetch_all("alerts")[-20:]
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            payload = {"alert_code": row["alert_code"], "severity": row["severity"]}
        if str(payload.get("severity", row["severity"])).upper() == "CRITICAL":
            result.append(payload)
    return result


def _latest_paper_drawdown(reports_root: Path) -> float:
    path = reports_root / "paper_state" / "paper_state_report.json"
    if not path.exists():
        return 0.0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return float(payload.get("paper_drawdown", 0.0) or 0.0)
    except Exception:
        return 0.0


def _parse_jsonl_logs(log_dir: Path) -> dict[str, Any]:
    files = list(log_dir.rglob("*.jsonl")) if log_dir.exists() else []
    invalid_examples: list[str] = []
    real_flags = 0
    lines = 0
    for path in files:
        try:
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not raw.strip():
                    continue
                lines += 1
                try:
                    payload = json.loads(raw)
                except Exception:
                    if len(invalid_examples) < 5:
                        invalid_examples.append(f"{path.name}:{lines}")
                    continue
                text = json.dumps(payload, sort_keys=True).lower()
                if '"execution_attempted": true' in text or '"order_send_called": true' in text or '"order_check_called": true' in text:
                    real_flags += 1
        except Exception as exc:
            if len(invalid_examples) < 5:
                invalid_examples.append(f"{path.name}:{exc}")
    return {
        "files": len(files),
        "lines": lines,
        "invalid_lines": len(invalid_examples),
        "invalid_examples": invalid_examples,
        "real_execution_flags": real_flags,
    }


def _classify(checks: Iterable[Mapping[str, Any]]) -> str:
    failures = [item for item in checks if item.get("status") == FAIL]
    if any(item.get("classification") == "NEEDS_CONFIG_REVIEW" for item in failures):
        return "NEEDS_CONFIG_REVIEW"
    if any(item.get("classification") == "NEEDS_STABLE_GATE" for item in failures):
        return "NEEDS_STABLE_GATE"
    if any(item.get("classification") == "NEEDS_PAPER_STATE_REVIEW" for item in failures):
        return "NEEDS_PAPER_STATE_REVIEW"
    if any(item.get("classification") == "NEEDS_EVIDENCE_REPAIR" for item in failures):
        return "NEEDS_EVIDENCE_REPAIR"
    if failures:
        return "NOT_READY_FOR_MARKET_OPEN"
    return "WEEKEND_SAFE"


def _next_action(classification: str) -> str:
    if classification == "WEEKEND_SAFE":
        return "Keep shadow paused until market open; use market-open-checklist before resuming paper observation."
    if classification == "NEEDS_PAPER_STATE_REVIEW":
        return "Run paper-state-report and paper-open-trades before market open."
    if classification == "NEEDS_STABLE_GATE":
        return "Regenerate stable_gate and balanced_stable artifacts before any BALANCED_STABLE shadow run."
    if classification == "NEEDS_EVIDENCE_REPAIR":
        return "Repair reports/log parsing and rerun forward-evidence offline."
    return "Review safety config before market open."


def _write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

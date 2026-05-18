"""Safe Telegram command center for shadow/paper operations only."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

import requests

from agi_style_forex_bot_mt5.contracts import Environment, Event, Severity
from agi_style_forex_bot_mt5.broker_quality import build_readiness_report
from agi_style_forex_bot_mt5.observability.daily_summary import DailySummary
from agi_style_forex_bot_mt5.observability.operational_status import build_health_status, build_status
from agi_style_forex_bot_mt5.execution_simulation import compare_paper_vs_backtest, run_simulation_calibration
from agi_style_forex_bot_mt5.persistence import check_db_health, create_backup, flush_telegram_outbox, replay_audit
from agi_style_forex_bot_mt5.portfolio import build_portfolio_state
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry.logger_setup import redact_text, utc_now_iso
from pathlib import Path


@dataclass(frozen=True)
class TelegramCommandResult:
    command: str
    accepted: bool
    response_text: str
    status: str
    execution_attempted: bool = False


class TelegramCommandCenter:
    """Process allowlisted Telegram commands without execution permissions."""

    COMMANDS = {
        "/status",
        "/health",
        "/summary",
        "/open_trades",
        "/today",
        "/symbols",
        "/rejections",
        "/drift",
        "/pause_shadow",
        "/resume_shadow",
        "/help",
        "/broker",
        "/readiness",
        "/spreads",
        "/latency",
        "/ml",
        "/ml_status",
        "/portfolio",
        "/exposure",
        "/correlation",
        "/risk",
        "/db",
        "/backup",
        "/replay",
        "/outbox",
        "/fills",
        "/costs",
        "/paper_vs_backtest",
        "/validation",
        "/pipeline",
        "/stable",
        "/stable_gate",
        "/shadow_stable",
        "/stable_status",
        "/stable_trades",
        "/stable_drift",
        "/stable_today",
        "/pause_stable_shadow",
        "/resume_stable_shadow",
        "/evidence",
        "/acceptance",
        "/stable_report",
        "/paper_audit",
        "/signal_diag",
        "/near_misses",
        "/forward_blockers",
        "/live_features",
        "/candidate_replay",
        "/blocker_sensitivity",
        "/regime_blocks",
        "/score_blocks",
    }

    def __init__(
        self,
        *,
        database: TelemetryDatabase,
        audit_logger: JsonlAuditLogger | None = None,
        allowed_chat_id: str | None = None,
        daily_report_dir: str = "data/reports/forward_shadow/daily",
        run_id: str = "telegram_command_center",
        bot_token: str | None = None,
        update_getter: Callable[[str, Mapping[str, Any], float], requests.Response] | None = None,
        message_sender: Callable[[str, Mapping[str, Any], float], requests.Response] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.database = database
        self.audit_logger = audit_logger
        self.allowed_chat_id = allowed_chat_id or os.getenv("TELEGRAM_ALLOWED_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
        self.daily_report_dir = daily_report_dir
        self.run_id = run_id
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.update_getter = update_getter or _default_getter
        self.message_sender = message_sender or _default_sender
        self.timeout_seconds = timeout_seconds

    def process_update(self, update: Mapping[str, Any]) -> TelegramCommandResult:
        message = dict(update.get("message") or update)
        chat = dict(message.get("chat") or {})
        chat_id = str(chat.get("id") or message.get("chat_id") or "")
        text = str(message.get("text") or "").strip()
        command = text.split()[0] if text else ""
        if not self.allowed_chat_id or chat_id != str(self.allowed_chat_id):
            result = TelegramCommandResult(command=command, accepted=False, response_text="", status="UNAUTHORIZED")
            self._record_command(chat_id, command, result)
            self._audit("UNAUTHORIZED_TELEGRAM_COMMAND", Severity.WARNING, {"command": command, "chat_id": redact_text(chat_id)})
            return result
        if command not in self.COMMANDS:
            result = TelegramCommandResult(command=command, accepted=False, response_text=self._help(), status="UNKNOWN_COMMAND")
            self._record_command(chat_id, command, result)
            self._audit("TELEGRAM_COMMAND_REJECTED", Severity.WARNING, {"command": command, "reason": "unknown command"})
            return result
        result = self._handle(command, text)
        self._record_command(chat_id, command, result)
        self._audit("TELEGRAM_COMMAND_PROCESSED", Severity.INFO, {"command": command, "status": result.status})
        return result

    def poll_and_process(self) -> int:
        """Poll Telegram updates when credentials exist; fail safe on errors."""

        if not self.bot_token:
            return 0
        state = self.database.get_operational_state()
        offset = int(state.get("telegram_update_offset") or 0)
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        try:
            response = self.update_getter(url, {"offset": offset + 1, "timeout": 0}, self.timeout_seconds)
            if response.status_code != 200:
                self._audit("TELEGRAM_COMMAND_POLL_ERROR", Severity.ERROR, {"status_code": response.status_code})
                return 0
            payload = response.json()
            processed = 0
            max_update_id = offset
            for update in payload.get("result", []):
                max_update_id = max(max_update_id, int(update.get("update_id", 0)))
                result = self.process_update(update)
                self._send_response(update, result)
                processed += 1
            if max_update_id > offset:
                self.database.update_operational_state({"telegram_update_offset": max_update_id})
            return processed
        except Exception as exc:
            self._audit("TELEGRAM_COMMAND_POLL_ERROR", Severity.ERROR, {"error": redact_text(str(exc))})
            return 0

    def _handle(self, command: str, text: str) -> TelegramCommandResult:
        if command == "/pause_shadow":
            reason = text.partition(" ")[2].strip() or "telegram command"
            self.database.set_shadow_paused(True, reason=reason, paused_by="telegram")
            return TelegramCommandResult(command, True, "Shadow entries paused. Open paper trades will still be managed.", "OK")
        if command == "/resume_shadow":
            self.database.set_shadow_paused(False, reason="", paused_by="telegram")
            return TelegramCommandResult(command, True, "Shadow entries resumed.", "OK")
        if command == "/pause_stable_shadow":
            reason = text.partition(" ")[2].strip() or "stable telegram command"
            self.database.set_shadow_paused(True, reason=reason, paused_by="telegram_stable")
            return TelegramCommandResult(command, True, "BALANCED_STABLE shadow entries paused. Open paper trades will still be managed.", "OK")
        if command == "/resume_stable_shadow":
            self.database.set_shadow_paused(False, reason="", paused_by="telegram_stable")
            return TelegramCommandResult(command, True, "BALANCED_STABLE shadow entries resumed.", "OK")
        if command == "/health":
            return TelegramCommandResult(command, True, str(build_health_status(self.database)), "OK")
        if command == "/status":
            return TelegramCommandResult(command, True, str(build_status(self.database)), "OK")
        if command in {"/summary", "/today"}:
            summary = DailySummary(self.database, self.daily_report_dir).generate()
            return TelegramCommandResult(command, True, str(summary), "OK")
        if command == "/open_trades":
            rows = self.database.fetch_open_paper_trades()
            return TelegramCommandResult(command, True, f"open_paper_trades={len(rows)}", "OK")
        if command == "/symbols":
            health = self.database.get_latest_health()
            return TelegramCommandResult(command, True, f"symbols_seen={health.get('symbols_seen', 'unknown')}", "OK")
        if command == "/rejections":
            status = build_status(self.database)
            reasons = status["metrics"].get("rejected_signals_by_reason", {})
            return TelegramCommandResult(command, True, str(reasons), "OK")
        if command == "/drift":
            return TelegramCommandResult(command, True, "drift_status=NEEDS_MORE_DATA", "OK")
        if command == "/broker":
            health = self.database.get_latest_health()
            return TelegramCommandResult(command, True, f"broker_quality={health.get('recent_alerts', [])}", "OK")
        if command == "/readiness":
            summary = build_readiness_report(
                reports_root="data/reports",
                output_dir="data/reports/readiness",
                database=self.database,
            )
            return TelegramCommandResult(command, True, str(summary), "OK")
        if command == "/spreads":
            rows = self.database.fetch_all("broker_quality")
            return TelegramCommandResult(command, True, f"broker_quality_records={len(rows)}", "OK")
        if command == "/latency":
            rows = self.database.fetch_all("broker_quality")
            latest = rows[-1]["payload_json"] if rows else "{}"
            return TelegramCommandResult(command, True, latest[:1000], "OK")
        if command in {"/ml", "/ml_status"}:
            rows = self.database.fetch_all("model_predictions")
            latest = rows[-1]["payload_json"] if rows else '{"ml_status":"ML_DISABLED","execution_attempted":false}'
            return TelegramCommandResult(command, True, latest[:1000], "OK")
        if command in {"/portfolio", "/risk"}:
            state = build_portfolio_state(self.database).to_dict()
            return TelegramCommandResult(command, True, str(state)[:1000], "OK")
        if command == "/exposure":
            exposure = build_portfolio_state(self.database).currency_exposure
            return TelegramCommandResult(command, True, str(exposure)[:1000], "OK")
        if command == "/correlation":
            return TelegramCommandResult(command, True, "correlation_status=READ_ONLY_REPORT_AVAILABLE via --mode correlation-report", "OK")
        if command == "/db":
            return TelegramCommandResult(command, True, str(check_db_health(sqlite_path=self.database.path))[:1000], "OK")
        if command == "/backup":
            return TelegramCommandResult(command, True, str(create_backup(sqlite_path=self.database.path, log_dir=None))[:1000], "OK")
        if command == "/replay":
            return TelegramCommandResult(command, True, str(replay_audit(database=self.database))[:1000], "OK")
        if command == "/outbox":
            return TelegramCommandResult(command, True, str(flush_telegram_outbox(database=self.database))[:1000], "OK")
        if command in {"/fills", "/costs"}:
            return TelegramCommandResult(command, True, str(run_simulation_calibration(database=self.database, reports_root="data/reports", output_dir="data/reports/execution_simulation"))[:1000], "OK")
        if command == "/paper_vs_backtest":
            return TelegramCommandResult(command, True, str(compare_paper_vs_backtest(database=self.database, reports_root="data/reports", output_dir="data/reports/paper_vs_backtest"))[:1000], "OK")
        if command in {"/validation", "/pipeline"}:
            summary_path = Path("data/reports/full_validation/pipeline_summary.json")
            decision_path = Path("data/reports/full_validation/master_decision.json")
            if summary_path.exists():
                response = summary_path.read_text(encoding="utf-8")[:1000]
            elif decision_path.exists():
                response = decision_path.read_text(encoding="utf-8")[:1000]
            else:
                response = '{"mode":"full-validation","status":"NO_PIPELINE_RUN","execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command in {"/stable", "/stable_gate", "/shadow_stable"}:
            summary_path = Path("data/reports/stable_gate/stable_gate_summary.json")
            if summary_path.exists():
                response = summary_path.read_text(encoding="utf-8")[:1000]
            else:
                response = '{"mode":"stable-robustness-gate","stable_gate_decision":"NO_STABLE_GATE_RUN","paper_shadow_ready":false,"execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/stable_status":
            summary_path = Path("data/reports/stable_gate/stable_gate_summary.json")
            health = self.database.get_latest_health()
            response = {
                "stable_gate": json_safe(summary_path),
                "last_heartbeat_utc": health.get("last_heartbeat_utc"),
                "open_paper_trades": health.get("open_paper_trades", 0),
                "shadow_paused": health.get("shadow_paused", False),
                "execution_attempted": False,
            }
            return TelegramCommandResult(command, True, str(response)[:1000], "OK")
        if command == "/stable_trades":
            rows = [json.loads(row["payload_json"]) for row in self.database.fetch_paper_trades()]
            stable = [row for row in rows if str((row.get("metadata") or {}).get("profile", "")).upper() == "BALANCED_STABLE"]
            open_count = sum(1 for row in stable if str(row.get("status", "")).upper() == "OPEN")
            closed_count = sum(1 for row in stable if str(row.get("status", "")).upper() == "CLOSED")
            return TelegramCommandResult(command, True, f"stable_open={open_count} stable_closed={closed_count} execution_attempted=false", "OK")
        if command == "/stable_drift":
            path = Path("data/reports/forward_shadow_stable/daily/drift.json")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"stable_drift_status":"NEEDS_MORE_DATA","execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/stable_today":
            path = Path("data/reports/forward_shadow_stable/daily/daily_summary.json")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"mode":"stable-daily-summary","status":"NO_DAILY_SUMMARY","execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command in {"/evidence", "/stable_report"}:
            from agi_style_forex_bot_mt5.forward_evidence import run_forward_evidence

            summary = run_forward_evidence(database=self.database, log_dir="data/logs/forward-shadow-stable", reports_root="data/reports", output_dir="data/reports/forward_evidence")
            return TelegramCommandResult(command, True, str(summary)[:1000], "OK")
        if command == "/acceptance":
            from agi_style_forex_bot_mt5.forward_evidence import run_forward_acceptance

            summary = run_forward_acceptance(database=self.database, log_dir="data/logs/forward-shadow-stable", reports_root="data/reports", output_dir="data/reports/forward_evidence")
            return TelegramCommandResult(command, True, str(summary)[:1000], "OK")
        if command == "/paper_audit":
            path = Path("data/reports/forward_evidence/paper_trade_audit.json")
            if not path.exists():
                from agi_style_forex_bot_mt5.forward_evidence import run_forward_evidence

                run_forward_evidence(database=self.database, log_dir="data/logs/forward-shadow-stable", reports_root="data/reports", output_dir="data/reports/forward_evidence")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"mode":"paper-trade-audit","status":"NO_AUDIT","execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/signal_diag":
            path = Path("data/reports/forward_diagnostics/signal_scarcity_summary.json")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"mode":"forward-signal-diagnose","status":"NO_DIAGNOSTIC_RUN","execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/near_misses":
            path = Path("data/reports/forward_diagnostics/near_misses.csv")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else "near_misses=0 execution_attempted=false"
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/forward_blockers":
            path = Path("data/reports/forward_diagnostics/signal_scarcity_summary.json")
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                response = str(payload.get("top_blockers", []))[:1000]
            else:
                response = "top_forward_blockers=[] execution_attempted=false"
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/live_features":
            path = Path("data/reports/forward_diagnostics/live_feature_probe.csv")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else "live_feature_probe=NO_DIAGNOSTIC_RUN execution_attempted=false"
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/candidate_replay":
            path = Path("data/reports/forward_research/candidate_replay_summary.json")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"mode":"forward-candidate-replay","status":"NO_REPLAY_RUN","execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/blocker_sensitivity":
            path = Path("data/reports/forward_research/blocker_sensitivity.json")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"mode":"forward-blocker-sensitivity","status":"NO_SENSITIVITY_RUN","execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/regime_blocks":
            path = Path("data/reports/forward_research/regime_mismatch_analysis.json")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"blocked_by_regime":{},"execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        if command == "/score_blocks":
            path = Path("data/reports/forward_research/ensemble_score_analysis.json")
            response = path.read_text(encoding="utf-8")[:1000] if path.exists() else '{"top_score_drag_components":[],"execution_attempted":false}'
            return TelegramCommandResult(command, True, response, "OK")
        return TelegramCommandResult(command, True, self._help(), "OK")

    def _help(self) -> str:
        return "Commands: " + " ".join(sorted(self.COMMANDS))

    def _send_response(self, update: Mapping[str, Any], result: TelegramCommandResult) -> None:
        if not self.bot_token or not result.response_text:
            return
        message = dict(update.get("message") or update)
        chat = dict(message.get("chat") or {})
        chat_id = str(chat.get("id") or message.get("chat_id") or "")
        if not self.allowed_chat_id or chat_id != str(self.allowed_chat_id):
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            self.message_sender(
                url,
                {"chat_id": chat_id, "text": redact_text(result.response_text)[:3900], "disable_web_page_preview": True},
                self.timeout_seconds,
            )
        except Exception as exc:
            self._audit("TELEGRAM_COMMAND_RESPONSE_ERROR", Severity.ERROR, {"error": redact_text(str(exc))})

    def _record_command(self, chat_id: str, command: str, result: TelegramCommandResult) -> None:
        self.database.insert_telegram_command(
            {
                "command_id": f"tgc_{uuid4().hex}",
                "chat_id_redacted": redact_text(chat_id),
                "command": command,
                "status": result.status,
                "timestamp_utc": utc_now_iso(),
                "response_text": result.response_text[:1000],
                "execution_attempted": False,
            }
        )

    def _audit(self, event_type: str, severity: Severity, payload: Mapping[str, Any]) -> None:
        event = Event.create(
            run_id=self.run_id,
            environment=Environment.DEMO,
            severity=severity,
            module="telegram_command_center",
            event_type=event_type,
            message=event_type.lower(),
            correlation_id=f"{self.run_id}:{event_type}",
            payload={**dict(payload), "execution_attempted": False},
        )
        self.database.insert_event(event)
        if self.audit_logger is not None:
            self.audit_logger.append_event(event)


def _default_getter(url: str, params: Mapping[str, Any], timeout: float) -> requests.Response:
    return requests.get(url, params=params, timeout=timeout)


def json_safe(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"stable_gate_decision": "NO_STABLE_GATE_RUN", "paper_shadow_ready": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"stable_gate_decision": "STABLE_GATE_READ_ERROR", "paper_shadow_ready": False}


def _default_sender(url: str, payload: Mapping[str, Any], timeout: float) -> requests.Response:
    return requests.post(url, json=payload, timeout=timeout)

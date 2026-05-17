"""Real-data research orchestration without order execution."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping

import pandas as pd

from .backtesting import (
    BacktestSettings,
    CostModel,
    WalkForwardSettings,
    classify_sample_size,
    run_backtest_for_symbols,
    run_monte_carlo_report,
    run_stress_report,
    run_walk_forward_for_symbols,
)
from .benchmarks import build_competitive_scorecard, run_benchmarks
from .calibration import bot_config_with_signal_profile, get_signal_profile, profile_allowed_for_shadow, profile_trade_frequency_status, write_profile_comparison
from .config import BotConfig
from .data_pipeline import audit_historical_data, build_broker_cost_profile, build_dataset_manifest, build_feature_availability_report, build_strategy_data_contract_report, cost_for_symbol, resolve_historical_data
from .market_structure import run_strategy_diagnose, write_structure_report
from .mt5_data_bot import DEFAULT_FOREX_SYMBOLS, MT5DiagnoseBot, summary_to_json
from .mt5_history_exporter import MT5HistoryExporter
from .research import run_research
from .telemetry import JsonlAuditLogger, TelemetryDatabase
from .validation_pipeline import PipelineConfig, run_full_validation


EXPORT_BAR_TARGETS = {"M5": 50_000, "M15": 30_000, "H1": 10_000}
VALID_STAGE_STATUSES = {"PASSED", "WARNING", "FAILED", "SKIPPED"}
TRADE_COLUMNS = (
    "signal_id",
    "symbol",
    "direction",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "profit",
    "r_multiple",
    "exit_reason",
    "regime",
    "session",
)


@dataclass(frozen=True)
class RealDataResearchConfig:
    """Serializable configuration for a real-data research run."""

    symbols: tuple[str, ...] = DEFAULT_FOREX_SYMBOLS
    output_root: str = "data/runs"
    bars: int = 50_000
    seed: int = 0
    fail_fast: bool = False
    run_id: str = ""
    signal_profile: str = "CONSERVATIVE"
    quick: bool = False
    skip_walk_forward: bool = False
    skip_monte_carlo: bool = False
    skip_stress_test: bool = False
    skip_research: bool = False
    skip_benchmark: bool = False
    max_symbols: int = 0
    max_bars: int = 0

    def __post_init__(self) -> None:
        symbols = _coerce_symbols(self.symbols)
        if self.max_symbols and self.max_symbols > 0:
            symbols = symbols[: self.max_symbols]
        object.__setattr__(self, "symbols", symbols)
        if self.max_bars and self.max_bars > 0:
            object.__setattr__(self, "bars", min(int(self.bars), int(self.max_bars)))
        profile = get_signal_profile(self.signal_profile)
        object.__setattr__(self, "signal_profile", profile.name)
        if not self.run_id:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            object.__setattr__(self, "run_id", f"{stamp}-real-data-research")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"execution_attempted": False}


@dataclass(frozen=True)
class ResearchStageResult:
    """Result for one real-data research stage."""

    name: str
    status: str
    started_at_utc: str
    ended_at_utc: str
    duration_seconds: float
    summary: dict[str, Any]
    error_message: str = ""
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        classification = str(self.summary.get("classification", ""))
        return {
            **payload,
            "stage_name": self.name,
            "classification": classification,
            "reports_created": list(self.summary.get("reports_created", [])),
        }


class RealDataResearchRunner:
    """Run real-data research stages in a safe, read-only/offline sequence."""

    def __init__(
        self,
        config: RealDataResearchConfig,
        *,
        bot_config: BotConfig | None = None,
        stage_overrides: Mapping[str, Callable[[], dict[str, Any]]] | None = None,
    ) -> None:
        self.config = config
        self.signal_profile = get_signal_profile(config.signal_profile)
        self.bot_config = bot_config_with_signal_profile(bot_config or BotConfig(), self.signal_profile.name)
        self.bot_config.validate_safety()
        self.stage_overrides = dict(stage_overrides or {})
        self.run_dir = Path(config.output_root) / config.run_id
        self.logs_dir = self.run_dir / "logs"
        self.historical_dir = self.run_dir / "historical"
        self.reports_dir = self.run_dir / "reports"
        self.sqlite_dir = self.run_dir / "sqlite"
        self.sqlite_path = self.sqlite_dir / "real-data-research.sqlite3"

    def run(self) -> dict[str, Any]:
        """Run all stages and write final JSON/HTML summaries."""

        self._prepare_dirs()
        results: list[ResearchStageResult] = []
        for name, function in self._stages():
            result = self._run_stage(name, function)
            results.append(result)
            if self.config.fail_fast and result.status == "FAILED":
                break

        final_decision, issues, next_actions = self._final_decision(results)
        compact = self._compact_summary(results, final_decision, issues, next_actions)
        profile_reports = self._write_profile_comparison(results, final_decision)
        summary = {
            "mode": "real-data-research",
            "run_id": self.config.run_id,
            "run_dir": str(self.run_dir),
            "symbols": list(self.config.symbols),
            "signal_profile_used": self.signal_profile.name,
            "thresholds_used": self.signal_profile.to_dict(),
            "profile_not_for_demo_live": bool(self.signal_profile.not_for_demo_live),
            "profile_allowed_for_shadow": profile_allowed_for_shadow(self.signal_profile.name),
            "stages": [result.to_dict() for result in results],
            "symbols_exported": self._symbols_exported(),
            "bars_by_symbol_timeframe": self._bars_by_symbol_timeframe(),
            "historical_data_status": self._stage_summary(results, "HISTORICAL_DATA_AUDIT").get("classification", ""),
            "feature_availability_status": self._stage_summary(results, "HISTORICAL_DATA_AUDIT").get("feature_availability", {}).get("classification", ""),
            "data_quality_status": self._stage_classification(results, "DATA_QUALITY"),
            "broker_cost_status": self._stage_classification(results, "BROKER_COST_PROFILE"),
            "strategy_diagnostics": self._stage_summary(results, "STRATEGY_DIAGNOSE"),
            "backtest_summary": self._stage_summary(results, "BACKTEST"),
            "walk_forward_summary": self._stage_summary(results, "WALK_FORWARD"),
            "monte_carlo_summary": self._stage_summary(results, "MONTE_CARLO"),
            "stress_summary": self._stage_summary(results, "STRESS_TEST"),
            "research_summary": self._stage_summary(results, "RESEARCH"),
            "benchmark_comparison": self._stage_summary(results, "BENCHMARK"),
            "competitive_scorecard": self._stage_summary(results, "COMPETITIVE_SCORECARD"),
            "full_validation_decision": self._stage_summary(results, "FULL_VALIDATION").get("final_decision", ""),
            "final_decision": final_decision,
            "top_5_issues_blocking_progress": issues[:5],
            "recommended_next_actions": next_actions,
            "compact_summary": compact,
            "reports_created": [
                str(self.run_dir / "final_summary.json"),
                str(self.run_dir / "final_summary.html"),
                str(self.run_dir / "final_summary_compact.json"),
                str(self.run_dir / "final_summary_compact.txt"),
                *profile_reports,
            ],
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
        (self.run_dir / "final_summary.json").write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
        (self.run_dir / "final_summary.html").write_text(_summary_html(summary), encoding="utf-8")
        (self.run_dir / "final_summary_compact.json").write_text(json.dumps(_jsonable(compact), indent=2, sort_keys=True), encoding="utf-8")
        (self.run_dir / "final_summary_compact.txt").write_text(_compact_text(compact), encoding="utf-8")
        return summary

    def _prepare_dirs(self) -> None:
        for path in (self.logs_dir, self.historical_dir, self.reports_dir, self.sqlite_dir):
            path.mkdir(parents=True, exist_ok=True)

    def _stages(self) -> tuple[tuple[str, Callable[[], dict[str, Any]]], ...]:
        stages = [
            ("MT5_DIAGNOSE", self._mt5_diagnose),
            ("EXPORT_HISTORY", self._export_history),
            ("HISTORICAL_DATA_AUDIT", self._historical_data_audit),
            ("DATA_CONTRACT_AUDIT", self._data_contract_audit),
            ("DATA_QUALITY", self._data_quality),
            ("BROKER_COST_PROFILE", self._broker_cost_profile),
            ("STRUCTURE_REPORT", self._structure_report),
            ("STRATEGY_DIAGNOSE", self._strategy_diagnose),
            ("BACKTEST", self._backtest),
            ("WALK_FORWARD", self._walk_forward),
            ("MONTE_CARLO", self._monte_carlo),
            ("STRESS_TEST", self._stress_test),
            ("RESEARCH", self._research),
            ("BENCHMARK", self._benchmark),
            ("COMPETITIVE_SCORECARD", self._competitive_scorecard),
            ("FULL_VALIDATION", self._full_validation),
        ]
        if self.config.quick:
            allowed = {"MT5_DIAGNOSE", "EXPORT_HISTORY", "HISTORICAL_DATA_AUDIT", "DATA_CONTRACT_AUDIT", "STRATEGY_DIAGNOSE", "BACKTEST"}
            return tuple((name, fn) for name, fn in stages if name in allowed)
        skipped = set()
        if self.config.skip_walk_forward:
            skipped.add("WALK_FORWARD")
        if self.config.skip_monte_carlo:
            skipped.add("MONTE_CARLO")
        if self.config.skip_stress_test:
            skipped.add("STRESS_TEST")
        if self.config.skip_research:
            skipped.add("RESEARCH")
        if self.config.skip_benchmark:
            skipped.update({"BENCHMARK", "COMPETITIVE_SCORECARD"})
        return tuple((name, fn) for name, fn in stages if name not in skipped)

    def _run_stage(self, name: str, function: Callable[[], dict[str, Any]]) -> ResearchStageResult:
        started = _now()
        start = perf_counter()
        try:
            stage_function = self.stage_overrides.get(name, function)
            summary = dict(stage_function())
            summary["execution_attempted"] = False
            summary.setdefault("signal_profile_used", self.signal_profile.name)
            summary.setdefault("thresholds_used", self.signal_profile.to_dict())
            summary.setdefault("profile_not_for_demo_live", bool(self.signal_profile.not_for_demo_live))
            summary.setdefault("profile_allowed_for_shadow", profile_allowed_for_shadow(self.signal_profile.name))
            status = self._status_for_summary(name, summary)
            error = ""
            if summary.get("mt5_connected") is False and name in {"MT5_DIAGNOSE", "EXPORT_HISTORY"}:
                status = "FAILED"
                error = "MT5 is not available for read-only research"
        except Exception as exc:
            summary = {"execution_attempted": False}
            status = "FAILED"
            error = str(exc)
        return ResearchStageResult(
            name=name,
            status=status,
            started_at_utc=started,
            ended_at_utc=_now(),
            duration_seconds=round(perf_counter() - start, 4),
            summary=summary,
            error_message=error,
            execution_attempted=False,
        )

    def _mt5_diagnose(self) -> dict[str, Any]:
        database = TelemetryDatabase(self.sqlite_path)
        try:
            bot = MT5DiagnoseBot(
                config=self.bot_config,
                symbols=self.config.symbols,
                bars=260,
                audit_logger=JsonlAuditLogger(self.logs_dir / "mt5-diagnose"),
                database=database,
            )
            return json.loads(summary_to_json(bot.run()))
        finally:
            database.close()

    def _export_history(self) -> dict[str, Any]:
        files_created = 0
        rows_exported = 0
        connected = True
        for timeframe, bars in self._export_targets().items():
            database = TelemetryDatabase(self.sqlite_path)
            try:
                exporter = MT5HistoryExporter(
                    config=self.bot_config,
                    symbols=self.config.symbols,
                    timeframes=(timeframe,),
                    bars=bars,
                    output_dir=self.historical_dir,
                    audit_logger=JsonlAuditLogger(self.logs_dir / "export-history"),
                    database=database,
                )
                summary = exporter.run()
                connected = connected and bool(summary.mt5_connected)
                files_created += int(summary.files_created)
                rows_exported += int(summary.rows_exported)
            finally:
                database.close()
        insufficiencies = self._data_insufficiencies()
        return {
            "mode": "export-history",
            "mt5_connected": connected,
            "symbols_requested": len(self.config.symbols),
            "files_created": files_created,
            "rows_exported": rows_exported,
            "bars_by_symbol_timeframe": self._bars_by_symbol_timeframe(),
            "data_insufficient": bool(insufficiencies),
            "insufficient_history": insufficiencies,
            "execution_attempted": False,
        }

    def _data_quality(self) -> dict[str, Any]:
        if not self._has_any_history():
            return self._write_skip_report("data_quality", "NEEDS_MORE_DATA", "no historical CSV files found")
        return build_dataset_manifest(
            data_dir=self.historical_dir,
            report_dir=self.reports_dir / "data_quality",
            symbols=self.config.symbols,
            timeframes=tuple(EXPORT_BAR_TARGETS),
        )

    def _historical_data_audit(self) -> dict[str, Any]:
        audit = audit_historical_data(
            data_dir=self.historical_dir,
            report_dir=self.reports_dir / "data_audit",
            symbols=self.config.symbols,
            timeframes=tuple(EXPORT_BAR_TARGETS),
        )
        feature = build_feature_availability_report(data_dir=self.historical_dir, report_dir=self.reports_dir / "data_audit", symbols=self.config.symbols)
        return {**audit, "feature_availability": feature, "reports_created": [*audit.get("reports_created", []), *feature.get("reports_created", [])], "execution_attempted": False}

    def _broker_cost_profile(self) -> dict[str, Any]:
        if not self._has_any_history():
            return self._write_skip_report("broker_costs", "NEEDS_MORE_DATA", "no historical CSV files found")
        return build_broker_cost_profile(data_dir=self.historical_dir, report_dir=self.reports_dir / "broker_costs", symbols=self.config.symbols)

    def _data_contract_audit(self) -> dict[str, Any]:
        return build_strategy_data_contract_report(
            data_dir=self.historical_dir,
            report_dir=self.reports_dir / "data_contract",
            symbols=self.config.symbols,
            timeframes=tuple(EXPORT_BAR_TARGETS),
        )

    def _structure_report(self) -> dict[str, Any]:
        if self._missing_history("M5"):
            return self._write_skip_report("market_structure", "NEEDS_MORE_DATA", "missing M5 historical CSV files")
        return write_structure_report(symbols=self.config.symbols, data_dir=self.historical_dir, report_dir=self.reports_dir / "market_structure")

    def _strategy_diagnose(self) -> dict[str, Any]:
        if self._missing_history("M5"):
            return self._write_skip_report("strategy_diagnostics", "NEEDS_MORE_DATA", "missing M5 historical CSV files")
        reports: list[dict[str, Any]] = []
        for symbol in self.config.symbols:
            reports.append(run_strategy_diagnose(symbol=symbol, data_dir=self.historical_dir, report_dir=self.reports_dir / "strategy_diagnostics" / symbol))
        return {
            "mode": "strategy-diagnose",
            "symbols_diagnosed": len(reports),
            "reports_created": [path for report in reports for path in report.get("reports_created", [])],
            "diagnostics": reports,
            "execution_attempted": False,
        }

    def _backtest(self) -> dict[str, Any]:
        missing = self._missing_history("M5")
        if missing:
            return self._write_empty_backtest_artifacts(
                classification="NEEDS_MORE_DATA",
                reason="missing M5 historical CSV files",
                details={"missing": missing},
            )
        profile = _load_optional_json(self.reports_dir / "broker_costs" / "broker_cost_profile.json")
        spread_points = cost_for_symbol(profile, self.config.symbols[0], fallback=10.0)
        try:
            result = run_backtest_for_symbols(
                data_dir=self.historical_dir,
                symbols=list(self.config.symbols),
                report_dir=self.reports_dir / "backtests",
                config=self.bot_config,
                settings=BacktestSettings(
                    cost_model=CostModel(
                        spread_points=spread_points,
                        slippage_points=1.0,
                        commission_per_lot_round_turn=0.0,
                        max_spread_points=self.bot_config.max_spread_points_default,
                    ),
                    data_source=str(self.historical_dir),
                    parameters={
                        "execution_attempted": False,
                        "SIGNAL_PROFILE": self.signal_profile.name,
                        "thresholds_used": self.signal_profile.to_dict(),
                    },
                ),
            )
        except Exception as exc:
            return self._write_empty_backtest_artifacts(
                classification="NEEDS_MORE_DATA",
                reason="backtest input validation failed",
                details={"error_message": str(exc)},
            )
        summary = dict(result.summary)
        if int(summary.get("total_trades", 0) or 0) == 0:
            if int(summary.get("signals_generated", 0) or 0) > 0:
                summary["classification"] = "WARNING_SIGNALS_NO_TRADES"
                summary["error_message"] = "backtest generated signals but no simulated trades"
            else:
                summary["classification"] = "WARNING_NO_TRADES"
                summary["error_message"] = "backtest completed but generated zero trades"
            self._ensure_empty_backtest_outputs(summary)
        summary.setdefault("sample_status", classify_sample_size(int(summary.get("total_trades", 0) or 0)))
        return summary

    def _walk_forward(self) -> dict[str, Any]:
        if not self._backtest_has_trades():
            return self._write_skip_report("walk_forward", "SKIPPED_NO_TRADES", "backtest generated no trades")
        total_trades = len(self._closed_trades_frame())
        if total_trades < 30:
            return self._write_skip_report("walk_forward", "NEEDS_MORE_TRADES", f"walk-forward requires at least 30 trades; observed {total_trades}", total_trades=total_trades)
        try:
            return run_walk_forward_for_symbols(
                data_dir=self.historical_dir,
                symbols=list(self.config.symbols),
                report_dir=self.reports_dir / "walk_forward",
                settings=WalkForwardSettings(),
            )
        except Exception as exc:
            return self._write_skip_report("walk_forward", "NEEDS_MORE_DATA", f"walk-forward input validation failed: {exc}")

    def _monte_carlo(self) -> dict[str, Any]:
        trades_path = self._find_trades_csv()
        if trades_path is None:
            return self._write_monte_carlo_skip("missing trades.csv")
        frame = _read_trades_frame(trades_path)
        if frame.empty:
            return self._write_monte_carlo_skip("trades.csv is empty", trades_path=trades_path)
        if "profit" in frame.columns:
            try:
                return run_monte_carlo_report(trades_path=trades_path, report_dir=self.reports_dir / "monte_carlo", seed=self.config.seed)
            except Exception as exc:
                return self._write_monte_carlo_skip(f"Monte Carlo input validation failed: {exc}", trades_path=trades_path)
        if "r_multiple" in frame.columns:
            values = pd.to_numeric(frame["r_multiple"], errors="coerce").dropna().astype(float).tolist()
            if not values:
                return self._write_monte_carlo_skip("r_multiple column has no numeric values", trades_path=trades_path)
            return run_monte_carlo_report(trades=values, trades_path=trades_path, report_dir=self.reports_dir / "monte_carlo", seed=self.config.seed)
        return self._write_monte_carlo_skip("trades.csv requires profit or r_multiple column", trades_path=trades_path)

    def _stress_test(self) -> dict[str, Any]:
        frame = self._closed_trades_frame()
        if frame.empty:
            return self._write_skip_report("stress", "SKIPPED_NO_TRADES", "backtest generated no trades")
        try:
            return run_stress_report(trades=frame.to_dict("records"), report_dir=self.reports_dir / "stress")
        except Exception as exc:
            return self._write_skip_report("stress", "SKIPPED_NO_TRADES", f"stress input validation failed: {exc}")

    def _research(self) -> dict[str, Any]:
        if self._missing_history("M5"):
            return self._write_skip_report("research", "NEEDS_MORE_DATA", "missing M5 historical CSV files")
        try:
            return run_research(
                symbols=list(self.config.symbols),
                data_dir=self.historical_dir,
                reports_root=self.reports_dir,
                output_dir=self.reports_dir / "research",
                max_candidates=100,
            )
        except Exception as exc:
            return self._write_skip_report("research", "NEEDS_MORE_DATA", f"research input validation failed: {exc}")

    def _benchmark(self) -> dict[str, Any]:
        if self._missing_history("M5"):
            return self._write_skip_report("benchmarks", "NEEDS_MORE_DATA", "missing M5 historical CSV files")
        profile = _load_optional_json(self.reports_dir / "broker_costs" / "broker_cost_profile.json")
        try:
            return run_benchmarks(data_dir=self.historical_dir, symbols=list(self.config.symbols), report_dir=self.reports_dir / "benchmarks", broker_cost_profile=profile, seed=self.config.seed)
        except Exception as exc:
            return self._write_skip_report("benchmarks", "NEEDS_MORE_DATA", f"benchmark input validation failed: {exc}")

    def _competitive_scorecard(self) -> dict[str, Any]:
        return build_competitive_scorecard(reports_root=self.reports_dir, output_dir=self.reports_dir / "competitive_scorecard")

    def _full_validation(self) -> dict[str, Any]:
        config = PipelineConfig(
            symbols=self.config.symbols,
            data_dir=str(self.historical_dir),
            reports_root=str(self.reports_dir),
            sqlite_path=str(self.sqlite_path),
            log_dir=str(self.logs_dir / "full-validation"),
            output_dir=str(self.reports_dir / "full_validation"),
            bars=self.config.bars,
            run_export_history=False,
            fail_fast=self.config.fail_fast,
            seed=self.config.seed,
        )
        return run_full_validation(config)

    def _status_for_summary(self, name: str, summary: Mapping[str, Any]) -> str:
        explicit = str(summary.get("stage_status", "")).upper()
        if explicit in VALID_STAGE_STATUSES:
            return explicit
        classification = str(summary.get("classification", "")).upper()
        if classification.startswith("SKIPPED"):
            return "SKIPPED"
        if classification in {"NEEDS_MORE_DATA", "NEEDS_MORE_TRADES", "WARNING_NO_TRADES", "WARNING_SIGNALS_NO_TRADES", "LOW_SAMPLE_WARNING", "WATCHLIST", "REJECTED", "NOT_READY"}:
            return "WARNING"
        if classification in {"OK", "APPROVED_FOR_SHADOW_OBSERVATION", "CONTINUE_FORWARD_SHADOW"}:
            return "PASSED"
        if summary.get("skipped") is True:
            return "SKIPPED"
        return "PASSED"

    def _export_targets(self) -> dict[str, int]:
        if self.config.bars >= 50_000:
            return dict(EXPORT_BAR_TARGETS)
        return {timeframe: min(self.config.bars, target) for timeframe, target in EXPORT_BAR_TARGETS.items()}

    def _data_insufficiencies(self) -> list[dict[str, Any]]:
        bars = self._bars_by_symbol_timeframe()
        rows: list[dict[str, Any]] = []
        for symbol in self.config.symbols:
            for timeframe, minimum in EXPORT_BAR_TARGETS.items():
                observed = int(bars.get(symbol, {}).get(timeframe, 0))
                if observed < minimum:
                    rows.append({"symbol": symbol, "timeframe": timeframe, "required_bars": minimum, "observed_bars": observed})
        return rows

    def _bars_by_symbol_timeframe(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for symbol in self.config.symbols:
            for timeframe in EXPORT_BAR_TARGETS:
                resolution = resolve_historical_data(self.historical_dir, symbol=symbol, timeframe=timeframe, min_bars=0)
                if resolution.found:
                    result.setdefault(symbol, {})[timeframe] = resolution.rows
        return result

    def _symbols_exported(self) -> list[str]:
        return sorted(self._bars_by_symbol_timeframe())

    def _has_any_history(self) -> bool:
        return any(self.historical_dir.rglob("*.csv"))

    def _missing_history(self, timeframe: str) -> list[str]:
        return [symbol for symbol in self.config.symbols if not resolve_historical_data(self.historical_dir, symbol=symbol, timeframe=timeframe, min_bars=0).found]

    def _find_trades_csv(self) -> Path | None:
        preferred = self.reports_dir / "backtests" / "trades.csv"
        if preferred.exists():
            return preferred
        matches = sorted((self.reports_dir / "backtests").glob("**/trades.csv"))
        return matches[0] if matches else None

    def _closed_trades_frame(self) -> pd.DataFrame:
        path = self._find_trades_csv()
        if path is None:
            return pd.DataFrame(columns=TRADE_COLUMNS)
        return _read_trades_frame(path)

    def _backtest_has_trades(self) -> bool:
        return not self._closed_trades_frame().empty

    def _ensure_empty_backtest_outputs(self, summary: Mapping[str, Any]) -> None:
        output = self.reports_dir / "backtests"
        output.mkdir(parents=True, exist_ok=True)
        trades_path = output / "trades.csv"
        equity_path = output / "equity_curve.csv"
        summary_path = output / "summary.json"
        if not trades_path.exists():
            pd.DataFrame(columns=TRADE_COLUMNS).to_csv(trades_path, index=False)
        if not equity_path.exists():
            pd.DataFrame({"timestamp": [datetime.now(timezone.utc).isoformat()], "equity": [10_000.0]}).to_csv(equity_path, index=False)
        payload = dict(summary)
        payload.setdefault("reports_created", [str(summary_path), str(trades_path), str(equity_path)])
        summary_path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")

    def _write_empty_backtest_artifacts(self, *, classification: str, reason: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
        output = self.reports_dir / "backtests"
        output.mkdir(parents=True, exist_ok=True)
        summary_path = output / "summary.json"
        trades_path = output / "trades.csv"
        equity_path = output / "equity_curve.csv"
        pd.DataFrame(columns=TRADE_COLUMNS).to_csv(trades_path, index=False)
        pd.DataFrame({"timestamp": [datetime.now(timezone.utc).isoformat()], "equity": [10_000.0]}).to_csv(equity_path, index=False)
        summary = {
            "mode": "backtest",
            "signal_profile_used": self.signal_profile.name,
            "thresholds_used": self.signal_profile.to_dict(),
            "profile_not_for_demo_live": bool(self.signal_profile.not_for_demo_live),
            "profile_allowed_for_shadow": profile_allowed_for_shadow(self.signal_profile.name),
            "symbols_tested": 0,
            "signals_generated": 0,
            "trades_generated": 0,
            "total_trades": 0,
            "sample_status": "LOW_SAMPLE",
            "min_required_trades": 30,
            "trades_by_symbol": [],
            "trades_by_strategy": [],
            "classification": classification,
            "error_message": reason,
            "details": dict(details or {}),
            "reports_created": [str(summary_path), str(trades_path), str(equity_path)],
            "execution_attempted": False,
        }
        summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
        return summary

    def _write_monte_carlo_skip(self, reason: str, *, trades_path: Path | None = None) -> dict[str, Any]:
        output = self.reports_dir / "monte_carlo"
        output.mkdir(parents=True, exist_ok=True)
        summary_path = output / "summary.json"
        simulations_path = output / "simulations.csv"
        pd.DataFrame(columns=["simulation", "final_equity", "return_pct", "max_drawdown_pct", "longest_losing_streak"]).to_csv(simulations_path, index=False)
        summary = {
            "mode": "monte-carlo",
            "input_files": [str(trades_path)] if trades_path else [],
            "classification": "SKIPPED_NO_TRADES",
            "total_trades": 0,
            "sample_status": "LOW_SAMPLE",
            "error_message": reason,
            "reports_created": [str(summary_path), str(simulations_path)],
            "execution_attempted": False,
        }
        summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
        return summary

    def _write_skip_report(self, report_name: str, classification: str, reason: str, **extra: Any) -> dict[str, Any]:
        output = self.reports_dir / report_name
        output.mkdir(parents=True, exist_ok=True)
        summary_path = output / "summary.json"
        summary = {
            "mode": report_name.replace("_", "-"),
            "classification": classification,
            "error_message": reason,
            **extra,
            "reports_created": [str(summary_path)],
            "execution_attempted": False,
        }
        summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
        return summary

    def _stage_summary(self, results: list[ResearchStageResult], name: str) -> dict[str, Any]:
        for result in results:
            if result.name == name:
                return result.summary
        return {}

    def _stage_classification(self, results: list[ResearchStageResult], name: str) -> str:
        summary = self._stage_summary(results, name)
        return str(summary.get("classification") or summary.get("status") or "")

    def _final_decision(self, results: list[ResearchStageResult]) -> tuple[str, list[str], list[str]]:
        issues: list[str] = []
        failed = [result for result in results if result.status == "FAILED"]
        for result in failed:
            issues.append(f"{result.name} failed: {result.error_message or result.summary}")
        insufficiencies = self._data_insufficiencies()
        if insufficiencies:
            issues.append("historical data is insufficient for one or more required symbol/timeframe pairs")
            return "NEEDS_MORE_DATA", issues, [
                "Keep MT5 connected and rerun export-history until required bar counts are met.",
                "Verify broker symbols and market availability with mt5-diagnose.",
            ]
        if failed:
            return "NEEDS_MORE_DATA", issues, ["Fix failed stages and rerun real-data-research."]
        full = self._stage_summary(results, "FULL_VALIDATION")
        decision = str(full.get("final_decision") or "")
        if decision:
            if decision == "CONTINUE_FORWARD_SHADOW" and self.signal_profile.name in {"ACTIVE", "RESEARCH_ONLY"}:
                issues.append(f"{self.signal_profile.name} is NOT_FOR_DEMO_LIVE and cannot promote to forward-shadow continuation")
                return "NEEDS_STRATEGY_RESEARCH", issues, _actions_for_decision("NEEDS_STRATEGY_RESEARCH")
            return decision, issues or _issues_for_decision(decision), _actions_for_decision(decision)
        competitive = self._stage_summary(results, "COMPETITIVE_SCORECARD")
        if str(competitive.get("classification", "")).upper() in {"REJECTED", "WEAK_EDGE"}:
            return "NEEDS_STRATEGY_RESEARCH", ["competitive scorecard did not show durable edge"], _actions_for_decision("NEEDS_STRATEGY_RESEARCH")
        if self.signal_profile.name in {"ACTIVE", "RESEARCH_ONLY"}:
            issues.append(f"{self.signal_profile.name} is NOT_FOR_DEMO_LIVE and limited to research diagnostics")
            return "NEEDS_STRATEGY_RESEARCH", issues, _actions_for_decision("NEEDS_STRATEGY_RESEARCH")
        return "CONTINUE_FORWARD_SHADOW", issues or ["evidence collected; continue paper observation"], _actions_for_decision("CONTINUE_FORWARD_SHADOW")

    def _compact_summary(self, results: list[ResearchStageResult], final_decision: str, issues: list[str], actions: list[str]) -> dict[str, Any]:
        backtest = self._stage_summary(results, "BACKTEST")
        benchmark = self._stage_summary(results, "BENCHMARK")
        total_trades = int(backtest.get("total_trades", 0) or 0)
        signals_generated = int(backtest.get("signals_generated", 0) or 0)
        trades_generated = int(backtest.get("trades_generated", total_trades) or 0)
        sample_status = str(backtest.get("sample_status") or classify_sample_size(total_trades))
        data_quality_ok = str(self._stage_classification(results, "DATA_QUALITY")).upper() == "OK"
        zero_trade_detected = total_trades == 0
        return {
            "run_id": self.config.run_id,
            "final_decision": final_decision,
            "signal_profile_used": self.signal_profile.name,
            "thresholds_used": self.signal_profile.to_dict(),
            "profile_not_for_demo_live": bool(self.signal_profile.not_for_demo_live),
            "profile_allowed_for_shadow": profile_allowed_for_shadow(self.signal_profile.name),
            "symbols_exported": self._symbols_exported(),
            "bars_by_symbol_timeframe": self._bars_by_symbol_timeframe(),
            "historical_data_status": self._historical_context(results).get("historical_data_status", ""),
            "timestamp_status": self._historical_context(results).get("timestamp_status", ""),
            "h1_bars_status": self._historical_context(results).get("h1_bars_status", ""),
            "data_contract_status": self._data_contract_context(results).get("data_contract_status", ""),
            "csv_blockers": self._data_contract_context(results).get("csv_blockers", []),
            "data_valid_symbols": self._data_contract_context(results).get("data_valid_symbols", []),
            "strategy_input_ready_symbols": self._data_contract_context(results).get("strategy_input_ready_symbols", []),
            "missing_timeframes": self._historical_context(results).get("missing_timeframes", []),
            "insufficient_timeframes": self._historical_context(results).get("insufficient_timeframes", []),
            "feature_availability_status": self._historical_context(results).get("feature_availability_status", ""),
            "main_feature_blocker": self._historical_context(results).get("main_feature_blocker", ""),
            "main_data_blocker": self._historical_context(results).get("main_data_blocker", ""),
            "total_trades": total_trades,
            "sample_status": sample_status,
            "min_required_trades": 30,
            "trades_by_symbol": backtest.get("trades_by_symbol", []),
            "trades_by_strategy": backtest.get("trades_by_strategy", []),
            "benchmark_status": next((result.status for result in results if result.name == "BENCHMARK"), ""),
            "benchmark_classification": str(benchmark.get("classification", "")),
            "zero_trade_detected": zero_trade_detected,
            "signals_generated": signals_generated,
            "trades_generated": trades_generated,
            "trade_frequency_status": profile_trade_frequency_status(signals_generated=signals_generated, trades_generated=trades_generated),
            "next_recommended_profile": self._next_recommended_profile(signals_generated=signals_generated, trades_generated=trades_generated),
            "likely_next_step": self._recommended_next_action(results, zero_trade_detected=zero_trade_detected, data_quality_ok=data_quality_ok, final_decision=final_decision),
            "recommended_next_action": self._recommended_next_action(results, zero_trade_detected=zero_trade_detected, data_quality_ok=data_quality_ok, final_decision=final_decision),
            "calibration": self._calibration_context(),
            "top_strategy_blockers": backtest.get("top_blocking_reasons", []),
            "failed_stage_error_codes": self._failed_stage_error_codes(results),
            "next_best_command": self._next_best_command(sample_status=sample_status, final_decision=final_decision),
            "stages_passed": sum(1 for result in results if result.status == "PASSED"),
            "stages_warning": sum(1 for result in results if result.status == "WARNING"),
            "stages_failed": sum(1 for result in results if result.status == "FAILED"),
            "stages_skipped": sum(1 for result in results if result.status == "SKIPPED"),
            "top_issues": issues[:5],
            "recommended_next_actions": actions,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }

    def _historical_context(self, results: list[ResearchStageResult]) -> dict[str, Any]:
        audit = self._stage_summary(results, "HISTORICAL_DATA_AUDIT")
        feature = audit.get("feature_availability", {}) if isinstance(audit.get("feature_availability"), Mapping) else {}
        return {
            "historical_data_status": audit.get("historical_data_status", audit.get("classification", "")),
            "timestamp_status": audit.get("timestamp_status", ""),
            "h1_bars_status": audit.get("h1_bars_status", ""),
            "missing_timeframes": audit.get("missing_timeframes", []),
            "insufficient_timeframes": audit.get("insufficient_timeframes", []),
            "feature_availability_status": feature.get("feature_availability_status", feature.get("classification", "")),
            "main_feature_blocker": feature.get("main_feature_blocker", ""),
            "main_data_blocker": audit.get("main_data_blocker", ""),
        }

    def _data_contract_context(self, results: list[ResearchStageResult]) -> dict[str, Any]:
        contract = self._stage_summary(results, "DATA_CONTRACT_AUDIT")
        return {
            "data_contract_status": contract.get("data_contract_status", contract.get("classification", "")),
            "csv_blockers": contract.get("csv_blockers", []),
            "data_valid_symbols": contract.get("data_valid_symbols", []),
            "strategy_input_ready_symbols": contract.get("strategy_input_ready_symbols", []),
        }

    def _recommended_next_action(self, results: list[ResearchStageResult], *, zero_trade_detected: bool, data_quality_ok: bool, final_decision: str) -> str:
        context = self._historical_context(results)
        main_blocker = str(context.get("main_data_blocker", ""))
        if context.get("timestamp_status") == "FAILED":
            return "Run FASE 18D timestamp normalization repair or re-export history."
        contract = self._data_contract_context(results)
        if contract.get("data_contract_status") not in {"", "OK"}:
            blockers = contract.get("csv_blockers", [])
            first = blockers[0].get("blocker") if blockers and isinstance(blockers[0], Mapping) else "CSV contract failed"
            return f"Fix historical CSV contract before threshold tuning: {first}."
        if main_blocker == "INSUFFICIENT_H1_BARS":
            return "Export more H1 bars or lower calibration diagnostic minimum only for research."
        if context.get("h1_bars_status") == "CALIBRATION_ONLY":
            return "Export more H1 bars for full validation; calibration may continue."
        if zero_trade_detected and data_quality_ok and not context.get("main_data_blocker"):
            return "Run FASE 19: Strategy Threshold Application / Balanced Profile Backtest."
        if zero_trade_detected and data_quality_ok:
            return "Run FASE 18: Signal Frequency Calibration"
        return _likely_next_step(final_decision)

    def _calibration_context(self) -> dict[str, Any]:
        summary = _load_optional_json(self.reports_dir / "calibration" / "summary.json") or _load_optional_json(self.reports_dir / "calibration" / "threshold_sweep_summary.json")
        if not summary:
            return {}
        return {
            "calibration_status": str(summary.get("classification") or summary.get("status") or ""),
            "recommended_profile": summary.get("recommended_profile", ""),
            "suggested_threshold_changes": summary.get("suggested_threshold_changes", {}),
            "expected_signal_frequency": summary.get("expected_signal_frequency", summary.get("signals_found", 0)),
            "signals_found": summary.get("signals_found", 0),
            "near_misses": summary.get("near_misses", 0),
            "top_blocking_reasons": summary.get("top_blocking_reasons", []),
            "top_blockers": summary.get("top_blocking_reasons", []),
        }

    def _next_recommended_profile(self, *, signals_generated: int, trades_generated: int) -> str:
        if signals_generated <= 0:
            return "BALANCED" if self.signal_profile.name == "CONSERVATIVE" else "ACTIVE"
        if trades_generated <= 0:
            return self.signal_profile.name if self.signal_profile.name in {"BALANCED", "ACTIVE"} else "BALANCED"
        return self.signal_profile.name

    def _failed_stage_error_codes(self, results: list[ResearchStageResult]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for result in results:
            if result.status not in {"FAILED", "WARNING"}:
                continue
            code = str(result.summary.get("classification") or result.summary.get("error_code") or result.error_message or "WARNING")
            rows.append({"stage_name": result.name, "error_code": code})
        return rows

    def _next_best_command(self, *, sample_status: str, final_decision: str) -> str:
        symbols = ",".join(list(self.config.symbols)[:3] or ["EURUSD", "GBPUSD", "USDJPY"])
        bars = max(int(self.config.bars or 0), 20_000)
        if sample_status == "LOW_SAMPLE":
            return f"py -m agi_style_forex_bot_mt5.cli --mode real-data-research --symbols {symbols} --bars {bars} --output-root data\\runs --signal-profile {self.signal_profile.name} --quick"
        if final_decision == "NEEDS_MORE_DATA":
            return f"py -m agi_style_forex_bot_mt5.cli --mode real-data-research --symbols {symbols} --bars {bars} --output-root data\\runs --signal-profile {self.signal_profile.name}"
        return "py -m agi_style_forex_bot_mt5.cli --mode latest-run-summary --runs-root data\\runs"

    def _write_profile_comparison(self, results: list[ResearchStageResult], final_decision: str) -> list[str]:
        backtest = self._stage_summary(results, "BACKTEST")
        benchmark = self._stage_summary(results, "BENCHMARK")
        metrics = {
            self.signal_profile.name: {
                "signals_generated": backtest.get("signals_generated", 0),
                "trades_generated": backtest.get("trades_generated", backtest.get("total_trades", 0)),
                "winrate": backtest.get("winrate", 0.0),
                "profit_factor": backtest.get("profit_factor", 0.0),
                "expectancy_r": backtest.get("expectancy_r", 0.0),
                "max_drawdown_pct": backtest.get("max_drawdown_pct", 0.0),
                "benchmark_classification": benchmark.get("classification", ""),
                "validation_decision": final_decision,
            }
        }
        return write_profile_comparison(self.reports_dir / "profile_runs", metrics)


def run_real_data_research(
    config: RealDataResearchConfig,
    *,
    bot_config: BotConfig | None = None,
    stage_overrides: Mapping[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for CLI and tests."""

    return RealDataResearchRunner(config, bot_config=bot_config, stage_overrides=stage_overrides).run()


def load_latest_run_summary(runs_root: str | Path = "data/runs") -> dict[str, Any]:
    """Load the compact summary from the newest real-data research run."""

    root = Path(runs_root)
    if not root.exists():
        return {
            "mode": "latest-run-summary",
            "classification": "NEEDS_MORE_DATA",
            "error_message": f"runs root does not exist: {root}",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    candidates = [path for path in root.iterdir() if path.is_dir() and (path / "final_summary_compact.json").exists()]
    if not candidates:
        return {
            "mode": "latest-run-summary",
            "classification": "NEEDS_MORE_DATA",
            "error_message": f"no final_summary_compact.json found under {root}",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    latest = sorted(candidates, key=lambda path: (path.name, path.stat().st_mtime))[-1]
    payload = json.loads((latest / "final_summary_compact.json").read_text(encoding="utf-8"))
    calibration = payload.get("calibration") if isinstance(payload.get("calibration"), dict) else {}
    latest_calibration = _load_optional_json(latest / "reports" / "calibration" / "threshold_sweep_summary.json") or _load_optional_json(latest / "reports" / "calibration" / "summary.json")
    if latest_calibration:
        calibration = {**calibration, **latest_calibration}
        payload["calibration"] = calibration
    payload["calibration_status"] = calibration.get("calibration_status") or calibration.get("classification", "")
    payload["recommended_profile"] = calibration.get("recommended_profile", payload.get("recommended_profile", ""))
    payload["signals_found"] = calibration.get("signals_found", payload.get("signals_found", 0))
    payload["near_misses"] = calibration.get("near_misses", payload.get("near_misses", 0))
    payload["top_blocking_reasons"] = calibration.get("top_blocking_reasons") or calibration.get("top_blockers") or payload.get("top_blocking_reasons", [])
    payload["suggested_threshold_changes"] = calibration.get("suggested_threshold_changes", payload.get("suggested_threshold_changes", {}))
    audit = _load_optional_json(latest / "reports" / "data_audit" / "historical_data_audit.json") or {}
    feature = _load_optional_json(latest / "reports" / "data_audit" / "feature_availability.json") or {}
    contract = _load_optional_json(latest / "reports" / "data_contract" / "data_contract_report.json") or {}
    edge = _load_optional_json(latest / "reports" / "edge" / "edge_summary.json") or {}
    if not edge:
        global_edge = _load_optional_json(Path("data/reports/edge/edge_summary.json")) or {}
        if str(global_edge.get("run_id", "")) == str(payload.get("run_id", latest.name)):
            edge = global_edge
    payload["historical_data_status"] = audit.get("historical_data_status", audit.get("classification", payload.get("historical_data_status", "")))
    payload["timestamp_status"] = audit.get("timestamp_status", payload.get("timestamp_status", ""))
    payload["h1_bars_status"] = audit.get("h1_bars_status", payload.get("h1_bars_status", ""))
    payload["missing_timeframes"] = audit.get("missing_timeframes", payload.get("missing_timeframes", []))
    payload["insufficient_timeframes"] = audit.get("insufficient_timeframes", payload.get("insufficient_timeframes", []))
    payload["feature_availability_status"] = feature.get("feature_availability_status", feature.get("classification", payload.get("feature_availability_status", "")))
    payload["main_feature_blocker"] = feature.get("main_feature_blocker", payload.get("main_feature_blocker", ""))
    payload["main_data_blocker"] = audit.get("main_data_blocker", payload.get("main_data_blocker", ""))
    payload["data_contract_status"] = contract.get("data_contract_status", contract.get("classification", payload.get("data_contract_status", "")))
    payload["csv_blockers"] = contract.get("csv_blockers", payload.get("csv_blockers", []))
    payload["data_valid_symbols"] = contract.get("data_valid_symbols", payload.get("data_valid_symbols", []))
    payload["strategy_input_ready_symbols"] = contract.get("strategy_input_ready_symbols", payload.get("strategy_input_ready_symbols", []))
    if edge:
        payload["edge_decision"] = edge.get("decision", "")
        payload["symbols_keep"] = edge.get("symbols_keep", [])
        payload["symbols_reject"] = edge.get("symbols_reject", [])
        payload["strategies_keep"] = edge.get("strategies_keep", [])
        payload["strategies_disable"] = edge.get("strategies_disable", [])
        if edge.get("decision"):
            payload["recommended_next_action"] = _edge_next_action(str(edge.get("decision")))
    if payload.get("timestamp_status") == "FAILED":
        payload["recommended_next_action"] = "Run FASE 18D timestamp normalization repair or re-export history."
    elif payload.get("data_contract_status") not in {"", "OK"}:
        blockers = payload.get("csv_blockers", [])
        first = blockers[0].get("blocker") if blockers and isinstance(blockers[0], Mapping) else "CSV contract failed"
        payload["recommended_next_action"] = f"Fix historical CSV contract before threshold tuning: {first}."
    elif payload.get("main_data_blocker") == "INSUFFICIENT_H1_BARS":
        payload["recommended_next_action"] = "Export more H1 bars or lower calibration diagnostic minimum only for research."
    elif payload.get("h1_bars_status") == "CALIBRATION_ONLY":
        payload["recommended_next_action"] = "Export more H1 bars for full validation; calibration may continue."
    elif int(payload.get("total_trades", 0) or 0) == 0 and not payload.get("main_data_blocker"):
        payload["recommended_next_action"] = "Run FASE 19: Strategy Threshold Application / Balanced Profile Backtest."
    return {"mode": "latest-run-summary", "run_dir": str(latest), **payload, "execution_attempted": False}


def _edge_next_action(decision: str) -> str:
    mapping = {
        "FORWARD_SHADOW_CANDIDATE": "Continue paper-only forward-shadow for selected symbols; no demo/live execution.",
        "CONTINUE_BALANCED_RESEARCH": "Run BALANCED quick research on more symbols/bars.",
        "TEST_ACTIVE_RESEARCH_ONLY": "Test ACTIVE only in research/profile-comparison; never demo/live.",
        "NEEDS_MORE_TRADES": "Run more BALANCED research history or symbols to reach at least 30 trades.",
        "NEEDS_STRATEGY_FIX": "Inspect strategy/session/regime selectors and blockers.",
        "NEEDS_BROKER_COST_FIX": "Review spread/cost blockers and broker cost profile.",
        "REJECT_CURRENT_CONFIG": "Reject current config and return to strategy research.",
    }
    return mapping.get(decision, "Review edge evaluation report.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_symbols(symbols: Any) -> tuple[str, ...]:
    if isinstance(symbols, str):
        parts = symbols.split(",")
    else:
        parts = list(symbols)
    normalized = tuple(str(symbol).strip().upper() for symbol in parts if str(symbol).strip())
    if not normalized:
        raise ValueError("RealDataResearchConfig requires at least one symbol")
    return normalized


def _read_trades_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=TRADE_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=list(frame.columns) or list(TRADE_COLUMNS))
    return frame


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _issues_for_decision(decision: str) -> list[str]:
    return {
        "NEEDS_MORE_DATA": ["critical reports or clean historical data are missing"],
        "NEEDS_STRATEGY_RESEARCH": ["current strategies do not show enough robust edge"],
        "NEEDS_BROKER_FIX": ["broker quality or symbol readiness is not acceptable"],
        "NEEDS_COST_RECALIBRATION": ["cost or paper-vs-backtest assumptions are not conservative enough"],
        "REJECTED": ["validation evidence rejected the current candidate set"],
        "CONTINUE_FORWARD_SHADOW": ["forward paper evidence is still accumulating"],
    }.get(decision, ["decision requires manual review"])


def _actions_for_decision(decision: str) -> list[str]:
    return {
        "NEEDS_MORE_DATA": ["Export more MT5 history and rerun data-quality.", "Check symbols with mt5-diagnose."],
        "NEEDS_STRATEGY_RESEARCH": ["Run research ablations and inspect weak symbols.", "Compare strategy versions against baselines."],
        "NEEDS_BROKER_FIX": ["Review spreads, tick freshness and broker readiness.", "Consider broker/session filters."],
        "NEEDS_COST_RECALIBRATION": ["Increase spread/slippage assumptions.", "Compare paper-vs-backtest fill quality."],
        "REJECTED": ["Do not promote candidates.", "Return to strategy research with stricter filters."],
        "CONTINUE_FORWARD_SHADOW": ["Continue forward-shadow observation.", "Collect more paper trades before any future demo execution review."],
    }.get(decision, ["Review final_summary.json manually."])


def _likely_next_step(decision: str) -> str:
    return {
        "NEEDS_MORE_DATA": "Collect/export more MT5 history and rerun real-data-research",
        "NEEDS_STRATEGY_RESEARCH": "Run strategy research and signal calibration",
        "NEEDS_BROKER_FIX": "Review broker quality and symbol readiness",
        "NEEDS_COST_RECALIBRATION": "Recalibrate spread/slippage/commission assumptions",
        "REJECTED": "Reject current candidate set and redesign strategy filters",
        "CONTINUE_FORWARD_SHADOW": "Continue forward-shadow observation",
    }.get(decision, "Review final summary manually")


def _summary_html(summary: Mapping[str, Any]) -> str:
    rows = "\n".join(f"<tr><th>{key}</th><td><pre>{json.dumps(_jsonable(value), ensure_ascii=True, indent=2)}</pre></td></tr>" for key, value in summary.items() if key != "stages")
    stage_rows = "\n".join(
        f"<tr><td>{stage['name']}</td><td>{stage['status']}</td><td>{stage.get('error_message', '')}</td></tr>"
        for stage in summary.get("stages", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Real Data Research Run</title></head>
<body>
<h1>Real Data Research Run</h1>
<p>Read-only/research run. No order_send or order_check path is enabled.</p>
<h2>Summary</h2>
<table>{rows}</table>
<h2>Stages</h2>
<table><tr><th>Stage</th><th>Status</th><th>Error</th></tr>{stage_rows}</table>
</body>
</html>
"""


def _compact_text(summary: Mapping[str, Any]) -> str:
    lines = [
        f"run_id: {summary.get('run_id', '')}",
        f"final_decision: {summary.get('final_decision', '')}",
        f"symbols_exported: {', '.join(summary.get('symbols_exported', []))}",
        f"stages_passed: {summary.get('stages_passed', 0)}",
        f"stages_warning: {summary.get('stages_warning', 0)}",
        f"stages_failed: {summary.get('stages_failed', 0)}",
        f"stages_skipped: {summary.get('stages_skipped', 0)}",
        "top_issues:",
    ]
    lines.extend(f"- {item}" for item in summary.get("top_issues", []))
    lines.append("recommended_next_actions:")
    lines.extend(f"- {item}" for item in summary.get("recommended_next_actions", []))
    lines.extend(
        [
            f"execution_attempted: {str(summary.get('execution_attempted', False)).lower()}",
            f"order_send_called: {str(summary.get('order_send_called', False)).lower()}",
            f"order_check_called: {str(summary.get('order_check_called', False)).lower()}",
        ]
    )
    return "\n".join(lines) + "\n"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    return value

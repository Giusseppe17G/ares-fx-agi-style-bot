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
    run_backtest_for_symbols,
    run_monte_carlo_report,
    run_stress_report,
    run_walk_forward_for_symbols,
)
from .benchmarks import build_competitive_scorecard, run_benchmarks
from .config import BotConfig
from .data_pipeline import build_broker_cost_profile, build_dataset_manifest, cost_for_symbol
from .market_structure import run_strategy_diagnose, write_structure_report
from .mt5_data_bot import DEFAULT_FOREX_SYMBOLS, MT5DiagnoseBot, summary_to_json
from .mt5_history_exporter import MT5HistoryExporter
from .research import run_research
from .telemetry import JsonlAuditLogger, TelemetryDatabase
from .validation_pipeline import PipelineConfig, run_full_validation


EXPORT_BAR_TARGETS = {"M5": 50_000, "M15": 30_000, "H1": 10_000}


@dataclass(frozen=True)
class RealDataResearchConfig:
    """Serializable configuration for a real-data research run."""

    symbols: tuple[str, ...] = DEFAULT_FOREX_SYMBOLS
    output_root: str = "data/runs"
    bars: int = 50_000
    seed: int = 0
    fail_fast: bool = False
    run_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(symbol.upper() for symbol in self.symbols))
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
        return asdict(self)


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
        self.bot_config = bot_config or BotConfig()
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
        summary = {
            "mode": "real-data-research",
            "run_id": self.config.run_id,
            "run_dir": str(self.run_dir),
            "symbols": list(self.config.symbols),
            "stages": [result.to_dict() for result in results],
            "symbols_exported": self._symbols_exported(),
            "bars_by_symbol_timeframe": self._bars_by_symbol_timeframe(),
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
            "reports_created": [
                str(self.run_dir / "final_summary.json"),
                str(self.run_dir / "final_summary.html"),
            ],
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
        (self.run_dir / "final_summary.json").write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
        (self.run_dir / "final_summary.html").write_text(_summary_html(summary), encoding="utf-8")
        return summary

    def _prepare_dirs(self) -> None:
        for path in (self.logs_dir, self.historical_dir, self.reports_dir, self.sqlite_dir):
            path.mkdir(parents=True, exist_ok=True)

    def _stages(self) -> tuple[tuple[str, Callable[[], dict[str, Any]]], ...]:
        return (
            ("MT5_DIAGNOSE", self._mt5_diagnose),
            ("EXPORT_HISTORY", self._export_history),
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
        )

    def _run_stage(self, name: str, function: Callable[[], dict[str, Any]]) -> ResearchStageResult:
        started = _now()
        start = perf_counter()
        try:
            stage_function = self.stage_overrides.get(name, function)
            summary = dict(stage_function())
            summary["execution_attempted"] = False
            status = "PASSED"
            error = ""
            if summary.get("mt5_connected") is False and name in {"MT5_DIAGNOSE", "EXPORT_HISTORY"}:
                status = "FAILED"
                error = "MT5 is not available for read-only research"
            if summary.get("classification") in {"REJECTED", "NOT_READY"}:
                status = "WARNING" if status == "PASSED" else status
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
        return build_dataset_manifest(
            data_dir=self.historical_dir,
            report_dir=self.reports_dir / "data_quality",
            symbols=self.config.symbols,
            timeframes=tuple(EXPORT_BAR_TARGETS),
        )

    def _broker_cost_profile(self) -> dict[str, Any]:
        return build_broker_cost_profile(data_dir=self.historical_dir, report_dir=self.reports_dir / "broker_costs", symbols=self.config.symbols)

    def _structure_report(self) -> dict[str, Any]:
        return write_structure_report(symbols=self.config.symbols, data_dir=self.historical_dir, report_dir=self.reports_dir / "market_structure")

    def _strategy_diagnose(self) -> dict[str, Any]:
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
        profile = _load_optional_json(self.reports_dir / "broker_costs" / "broker_cost_profile.json")
        spread_points = cost_for_symbol(profile, self.config.symbols[0], fallback=10.0)
        result = run_backtest_for_symbols(
            data_dir=self.historical_dir,
            symbols=self.config.symbols,
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
                parameters={"execution_attempted": False},
            ),
        )
        return dict(result.summary)

    def _walk_forward(self) -> dict[str, Any]:
        return run_walk_forward_for_symbols(
            data_dir=self.historical_dir,
            symbols=self.config.symbols,
            report_dir=self.reports_dir / "walk_forward",
            settings=WalkForwardSettings(),
        )

    def _monte_carlo(self) -> dict[str, Any]:
        return run_monte_carlo_report(
            trades_path=self.reports_dir / "backtests" / "trades.csv",
            report_dir=self.reports_dir / "monte_carlo",
            seed=self.config.seed,
        )

    def _stress_test(self) -> dict[str, Any]:
        return run_stress_report(data_dir=self.historical_dir, symbols=self.config.symbols, report_dir=self.reports_dir / "stress")

    def _research(self) -> dict[str, Any]:
        return run_research(
            symbols=self.config.symbols,
            data_dir=self.historical_dir,
            reports_root=self.reports_dir,
            output_dir=self.reports_dir / "research",
            max_candidates=100,
        )

    def _benchmark(self) -> dict[str, Any]:
        profile = _load_optional_json(self.reports_dir / "broker_costs" / "broker_cost_profile.json")
        return run_benchmarks(data_dir=self.historical_dir, symbols=self.config.symbols, report_dir=self.reports_dir / "benchmarks", broker_cost_profile=profile, seed=self.config.seed)

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
        for path in sorted(self.historical_dir.glob("*.csv")):
            parts = path.stem.upper().replace("-", "_").split("_")
            if len(parts) < 2:
                continue
            symbol, timeframe = parts[0], parts[1]
            try:
                rows = len(pd.read_csv(path, usecols=["time"]))
            except Exception:
                rows = 0
            result.setdefault(symbol, {})[timeframe] = rows
        return result

    def _symbols_exported(self) -> list[str]:
        return sorted(self._bars_by_symbol_timeframe())

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
            return decision, issues or _issues_for_decision(decision), _actions_for_decision(decision)
        competitive = self._stage_summary(results, "COMPETITIVE_SCORECARD")
        if str(competitive.get("classification", "")).upper() in {"REJECTED", "WEAK_EDGE"}:
            return "NEEDS_STRATEGY_RESEARCH", ["competitive scorecard did not show durable edge"], _actions_for_decision("NEEDS_STRATEGY_RESEARCH")
        return "CONTINUE_FORWARD_SHADOW", issues or ["evidence collected; continue paper observation"], _actions_for_decision("CONTINUE_FORWARD_SHADOW")


def run_real_data_research(
    config: RealDataResearchConfig,
    *,
    bot_config: BotConfig | None = None,
    stage_overrides: Mapping[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for CLI and tests."""

    return RealDataResearchRunner(config, bot_config=bot_config, stage_overrides=stage_overrides).run()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

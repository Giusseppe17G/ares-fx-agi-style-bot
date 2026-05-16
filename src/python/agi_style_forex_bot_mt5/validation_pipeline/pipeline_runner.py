"""Full validation pipeline runner."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping
from uuid import uuid4

from .master_decision_engine import MasterDecisionEngine
from .pipeline_config import PipelineConfig
from .pipeline_lock import PipelineLock
from .pipeline_report import write_pipeline_reports
from .pipeline_stage import PipelineStage, StageStatus
from .stage_results import StageResult
from .validation_artifacts import artifact_paths


class PipelineRunner:
    """Run configured validation stages in a safe, reproducible order."""

    def __init__(self, config: PipelineConfig, *, stage_overrides: Mapping[str, Any] | None = None) -> None:
        self.config = config
        self.pipeline_run_id = f"fvp_{uuid4().hex}"
        self.stage_overrides = dict(stage_overrides or {})

    def run(self) -> dict[str, Any]:
        output = Path(self.config.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        with PipelineLock(output / ".pipeline.lock"):
            results: list[StageResult] = []
            for stage in self._stages():
                result = self._run_stage(stage)
                results.append(result)
                if self.config.fail_fast and result.status == StageStatus.FAILED.value:
                    break
            decision_result = self._master_decision_stage()
            results.append(decision_result)
            decision = MasterDecisionEngine().decide(
                reports_root=self.config.reports_root,
                output_dir=self.config.output_dir,
                symbols=self.config.symbols,
            )
            summary = self._summary(results, decision.final_decision)
            reports = write_pipeline_reports(
                output_dir=self.config.output_dir,
                reports_root=self.config.reports_root,
                pipeline_summary=summary,
                stage_results=results,
                decision=decision,
            )
            summary["reports_created"] = reports
            (output / "pipeline_summary.json").write_text(__import__("json").dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
            return summary

    def _stages(self) -> tuple[PipelineStage, ...]:
        paths = artifact_paths(self.config.reports_root, self.config.output_dir)
        cfg = self.config
        return (
            self._stage("EXPORT_HISTORY", cfg.run_export_history, (), self._export_history, required=False),
            self._stage("DATA_QUALITY", cfg.run_data_quality, (paths["data_quality"],), self._data_quality),
            self._stage("BROKER_COST_PROFILE", cfg.run_cost_profile, (paths["broker_cost_profile"],), self._broker_cost_profile),
            self._stage("BACKTEST", cfg.run_backtest, (paths["backtest"],), self._backtest),
            self._stage("WALK_FORWARD", cfg.run_walk_forward, (paths["walk_forward"],), self._walk_forward),
            self._stage("MONTE_CARLO", cfg.run_monte_carlo, (paths["monte_carlo"],), self._monte_carlo),
            self._stage("STRESS_TEST", cfg.run_stress_test, (paths["stress"],), self._stress_test),
            self._stage("RESEARCH", cfg.run_research, (paths["research"],), self._research),
            self._stage("BENCHMARK", cfg.run_benchmark, (paths["benchmark"],), self._benchmark),
            self._stage("COMPETITIVE_SCORECARD", cfg.run_competitive_scorecard, (paths["competitive_scorecard"],), self._competitive_scorecard),
            self._stage("BROKER_QUALITY", cfg.run_broker_quality, (paths["broker_quality"],), self._broker_quality, required=False),
            self._stage("SIMULATION_CALIBRATION", cfg.run_simulation_calibration, (paths["simulation_calibration"],), self._simulation_calibration),
            self._stage("PAPER_VS_BACKTEST", cfg.run_paper_vs_backtest, (paths["paper_vs_backtest"],), self._paper_vs_backtest),
            self._stage("VALIDATION_REPORT", cfg.run_validation_report, (paths["validation_report"],), self._validation_report),
        )

    def _stage(self, name: str, enabled: bool, outputs: tuple[Path, ...], function: Any, *, required: bool = True) -> PipelineStage:
        override = self.stage_overrides.get(name)
        return PipelineStage(name=name, enabled=enabled, function=override or function, expected_outputs=outputs, required=required, command_or_function=getattr(override or function, "__name__", name))

    def _run_stage(self, stage: PipelineStage) -> StageResult:
        if not stage.enabled:
            return StageResult(stage.name, StageStatus.SKIPPED.value, None, None, 0.0, stage.command_or_function, tuple(str(path) for path in stage.input_paths), tuple(str(path) for path in stage.expected_outputs), {"skipped": True}, "", False)
        started = _now()
        start = perf_counter()
        try:
            summary = dict(stage.function())
            missing = [str(path) for path in stage.expected_outputs if not path.exists()]
            status = StageStatus.PASSED.value
            error = ""
            if missing:
                status = StageStatus.FAILED.value if stage.required else StageStatus.WARNING.value
                error = "missing expected outputs: " + ", ".join(missing)
            if summary.get("classification") in {"REJECTED", "NOT_READY"}:
                status = StageStatus.WARNING.value if status == StageStatus.PASSED.value else status
        except Exception as exc:
            summary = {"execution_attempted": False}
            status = StageStatus.FAILED.value
            error = str(exc)
        ended = _now()
        return StageResult(stage.name, status, started, ended, round(perf_counter() - start, 4), stage.command_or_function, tuple(str(path) for path in stage.input_paths), tuple(str(path) for path in stage.expected_outputs), {**summary, "execution_attempted": False}, error, False)

    def _master_decision_stage(self) -> StageResult:
        started = _now()
        start = perf_counter()
        decision = MasterDecisionEngine().decide(reports_root=self.config.reports_root, output_dir=self.config.output_dir, symbols=self.config.symbols)
        return StageResult("MASTER_DECISION", StageStatus.PASSED.value, started, _now(), round(perf_counter() - start, 4), "MasterDecisionEngine.decide", (), (), decision.to_dict(), "", False)

    def _summary(self, results: list[StageResult], final_decision: str) -> dict[str, Any]:
        return {
            "mode": "full-validation",
            "pipeline_run_id": self.pipeline_run_id,
            "stages_passed": sum(1 for result in results if result.status == StageStatus.PASSED.value),
            "stages_warning": sum(1 for result in results if result.status == StageStatus.WARNING.value),
            "stages_failed": sum(1 for result in results if result.status == StageStatus.FAILED.value),
            "stages_skipped": sum(1 for result in results if result.status == StageStatus.SKIPPED.value),
            "final_decision": final_decision,
            "config": self.config.to_dict(),
            "stage_results": [result.to_dict() for result in results],
            "reports_created": [],
            "execution_attempted": False,
        }

    def _export_history(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.config import BotConfig
        from agi_style_forex_bot_mt5.mt5_history_exporter import MT5HistoryExporter
        from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

        database = TelemetryDatabase(self.config.sqlite_path)
        try:
            exporter = MT5HistoryExporter(
                config=BotConfig(),
                symbols=self.config.symbols,
                timeframes=self.config.timeframes,
                bars=self.config.bars,
                output_dir=self.config.data_dir,
                audit_logger=JsonlAuditLogger(self.config.log_dir),
                database=database,
            )
            return exporter.run().__dict__ | {"execution_attempted": False}
        finally:
            database.close()

    def _data_quality(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.data_pipeline import build_dataset_manifest

        return build_dataset_manifest(data_dir=self.config.data_dir, report_dir=Path(self.config.reports_root) / "data_quality", symbols=self.config.symbols, timeframes=self.config.timeframes)

    def _broker_cost_profile(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.data_pipeline import build_broker_cost_profile

        return build_broker_cost_profile(data_dir=self.config.data_dir, report_dir=Path(self.config.reports_root) / "broker_costs", symbols=self.config.symbols)

    def _backtest(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.backtesting import run_backtest_for_symbols

        return run_backtest_for_symbols(data_dir=self.config.data_dir, symbols=self.config.symbols, report_dir=Path(self.config.reports_root) / "backtests").summary

    def _walk_forward(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.backtesting import run_walk_forward_for_symbols

        return run_walk_forward_for_symbols(data_dir=self.config.data_dir, symbols=self.config.symbols, report_dir=Path(self.config.reports_root) / "walk_forward")

    def _monte_carlo(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.backtesting import run_monte_carlo_report

        return run_monte_carlo_report(trades_path=Path(self.config.reports_root) / "backtests" / "trades.csv", report_dir=Path(self.config.reports_root) / "monte_carlo", seed=self.config.seed)

    def _stress_test(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.backtesting import run_stress_report

        return run_stress_report(data_dir=self.config.data_dir, symbols=self.config.symbols, report_dir=Path(self.config.reports_root) / "stress")

    def _research(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.research import run_research

        return run_research(symbols=self.config.symbols, data_dir=self.config.data_dir, reports_root=self.config.reports_root, output_dir=Path(self.config.reports_root) / "research", max_candidates=100)

    def _benchmark(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.benchmarks import run_benchmarks

        return run_benchmarks(data_dir=self.config.data_dir, symbols=self.config.symbols, report_dir=Path(self.config.reports_root) / "benchmarks", seed=self.config.seed)

    def _competitive_scorecard(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.benchmarks import build_competitive_scorecard

        return build_competitive_scorecard(reports_root=self.config.reports_root, output_dir=Path(self.config.reports_root) / "competitive_scorecard")

    def _broker_quality(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.broker_quality import run_broker_quality
        from agi_style_forex_bot_mt5.config import BotConfig
        from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

        database = TelemetryDatabase(self.config.sqlite_path)
        try:
            return run_broker_quality(config=BotConfig(), symbols=self.config.symbols, log_dir=self.config.log_dir, database=database, report_dir=Path(self.config.reports_root) / "broker_quality")
        finally:
            database.close()

    def _simulation_calibration(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.execution_simulation import run_simulation_calibration
        from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

        database = TelemetryDatabase(self.config.sqlite_path)
        try:
            return run_simulation_calibration(database=database, reports_root=self.config.reports_root, output_dir=Path(self.config.reports_root) / "execution_simulation")
        finally:
            database.close()

    def _paper_vs_backtest(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.execution_simulation import compare_paper_vs_backtest
        from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

        database = TelemetryDatabase(self.config.sqlite_path)
        try:
            return compare_paper_vs_backtest(database=database, reports_root=self.config.reports_root, output_dir=Path(self.config.reports_root) / "paper_vs_backtest")
        finally:
            database.close()

    def _validation_report(self) -> dict[str, Any]:
        from agi_style_forex_bot_mt5.backtesting import build_master_validation_report

        return build_master_validation_report(reports_root=self.config.reports_root, output_dir=Path(self.config.reports_root) / "validation")


def run_full_validation(config: PipelineConfig, *, stage_overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return PipelineRunner(config, stage_overrides=stage_overrides).run()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


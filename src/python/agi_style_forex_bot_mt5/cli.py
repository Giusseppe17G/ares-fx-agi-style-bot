"""Command line entry point for shadow/demo runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .bot import ShadowDemoBot
from .backtesting import (
    BacktestSettings,
    CostModel,
    WalkForwardSettings,
    build_master_validation_report,
    run_backtest_for_symbols,
    run_monte_carlo_report,
    run_stress_report,
    run_walk_forward_for_symbols,
)
from .benchmarks import build_competitive_scorecard, run_benchmarks
from .broker_quality import build_readiness_report, run_broker_quality
from .config import load_config
from .contracts import AccountState, MarketSnapshot, utc_now
from .data_pipeline import build_broker_cost_profile, build_dataset_manifest, cost_for_symbol
from .execution_simulation import compare_paper_vs_backtest, run_simulation_calibration
from .mt5_data_bot import DEFAULT_FOREX_SYMBOLS, MT5DataOnlyBot, MT5DiagnoseBot, summary_to_json
from .mt5_history_exporter import MT5HistoryExporter, export_summary_to_json
from .ml import build_ml_dataset, build_ml_report, train_ml_filter
from .observability import DailySummary, build_health_status, build_status
from .paper_trading import ForwardShadowBot, forward_summary_to_json
from .persistence import (
    check_db_health,
    compact_jsonl_logs,
    create_backup,
    flush_telegram_outbox,
    replay_audit,
    run_db_migrations,
    validate_event_integrity,
)
from .portfolio import build_correlation_report, build_exposure_report, build_portfolio_status
from .research import run_research
from .telemetry import JsonlAuditLogger, TelegramNotifier, TelemetryDatabase
from .validation_pipeline import PipelineConfig, run_full_validation


def build_sample_snapshot() -> MarketSnapshot:
    """Build a deterministic demo snapshot for smoke testing."""

    return MarketSnapshot(
        symbol="EURUSD",
        timeframe="M5",
        timestamp_utc=utc_now(),
        bid=1.10000,
        ask=1.10010,
        spread_points=10,
        digits=5,
        point=0.00001,
        tick_value=1.0,
        tick_size=0.00001,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        stops_level_points=10,
        freeze_level_points=5,
    )


def build_sample_features() -> dict[str, object]:
    """Build deterministic trend-pullback features for a shadow smoke run."""

    return {
        "regime": "TREND_UP",
        "ema20": 1.1010,
        "ema50": 1.1000,
        "ema200": 1.0980,
        "ema_fast": 1.10130,
        "ema_slow": 1.10030,
        "rsi": 48,
        "rsi14": 48,
        "atr14": 0.0010,
        "atr": 0.0010,
        "atr_points": 18,
        "atr_mean_points": 12,
        "atr_percent": 0.09,
        "ema_slope": 0.0002,
        "trend_slope": 0.00030,
        "trend_strength": 1.4,
        "momentum": 0.0004,
        "momentum_points": 12,
        "range_points": 25,
        "body_ratio": 0.62,
        "previous_close": 1.10080,
        "close": 1.10120,
        "prior_high": 1.10100,
        "lower_wick": 0.0003,
        "upper_wick": 0.0001,
        "spread_points": 10,
        "max_strategy_spread_points": 25,
        "session": "LONDON",
        "volatility": 0.0002,
    }


def main(argv: list[str] | None = None) -> int:
    """Run one shadow/demo cycle and print a JSON summary."""

    parser = argparse.ArgumentParser(description="Run AGI_STYLE_FOREX_BOT_MT5 safely.")
    parser.add_argument("--config", type=Path, default=None, help="Path to config INI.")
    parser.add_argument(
        "--mode",
        choices=[
            "shadow",
            "demo",
            "mt5-data",
            "mt5-diagnose",
            "backtest",
            "export-history",
            "walk-forward",
            "monte-carlo",
            "stress-test",
            "validation-report",
            "data-quality",
            "build-cost-profile",
            "benchmark",
            "competitive-scorecard",
            "research",
            "forward-shadow",
            "status",
            "health",
            "daily-summary",
            "broker-quality",
            "readiness-report",
            "build-ml-dataset",
            "train-ml-filter",
            "ml-report",
            "portfolio-status",
            "exposure-report",
            "correlation-report",
            "db-migrate",
            "db-health",
            "backup",
            "audit-replay",
            "telegram-outbox-flush",
            "compact-logs",
            "simulation-calibration",
            "paper-vs-backtest",
            "full-validation",
        ],
        default="shadow",
    )
    parser.add_argument("--log-dir", type=Path, default=Path("data/logs"))
    parser.add_argument("--sqlite", type=Path, default=None, help="Optional telemetry SQLite path.")
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_FOREX_SYMBOLS),
        help="Comma-separated symbols for mt5-data, mt5-diagnose, backtest, or export-history.",
    )
    parser.add_argument("--symbol", default="", help="Single symbol convenience override.")
    parser.add_argument("--bars", type=int, default=260, help="Bars per timeframe for mt5-data.")
    parser.add_argument("--timeframes", default="M5,M15,H1", help="Comma-separated timeframes for export-history.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/historical"), help="Historical CSV directory for backtest.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/historical"), help="CSV output directory for export-history.")
    parser.add_argument("--report-dir", type=Path, default=Path("data/reports/backtests"), help="Backtest report output directory.")
    parser.add_argument("--reports-root", type=Path, default=Path("data/reports"), help="Reports root for validation-report.")
    parser.add_argument("--trades", type=Path, default=None, help="Trades CSV for monte-carlo.")
    parser.add_argument("--dataset", type=Path, default=None, help="ML dataset CSV for train-ml-filter.")
    parser.add_argument("--model-dir", type=Path, default=Path("data/models/ml_filter"), help="ML model registry directory.")
    parser.add_argument("--backup-dir", type=Path, default=Path("data/backups"), help="Local backup directory.")
    parser.add_argument("--simulations", type=int, default=1000, help="Monte Carlo simulation count.")
    parser.add_argument("--seed", type=int, default=0, help="Reproducible random seed.")
    parser.add_argument("--max-candidates", type=int, default=100, help="Maximum research candidates.")
    parser.add_argument("--cycle-seconds", type=int, default=30, help="Forward shadow cycle interval.")
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum forward shadow cycles for tests/smoke.")
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--step-days", type=int, default=30)
    parser.add_argument("--spread-points", type=float, default=10.0)
    parser.add_argument("--slippage-points", type=float, default=1.0)
    parser.add_argument("--commission", type=float, default=0.0, help="Commission per lot round turn.")
    parser.add_argument("--skip-export-history", action="store_true", help="Skip MT5 history export in full-validation.")
    parser.add_argument("--run-export-history", action="store_true", help="Run MT5 history export in full-validation.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop full-validation at the first failed stage.")
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enable optional Telegram notifications using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.mode in {
        "mt5-data",
        "mt5-diagnose",
        "status",
        "health",
        "daily-summary",
        "broker-quality",
        "readiness-report",
        "build-ml-dataset",
        "portfolio-status",
        "exposure-report",
        "db-migrate",
        "db-health",
        "backup",
        "audit-replay",
        "telegram-outbox-flush",
        "simulation-calibration",
        "paper-vs-backtest",
        "full-validation",
    } and args.sqlite is None:
        parser.error(f"--mode {args.mode} requires --sqlite for durable audit")
    direct_persistence_modes = {"db-migrate", "db-health", "backup", "compact-logs"}
    database = None if args.mode in direct_persistence_modes else (TelemetryDatabase(args.sqlite) if args.sqlite else None)
    try:
        selected_symbols = _selected_symbols(args.symbol, args.symbols)
        if args.mode == "db-migrate":
            summary = run_db_migrations(sqlite_path=args.sqlite, backup_dir=args.backup_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "db-health":
            summary = check_db_health(sqlite_path=args.sqlite, report_dir=_persistence_report_dir(args.report_dir))
            print(_json_dumps(summary))
            return 0

        if args.mode == "backup":
            summary = create_backup(sqlite_path=args.sqlite, log_dir=args.log_dir, backup_dir=args.backup_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "compact-logs":
            summary = compact_jsonl_logs(log_dir=args.log_dir, backup_dir=args.backup_dir, max_file_mb=config.max_jsonl_file_mb)
            print(_json_dumps(summary))
            return 0

        if args.mode == "audit-replay":
            assert database is not None
            summary = replay_audit(database=database, output_dir=_persistence_report_dir(args.report_dir))
            integrity = validate_event_integrity(database=database)
            print(_json_dumps({**summary, "event_integrity": integrity}))
            return 0

        if args.mode == "telegram-outbox-flush":
            assert database is not None
            summary = flush_telegram_outbox(database=database)
            print(_json_dumps(summary))
            return 0

        if args.mode == "simulation-calibration":
            assert database is not None
            summary = run_simulation_calibration(database=database, reports_root=args.reports_root, output_dir=args.output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "paper-vs-backtest":
            assert database is not None
            summary = compare_paper_vs_backtest(database=database, reports_root=args.reports_root, output_dir=args.output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "full-validation":
            config_for_pipeline = PipelineConfig.from_paths(
                symbols=selected_symbols,
                timeframes=tuple(item.strip() for item in args.timeframes.split(",") if item.strip()),
                data_dir=args.data_dir,
                reports_root=args.reports_root,
                sqlite_path=args.sqlite,
                log_dir=args.log_dir,
                output_dir=args.output_dir,
                bars=args.bars,
                run_export_history=bool(args.run_export_history and not args.skip_export_history),
                fail_fast=args.fail_fast,
                seed=args.seed,
            )
            summary = run_full_validation(config_for_pipeline)
            print(_json_dumps(summary))
            return 0

        if args.mode == "backtest":
            cost_profile = _load_optional_json(args.reports_root / "broker_costs" / "broker_cost_profile.json")
            spread_points = cost_for_symbol(cost_profile, selected_symbols[0], fallback=args.spread_points)
            result = run_backtest_for_symbols(
                data_dir=args.data_dir,
                symbols=selected_symbols,
                report_dir=args.report_dir,
                config=config,
                settings=BacktestSettings(
                    cost_model=CostModel(
                        spread_points=spread_points,
                        slippage_points=args.slippage_points,
                        commission_per_lot_round_turn=args.commission,
                        max_spread_points=config.max_spread_points_default,
                    ),
                    break_even_trigger_r=0.6,
                    trailing_start_r=0.8,
                    trailing_distance_points=80,
                    max_bars_in_trade=96,
                    data_source=str(args.data_dir),
                    parameters={
                        "DEMO_ONLY": config.demo_only,
                        "LIVE_TRADING_APPROVED": config.live_trading_approved,
                        "execution_attempted": False,
                    },
                ),
            )
            print(_json_dumps(result.summary))
            return 0

        if args.mode == "export-history":
            exporter = MT5HistoryExporter(
                config=config,
                symbols=selected_symbols,
                timeframes=tuple(item.strip() for item in args.timeframes.split(",") if item.strip()),
                bars=args.bars,
                output_dir=args.output_dir,
                audit_logger=JsonlAuditLogger(args.log_dir, max_file_mb=config.max_jsonl_file_mb),
                database=database,
            )
            print(export_summary_to_json(exporter.run()))
            return 0

        if args.mode == "walk-forward":
            summary = run_walk_forward_for_symbols(
                data_dir=args.data_dir,
                symbols=selected_symbols,
                report_dir=args.report_dir,
                settings=WalkForwardSettings(
                    train_days=args.train_days,
                    validation_days=args.validation_days,
                    test_days=args.test_days,
                    step_days=args.step_days,
                ),
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "monte-carlo":
            summary = run_monte_carlo_report(
                trades_path=args.trades,
                report_dir=args.report_dir,
                seed=args.seed,
                iterations=args.simulations,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "stress-test":
            summary = run_stress_report(
                data_dir=args.data_dir,
                symbols=selected_symbols,
                report_dir=args.report_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "validation-report":
            summary = build_master_validation_report(
                reports_root=args.reports_root,
                output_dir=args.output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "data-quality":
            summary = build_dataset_manifest(
                data_dir=args.data_dir,
                report_dir=args.report_dir,
                symbols=selected_symbols,
                timeframes=tuple(item.strip() for item in args.timeframes.split(",") if item.strip()),
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "build-cost-profile":
            summary = build_broker_cost_profile(
                data_dir=args.data_dir,
                report_dir=args.report_dir,
                symbols=selected_symbols,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "benchmark":
            cost_profile = _load_optional_json(args.reports_root / "broker_costs" / "broker_cost_profile.json")
            summary = run_benchmarks(
                data_dir=args.data_dir,
                symbols=selected_symbols,
                report_dir=args.report_dir,
                broker_cost_profile=cost_profile,
                seed=args.seed,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "competitive-scorecard":
            summary = build_competitive_scorecard(
                reports_root=args.reports_root,
                output_dir=args.output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "research":
            summary = run_research(
                symbols=selected_symbols,
                data_dir=args.data_dir,
                reports_root=args.reports_root,
                output_dir=args.output_dir,
                max_candidates=args.max_candidates,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "forward-shadow":
            if database is None:
                parser.error("--mode forward-shadow requires --sqlite for paper lifecycle persistence")
            bot = ForwardShadowBot(
                config=config,
                symbols=selected_symbols,
                audit_logger=JsonlAuditLogger(args.log_dir, max_file_mb=config.max_jsonl_file_mb),
                database=database,
                telegram_notifier=TelegramNotifier.from_env(
                    database=database,
                    enabled=bool(args.telegram or config.telegram_enabled),
                ),
                cycle_seconds=args.cycle_seconds,
                max_cycles=args.max_cycles,
            )
            print(forward_summary_to_json(bot.run()))
            return 0

        if args.mode == "status":
            assert database is not None
            print(_json_dumps(build_status(database)))
            return 0

        if args.mode == "health":
            assert database is not None
            print(_json_dumps(build_health_status(database, log_dir=args.log_dir)))
            return 0

        if args.mode == "daily-summary":
            assert database is not None
            print(_json_dumps(DailySummary(database, args.report_dir).generate()))
            return 0

        if args.mode == "broker-quality":
            assert database is not None
            summary = run_broker_quality(
                config=config,
                symbols=selected_symbols,
                log_dir=args.log_dir,
                database=database,
                report_dir=args.report_dir,
                bars=args.bars,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "readiness-report":
            assert database is not None
            summary = build_readiness_report(
                reports_root=args.reports_root,
                output_dir=args.output_dir,
                database=database,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "build-ml-dataset":
            assert database is not None
            summary = build_ml_dataset(
                database=database,
                reports_root=args.reports_root,
                output_dir=args.output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "train-ml-filter":
            if args.dataset is None:
                parser.error("--mode train-ml-filter requires --dataset")
            summary = train_ml_filter(
                dataset_path=args.dataset,
                model_dir=args.model_dir,
                report_dir=args.report_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "ml-report":
            summary = build_ml_report(
                model_dir=args.model_dir,
                report_dir=args.report_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "portfolio-status":
            assert database is not None
            output_dir = _portfolio_output_dir(args.output_dir, args.reports_root)
            summary = build_portfolio_status(
                database=database,
                reports_root=args.reports_root,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "exposure-report":
            assert database is not None
            summary = build_exposure_report(
                database=database,
                output_dir=_portfolio_output_dir(args.output_dir, args.reports_root),
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "correlation-report":
            summary = build_correlation_report(
                data_dir=args.data_dir,
                output_dir=_portfolio_output_dir(args.output_dir, args.reports_root),
            )
            print(_json_dumps(summary))
            return 0

        if args.mode in {"mt5-data", "mt5-diagnose"}:
            bot_cls = MT5DiagnoseBot if args.mode == "mt5-diagnose" else MT5DataOnlyBot
            bot = bot_cls(
                config=config,
                symbols=selected_symbols,
                bars=args.bars,
                audit_logger=JsonlAuditLogger(args.log_dir, max_file_mb=config.max_jsonl_file_mb),
                database=database,
                telegram_notifier=TelegramNotifier.from_env(
                    database=database,
                    enabled=bool(args.telegram or config.telegram_enabled),
                ),
            )
            print(summary_to_json(bot.run()))
            return 0

        bot = ShadowDemoBot(
            config=config,
            audit_logger=JsonlAuditLogger(args.log_dir, max_file_mb=config.max_jsonl_file_mb),
            database=database,
            telegram_notifier=TelegramNotifier.from_env(
                database=database,
                enabled=bool(args.telegram or config.telegram_enabled),
            ),
        )
        result = bot.run_once(
            snapshot=build_sample_snapshot(),
            features=build_sample_features(),
            account=AccountState(
                login=100001,
                trade_mode="DEMO",
                balance=10_000,
                equity=10_000,
                margin_free=9_000,
                is_demo=True,
                trade_allowed=True,
            ),
            mode=args.mode,
        )
        print(json.dumps(asdict(result), ensure_ascii=True, sort_keys=True))
        return 0
    finally:
        if database is not None:
            database.close()


def _selected_symbols(single_symbol: str, symbols: str) -> tuple[str, ...]:
    if single_symbol.strip():
        return (single_symbol.strip().upper(),)
    return tuple(item.strip().upper() for item in symbols.split(",") if item.strip())


def _json_dumps(payload: object) -> str:
    def convert(value: object) -> object:
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        if isinstance(value, float) and math_is_inf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value

    return json.dumps(convert(payload), ensure_ascii=True, sort_keys=True)


def math_is_inf(value: float) -> bool:
    return value == float("inf") or value == float("-inf")


def _load_optional_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _portfolio_output_dir(output_dir: Path, reports_root: Path) -> Path:
    if output_dir == Path("data/historical"):
        return reports_root / "portfolio"
    return output_dir


def _persistence_report_dir(report_dir: Path) -> Path:
    if report_dir == Path("data/reports/backtests"):
        return Path("data/reports/persistence")
    return report_dir


if __name__ == "__main__":
    raise SystemExit(main())

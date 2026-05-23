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
from .calibration import apply_signal_profile, bot_config_with_signal_profile, profile_allowed_for_shadow, run_blocking_reasons_report, run_signal_calibration, run_threshold_sweep_report
from .broker_quality import build_readiness_report, run_broker_quality
from .config import load_config
from .contracts import AccountState, Environment, Event, MarketSnapshot, Severity, utc_now
from .data_pipeline import audit_historical_data, audit_timestamps, build_broker_cost_profile, build_dataset_manifest, build_feature_availability_report, build_live_feature_contract_report, build_strategy_data_contract_report, cost_for_symbol
from .edge_filtering import run_edge_filtering, run_filtered_profile_builder
from .edge_evaluation import run_edge_evaluation, run_strategy_selection, run_symbol_selection
from .execution_simulation import compare_paper_vs_backtest, run_simulation_calibration
from .forward_evidence import run_forward_acceptance, run_forward_evidence
from .forward_diagnostics import run_forward_signal_diagnose
from .forward_research import run_forward_blocker_sensitivity, run_forward_candidate_replay
from .market_structure import run_strategy_diagnose, write_structure_report
from .mt5_data_bot import DEFAULT_FOREX_SYMBOLS, MT5DataOnlyBot, MT5DiagnoseBot, summary_to_json
from .mt5_history_exporter import MT5HistoryExporter, export_summary_to_json
from .ml import build_ml_dataset, build_ml_report, train_ml_filter
from .observability import DailySummary, build_health_status, build_status
from .operational_readiness import run_ec2_readiness_audit, run_market_open_checklist, run_weekend_readiness
from .paper_trading import (
    ForwardShadowBot,
    build_paper_open_trades_report,
    build_paper_state_report,
    build_stable_health,
    close_all_paper_trades,
    forward_summary_to_json,
    pause_shadow,
    resume_shadow,
    write_stable_shadow_daily_report,
)
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
from .profile_validation import run_balanced_candidate_gate, run_profile_integrity, run_profile_threshold_audit
from .real_data_research import RealDataResearchConfig, load_latest_run_summary, run_real_data_research
from .research import run_research
from .robustness_validation import run_robustness_fast, run_stable_robustness_gate
from .stability_repair import run_build_stable_profile, run_stability_repair, run_walk_forward_failure_analysis
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
            "forward-evidence",
            "forward-acceptance",
            "forward-signal-diagnose",
            "forward-candidate-replay",
            "forward-blocker-sensitivity",
            "paper-open-trades",
            "paper-state-report",
            "paper-close-all",
            "pause-shadow",
            "resume-shadow",
            "stable-health",
            "stable-daily-summary",
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
            "strategy-diagnose",
            "structure-report",
            "real-data-research",
            "latest-run-summary",
            "signal-calibration",
            "threshold-sweep",
            "blocking-reasons",
            "historical-data-audit",
            "timestamp-audit",
            "strategy-data-contract",
            "live-feature-contract",
            "apply-signal-profile",
            "profile-comparison-run",
            "edge-evaluation",
            "symbol-selection",
            "strategy-selection",
            "edge-filtering",
            "build-filtered-profile",
            "profile-integrity",
            "balanced-candidate-gate",
            "profile-threshold-audit",
            "robustness-fast",
            "stable-robustness-gate",
            "walk-forward-failure-analysis",
            "stability-repair",
            "build-stable-profile",
            "weekend-readiness",
            "market-open-checklist",
            "ec2-readiness-audit",
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
    parser.add_argument("--output-root", type=Path, default=Path("data/runs"), help="Root directory for real-data-research run folders.")
    parser.add_argument("--runs-root", type=Path, default=Path("data/runs"), help="Root directory for latest-run-summary.")
    parser.add_argument("--run-id", default="", help="Exact real-data-research run id for edge evaluation modes.")
    parser.add_argument("--edge-dir", type=Path, default=Path("data/reports/edge"), help="Edge evaluation report directory.")
    parser.add_argument("--base-profile", default="BALANCED", help="Base profile for filtered edge profile generation.")
    parser.add_argument("--profile-config", type=Path, default=None, help="Profile overlay INI for BALANCED_FILTERED research runs.")
    parser.add_argument("--stable-gate", type=Path, default=Path("data/reports/stable_gate/stable_gate_summary.json"), help="BALANCED_STABLE gate summary JSON.")
    parser.add_argument("--require-actionable-filter", default="false", help="Require edge-filtering to create an actionable BALANCED_FILTERED overlay.")
    parser.add_argument("--report-dir", type=Path, default=Path("data/reports/backtests"), help="Backtest report output directory.")
    parser.add_argument("--reports-root", type=Path, default=Path("data/reports"), help="Reports root for validation-report.")
    parser.add_argument("--diagnostics-dir", type=Path, default=Path("data/reports/forward_diagnostics"), help="Forward diagnostics report directory.")
    parser.add_argument("--profile-runs-dir", type=Path, default=Path("data/reports/profile_runs"), help="Profile comparison report directory.")
    parser.add_argument("--robustness-dir", type=Path, default=Path("data/reports/robustness"), help="Robustness fast-track report directory.")
    parser.add_argument("--stability-dir", type=Path, default=Path("data/reports/stability_repair"), help="Stability repair report directory.")
    parser.add_argument("--trades", type=Path, default=None, help="Trades CSV for monte-carlo.")
    parser.add_argument("--dataset", type=Path, default=None, help="ML dataset CSV for train-ml-filter.")
    parser.add_argument("--model-dir", type=Path, default=Path("data/models/ml_filter"), help="ML model registry directory.")
    parser.add_argument("--backup-dir", type=Path, default=Path("data/backups"), help="Local backup directory.")
    parser.add_argument("--simulations", type=int, default=1000, help="Monte Carlo simulation count.")
    parser.add_argument("--seed", type=int, default=0, help="Reproducible random seed.")
    parser.add_argument("--max-candidates", type=int, default=100, help="Maximum research candidates.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Limit symbol count for real-data-research quick iteration.")
    parser.add_argument("--max-bars", type=int, default=0, help="Cap exported bars for real-data-research quick iteration.")
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
    parser.add_argument("--quick", action="store_true", help="Run the fast real-data-research subset.")
    parser.add_argument("--skip-walk-forward", action="store_true", help="Skip walk-forward in real-data-research.")
    parser.add_argument("--skip-monte-carlo", action="store_true", help="Skip Monte Carlo in real-data-research.")
    parser.add_argument("--skip-stress-test", action="store_true", help="Skip stress test in real-data-research.")
    parser.add_argument("--skip-research", action="store_true", help="Skip research runner in real-data-research.")
    parser.add_argument("--skip-benchmark", action="store_true", help="Skip benchmark and competitive scorecard in real-data-research.")
    parser.add_argument("--profiles", default="", help="Comma-separated signal profiles for threshold-sweep.")
    parser.add_argument("--compare-profiles", default="", help="Comma-separated profiles for profile-comparison-run.")
    parser.add_argument("--profile", default="BALANCED", help="Signal profile for apply-signal-profile.")
    parser.add_argument(
        "--signal-profile",
        choices=["CONSERVATIVE", "BALANCED", "BALANCED_FILTERED", "BALANCED_STABLE", "ACTIVE", "RESEARCH_ONLY"],
        default="",
        help="Research/backtest signal profile overlay.",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enable optional Telegram notifications using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
    )
    parser.add_argument("--reason", default="", help="Operational reason for paper/shadow state commands.")
    parser.add_argument("--confirm-paper-only", default="false", help="Set true to execute paper-only close commands.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.mode in {
        "mt5-data",
        "mt5-diagnose",
        "status",
        "health",
        "daily-summary",
        "stable-health",
        "stable-daily-summary",
        "forward-evidence",
        "forward-acceptance",
        "forward-signal-diagnose",
        "forward-candidate-replay",
        "paper-open-trades",
        "paper-state-report",
        "paper-close-all",
        "pause-shadow",
        "resume-shadow",
        "weekend-readiness",
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
    direct_persistence_modes = {"db-migrate", "db-health", "backup", "compact-logs", "weekend-readiness"}
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

        if args.mode == "strategy-diagnose":
            symbol = selected_symbols[0]
            summary = run_strategy_diagnose(symbol=symbol, data_dir=args.data_dir, report_dir=args.report_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "structure-report":
            summary = write_structure_report(symbols=selected_symbols, data_dir=args.data_dir, report_dir=args.report_dir)
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

        if args.mode == "real-data-research":
            research_config = RealDataResearchConfig(
                symbols=selected_symbols,
                output_root=str(args.output_root),
                bars=args.bars,
                seed=args.seed,
                fail_fast=args.fail_fast,
                signal_profile=args.signal_profile or config.signal_profile,
                quick=args.quick,
                skip_walk_forward=args.skip_walk_forward,
                skip_monte_carlo=args.skip_monte_carlo,
                skip_stress_test=args.skip_stress_test,
                skip_research=args.skip_research,
                skip_benchmark=args.skip_benchmark,
                max_symbols=args.max_symbols,
                max_bars=args.max_bars,
                profile_config=str(args.profile_config) if args.profile_config else "",
            )
            summary = run_real_data_research(research_config, bot_config=config)
            print(_json_dumps(summary))
            return 0

        if args.mode == "latest-run-summary":
            print(_json_dumps(load_latest_run_summary(args.runs_root)))
            return 0

        if args.mode == "weekend-readiness":
            summary = run_weekend_readiness(sqlite_path=args.sqlite, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=args.output_dir, config=config)
            print(_json_dumps(summary))
            return 0

        if args.mode == "market-open-checklist":
            sqlite_path = args.sqlite or Path("data/sqlite/forward-shadow-stable.sqlite3")
            summary = run_market_open_checklist(sqlite_path=sqlite_path, reports_root=args.reports_root, output_dir=args.output_dir, symbols=",".join(selected_symbols))
            print(_json_dumps(summary))
            return 0

        if args.mode == "ec2-readiness-audit":
            summary = run_ec2_readiness_audit(reports_root=args.reports_root, output_dir=args.output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "apply-signal-profile":
            output_dir = Path("data/reports/applied_profiles") if args.output_dir == Path("data/historical") else args.output_dir
            summary = apply_signal_profile(profile_name=args.profile, runs_root=args.runs_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "profile-comparison-run":
            from .calibration.profile_application import run_profile_comparison

            summary = run_profile_comparison(
                profiles_value=args.compare_profiles or args.profiles or "BALANCED,BALANCED_FILTERED,ACTIVE",
                data_dir=args.data_dir,
                symbols=selected_symbols,
                output_dir=args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/profile_runs"),
                base_config=config,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "edge-evaluation":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/edge")
            summary = run_edge_evaluation(runs_root=args.runs_root, output_dir=output_dir, run_id=args.run_id or None)
            print(_json_dumps(summary))
            return 0

        if args.mode == "symbol-selection":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/edge")
            summary = run_symbol_selection(runs_root=args.runs_root, output_dir=output_dir, run_id=args.run_id or None)
            print(_json_dumps(summary))
            return 0

        if args.mode == "strategy-selection":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/edge")
            summary = run_strategy_selection(runs_root=args.runs_root, output_dir=output_dir, run_id=args.run_id or None)
            print(_json_dumps(summary))
            return 0

        if args.mode == "edge-filtering":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/edge_filtering")
            summary = run_edge_filtering(runs_root=args.runs_root, edge_dir=args.edge_dir, output_dir=output_dir, base_profile=args.base_profile, require_actionable_filter=_bool_arg(args.require_actionable_filter))
            print(_json_dumps(summary))
            return 0

        if args.mode == "build-filtered-profile":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/edge_filtering")
            summary = run_filtered_profile_builder(runs_root=args.runs_root, edge_dir=args.edge_dir, output_dir=output_dir, base_profile=args.base_profile, require_actionable_filter=_bool_arg(args.require_actionable_filter))
            print(_json_dumps(summary))
            return 0

        if args.mode == "profile-integrity":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/profile_validation")
            summary = run_profile_integrity(profile_runs_dir=args.profile_runs_dir, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "profile-threshold-audit":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/profile_validation")
            summary = run_profile_threshold_audit(output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "balanced-candidate-gate":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/profile_validation")
            summary = run_balanced_candidate_gate(runs_root=args.runs_root, profile_runs_dir=args.profile_runs_dir, edge_dir=args.edge_dir, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "robustness-fast":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/robustness")
            summary = run_robustness_fast(
                runs_root=args.runs_root,
                profile_runs_dir=args.profile_runs_dir,
                profile=args.profile,
                profile_config=args.profile_config,
                output_dir=output_dir,
                simulations=args.simulations,
                seed=args.seed,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "stable-robustness-gate":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/stable_gate")
            summary = run_stable_robustness_gate(
                runs_root=args.runs_root,
                robustness_dir=args.robustness_dir,
                stability_dir=args.stability_dir,
                profile=args.profile,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "forward-evidence":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_evidence")
            summary = run_forward_evidence(database=database, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "forward-acceptance":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_evidence")
            summary = run_forward_acceptance(database=database, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "forward-signal-diagnose":
            assert database is not None
            if args.signal_profile:
                config = bot_config_with_signal_profile(config, args.signal_profile, str(args.profile_config) if args.profile_config else "")
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_diagnostics")
            summary = run_forward_signal_diagnose(
                config=config,
                symbols=selected_symbols,
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                output_dir=output_dir,
                bars=args.bars,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "forward-candidate-replay":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_research")
            summary = run_forward_candidate_replay(
                log_dir=args.log_dir,
                diagnostics_dir=args.diagnostics_dir,
                sqlite_path=args.sqlite,
                profile_config=args.profile_config,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "forward-blocker-sensitivity":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_research")
            summary = run_forward_blocker_sensitivity(
                log_dir=args.log_dir,
                diagnostics_dir=args.diagnostics_dir,
                profile_config=args.profile_config,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "paper-open-trades":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state")
            print(_json_dumps(build_paper_open_trades_report(database=database, output_dir=output_dir)))
            return 0

        if args.mode == "paper-state-report":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state")
            print(_json_dumps(build_paper_state_report(database=database, log_dir=args.log_dir, output_dir=output_dir)))
            return 0

        if args.mode == "paper-close-all":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state")
            print(
                _json_dumps(
                    close_all_paper_trades(
                        database=database,
                        reason=args.reason or "manual paper close",
                        output_dir=output_dir,
                        confirm_paper_only=str(args.confirm_paper_only).lower() == "true",
                    )
                )
            )
            return 0

        if args.mode == "pause-shadow":
            assert database is not None
            print(_json_dumps(pause_shadow(database=database, reason=args.reason or "manual pause")))
            return 0

        if args.mode == "resume-shadow":
            assert database is not None
            print(_json_dumps(resume_shadow(database=database, reason=args.reason or "manual resume")))
            return 0

        if args.mode == "walk-forward-failure-analysis":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/stability_repair")
            summary = run_walk_forward_failure_analysis(
                runs_root=args.runs_root,
                robustness_dir=args.robustness_dir,
                profile_runs_dir=args.profile_runs_dir,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "stability-repair":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/stability_repair")
            summary = run_stability_repair(
                runs_root=args.runs_root,
                robustness_dir=args.robustness_dir,
                profile_runs_dir=args.profile_runs_dir,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "build-stable-profile":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/stability_repair")
            summary = run_build_stable_profile(runs_root=args.runs_root, stability_dir=args.stability_dir, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "signal-calibration":
            data_dir = _resolve_calibration_data_dir(args.data_dir, args.runs_root)
            summary = run_signal_calibration(symbols=selected_symbols, data_dir=data_dir, report_dir=args.report_dir, profile_name=config.signal_profile)
            print(_json_dumps(summary))
            return 0

        if args.mode == "threshold-sweep":
            data_dir = _resolve_calibration_data_dir(args.data_dir, args.runs_root)
            summary = run_threshold_sweep_report(symbols=selected_symbols, data_dir=data_dir, report_dir=args.report_dir, profiles_value=args.profiles or None)
            print(_json_dumps(summary))
            return 0

        if args.mode == "blocking-reasons":
            reports_root = _resolve_calibration_reports_root(args.reports_root, args.runs_root)
            summary = run_blocking_reasons_report(reports_root=reports_root, output_dir=args.output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "historical-data-audit":
            audit = audit_historical_data(
                data_dir=args.data_dir,
                report_dir=args.report_dir,
                symbols=selected_symbols,
                timeframes=tuple(item.strip() for item in args.timeframes.split(",") if item.strip()),
            )
            feature = build_feature_availability_report(data_dir=args.data_dir, report_dir=args.report_dir, symbols=selected_symbols)
            print(_json_dumps({**audit, "feature_availability": feature, "reports_created": [*audit.get("reports_created", []), *feature.get("reports_created", [])]}))
            return 0

        if args.mode == "timestamp-audit":
            summary = audit_timestamps(
                data_dir=args.data_dir,
                report_dir=args.report_dir,
                symbols=selected_symbols,
                timeframes=tuple(item.strip() for item in args.timeframes.split(",") if item.strip()),
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "strategy-data-contract":
            summary = build_strategy_data_contract_report(
                data_dir=args.data_dir,
                report_dir=args.report_dir,
                symbols=selected_symbols,
                timeframes=tuple(item.strip() for item in args.timeframes.split(",") if item.strip()),
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "live-feature-contract":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_diagnostics")
            summary = build_live_feature_contract_report(
                config=config,
                symbols=selected_symbols,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "backtest":
            if args.signal_profile:
                config = bot_config_with_signal_profile(config, args.signal_profile, str(args.profile_config) if args.profile_config else "")
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
                        "SIGNAL_PROFILE": config.signal_profile,
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
            if args.signal_profile:
                config = bot_config_with_signal_profile(config, args.signal_profile, str(args.profile_config) if args.profile_config else "")
            if config.signal_profile == "BALANCED_STABLE":
                if not config.profile_config:
                    print(_json_dumps(_stable_forward_block("STABLE_PROFILE_CONFIG_REQUIRED", "BALANCED_STABLE requires --profile-config", args.stable_gate)))
                    return 0
                stable_gate = _stable_gate_status(args.stable_gate)
                if not stable_gate["exists"]:
                    print(_json_dumps(_stable_forward_block("STABLE_GATE_REQUIRED", "BALANCED_STABLE requires stable_gate_summary.json with PAPER_SHADOW_READY", args.stable_gate)))
                    return 0
                if not stable_gate["paper_shadow_ready"]:
                    print(_json_dumps(_stable_forward_block("STABLE_PROFILE_NOT_READY", "stable gate is not PAPER_SHADOW_READY", args.stable_gate, stable_gate)))
                    return 0
            elif not profile_allowed_for_shadow(config.signal_profile):
                parser.error(f"SIGNAL_PROFILE={config.signal_profile} is not allowed to create forward-shadow paper trades")
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
                report_dir="data/reports/forward_shadow_stable" if config.signal_profile == "BALANCED_STABLE" else "data/reports/forward_shadow",
                stable_gate_confirmed=config.signal_profile == "BALANCED_STABLE",
                stable_gate_decision="PAPER_SHADOW_READY" if config.signal_profile == "BALANCED_STABLE" else "",
            )
            if config.signal_profile == "BALANCED_STABLE":
                event = Event.create(
                    run_id="forward-shadow-stable",
                    environment=Environment.DEMO,
                    severity=Severity.INFO,
                    module="cli",
                    event_type="STABLE_GATE_CONFIRMED",
                    message="BALANCED_STABLE stable gate confirmed for paper-shadow",
                    correlation_id="forward-shadow-stable:stable-gate",
                    payload={"stable_gate": str(args.stable_gate), "execution_attempted": False},
                )
                database.insert_event(event)
            print(forward_summary_to_json(bot.run()))
            return 0

        if args.mode == "stable-health":
            assert database is not None
            print(_json_dumps(build_stable_health(database=database, stable_gate_path=args.stable_gate)))
            return 0

        if args.mode == "stable-daily-summary":
            assert database is not None
            report_dir = args.report_dir if args.report_dir != Path("data/reports/backtests") else Path("data/reports/forward_shadow_stable/daily")
            print(_json_dumps(write_stable_shadow_daily_report(database=database, report_dir=report_dir)))
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


def _resolve_calibration_data_dir(data_dir: Path, runs_root: Path) -> Path:
    """Prefer explicit CSV data, otherwise use the newest real-data run."""

    if _contains_csv(data_dir):
        return data_dir
    latest = _latest_run_dir(runs_root)
    if latest is not None and _contains_csv(latest / "historical"):
        return latest / "historical"
    return data_dir


def _resolve_calibration_reports_root(reports_root: Path, runs_root: Path) -> Path:
    """Prefer explicit reports, otherwise use the newest real-data run reports."""

    latest = _latest_run_dir(runs_root)
    if reports_root == Path("data/reports") and latest is not None and (latest / "reports").exists():
        return latest / "reports"
    if reports_root.exists() and any(reports_root.rglob("*.json")):
        return reports_root
    if latest is not None and (latest / "reports").exists():
        return latest / "reports"
    return reports_root


def _latest_run_dir(runs_root: Path) -> Path | None:
    if not runs_root.exists():
        return None
    candidates = [path for path in runs_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (path.name, path.stat().st_mtime))[-1]


def _contains_csv(path: Path) -> bool:
    return path.exists() and any(candidate.is_file() for candidate in path.rglob("*.csv"))


def _bool_arg(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _stable_gate_ready(path: Path = Path("data/reports/stable_gate/stable_gate_summary.json")) -> bool:
    return bool(_stable_gate_status(path)["paper_shadow_ready"])


def _stable_gate_status(path: Path) -> dict[str, object]:
    payload = _load_optional_json(path) or {}
    ready = bool(payload and payload.get("stable_gate_decision") == "PAPER_SHADOW_READY" and payload.get("paper_shadow_ready") is True and payload.get("execution_attempted") is False)
    return {
        "exists": path.exists(),
        "path": str(path),
        "stable_gate_decision": payload.get("stable_gate_decision", ""),
        "paper_shadow_ready": ready,
        "execution_attempted": bool(payload.get("execution_attempted", False)),
    }


def _stable_forward_block(classification: str, message: str, stable_gate: Path, gate_status: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "mode": "forward-shadow",
        "signal_profile_used": "BALANCED_STABLE",
        "classification": classification,
        "error_message": message,
        "stable_gate": str(stable_gate),
        "stable_gate_status": gate_status or {},
        "stable_gate_confirmed": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


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

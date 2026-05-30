"""Command line entry point for shadow/demo runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
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
from .execution_evidence import run_execution_evidence_audit
from .forward_evidence import run_acceptance_drawdown_policy_report, run_forward_acceptance, run_forward_evidence
from .forward_diagnostics import run_forward_signal_diagnose
from .forward_research import run_forward_blocker_sensitivity, run_forward_candidate_replay
from .forward_sufficiency import run_forward_sufficiency_audit
from .market_structure import run_strategy_diagnose, write_structure_report
from .micro_frequency_calibration import run_micro_frequency_calibration
from .micro_frequency_proposal import run_micro_frequency_proposal
from .micro_v2_clearance import run_micro_v2_clearance_runtime_check, run_micro_v2_paper_risk_clearance
from .micro_v2_dry_run_monitor import run_micro_v2_dry_run_monitor
from .micro_v2_dry_run_readiness import run_micro_v2_dry_run_readiness
from .micro_v2_runtime_profile import MICRO_V2_SIGNAL_PROFILE, run_micro_v2_runtime_profile_check, signal_profile_choices, validate_micro_v2_forward_shadow_runtime
from .micro_v2_review import run_micro_v2_proposed_review, run_micro_v2_review
from .micro_v2_symbol_rejection_audit import run_micro_v2_symbol_rejection_audit
from .mt5_data_bot import DEFAULT_FOREX_SYMBOLS, MT5DataOnlyBot, MT5DiagnoseBot, summary_to_json
from .mt5_history_exporter import MT5HistoryExporter, export_summary_to_json
from .ml import build_ml_dataset, build_ml_report, train_ml_filter
from .observability import DailySummary, build_health_status, build_status
from .operational_readiness import run_daily_operator_report, run_dry_run_market_open, run_ec2_deployment_pack, run_ec2_readiness_audit, run_market_open_checklist, run_operator_dashboard, run_operator_drill, run_weekend_readiness
from .paper_trading import (
    ForwardShadowBot,
    build_paper_open_trades_report,
    build_paper_state_report,
    build_stable_health,
    close_all_paper_trades,
    close_invalid_open_paper_trade,
    close_stale_open_paper_trade,
    forward_summary_to_json,
    pause_shadow,
    resume_shadow,
    run_config_error_fix_plan,
    run_config_error_root_cause_audit,
    run_invalid_open_paper_trade_audit,
    run_paper_state_recovery_audit,
    run_paper_state_recovery_plan,
    write_stable_shadow_daily_report,
)
from .paper_trading.paper_pnl_engine import extract_paper_risk_multiplier
from .paper_daily_risk_state import run_paper_daily_risk_audit, run_paper_daily_risk_clear, run_paper_legacy_drawdown_audit, validate_micro_daily_risk
from .paper_pnl_audit import run_paper_pnl_audit, run_paper_pnl_scaling_check, run_paper_risk_post_fix_gate, run_paper_risk_recommendation
from .paper_risk_calibration import build_paper_risk_profile, run_paper_risk_audit, run_paper_risk_status
from .paper_risk_review import run_paper_risk_clearance, run_paper_risk_clearance_check, run_paper_risk_review, validate_micro_resume_clearance
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
from .rejection_labeling import run_rejection_labeling_audit
from .research_candidate_ranking import run_research_candidate_ranking
from .research import run_research
from .robustness_validation import run_robustness_fast, run_stable_robustness_gate
from .stability_repair import run_build_stable_profile, run_stability_repair, run_walk_forward_failure_analysis
from .telemetry import JsonlAuditLogger, TelegramNotifier, TelemetryDatabase
from .telemetry_repair import run_quarantine_telemetry_issues, run_telemetry_acceptance_policy, run_telemetry_drift_audit, run_telemetry_status, run_telemetry_timestamp_audit
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
            "acceptance-drawdown-policy-audit",
            "forward-signal-diagnose",
            "forward-candidate-replay",
            "forward-blocker-sensitivity",
            "forward-sufficiency-audit",
            "micro-frequency-calibration",
            "micro-frequency-proposal",
            "micro-v2-review",
            "micro-v2-proposed-review",
            "micro-v2-dry-run-readiness",
            "micro-v2-dry-run-monitor",
            "micro-v2-symbol-rejection-audit",
            "rejection-labeling-audit",
            "micro-v2-runtime-profile-check",
            "micro-v2-paper-risk-clearance",
            "micro-v2-clearance-runtime-check",
            "execution-evidence-audit",
            "telemetry-timestamp-audit",
            "quarantine-telemetry-issues",
            "telemetry-status",
            "telemetry-acceptance-policy",
            "telemetry-drift-audit",
            "paper-open-trades",
            "paper-state-report",
            "paper-state-recovery-audit",
            "paper-state-recovery-plan",
            "config-error-root-cause-audit",
            "config-error-fix-plan",
            "invalid-open-paper-trade-audit",
            "paper-risk-audit",
            "build-paper-risk-profile",
            "paper-risk-status",
            "paper-risk-review",
            "paper-risk-clearance",
            "paper-risk-clearance-check",
            "paper-daily-risk-audit",
            "paper-daily-risk-clear",
            "paper-legacy-drawdown-audit",
            "paper-pnl-audit",
            "paper-pnl-scaling-check",
            "paper-risk-post-fix-gate",
            "paper-risk-recommendation",
            "paper-close-all",
            "paper-close-stale-open-trade",
            "paper-close-invalid-open-trade",
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
            "ec2-deployment-pack",
            "operator-drill",
            "dry-run-market-open",
            "operator-dashboard",
            "daily-operator-report",
            "research-candidate-ranking",
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
    parser.add_argument("--base-profile-config", type=Path, default=Path("data/reports/paper_risk/balanced_stable_micro.ini"), help="Base profile INI for micro V2 review.")
    parser.add_argument("--candidate-profile-config", type=Path, default=Path("data/reports/micro_frequency_calibration/balanced_stable_micro_v2_candidate.ini"), help="Candidate profile INI for micro V2 review.")
    parser.add_argument("--proposed-profile-config", type=Path, default=Path("data/reports/micro_frequency_proposal/balanced_stable_micro_v2_proposed.ini"), help="Proposed profile INI for micro V2 proposed review.")
    parser.add_argument("--v2-profile-config", type=Path, default=Path("data/reports/paper_risk/balanced_stable_micro_v2.ini"), help="Approved Micro V2 profile INI for dry-run readiness.")
    parser.add_argument("--base-sqlite", type=Path, default=Path("data/sqlite/forward-shadow-stable.sqlite3"), help="Stable/base SQLite path for Micro V2 comparison.")
    parser.add_argument("--base-log-dir", type=Path, default=Path("data/logs/forward-shadow-stable"), help="Stable/base log directory for Micro V2 comparison.")
    parser.add_argument("--v2-sqlite", type=Path, default=Path("data/sqlite/forward-shadow-v2-dryrun.sqlite3"), help="Isolated SQLite path for Micro V2 dry-run.")
    parser.add_argument("--v2-log-dir", type=Path, default=Path("data/logs/forward-shadow-v2-dryrun"), help="Isolated log directory for Micro V2 dry-run.")
    parser.add_argument("--v2-reports-dir", type=Path, default=Path("data/reports/micro_v2_dry_run"), help="Isolated report directory for Micro V2 dry-run.")
    parser.add_argument("--frequency-dir", type=Path, default=Path("data/reports/micro_frequency_calibration"), help="Micro frequency calibration report directory.")
    parser.add_argument("--v2-review-dir", type=Path, default=Path("data/reports/micro_v2_review"), help="Micro V2 review report directory.")
    parser.add_argument("--micro-v2-review-dir", type=Path, default=Path("data/reports/micro_v2_review_proposed"), help="Micro V2 proposed review report directory.")
    parser.add_argument("--runtime-profile-check-dir", type=Path, default=Path("data/reports/micro_v2_runtime_profile_check"), help="Micro V2 runtime profile check report directory.")
    parser.add_argument("--monitor-dir", type=Path, default=Path("data/reports/micro_v2_dry_run_monitor"), help="Micro V2 dry-run monitor report directory.")
    parser.add_argument("--stable-gate", type=Path, default=Path("data/reports/stable_gate/stable_gate_summary.json"), help="BALANCED_STABLE gate summary JSON.")
    parser.add_argument("--require-actionable-filter", default="false", help="Require edge-filtering to create an actionable BALANCED_FILTERED overlay.")
    parser.add_argument("--report-dir", type=Path, default=Path("data/reports/backtests"), help="Backtest report output directory.")
    parser.add_argument("--reports-root", type=Path, default=Path("data/reports"), help="Reports root for validation-report.")
    parser.add_argument("--diagnostics-dir", type=Path, default=Path("data/reports/forward_diagnostics"), help="Forward diagnostics report directory.")
    parser.add_argument("--profile-runs-dir", type=Path, default=Path("data/reports/profile_runs"), help="Profile comparison report directory.")
    parser.add_argument("--robustness-dir", type=Path, default=Path("data/reports/robustness"), help="Robustness fast-track report directory.")
    parser.add_argument("--stability-dir", type=Path, default=Path("data/reports/stability_repair"), help="Stability repair report directory.")
    parser.add_argument("--risk-audit-dir", type=Path, default=Path("data/reports/paper_risk"), help="Paper risk audit report directory.")
    parser.add_argument("--paper-risk-dir", type=Path, default=Path("data/reports/paper_risk"), help="Paper risk report directory.")
    parser.add_argument("--daily-risk-dir", type=Path, default=Path("data/reports/paper_daily_risk"), help="Daily paper risk report directory.")
    parser.add_argument("--pnl-audit-dir", type=Path, default=Path("data/reports/paper_pnl_audit"), help="Paper PnL audit report directory.")
    parser.add_argument("--telemetry-dir", type=Path, default=Path("data/reports/telemetry_repair"), help="Telemetry repair report directory.")
    parser.add_argument("--clearance-ledger", type=Path, default=None, help="Paper risk clearance ledger for paper-risk-status.")
    parser.add_argument("--base-clearance-ledger", type=Path, default=Path("data/reports/paper_risk_review/paper_risk_clearance_ledger.json"), help="Base BALANCED_STABLE_MICRO clearance ledger for Micro V2 clearance audit.")
    parser.add_argument("--paper-risk-clearance", type=Path, default=None, help="Paper risk clearance ledger required by BALANCED_STABLE_MICRO forward-shadow.")
    parser.add_argument("--daily-risk-ledger", type=Path, default=None, help="Daily paper risk ledger for BALANCED_STABLE_MICRO stale halt clearance.")
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
        choices=signal_profile_choices(),
        default="",
        help="Research/backtest signal profile overlay.",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enable optional Telegram notifications using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
    )
    parser.add_argument("--reason", default="", help="Operational reason for paper/shadow state commands.")
    parser.add_argument("--trade-id", default="", help="Paper trade id for protected paper-only recovery commands.")
    parser.add_argument("--issue-class", default="", help="Telemetry issue class filter for quarantine.")
    parser.add_argument("--status", default="QUARANTINED", help="Telemetry quarantine ledger status.")
    parser.add_argument("--confirm-paper-only", default="false", help="Set true to execute paper-only close commands.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if str(args.signal_profile or "").upper() == MICRO_V2_SIGNAL_PROFILE and args.mode not in {"forward-shadow", "micro-v2-clearance-runtime-check"}:
        print(
            _json_dumps(
                {
                    "mode": args.mode,
                    "classification": "MICRO_V2_RUNTIME_GUARDS_FAILED",
                    "decision": "BLOCK_SIGNAL_PROFILE",
                    "reason": "BALANCED_STABLE_MICRO_V2 is only valid for forward-shadow paper dry-run.",
                    "signal_profile_used": MICRO_V2_SIGNAL_PROFILE,
                    "execution_attempted": False,
                    "order_send_called": False,
                    "order_check_called": False,
                }
            )
        )
        return 0
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
        "acceptance-drawdown-policy-audit",
        "forward-signal-diagnose",
        "forward-candidate-replay",
        "forward-sufficiency-audit",
        "micro-frequency-calibration",
        "micro-frequency-proposal",
        "micro-v2-review",
        "micro-v2-proposed-review",
        "micro-v2-dry-run-readiness",
        "micro-v2-runtime-profile-check",
        "micro-v2-paper-risk-clearance",
        "micro-v2-clearance-runtime-check",
        "execution-evidence-audit",
        "telemetry-timestamp-audit",
        "quarantine-telemetry-issues",
        "telemetry-status",
        "telemetry-acceptance-policy",
        "telemetry-drift-audit",
        "paper-open-trades",
        "paper-state-report",
        "paper-state-recovery-audit",
        "config-error-root-cause-audit",
        "invalid-open-paper-trade-audit",
        "paper-risk-audit",
            "paper-risk-status",
            "paper-risk-review",
            "paper-risk-clearance",
            "paper-daily-risk-audit",
            "paper-daily-risk-clear",
            "paper-legacy-drawdown-audit",
            "paper-pnl-audit",
            "paper-pnl-scaling-check",
        "paper-close-all",
        "paper-close-stale-open-trade",
        "paper-close-invalid-open-trade",
        "pause-shadow",
        "resume-shadow",
        "weekend-readiness",
        "dry-run-market-open",
        "operator-dashboard",
        "daily-operator-report",
        "research-candidate-ranking",
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
    direct_persistence_modes = {"db-migrate", "db-health", "backup", "compact-logs", "weekend-readiness", "dry-run-market-open"}
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

        if args.mode == "ec2-deployment-pack":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/ec2_deployment_pack")
            summary = run_ec2_deployment_pack(reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "operator-drill":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/operator_drill")
            summary = run_operator_drill(reports_root=args.reports_root, output_dir=output_dir, config=config)
            print(_json_dumps(summary))
            return 0

        if args.mode == "dry-run-market-open":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/operator_drill")
            summary = run_dry_run_market_open(sqlite_path=args.sqlite, reports_root=args.reports_root, output_dir=output_dir, config=config)
            print(_json_dumps(summary))
            return 0

        if args.mode == "operator-dashboard":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/operator_dashboard")
            summary = run_operator_dashboard(database=database, reports_root=args.reports_root, log_dir=args.log_dir, output_dir=output_dir, config=config)
            print(_json_dumps(summary))
            return 0

        if args.mode == "daily-operator-report":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/daily_operator")
            summary = run_daily_operator_report(database=database, reports_root=args.reports_root, log_dir=args.log_dir, output_dir=output_dir, config=config)
            print(_json_dumps(summary))
            return 0

        if args.mode == "telemetry-timestamp-audit":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/telemetry_repair")
            summary = run_telemetry_timestamp_audit(sqlite_path=args.sqlite, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "quarantine-telemetry-issues":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/telemetry_repair")
            summary = run_quarantine_telemetry_issues(
                sqlite_path=args.sqlite,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                output_dir=output_dir,
                reason=args.reason or "Historical telemetry reviewed",
                issue_class=args.issue_class,
                status=args.status,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "telemetry-status":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/telemetry_repair")
            summary = run_telemetry_status(sqlite_path=args.sqlite, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "telemetry-acceptance-policy":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/telemetry_repair")
            summary = run_telemetry_acceptance_policy(sqlite_path=args.sqlite, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "telemetry-drift-audit":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/telemetry_repair")
            summary = run_telemetry_drift_audit(sqlite_path=args.sqlite, log_dir=args.log_dir, reports_root=args.reports_root, telemetry_dir=args.telemetry_dir, output_dir=output_dir)
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

        if args.mode == "research-candidate-ranking":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/research_candidate_ranking")
            summary = run_research_candidate_ranking(database=database, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "forward-sufficiency-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_sufficiency")
            summary = run_forward_sufficiency_audit(database=database, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-frequency-calibration":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_frequency_calibration")
            summary = run_micro_frequency_calibration(
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                profile_config=args.profile_config,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-review":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_review")
            summary = run_micro_v2_review(
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                base_profile_config=args.base_profile_config,
                candidate_profile_config=args.candidate_profile_config,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-frequency-proposal":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_frequency_proposal")
            summary = run_micro_frequency_proposal(
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                base_profile_config=args.base_profile_config,
                frequency_dir=args.frequency_dir,
                v2_review_dir=args.v2_review_dir,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-proposed-review":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_review_proposed")
            summary = run_micro_v2_proposed_review(
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                base_profile_config=args.base_profile_config,
                proposed_profile_config=args.proposed_profile_config,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-dry-run-readiness":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_dry_run_readiness")
            summary = run_micro_v2_dry_run_readiness(
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                v2_profile_config=args.v2_profile_config,
                stable_gate=args.stable_gate,
                paper_risk_clearance=args.paper_risk_clearance,
                daily_risk_ledger=args.daily_risk_ledger,
                output_dir=output_dir,
                v2_sqlite=args.v2_sqlite,
                v2_log_dir=args.v2_log_dir,
                v2_reports_dir=args.v2_reports_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-dry-run-monitor":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_dry_run_monitor")
            summary = run_micro_v2_dry_run_monitor(
                base_sqlite=args.base_sqlite,
                base_log_dir=args.base_log_dir,
                v2_sqlite=args.v2_sqlite,
                v2_log_dir=args.v2_log_dir,
                reports_root=args.reports_root,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-symbol-rejection-audit":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_symbol_rejection_audit")
            summary = run_micro_v2_symbol_rejection_audit(
                v2_sqlite=args.v2_sqlite,
                v2_log_dir=args.v2_log_dir,
                reports_root=args.reports_root,
                v2_profile_config=args.v2_profile_config,
                stable_gate=args.stable_gate,
                monitor_dir=args.monitor_dir,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "rejection-labeling-audit":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/rejection_labeling_audit")
            summary = run_rejection_labeling_audit(
                base_sqlite=args.base_sqlite,
                v2_sqlite=args.v2_sqlite,
                base_log_dir=args.base_log_dir,
                v2_log_dir=args.v2_log_dir,
                reports_root=args.reports_root,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-runtime-profile-check":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_runtime_profile_check")
            summary = run_micro_v2_runtime_profile_check(
                sqlite_path=args.sqlite,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                v2_profile_config=args.v2_profile_config,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-paper-risk-clearance":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_clearance")
            summary = run_micro_v2_paper_risk_clearance(
                sqlite_path=args.sqlite,
                reports_root=args.reports_root,
                base_clearance_ledger=args.base_clearance_ledger,
                v2_profile_config=args.v2_profile_config,
                micro_v2_review_dir=args.micro_v2_review_dir,
                runtime_profile_check_dir=args.runtime_profile_check_dir,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "micro-v2-clearance-runtime-check":
            assert database is not None
            if not args.signal_profile:
                parser.error("--mode micro-v2-clearance-runtime-check requires --signal-profile BALANCED_STABLE_MICRO_V2")
            if not args.profile_config:
                parser.error("--mode micro-v2-clearance-runtime-check requires --profile-config")
            if not args.paper_risk_clearance:
                parser.error("--mode micro-v2-clearance-runtime-check requires --paper-risk-clearance")
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/micro_v2_clearance_runtime_check")
            summary = run_micro_v2_clearance_runtime_check(
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                signal_profile=args.signal_profile,
                profile_config=args.profile_config,
                paper_risk_clearance=args.paper_risk_clearance,
                daily_risk_ledger=args.daily_risk_ledger,
                output_dir=output_dir,
            )
            print(_json_dumps(summary))
            return 0

        if args.mode == "acceptance-drawdown-policy-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/forward_evidence")
            summary = run_acceptance_drawdown_policy_report(
                database=database,
                log_dir=args.log_dir,
                reports_root=args.reports_root,
                paper_risk_dir=args.paper_risk_dir,
                daily_risk_dir=args.daily_risk_dir,
                pnl_audit_dir=args.pnl_audit_dir,
                clearance_ledger=args.clearance_ledger,
                daily_risk_ledger=args.daily_risk_ledger,
                profile_config=args.profile_config,
                output_dir=output_dir,
            )
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

        if args.mode == "execution-evidence-audit":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/execution_evidence")
            summary = run_execution_evidence_audit(sqlite_path=args.sqlite, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)
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

        if args.mode == "paper-state-recovery-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state_recovery")
            print(
                _json_dumps(
                    run_paper_state_recovery_audit(
                        database=database,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        daily_risk_dir=args.daily_risk_dir,
                        pnl_audit_dir=args.pnl_audit_dir,
                        clearance_ledger=args.clearance_ledger,
                        daily_risk_ledger=args.daily_risk_ledger,
                        profile_config=args.profile_config,
                        stable_gate=args.stable_gate,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "paper-state-recovery-plan":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state_recovery")
            print(_json_dumps(run_paper_state_recovery_plan(audit_dir=output_dir, output_dir=output_dir)))
            return 0

        if args.mode == "config-error-root-cause-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/config_error_recovery")
            print(
                _json_dumps(
                    run_config_error_root_cause_audit(
                        database=database,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        daily_risk_dir=args.daily_risk_dir,
                        pnl_audit_dir=args.pnl_audit_dir,
                        clearance_ledger=args.clearance_ledger,
                        daily_risk_ledger=args.daily_risk_ledger,
                        profile_config=args.profile_config,
                        stable_gate=args.stable_gate,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "config-error-fix-plan":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/config_error_recovery")
            print(_json_dumps(run_config_error_fix_plan(audit_dir=output_dir, output_dir=output_dir)))
            return 0

        if args.mode == "invalid-open-paper-trade-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state_recovery")
            print(
                _json_dumps(
                    run_invalid_open_paper_trade_audit(
                        database=database,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "paper-risk-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_risk")
            print(_json_dumps(run_paper_risk_audit(database=database, log_dir=args.log_dir, reports_root=args.reports_root, output_dir=output_dir)))
            return 0

        if args.mode == "build-paper-risk-profile":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_risk")
            print(_json_dumps(build_paper_risk_profile(base_profile=args.base_profile, risk_audit_dir=args.risk_audit_dir, output_dir=output_dir)))
            return 0

        if args.mode == "paper-risk-status":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_risk")
            print(
                _json_dumps(
                    run_paper_risk_status(
                        database=database,
                        profile_config=args.profile_config,
                        clearance_ledger=args.clearance_ledger,
                        daily_risk_ledger=args.daily_risk_ledger,
                        profile_name="" if args.profile == "BALANCED" else args.profile,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "paper-daily-risk-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_daily_risk")
            print(
                _json_dumps(
                    run_paper_daily_risk_audit(
                        database=database,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        clearance_ledger=args.clearance_ledger,
                        daily_risk_ledger=args.daily_risk_ledger,
                        profile_config=args.profile_config,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "paper-daily-risk-clear":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_daily_risk")
            print(
                _json_dumps(
                    run_paper_daily_risk_clear(
                        database=database,
                        reason=args.reason,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        clearance_ledger=args.clearance_ledger,
                        profile_config=args.profile_config,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "paper-legacy-drawdown-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_daily_risk")
            print(
                _json_dumps(
                    run_paper_legacy_drawdown_audit(
                        database=database,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        pnl_audit_dir=args.pnl_audit_dir,
                        clearance_ledger=args.clearance_ledger,
                        daily_risk_ledger=args.daily_risk_ledger,
                        profile_config=args.profile_config,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "paper-pnl-audit":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_pnl_audit")
            print(
                _json_dumps(
                    run_paper_pnl_audit(
                        database=database,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        daily_risk_dir=args.daily_risk_dir,
                        profile_config=args.profile_config,
                        output_dir=output_dir,
                    )
                )
            )
            return 0

        if args.mode == "paper-pnl-scaling-check":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_pnl_audit")
            print(_json_dumps(run_paper_pnl_scaling_check(database=database, log_dir=args.log_dir, profile_config=args.profile_config, output_dir=output_dir)))
            return 0

        if args.mode == "paper-risk-post-fix-gate":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_pnl_audit")
            print(_json_dumps(run_paper_risk_post_fix_gate(reports_root=args.reports_root, output_dir=output_dir)))
            return 0

        if args.mode == "paper-risk-recommendation":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_pnl_audit")
            print(_json_dumps(run_paper_risk_recommendation(reports_root=args.reports_root, pnl_audit_dir=args.pnl_audit_dir, output_dir=output_dir)))
            return 0

        if args.mode == "paper-risk-review":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_risk_review")
            print(_json_dumps(run_paper_risk_review(database=database, log_dir=args.log_dir, reports_root=args.reports_root, paper_risk_dir=args.paper_risk_dir, output_dir=output_dir)))
            return 0

        if args.mode == "paper-risk-clearance":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_risk_review")
            print(_json_dumps(run_paper_risk_clearance(database=database, reason=args.reason, log_dir=args.log_dir, reports_root=args.reports_root, paper_risk_dir=args.paper_risk_dir, output_dir=output_dir)))
            return 0

        if args.mode == "paper-risk-clearance-check":
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_risk_review")
            print(
                _json_dumps(
                    run_paper_risk_clearance_check(
                        profile="" if args.profile == "BALANCED" else args.profile,
                        profile_config=args.profile_config,
                        clearance_ledger=args.clearance_ledger,
                        output_dir=output_dir,
                    )
                )
            )
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

        if args.mode == "paper-close-stale-open-trade":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state_recovery")
            print(
                _json_dumps(
                    close_stale_open_paper_trade(
                        database=database,
                        reason=args.reason,
                        output_dir=output_dir,
                        confirm_paper_only=str(args.confirm_paper_only).lower() == "true",
                    )
                )
            )
            return 0

        if args.mode == "paper-close-invalid-open-trade":
            assert database is not None
            output_dir = args.output_dir if args.output_dir != Path("data/historical") else Path("data/reports/paper_state_recovery")
            print(
                _json_dumps(
                    close_invalid_open_paper_trade(
                        database=database,
                        trade_id=args.trade_id,
                        reason=args.reason,
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
            if str(args.signal_profile or "").upper() == MICRO_V2_SIGNAL_PROFILE:
                runtime_guard = validate_micro_v2_forward_shadow_runtime(
                    mode=args.mode,
                    signal_profile=args.signal_profile,
                    profile_config=args.profile_config,
                    sqlite_path=args.sqlite,
                    log_dir=args.log_dir,
                )
                if runtime_guard.get("micro_v2_runtime_guard_status") != "MICRO_V2_RUNTIME_GUARDS_PASSED":
                    print(
                        _json_dumps(
                            {
                                **_stable_forward_block(
                                    str(runtime_guard.get("micro_v2_runtime_guard_status") or "MICRO_V2_RUNTIME_GUARDS_FAILED"),
                                    "BALANCED_STABLE_MICRO_V2 runtime guard failed before forward-shadow launch",
                                    args.stable_gate,
                                    runtime_guard,
                                    signal_profile=MICRO_V2_SIGNAL_PROFILE,
                                ),
                                "micro_v2_runtime_guard": runtime_guard,
                            }
                        )
                    )
                    return 0
            if args.signal_profile:
                config = bot_config_with_signal_profile(config, args.signal_profile, str(args.profile_config) if args.profile_config else "")
            stable_shadow_profiles = {"BALANCED_STABLE", "BALANCED_STABLE_MICRO", MICRO_V2_SIGNAL_PROFILE}
            micro_shadow_profiles = {"BALANCED_STABLE_MICRO", MICRO_V2_SIGNAL_PROFILE}
            if config.signal_profile in stable_shadow_profiles:
                if not config.profile_config:
                    print(_json_dumps(_stable_forward_block("STABLE_PROFILE_CONFIG_REQUIRED", f"{config.signal_profile} requires --profile-config", args.stable_gate, signal_profile=config.signal_profile)))
                    return 0
                if config.signal_profile in micro_shadow_profiles:
                    if extract_paper_risk_multiplier(config.profile_config) is None:
                        print(_json_dumps(_stable_forward_block("PAPER_PNL_SCALING_CONFIG_MISSING", f"{config.signal_profile} requires PAPER_RISK_MULTIPLIER in --profile-config", args.stable_gate, signal_profile=config.signal_profile)))
                        return 0
                    clearance = validate_micro_resume_clearance(
                        database=database,
                        clearance_ledger=args.paper_risk_clearance,
                        profile=config.signal_profile,
                        profile_config=config.profile_config,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                        daily_risk_ledger=args.daily_risk_ledger,
                    )
                    if not clearance.get("accepted"):
                        print(_json_dumps(_stable_forward_block(str(clearance.get("paper_risk_clearance_status") or "PAPER_RISK_CLEARANCE_REQUIRED"), str(clearance.get("reason") or f"{config.signal_profile} requires valid paper risk clearance"), args.stable_gate, clearance, signal_profile=config.signal_profile)))
                        return 0
                    daily_risk = validate_micro_daily_risk(
                        database=database,
                        clearance_ledger=args.paper_risk_clearance,
                        daily_risk_ledger=args.daily_risk_ledger,
                        profile_config=config.profile_config,
                        profile=config.signal_profile,
                        log_dir=args.log_dir,
                        reports_root=args.reports_root,
                        paper_risk_dir=args.paper_risk_dir,
                    )
                    if not daily_risk.get("accepted"):
                        print(_json_dumps(_stable_forward_block(str(daily_risk.get("paper_daily_risk_status") or "PAPER_DAILY_RISK_LEDGER_REQUIRED"), str(daily_risk.get("reason") or f"{config.signal_profile} requires valid daily paper risk ledger"), args.stable_gate, daily_risk, signal_profile=config.signal_profile)))
                        return 0
                    config = replace(config, paper_risk_clearance=str(args.paper_risk_clearance), paper_daily_risk_ledger=str(args.daily_risk_ledger or ""))
                stable_gate = _stable_gate_status(args.stable_gate)
                if not stable_gate["exists"]:
                    print(_json_dumps(_stable_forward_block("STABLE_GATE_REQUIRED", f"{config.signal_profile} requires stable_gate_summary.json with PAPER_SHADOW_READY", args.stable_gate, signal_profile=config.signal_profile)))
                    return 0
                if not stable_gate["paper_shadow_ready"]:
                    print(_json_dumps(_stable_forward_block("STABLE_PROFILE_NOT_READY", "stable gate is not PAPER_SHADOW_READY", args.stable_gate, stable_gate, signal_profile=config.signal_profile)))
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
                report_dir="data/reports/forward_shadow_stable" if config.signal_profile in stable_shadow_profiles else "data/reports/forward_shadow",
                stable_gate_confirmed=config.signal_profile in stable_shadow_profiles,
                stable_gate_decision="PAPER_SHADOW_READY" if config.signal_profile in stable_shadow_profiles else "",
            )
            if config.signal_profile in stable_shadow_profiles:
                event = Event.create(
                    run_id="forward-shadow-stable",
                    environment=Environment.DEMO,
                    severity=Severity.INFO,
                    module="cli",
                    event_type="STABLE_GATE_CONFIRMED",
                    message=f"{config.signal_profile} stable gate confirmed for paper-shadow",
                    correlation_id="forward-shadow-stable:stable-gate",
                    payload={"stable_gate": str(args.stable_gate), "signal_profile_used": config.signal_profile, "execution_attempted": False},
                )
                database.insert_event(event)
            if config.signal_profile in micro_shadow_profiles:
                event = Event.create(
                    run_id="forward-shadow-stable",
                    environment=Environment.DEMO,
                    severity=Severity.INFO,
                    module="cli",
                    event_type="PAPER_RISK_CLEARANCE_ACCEPTED",
                    message=f"{config.signal_profile} paper risk clearance accepted",
                    correlation_id="forward-shadow-stable:paper-risk-clearance",
                    payload={"paper_risk_clearance": str(args.paper_risk_clearance), "daily_risk_ledger": str(args.daily_risk_ledger), "signal_profile_used": config.signal_profile, "paper_risk_profile": config.signal_profile, "execution_attempted": False},
                )
                database.insert_event(event)
                event = Event.create(
                    run_id="forward-shadow-stable",
                    environment=Environment.DEMO,
                    severity=Severity.INFO,
                    module="cli",
                    event_type="PAPER_DAILY_RISK_LEDGER_ACCEPTED",
                    message=f"{config.signal_profile} daily paper risk ledger accepted",
                    correlation_id="forward-shadow-stable:paper-daily-risk",
                    payload={"daily_risk_ledger": str(args.daily_risk_ledger), "signal_profile_used": config.signal_profile, "execution_attempted": False},
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


def _stable_forward_block(classification: str, message: str, stable_gate: Path, gate_status: dict[str, object] | None = None, signal_profile: str = "BALANCED_STABLE") -> dict[str, object]:
    return {
        "mode": "forward-shadow",
        "signal_profile_used": signal_profile,
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

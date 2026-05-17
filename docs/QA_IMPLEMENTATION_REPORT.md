# QA Implementation Report

## Scope

Role: QA / Integration Engineer.

Reviewed required sources:

- `AGENTS.md`
- `PROJECT_SPEC.md`
- `config/defaults.example.ini`
- `docs/interfaces/README.md`
- Current implementation under `src/python`
- Current tests under `tests/python`

Edited files:

- `tests/python/test_integration_safety.py`
- `docs/QA_IMPLEMENTATION_REPORT.md`

## Summary

Status: PASS with implementation gaps to track before any executable demo/live path.

The Python implementation is currently fail-closed for the reviewed paths. Default config remains demo-only, shadow mode prevents order attempts in the top-level bot loop, risk rejects unsafe signals before execution, and the MT5 execution layer can be tested with an injected mock client. No real execution route was observed while `DEMO_ONLY=True`, and the lower execution adapter also blocks real accounts when `LIVE_TRADING_APPROVED=False`.

## Phase 8 Forward Shadow Update

Status: PASS.

Integrated in Phase 8:

- Added `paper_trading` package with `PaperTrade`, paper fill model, paper position manager, performance/reporting, reconciliation, drift detection, and forward shadow orchestration.
- Added `--mode forward-shadow` for 24/7 paper observation with MT5 read-only snapshots, SQLite/JSONL audit, optional fail-safe Telegram, cycle summaries, and `execution_attempted=false`.
- Added SQLite tables: `paper_trades`, `paper_trade_events`, `paper_performance_snapshots`, and `forward_shadow_sessions`.
- Added forward reports: `summary.json`, `trades.csv`, `equity_curve.csv`, `by_symbol.csv`, `by_strategy.csv`, `by_regime.csv`, `by_session.csv`, `rejections.csv`, and `report.html`.
- Updated EC2 healthcheck to detect `forward-shadow`, inspect JSONL critical events, and flag `execution_attempted=true`.
- Added docs: `FORWARD_SHADOW.md`, `PAPER_TRADING_LIFECYCLE.md`, and `FORWARD_DRIFT_DETECTION.md`.

Additional Phase 8 tests:

- PaperTrade JSON roundtrip.
- Paper fill model uses ask for BUY entry and bid for SELL entry, with slippage.
- Paper position manager opens trades, blocks duplicates by idempotency, and reloads open trades.
- Paper trades close by SL, TP, and time stop.
- Break-even/trailing management never retreats the stop.
- Forward shadow loop tolerates Telegram failure and does not call `order_send`.
- Forward reports are written.
- Drift detector classifies performance drift.
- CLI accepts `--mode forward-shadow` and returns `execution_attempted=false`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 9 Observability And Command Center Update

Status: PASS.

Integrated in Phase 9:

- Added `observability` package with heartbeat, metrics collector, alert rules, daily summary, operational status, incidents and report helpers.
- Added persistent SQLite tables: `heartbeats`, `alerts`, `telegram_commands`, `operational_state`, `daily_summaries`, and `incidents`.
- Added Telegram Command Center with allowlisted commands for `/status`, `/health`, `/summary`, `/open_trades`, `/today`, `/symbols`, `/rejections`, `/drift`, `/pause_shadow`, `/resume_shadow`, and `/help`.
- Integrated `forward-shadow` heartbeat, alert evaluation, `shadow_paused`, daily summary generation and extended cycle summary fields.
- Added CLI modes: `status`, `health`, and `daily-summary`.
- Added Windows scripts: `run_forward_shadow.ps1`, `watchdog_forward_shadow.ps1`, and `status.ps1`.
- Added docs: `OBSERVABILITY.md`, `TELEGRAM_COMMAND_CENTER.md`, and `OPERATIONAL_RUNBOOK.md`.

Additional Phase 9 tests:

- Heartbeat persists.
- MT5 disconnected alert fires and deduplicates.
- Operational state pauses and resumes shadow.
- Telegram `/status`, `/pause_shadow`, `/resume_shadow` and unauthorized command handling are audited.
- Daily summary writes JSON.
- Forward shadow respects `shadow_paused` and writes heartbeat.
- CLI accepts `status`, `health`, and `daily-summary`.
- Forward-shadow operational scripts exist.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 10 Broker Quality And Readiness Update

Status: PASS.

Integrated in Phase 10:

- Added `broker_quality` package with read-only broker probe, spread analysis, tick freshness analysis, read latency measurement, session helper, readiness scoring and report writers.
- Added CLI modes: `broker-quality` and `readiness-report`.
- Added broker quality reports: `summary.json`, `by_symbol.csv`, `spread_by_session.csv`, `tick_freshness.csv`, `latency.csv`, `readiness_score.csv`, and `report.html`.
- Added execution readiness reports: `execution_readiness_report.json`, `.csv`, and `.html`.
- Updated validation-report to include broker quality, readiness and forward-shadow evidence when available.
- Extended observability alert rules with broker readiness, spread degradation, tick freshness degradation, MT5 read latency and rollover spread danger alerts.
- Extended Telegram Command Center with `/broker`, `/readiness`, `/spreads`, and `/latency`.
- Added docs: `BROKER_QUALITY.md` and `EXECUTION_READINESS_AUDIT.md`.

Additional Phase 10 tests:

- BrokerQualityProbe does not call `order_send`.
- Broker-quality summaries return `execution_attempted=false`.
- Spread analyzer calculates p95/p99 and blocks high p95.
- Tick freshness analyzer detects recurrent stale ticks.
- Latency monitor measures read-only mock calls.
- Readiness score classifies high-spread symbols as `NOT_READY`.
- CLI accepts `broker-quality` and `readiness-report`.
- Telegram `/broker` and `/readiness` return read-only summaries.
- Validation report includes broker readiness.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 16 Strategy Quality Upgrade

Status: PASS. Full suite result: 185 collected, 185 passed.

Integrated in Phase 16:

- Added `market_structure` package with swing points, structure, liquidity zones, session levels, volatility context, price action features, and reports.
- Upgraded core strategies to version `0.2.0` with market-structure, session, volatility, liquidity and cost-aware blocking rules.
- Added explainable setup scoring with component scores and setup quality labels.
- Added CLI modes: `strategy-diagnose` and `structure-report`.
- Forward-shadow now audits strategy context when available.
- Research reports now include `ablation_results.csv` and `strategy_version_comparison.csv`.
- Backtest reports now include setup-quality/blocking-reason placeholder breakdowns for compatibility.
- Added docs: `STRATEGY_QUALITY_UPGRADE.md`, `MARKET_STRUCTURE.md`, and `SETUP_SCORING.md`.

Additional Phase 16 tests:

- Swing high/low detection.
- BOS/CHOCH context.
- Liquidity sweep with reclaim.
- Session level ranges.
- Strategy context blockers.
- Component score metadata.
- Research ablation artifacts.
- CLI accepts `strategy-diagnose` and `structure-report`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 19B Low-Sample And Quick Research Update

Status: PASS. Verification: `py -m pytest -q` completed successfully, 257 tests collected.

Integrated in Phase 19B:

- Stress tests now tolerate trade dictionaries with extra context fields such as `regime`, `session`, and `strategy_name`.
- Added sample status classes: `LOW_SAMPLE`, `SMALL_SAMPLE`, `USABLE_SAMPLE`, and `PROMOTION_SAMPLE_SIZE`.
- Monte Carlo and stress return `LOW_SAMPLE_WARNING` when they run on fewer than 30 trades.
- Walk-forward returns `NEEDS_MORE_TRADES` for low-sample backtests instead of treating the condition as a bug.
- Real-data research compact summaries include `sample_status`, `min_required_trades`, trade breakdowns, failed stage codes, and `next_best_command`.
- Added `--quick` and skip flags for incremental real-data research.
- Added `--mode profile-comparison-run` for fast profile backtest comparison.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 19 Calibrated Signal Profile Update

Status: PASS. Verification: `py -m pytest -q` completed successfully, 249 tests collected.

Integrated in Phase 19:

- Added safe signal profile application through `--mode apply-signal-profile`.
- Added `profile_application.py` to load generated profile suggestions, write `applied_profile.json`, `applied_profile.ini`, `profile_diff.json`, and profile comparison reports.
- Added `--signal-profile` to `real-data-research` so each run can use `CONSERVATIVE`, `BALANCED`, `ACTIVE`, or `RESEARCH_ONLY` as a research overlay.
- Backtest now records `signal_profile_used`, `thresholds_used`, `signals_generated`, `trades_generated`, and `profile_not_for_demo_live`.
- Real-data research compact summaries now include signal/trade frequency status and next recommended profile.
- Master decision blocks `ACTIVE` and `RESEARCH_ONLY` from `CONTINUE_FORWARD_SHADOW`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 17 Real Data Research Run

Status: PASS. Full suite result: 191 collected, 191 passed.

Integrated in Phase 17:

- Added `real_data_research` orchestration for MT5 diagnose, history export, data quality, broker costs, structure reports, strategy diagnostics, backtest, walk-forward, Monte Carlo, stress, research, benchmark, competitive scorecard, and full validation.
- Added CLI mode: `real-data-research`.
- Added Windows script: `scripts/run_real_data_research.ps1`.
- Added timestamped run folders under `data/runs/<run_id>/` with `logs`, `historical`, `reports`, `sqlite`, `final_summary.json`, and `final_summary.html`.
- Added insufficient-history detection so the final decision becomes `NEEDS_MORE_DATA` when required bar counts are missing.
- Added docs: `REAL_DATA_RESEARCH_RUN.md`.

Additional Phase 17 tests:

- Windows script exists.
- CLI accepts `real-data-research`.
- Run folder structure is created.
- `final_summary.json` is generated.
- Missing history returns `NEEDS_MORE_DATA`.
- Failed stages are reflected in the final summary.
- Summary and stages return `execution_attempted=false`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 17B Real Data Research Repair

Status: PASS. Full suite result: 198 collected, 198 passed.

Integrated in Phase 17B:

- Hardened `real-data-research` stage handling so missing/no-trade inputs return `WARNING` or `SKIPPED` instead of crashing the full run.
- Added `SKIPPED_NO_TRADES` handling for Monte Carlo, walk-forward and stress when `reports/backtests/trades.csv` is missing or empty.
- Ensured backtest artifacts are always created: `summary.json`, `trades.csv`, and `equity_curve.csv`, including the zero-trade case.
- Added compact operator summaries: `final_summary_compact.json` and `final_summary_compact.txt`.
- Added CLI mode: `latest-run-summary`.
- Normalized stage result fields with `stage_name`, `status`, `classification`, `reports_created`, and `execution_attempted=false`.
- Fixed symbol normalization so a comma-separated string becomes symbol tokens, not characters.

Additional Phase 17B tests:

- Backtest creates empty contract files when no trades are generated.
- Walk-forward, Monte Carlo, stress and research do not crash with zero trades.
- Monte Carlo skips missing or empty `trades.csv`.
- `latest-run-summary` reads the newest compact run summary.
- Stage statuses are normalized to `PASSED`, `WARNING`, `FAILED`, or `SKIPPED`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 17C Benchmark And Zero-Trade Pipeline Repair

Status: PASS. Full suite result: 202 collected, 202 passed.

Integrated in Phase 17C:

- Hardened benchmark runner so missing, empty, or invalid CSV inputs return `classification=NEEDS_MORE_DATA` instead of crashing.
- Benchmark now writes `summary.json`, `by_symbol.csv`, and `baselines.csv` even when no baseline can run.
- Individual baselines can be marked `SKIPPED` without failing the whole benchmark stage.
- Competitive scorecard now handles benchmark `NEEDS_MORE_DATA` with reason `benchmark data insufficient`.
- Full validation now distinguishes benchmark data insufficiency from weak strategy edge.
- Compact run summary now includes `total_trades`, `benchmark_status`, `benchmark_classification`, `zero_trade_detected`, and `likely_next_step`.

Additional Phase 17C tests:

- Benchmark does not crash with an empty CSV.
- Benchmark accepts symbols as comma-separated string.
- Benchmark returns `NEEDS_MORE_DATA` and writes reports when data is insufficient.
- Competitive scorecard handles benchmark `NEEDS_MORE_DATA`.
- Master decision distinguishes missing data from zero-trade strategy output.
- Compact summary includes zero-trade fields and suggests FASE 18 when data quality is OK.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 18 Signal Frequency Calibration

Status: PASS. Full suite result: 210 collected, 210 passed.

Integrated in Phase 18:

- Added `SIGNAL_PROFILE` config with `CONSERVATIVE`, `BALANCED`, `ACTIVE`, and `RESEARCH_ONLY`.
- Added `calibration` package with signal profiles, threshold config, signal frequency analyzer, blocking reason analyzer, threshold sweeper, and report writers.
- Added CLI modes: `signal-calibration`, `threshold-sweep`, and `blocking-reasons`.
- Added near-miss detection for blocked setups close to threshold.
- Added config suggestions for all profiles, with `ACTIVE` and `RESEARCH_ONLY` marked `NOT FOR DEMO/LIVE EXECUTION`.
- Real-data compact summaries can include calibration context when reports exist.
- Added docs: `SIGNAL_FREQUENCY_CALIBRATION.md` and `THRESHOLD_SWEEP.md`.

Additional Phase 18 tests:

- Valid and invalid signal profiles.
- Threshold grid generation.
- Near-miss detection.
- Blocking reason aggregation.
- Signal calibration report generation.
- Threshold sweep CLI.
- Blocking reasons CLI.
- Real-data research recommends Fase 18 and includes calibration context.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 15 Full Validation Pipeline Update

Status: PASS. Full suite result: 179 collected, 179 passed.

Integrated in Phase 15:

- Added `validation_pipeline` package with config, stage definitions, stage results, runner, lock, artifacts, report writer, and master decision engine.
- Added `--mode full-validation`.
- Added pipeline lock to prevent concurrent full validation runs.
- Added reports: `pipeline_summary.json`, `stage_results.csv`, `master_decision.json`, `master_decision.csv`, and `report.html`.
- Added Telegram commands: `/validation` and `/pipeline`.
- Added Windows script: `scripts/run_full_validation.ps1`.
- Added docs: `FULL_VALIDATION_PIPELINE.md` and `MASTER_DECISION_ENGINE.md`.

Additional Phase 15 tests:

- Pipeline config serializes.
- Pipeline runner executes mocked stages in order.
- Pipeline lock blocks duplicate runs.
- Missing expected output marks a stage failed.
- Master decision returns `NEEDS_MORE_DATA`, `NEEDS_STRATEGY_RESEARCH`, `REJECTED`, `NEEDS_BROKER_FIX`, and `NEEDS_COST_RECALIBRATION` for the expected evidence.
- CLI accepts `full-validation`.
- Telegram `/validation` returns the latest summary.
- Windows script exists.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 14 Execution Simulation Calibration Update

Status: PASS. Full suite result: 172 collected, 172 passed.

Integrated in Phase 14:

- Added `execution_simulation` package with fill, spread, slippage, commission, latency, gap, partial-fill, calibration, paper-vs-backtest, and report modules.
- Updated paper fill and paper position management to use conservative bid/ask fills and store execution simulation metadata on paper trades.
- Added CLI modes: `simulation-calibration` and `paper-vs-backtest`.
- Added validation-report inputs for execution simulation and paper-vs-backtest calibration.
- Added observability metrics and alerts for fill quality, ambiguous events, cost assumptions and backtest-forward divergence.
- Added Telegram commands: `/fills`, `/costs`, and `/paper_vs_backtest`.
- Added docs: `EXECUTION_SIMULATION.md` and `PAPER_VS_BACKTEST_CALIBRATION.md`.

Additional Phase 14 tests:

- BUY entry uses ask and SELL entry uses bid.
- BUY exit uses bid and SELL exit uses ask.
- Extreme spread and stale ticks reject fills.
- Adverse slippage worsens fills.
- Same-bar SL/TP conservative mode assumes the worse outcome.
- Gap through SL closes worse than SL.
- Commission model applies explicit costs.
- Spread model uses p95 fallback.
- Paper trade metadata includes fill assumptions.
- Paper-vs-backtest detects optimistic backtests or underestimated costs.
- CLI accepts `simulation-calibration` and `paper-vs-backtest`.
- Telegram `/fills` returns a read-only summary.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 13 Persistence Hardening Update

Status: PASS. Full suite result: 164 collected, 164 passed.

Integrated in Phase 13:

- Added `persistence` package with canonical audit events, migrations, DB health, backup manager, audit replay, event integrity, JSONL compaction, Telegram outbox flushing, recovery manager, and persistence reports.
- Added CLI modes: `db-migrate`, `db-health`, `backup`, `audit-replay`, `telegram-outbox-flush`, and `compact-logs`.
- Integrated recovery startup checks into `forward-shadow` with `RECOVERY_STARTED`, `RECOVERY_COMPLETED`, and `RECOVERY_FAILED` events.
- Added observability metrics and alerts for DB integrity, audit gaps, Telegram outbox backlog, stale backups, recovery failure, and JSONL rotation failure.
- Added Telegram commands: `/db`, `/backup`, `/replay`, and `/outbox`.
- Added docs: `PERSISTENCE_AND_RECOVERY.md`, `AUDIT_REPLAY.md`, and `BACKUP_AND_RESTORE.md`.

Additional Phase 13 tests:

- Migrations are idempotent.
- DB health detects missing tables.
- Backup creates files and excludes `.env`.
- Audit replay reconstructs paper trades.
- Event integrity detects duplicate idempotency keys and heartbeat gaps.
- Telegram outbox flush does not duplicate sent messages.
- JSONL compactor rotates oversized logs after backup.
- Recovery manager loads open paper trades.
- Forward-shadow calls recovery manager.
- CLI accepts all persistence modes.
- Telegram `/db` and `/backup` work safely.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 12 Portfolio Intelligence Update

Status: PASS. Full suite result: 155 collected, 155 passed.

Integrated in Phase 12:

- Added `portfolio` package with currency exposure, correlation matrix, portfolio state, signal ranking, portfolio guard, dynamic risk allocation, exposure report, and portfolio report modules.
- Integrated `forward-shadow` with `SIGNAL_RANKED`, `PORTFOLIO_DECISION`, `DYNAMIC_RISK_ADJUSTED`, `CORRELATION_REJECTED`, and `EXPOSURE_REJECTED` audit events.
- Added CLI modes: `portfolio-status`, `exposure-report`, and `correlation-report`.
- Added Telegram read-only commands: `/portfolio`, `/exposure`, `/correlation`, and `/risk`.
- Added observability metrics and alerts for portfolio risk, currency exposure, correlation clusters, dynamic risk reduction, strategy concentration, and regime concentration.
- Added docs: `PORTFOLIO_INTELLIGENCE.md`, `CORRELATION_GUARD.md`, and `DYNAMIC_RISK_ALLOCATION.md`.

Additional Phase 12 tests:

- Currency exposure BUY/SELL and USD aggregation.
- Correlation matrix detects high correlation.
- Portfolio guard rejects exposure and correlation.
- Dynamic risk reduces for drawdown/loss streak and never exceeds `1.0`.
- Signal ranker prioritizes ML probability and penalizes spread.
- Forward-shadow audits portfolio decisions.
- CLI accepts portfolio modes and returns `execution_attempted=false`.
- Telegram `/portfolio` returns read-only status.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 11 ML Meta-Filter Update

Status: PASS.

Integrated in Phase 11:

- Added `ml` package with feature store, label builder, dataset builder, numpy logistic baseline trainer, sigmoid probability calibrator, model registry, runtime ML filter, prediction audit and ML reports.
- Added CLI modes: `build-ml-dataset`, `train-ml-filter`, and `ml-report`.
- Integrated forward-shadow with ML filtering after strategy and risk gates. `ML_DISABLED` allows current shadow behavior; `ML_REJECTED` blocks paper trade creation only.
- Added persistent prediction audit through `model_predictions` and `ML_PREDICTION` events.
- Added observability metrics for ML predictions, approvals, rejections, average probability and model status.
- Added Telegram commands `/ml` and `/ml_status`.
- Added docs: `ML_META_FILTER.md`, `ML_DATASET.md`, and `PROBABILITY_CALIBRATION.md`.

Additional Phase 11 tests:

- Feature store generates required columns.
- Label builder excludes open trades.
- Dataset builder uses temporal train/validation/test splits and avoids label leakage.
- Baseline trainer creates registry artifacts.
- Calibrator reports Brier score.
- ML filter returns `ML_DISABLED` when no approved model exists.
- ML filter rejects low-probability candidates without risk changes.
- Forward-shadow audits `ML_PREDICTION`.
- CLI accepts all ML modes.
- Telegram `/ml_status` returns ML state.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Interface Compatibility

Findings:

- `MarketSnapshot`, `TradeSignal`, `RiskDecision`, `ExecutionRequest`, `ExecutionResult`, and `Event` are represented in `src/python/agi_style_forex_bot_mt5/contracts.py`.
- Core semantic invariants are implemented: valid market prices, directional SL/TP checks, rejected `RiskDecision` zeroes approved lot and risk amount, `ExecutionRequest.validate()` requires positive lot, SL, TP, and magic number.
- `docs/interfaces/README.md` says `ExecutionRequest` must only be built after `RiskDecision.accepted=True` and local audit confirmation. `ExecutionEngine._preflight()` enforces accepted risk and audit confirmation before `_build_execution_request()`.
- Minor compatibility note: Python uses rich in-memory fields such as `TradeSignal.metadata` and `Event.payload`; serialized `metadata_json`/`payload_json` compatibility is provided by telemetry serialization rather than the contract dataclass field names. MQL5 or external API adapters should normalize these names explicitly at boundaries.

## Safety Checks Verified

No real execution path:

- `BotConfig` defaults to `demo_only=True`, `live_trading_approved=False`, and `shadow_mode=True`.
- `ShadowDemoBot.run_once()` audits strategy/risk and returns `execution_attempted=False`.
- `MT5Connector.validate_account_for_trading()` rejects non-demo accounts when `DEMO_ONLY=True`.
- If `demo_only=False` is manually constructed, `MT5Connector` still rejects non-demo accounts when `LIVE_TRADING_APPROVED=False`.

No order without SL/TP:

- `TradeSignal.validate_against_snapshot()` requires positive SL and TP and directional placement.
- `RiskEngine` rejects missing TP with `MISSING_TP`.
- `ExecutionEngine` rejects a signal without TP before `order_check` or `order_send`.

Audit of signals and rejections:

- `ShadowDemoBot` writes `SIGNAL_GENERATED`, `TRADE_SIGNAL_CREATED`, `SIGNAL_ACCEPTED` or `SIGNAL_REJECTED`, and `EXECUTION_SKIPPED` JSONL events.
- Risk decisions include structured `checks` and rejection codes.
- Audit failure behavior is fail-closed: `RiskEngine` rejects when `RiskRuntimeState.audit_confirmed=False`, and `ExecutionEngine` rejects when `audit_confirmed=False`.

Telegram failure isolation:

- `TelegramNotifier.notify_event()` catches `requests.RequestException`, redacts sensitive values, returns `FAILED`, and does not raise to the caller.
- Existing telemetry tests verify durable outbox behavior when a database is supplied.

MT5 mocking:

- `MT5Connector` accepts `mt5_client`, allowing deterministic fake MT5 clients in tests.
- Mocked execution reaches `order_check` and `order_send` only when account, audit, risk, spread, volume, stops, netting policy, and filling mode gates pass.

## Tests Added

Added `tests/python/test_integration_safety.py` with coverage for:

- Shadow loop audits signal/risk decision and skips execution.
- Real account blocked and audited under `DEMO_ONLY=True`.
- Real account blocked by `LIVE_TRADING_APPROVED=False` even if `demo_only=False` is manually supplied.
- Missing TP rejected at risk and execution gates with no MT5 send.
- Telegram sender failure does not raise and redacts token.
- MT5 execution can be mocked and sends only after all gates pass.

## Commands Run

- `python -m pytest tests/python/test_integration_safety.py -q`
  - Result: failed before tests because `python` resolves to the Windows Store alias in this environment.
- `py -m pytest tests/python/test_integration_safety.py -q`
  - Result: passed, `6 passed`.
- `py -m pytest -q`
  - Result: passed, `46 passed`.

## Risks And Gaps

- Telegram is implemented as a notifier, but `ShadowDemoBot` does not wire important audit events to `TelegramNotifier` yet. Current verification proves notifier failure isolation, not end-to-end bot notification delivery.
- Lower-level `ExecutionEngine` returns `ExecutionResult` but does not itself persist execution events. A caller must audit `ORDER_SENT`, MT5 rejections, fills, and duplicate/stale rejects before executable demo mode.
- Local JSONL audit is append-only, but `_audit()` does not catch database insert failures when an optional database is supplied. This remains fail-closed for trading because exceptions stop the loop, but it can interrupt shadow collection.
- Python dataclass contracts are semantically compatible but not a byte-for-byte serialized schema for MQL5. Boundary adapters should formalize JSON field names such as `metadata_json` and `payload_json`.
- Live trading remains out of scope. Tests intentionally confirm blocking behavior only; they do not approve or exercise any live execution path.

## Recommendations

- Keep execution disabled in the top-level bot until an audited execution orchestrator exists that persists signal, risk decision, execution gate decision, request, and result before/after each step.
- Wire `TelegramNotifier` behind the audit/event pipeline with durable outbox enabled for important events, while preserving the current non-raising behavior.
- Add an explicit serialization contract test for JSON-compatible `TradeSignal`, `RiskDecision`, `ExecutionRequest`, `ExecutionResult`, and `Event` records before MQL5/Python interoperability work.
- Add an execution audit integration test once executable demo mode is introduced.
- Keep `DEMO_ONLY=True`, `LIVE_TRADING_APPROVED=False`, and `shadow_mode=True` as defaults until the documented promotion and architecture gates are satisfied.

## Phase 2 End-To-End Integration Update

Status: PASS.

Integrated in Phase 2:

- `ShadowDemoBot` now emits end-to-end lifecycle events: `BOT_STARTED`, `ACCOUNT_SNAPSHOT`, `SIGNAL_DETECTED`, compatibility `SIGNAL_GENERATED`, `SIGNAL_REJECTED`, `RISK_REJECTED`, `SHADOW_ORDER_CREATED`, `EXECUTION_SKIPPED`, `BOT_STOPPED`, `CRITICAL_ERROR`, and `TELEGRAM_ERROR`.
- Telegram is wired into the bot audit pipeline through `TelegramNotifier`. Notification failures are caught, redacted, audited as `TELEGRAM_ERROR`, and do not break the loop.
- `ShadowExecutionEngine` creates idempotent `ShadowOrder` records only after accepted risk and validated SL/TP/lot/risk.
- Shadow orders are persisted to SQLite `orders` when a database is supplied and are also written to JSONL through the `SHADOW_ORDER_CREATED` event.
- `ShadowDemoBot` still never calls MT5 `order_send`; top-level result keeps `execution_attempted=False`.
- JSON boundary contracts were documented in `docs/interfaces/json_contracts.md` and backed by runtime validation helpers in `json_contracts.py`.

Additional Phase 2 tests:

- Telegram fail-safe.
- Shadow order persistence.
- No `order_send` in shadow mode.
- Accepted signal creates a shadow order.
- Strategy rejection creates no shadow order.
- Risk rejection creates no shadow order.
- Bad/missing SL/TP path fails closed before shadow order.
- Missing audit sink fails closed.
- Idempotency prevents duplicate shadow orders.
- JSON contracts validate required fields.

Commands run:

- `py -m pytest -q`
  - Result: passed, `55 passed`.
- `$env:PYTHONPATH='src/python'; py -m agi_style_forex_bot_mt5.cli --mode shadow --log-dir data\logs\phase2-smoke --sqlite data\sqlite\phase2-smoke.sqlite3`
  - Result: passed, produced `shadow_order_created=true` and `execution_attempted=false`.

Remaining risks:

- Telegram outbox durability requires SQLite to be supplied. Without SQLite, Telegram still fails safely but failed messages are not durably queued.
- `ExecutionEngine` is ready for future demo execution but remains separate from the top-level shadow bot. Any future executable demo orchestrator must persist pre-send and post-send execution events before calling MT5.
- JSON contracts are now documented and validated in Python, but MQL5 adapters still need explicit serialization/deserialization tests.
- Shadow orders are simulation artifacts and not proof of live broker fill quality.

Recommendation after Phase 2:

- Keep shadow mode as the only top-level run mode until execution-event persistence, MQL5/Python JSON adapters, and strategy promotion evidence are complete.

## Phase 3 MT5 Data-Only Update

Status: PASS.

Integrated in Phase 3:

- Added `--mode mt5-data` to the CLI.
- Added `MT5DataOnlyBot`, a read-only MT5 orchestrator that initializes MT5, reads account/symbol/tick/rates data, computes features, runs strategy/risk, and creates shadow orders only.
- `mt5-data` reads `account_info`, `symbol_info`, `symbol_info_tick`, and `copy_rates_from_pos`. It does not call `order_send`.
- Real accounts under `DEMO_ONLY=True` are audited as `ACCOUNT_REAL_DETECTED_READ_ONLY` and the run stops before symbol processing.
- MT5 initialization failure or missing account info fails closed with `execution_attempted=false`.
- Symbol/tick/rates validation failures emit `SYMBOL_REJECTED` or market-data rejection payloads and continue to the next symbol.
- Added documentation in `docs/MT5_DATA_ONLY_MODE.md`.

Additional Phase 3 tests:

- CLI accepts `--mode mt5-data`.
- `mt5-data` never calls `order_send`.
- MT5 initialize failure fails closed.
- Missing `account_info` fails closed.
- Missing `symbol_info` rejects symbol.
- Stale tick rejects symbol.
- Empty market data rejects symbol.
- Valid mocked MT5 data creates a shadow order.
- Risk rejection creates no shadow order.
- Missing audit sink fails closed.
- Telegram failure does not break the loop.
- Final summary always includes `execution_attempted=false`.

Commands run:

- `py -m pytest -q`
  - Result: passed.
- `$env:PYTHONPATH='src/python'; py -m agi_style_forex_bot_mt5.cli --mode mt5-data --log-dir data\logs\mt5-data-smoke --sqlite data\sqlite\mt5-data-smoke.sqlite3`
  - Result in this environment: fail-closed if MT5 is unavailable or not initialized; no `order_send` path is used.

Remaining risks:

- `mt5-data` validates read-only integration, not broker execution or fills.
- Multi-symbol risk correlation can be expanded once real symbol sets are configured.
- MQL5-side JSON exchange remains future work.

## Phase 3B MT5 Tick Diagnostics Update

Status: PASS.

Integrated in Phase 3B:

- Added `--mode mt5-diagnose` to the CLI.
- Added `MT5DiagnoseBot`, which connects to MT5, reads account/symbol/tick diagnostics, audits `MT5_DIAGNOSTIC`, and never generates signals or orders.
- Tick freshness now uses UTC consistently and prefers valid `tick.time_msc`, with `tick.time` as fallback.
- Tick diagnostics include raw timestamps, UTC interpretations, both age calculations, `now_utc`, bid/ask, spread, MT5 `last_error()`, and `market_is_probably_closed`.
- Stale Forex ticks during likely market closure are rejected as `MARKET_CLOSED_OR_NO_TICKS` instead of critical bot errors.
- Symbol resolution now keeps `canonical_symbol` separate from `broker_symbol` and supports common suffixes such as `EURUSDm`, `EURUSD.r`, `EURUSD.raw`, `EURUSDpro`, and `EURUSD.`.
- `mt5-data` and `mt5-diagnose` default to the configured major FX basket: `EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF, AUDUSD, EURJPY, NZDUSD`.
- Empty `copy_rates_from_pos` reads now audit `MT5_RATES_EMPTY` and try `copy_rates_range` before rejecting market data.

Additional Phase 3B tests:

- CLI accepts `--mode mt5-diagnose`.
- `tick.time` and `tick.time_msc` freshness calculations.
- Weekend stale tick uses `MARKET_CLOSED_OR_NO_TICKS`.
- Fresh tick produces an accepted snapshot.
- `time_msc` prevents a false stale rejection when `time` is skewed.
- Diagnostic output includes tick UTC fields and `execution_attempted=false`.
- Multi-symbol runs continue after one rejected symbol.
- Symbol mapper detects `EURUSDm`.
- `scripts/run_mt5_diagnose.ps1` points at the real CLI mode.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 7 Strategy Research Update

Status: PASS.

Integrated in Phase 7:

- Added `research` package with versioned `StrategyCandidate`, controlled parameter spaces, objective functions, `OverfitGuard`, candidate registry, regime selector, symbol strategy selector, research runner, and report writer.
- Added CLI mode `--mode research`.
- Research mode writes `research_summary.json`, `research_summary.csv`, `candidate_registry.json`, `recommended_strategy_mix.json`, `rejected_candidates.csv`, and `report.html`.
- Validation report now reads research summary, candidate registry, and recommended strategy mix.
- Added docs: `STRATEGY_RESEARCH.md`, `REGIME_STRATEGY_SELECTION.md`, and `OVERFIT_GUARD.md`.

Additional Phase 7 tests:

- StrategyCandidate serializes to JSON.
- ParameterSpace generation is reproducible.
- CandidateRegistry avoids duplicates.
- Composite objective penalizes few trades and high drawdown.
- OverfitGuard detects train-positive/test-negative and top-trade concentration.
- RegimeStrategySelector returns weights and blocks closed/no-tick regimes.
- SymbolStrategySelector generates recommended strategy mix.
- Research runner produces reports.
- CLI accepts `--mode research` and returns `execution_attempted=false`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 6 Data Pipeline And Competitive Benchmark Update

Status: PASS.

Integrated in Phase 6:

- Added `data_pipeline` package with historical CSV quality checks, dataset manifest generation, and broker cost profile generation.
- Added `benchmarks` package with simple baseline strategies, benchmark runner, and competitive scorecard.
- Added CLI modes: `data-quality`, `build-cost-profile`, `benchmark`, and `competitive-scorecard`.
- Updated master validation report to include data quality, broker costs, benchmark comparison, competitive scorecard, and final decision labels: `APPROVED_FOR_SHADOW_OBSERVATION`, `NEEDS_MORE_DATA`, `NEEDS_OPTIMIZATION`, `REJECTED`.
- Added documentation: `docs/DATA_PIPELINE.md`, `docs/BENCHMARKING.md`, and `docs/COMPETITIVE_SCORECARD.md`.

Additional Phase 6 tests:

- Data quality detects gaps.
- Data quality detects duplicate timestamps.
- Dataset fingerprint is reproducible.
- Broker cost profile calculates spread p95/p99.
- Random benchmark baseline is reproducible with seed.
- Benchmark runner generates baseline reports.
- Competitive scorecard rejects weak baseline/OOS evidence.
- Validation report includes data quality and benchmark summaries.
- CLI accepts all Phase 6 modes and returns `execution_attempted=false`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 5 Advanced Validation Update

Status: PASS.

Integrated in Phase 5:

- Added `--mode walk-forward` with strict train/validation/test ordering and no test leakage.
- Added robust anti-overfitting scoring that penalizes low sample size, drawdown, suspicious profit factor, out-of-sample deterioration, concentration, and cost sensitivity.
- Strengthened Monte Carlo validation with reproducible seed, bootstrap/permutation support, risk of ruin, final equity distribution, drawdown distribution, losing-streak distribution, and CSV/JSON exports.
- Strengthened stress testing with spread/slippage/commission multipliers, best-trade removal, artificial loss streaks, missing-bars proxy, one-bar delay proxy, and session shift proxy.
- Added `--mode validation-report` to consolidate base backtest, walk-forward, Monte Carlo, and stress summaries into a master decision.
- Added documentation: `docs/WALK_FORWARD.md`, `docs/MONTE_CARLO.md`, `docs/STRESS_TESTING.md`, and `docs/VALIDATION_PIPELINE.md`.

Additional Phase 5 tests:

- Walk-forward preserves temporal order and avoids leakage.
- Robust scoring penalizes few trades and out-of-sample deterioration.
- Monte Carlo report is reproducible with a fixed seed and includes probability of ruin.
- Stress testing worsens results when spread increases and removes top trades correctly.
- Master validation report consolidates all summaries.
- CLI accepts `walk-forward`, `monte-carlo`, `stress-test`, and `validation-report`.
- New validation modes return `execution_attempted=false`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 4 Backtesting Update

Status: PASS.

Integrated in Phase 4:

- Added `--mode backtest` for offline, reproducible backtests from local CSV files.
- Added `--mode export-history` for MT5 read-only CSV export with no signals, no shadow orders, and no broker execution.
- Historical CSV loading validates required columns, empty/corrupt datasets, duplicate timestamps, large gaps, and data fingerprints.
- Backtests run per symbol and multi-symbol using M5 as the base timeframe.
- The simulator applies spread, slippage, commission, SL/TP, break-even at `0.6R`, trailing from `0.8R`, and optional time stop settings.
- Reports include summary, trades, equity curve, data quality, Strategy Promotion Gate results, and breakdowns by symbol, regime, session, weekday, and UTC hour.
- Added `docs/BACKTESTING.md` and `docs/STRATEGY_PROMOTION_GATE.md`.

Additional Phase 4 tests:

- Valid CSV loads correctly.
- CSV missing mandatory columns fails.
- Empty CSV fails.
- Backtest remains offline and does not call `order_send`.
- Simulated trades use SL/TP candidates.
- Break-even moves stop to non-loss.
- Trailing stop does not retreat.
- Profit factor, drawdown, and expectancy are reproducible.
- JSON/CSV/HTML reports are created.
- Strategy Promotion Gate classifies approved, watchlist, and rejected cases.
- `export-history` does not call `order_send`.
- CLI accepts `--mode backtest`.
- CLI accepts `--mode export-history`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.

## Phase 18B Calibration Diagnostics Repair

Status: PASS. Verification: `py -m pytest -q` completed successfully, 215 tests collected.

Integrated in Phase 18B:

- Repaired threshold sweep so `blocked_candidates > 0` always produces non-empty `top_blocking_reasons`.
- Added canonical blocker codes: `DATA_MISSING`, `REGIME_MISMATCH`, `SESSION_BLOCK`, `SPREAD_BLOCK`, `STRUCTURE_BLOCK`, `VOLATILITY_BLOCK`, `ENSEMBLE_SCORE_LOW`, and `UNKNOWN_BLOCKER`.
- Added latest-run auto-discovery for calibration modes through `--runs-root data\runs` when `data\historical` is empty.
- Expanded blocking-reasons ingestion to read strategy diagnostics, backtest/research JSON, and compact/final run summaries.
- Added required calibration outputs: `near_misses.csv`, blocking summaries, per-symbol, per-strategy, per-regime, and per-session CSVs.
- Updated `latest-run-summary` to surface calibration status, recommended profile, signal counts, near misses, blockers, and suggested threshold changes.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 18C Historical Data Resolution Update

Status: PASS. Verification: `py -m pytest -q` completed successfully, 226 tests collected.

Integrated in Phase 18C:

- Added `HistoricalDataResolver` for supported MT5 CSV layouts including flat, dashed, rates suffix, double underscore, timeframe folder, and symbol folder formats.
- Added `--mode historical-data-audit` with JSON/CSV/HTML outputs plus missing-data reporting.
- Added feature availability reporting for indicators, market structure, session levels, liquidity sweep, and regime detection.
- Calibration and strategy diagnostics now use the resolver instead of manual `SYMBOL_M5.csv` path assumptions.
- Replaced generic `DATA_MISSING` where possible with specific blockers such as `MISSING_M5_FILE`, `MISSING_H1_FILE`, `INSUFFICIENT_H1_BARS`, `MISSING_REQUIRED_COLUMNS`, `EMPTY_CSV`, and `CSV_PARSE_ERROR`.
- Real-data research now includes a `HISTORICAL_DATA_AUDIT` stage and exposes historical/feature status in compact summaries.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 18D Timestamp Normalization Update

Status: PASS. Verification: `py -m pytest -q` completed successfully, 233 tests collected.

Integrated in Phase 18D:

- Added `TimestampNormalizer` for `timestamp_utc`, `timestamp`, `datetime`, `date`, and `time` columns.
- Timestamp parsing now supports epoch seconds, epoch milliseconds, ISO strings, plain datetime strings, and pandas datetime values.
- Historical resolution now audits timestamp source, status, min/max timestamps, duplicate timestamps, calibration sufficiency, and full-validation sufficiency.
- Feature availability now normalizes timestamps before indicator and market-structure feature builds, preventing `timestamp_utc must be datetime-like` when MT5 CSVs contain parseable `time`.
- Added `--mode timestamp-audit` with JSON/CSV/HTML reports.
- `export-history` now writes both `time` and normalized `timestamp_utc` columns.
- Compact run summaries include `timestamp_status`, `h1_bars_status`, `feature_availability_status`, and `main_feature_blocker`.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

## Phase 18E CSV Contract Update

Status: PASS. Verification: `py -m pytest -q` completed successfully, 240 tests collected.

Integrated in Phase 18E:

- Added a single `HistoricalCSVLoader` that normalizes historical CSV ingestion for strategy, calibration and backtesting flows.
- Added `--mode strategy-data-contract` to audit file discovery, columns, timestamp readiness, numeric OHLC conversion, feature build readiness and strategy input readiness.
- The canonical DataFrame contract is now `timestamp_utc`, `time`, `open`, `high`, `low`, `close`, `tick_volume`, `spread`, and `real_volume`.
- Replaced duplicate historical CSV readers in backtest, benchmark, research, walk-forward, market-structure, feature-availability and calibration paths where they affected strategy inputs.
- Backtest now distinguishes data-valid/no-setup runs with `WARNING_NO_SIGNALS` from setups without trades with `WARNING_NO_TRADES`.
- Real-data research now includes `DATA_CONTRACT_AUDIT` and compact summaries expose data contract status, CSV blockers and strategy-ready symbols.

Safety remains unchanged:

- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `execution_attempted=false`.
- `order_send was not called`.
- `order_check was not called`.

# Operational Runbook

Use this runbook for Windows EC2 24/7 `forward-shadow` operation.

## Start Forward Shadow

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_forward_shadow.ps1
```

## Start Watchdog

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\watchdog_forward_shadow.ps1
```

## Start BALANCED_STABLE Shadow

Only after `stable-robustness-gate` returns `PAPER_SHADOW_READY`:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_forward_shadow_balanced_stable.ps1
```

For 24/7 paper observation:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\watchdog_forward_shadow_balanced_stable.ps1
```

These scripts keep `DEMO_ONLY=True`, `LIVE_TRADING_APPROVED=False`, and paper/shadow mode only.

Stable health and daily report:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\status_forward_shadow_stable.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\daily_summary_stable.ps1
```

Pause `BALANCED_STABLE` paper observation if stable drift becomes `CRITICAL_DRIFT` or `PAUSE_STABLE_SHADOW`.

Forward evidence pack:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\forward_evidence_stable.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\forward_acceptance_stable.ps1
```

If acceptance returns `PAUSE_FORWARD_SHADOW`, stop the stable watchdog and inspect drift, paper trade audit and telemetry before restarting.

If the pause reason says an execution path appeared in evidence, run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\execution_evidence_audit.ps1
```

`order_send_called=false`, `order_check_called=false`, and `execution_attempted=false` are safe false fields. They should not block acceptance. A true field or ambiguous source remains a pause condition until reviewed. Do not delete historical evidence; keep it and classify it.

## Weekend Closed-Market Procedure

Do not run live `forward-shadow` while the Forex market is closed. Use the offline readiness checks instead:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\weekend_readiness.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\market_open_checklist.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\ec2_readiness_audit.ps1
```

`weekend-readiness` expects a clean paper state: SQLite opens, zero open paper trades, shadow paused, stable gate present, `balanced_stable.ini` present, JSONL logs parseable, and `DEMO_ONLY=True` with `LIVE_TRADING_APPROVED=False`.

If the result is not `WEEKEND_SAFE`, keep shadow paused and fix the reported class first:

- `NEEDS_PAPER_STATE_REVIEW`: run `paper-state-report` and inspect/close only simulated paper trades if needed.
- `NEEDS_EVIDENCE_REPAIR`: rerun forward evidence after repairing invalid JSONL/report state.
- `NEEDS_STABLE_GATE`: regenerate stable readiness artifacts before any BALANCED_STABLE paper run.
- `NEEDS_CONFIG_REVIEW`: stop and restore mandatory safety defaults.

## Market Open Checklist

At Sunday/Monday open, generate exact commands with:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode market-open-checklist --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reports-root data\reports --output-dir data\reports\market_open_checklist
```

Run the generated `commands.ps1` steps manually in order: `mt5-diagnose`, `live-feature-contract`, `resume-shadow`, paper-only `forward-shadow`, then `forward-signal-diagnose` after 30-60 minutes and `forward-evidence` after 2-4 hours. Do not enable demo/live execution.

## EC2 Operator Handoff

Before an EC2 migration or dry run, generate the deployment pack:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\ec2_operator_handoff.ps1
```

The pack under `data\reports\ec2_deployment_pack` contains the install checklist, exact commands, rollback plan, and guardrails. Operators should use `EC2_COMMANDS.ps1` as a command reference, not as permission to run during the weekend. The market-open commands must wait until MT5 has fresh data.

Safe EC2 helper scripts:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\ec2_market_open_runbook.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\ec2_collect_evidence.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\ec2_backup_and_health.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\ec2_safe_stop_shadow.ps1
```

All of them remain paper/shadow only and keep `execution_attempted=false`.

## Operator Drill Before Market Open

During the weekend or any closed-market window, rehearse the opening flow offline:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\operator_drill.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\dry_run_market_open.ps1
```

`operator-drill` simulates the runbook and failure handling for MT5 disconnected, all symbols rejected, feature pipeline not ready, paper daily drawdown, partial invalid timestamps and manual pause.

`dry-run-market-open` validates local prerequisites without connecting to MT5: commands exist, SQLite opens, stable gate/profile config exist, EC2 scripts exist, shadow is paused, no paper trades are open, and safety flags remain intact.

Only `DRY_RUN_MARKET_OPEN_READY` means the operator can wait for market open and then run real diagnostics. It does not start forward-shadow and does not permit demo/live execution.

## Offline Operator Dashboard

Generate the daily offline dashboard and operator report without connecting to MT5:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\operator_dashboard.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\daily_operator_report.ps1
```

The dashboard consolidates weekend readiness, EC2 readiness, deployment pack status, operator drill, dry-run market-open state, paper state, evidence, diagnostics, stable gate, security guardrails, alerts and next commands.

Telegram read-only commands:

- `/dashboard`
- `/daily_report`
- `/next_action`

They only report local status. They never start forward-shadow, never touch MT5 orders, and keep `execution_attempted=false`.

## Check Status

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\status.ps1
```

## If MT5 Disconnects

1. Connect by RDP.
2. Confirm `terminal64.exe` is running.
3. Confirm the account is logged in.
4. Run `mt5-diagnose`.
5. Check latest `MT5_DISCONNECTED` or `SYMBOL_REJECTED` alerts.

Do not change `DEMO_ONLY=True`, `LIVE_TRADING_APPROVED=False`, spread gates or tick freshness gates to bypass the issue.

## If All Ticks Are Stale

1. Check whether Forex market is closed.
2. Confirm symbols are visible in Market Watch.
3. Run:

```powershell
.\scripts\run_mt5_diagnose.ps1
```

If the market is closed or the broker has no fresh ticks, rejection is correct.

## If Performance Drift Appears

1. Keep strategy in `WATCHLIST` or `REJECTED`.
2. Review forward reports.
3. Compare with backtest, walk-forward, Monte Carlo and stress results.
4. Do not enable demo execution.

## Broker Quality Audit

Run a read-only broker quality probe:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode broker-quality --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --log-dir data\logs\broker-quality --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\broker_quality
```

Then consolidate readiness:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode readiness-report --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\readiness
```

If readiness returns `NEEDS_BROKER_FIX` or `NOT_READY`, keep the system in shadow observation and review spreads, stale ticks, stops/freeze levels, volume restrictions and MT5 read latency.

## Persistence And Recovery

Run DB health:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode db-health --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\persistence
```

Create a local backup:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode backup --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow --backup-dir data\backups
```

Replay a session:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode audit-replay --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\persistence
```

Flush Telegram outbox:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode telegram-outbox-flush --sqlite data\sqlite\forward-shadow.sqlite3
```

Compact JSONL logs:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode compact-logs --log-dir data\logs\forward-shadow --backup-dir data\backups
```

If recovery emits `RECOVERY_FAILED`, keep the bot stopped and inspect `db-health`, `audit-replay`, backups, and JSONL logs before restarting.

## Full Validation

Run the full validation pipeline:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode full-validation --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\full_validation --skip-export-history
```

Or on Windows EC2:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_full_validation.ps1
```

Read `data\reports\full_validation\master_decision.json`.

If the decision is `NEEDS_MORE_DATA`, collect cleaner history or more forward paper data.
If it is `NEEDS_STRATEGY_RESEARCH`, revisit research candidates and baselines.
If it is `NEEDS_BROKER_FIX`, review broker quality/readiness.
If it is `NEEDS_COST_RECALIBRATION`, review spread/slippage/commission and paper-vs-backtest.
If it is `REJECTED`, do not promote the strategy.

## Real Data Research Run

Use this when MT5 is available and you want one complete research run from read-only broker data through final decision:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode real-data-research --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --bars 50000 --output-root data\runs
```

Or on Windows:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_real_data_research.ps1
```

Read:

- `data\runs\<run_id>\final_summary.json`
- `data\runs\<run_id>\final_summary.html`

If the decision is `NEEDS_MORE_DATA`, leave MT5 connected longer, verify the broker symbols with `mt5-diagnose`, and rerun export/history quality. If the decision is `NEEDS_STRATEGY_RESEARCH`, inspect research ablations, benchmark gaps and rejected candidates. If the decision is `NEEDS_BROKER_FIX`, review spread, tick freshness, broker readiness and session quality.

## Safety

Operational controls are shadow-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`
# Phase 28 MT5 Clock Checks

Before investigating stale/future tick rejects, compare local and UTC clocks:

```powershell
Get-Date
(Get-Date).ToUniversalTime()
Get-TimeZone
```

Then run:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols EURUSD,GBPUSD,USDJPY --log-dir data\logs\mt5-diagnose-open --sqlite data\sqlite\mt5-diagnose-open.sqlite3
```

If `timestamp_normalized=true` and `tick_time_status=NORMALIZED_FRESH`, the broker/server offset was handled safely. If `tick_time_status` is `FUTURE_TOO_FAR`, `INVALID_TIMESTAMP`, or `NORMALIZED_STALE`, keep the system in read-only/shadow mode and inspect broker sessions, symbol availability, and MT5 terminal clock behavior.

# Phase 29 Zero Signal Forward Check

When BALANCED_STABLE forward-shadow is connected but no signals are detected, run:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode forward-signal-diagnose --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE --profile-config data\reports\stability_repair\balanced_stable.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\forward_diagnostics
```

If the result is `FORWARD_PIPELINE_OK_WAIT_FOR_SETUP`, keep observing. If it is `FEATURE_PIPELINE_NOT_READY`, inspect live bars/features. If it is `STABLE_FILTER_TOO_RESTRICTIVE`, revisit stability repair in research only. Do not adjust thresholds directly in forward-shadow.

# Phase 31 Candidate Replay

When candidates exist but are blocked by `REGIME_MISMATCH` or `ENSEMBLE_SCORE_LOW`, replay them in research-only mode:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-candidate-replay --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --diagnostics-dir data\reports\forward_diagnostics --profile-config data\reports\stability_repair\balanced_stable.ini --output-dir data\reports\forward_research
py -m agi_style_forex_bot_mt5.cli --mode forward-blocker-sensitivity --diagnostics-dir data\reports\forward_diagnostics --profile-config data\reports\stability_repair\balanced_stable.ini --output-dir data\reports\forward_research
```

These modes only read evidence and write reports. They do not modify the active forward-shadow terminal, paper trade SQLite state, risk limits, thresholds, or execution settings.

# Paper State Repair

If `PAPER_DAILY_DRAWDOWN`, `PARTIAL_INVALID_TIMESTAMPS`, open paper trades, or a zero-cycle forward-shadow exit appears, inspect the paper state first:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --output-dir data\reports\paper_state
py -m agi_style_forex_bot_mt5.cli --mode paper-open-trades --sqlite data\sqlite\forward-shadow-stable.sqlite3 --output-dir data\reports\paper_state
```

Pause or resume shadow entries safely:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode pause-shadow --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "PAPER_DAILY_DRAWDOWN review"
py -m agi_style_forex_bot_mt5.cli --mode resume-shadow --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "manual resume after review"
```

Paper-only close has a dry-run default:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-close-all --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "manual paper reset after evidence parsing repair" --output-dir data\reports\paper_state
py -m agi_style_forex_bot_mt5.cli --mode paper-close-all --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "manual paper reset after evidence parsing repair" --confirm-paper-only true --output-dir data\reports\paper_state
```

These commands only modify local SQLite paper/shadow state. They never modify MT5 positions.

# Telemetry Timestamp Repair

If `forward-acceptance` returns `NEEDS_TELEMETRY_FIX` or `NEEDS_TELEMETRY_REVIEW`, inspect timestamp evidence offline:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode telemetry-timestamp-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
```

If the report says `TELEMETRY_ACTIVE_BLOCKING`, do not resume shadow. Repair the producer that is writing invalid recent timestamps. If the report says `TELEMETRY_HISTORICAL_ISSUES_ONLY`, review the CSV and quarantine the historical evidence without deleting or editing originals:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode quarantine-telemetry-issues --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair --reason "Historical redacted timestamps reviewed after paper reset"
py -m agi_style_forex_bot_mt5.cli --mode telemetry-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
py -m agi_style_forex_bot_mt5.cli --mode telemetry-acceptance-policy --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
```

`telemetry_quarantine_ledger.json` records the review decision, raw-value hash and source. It is a ledger, not a data rewrite. After `telemetry_status=TELEMETRY_HISTORICAL_QUARANTINED` and `telemetry_acceptance_clear=true`, rerun `forward-acceptance`; any remaining block should come from current operational criteria such as drawdown, drift, hours observed, closed paper trades, paper audit or execution evidence.

# Phase 39 Paper Risk Calibration

Do not keep resuming after repeated `PAPER_DAILY_DRAWDOWN_HALT`. First run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\paper_risk
py -m agi_style_forex_bot_mt5.cli --mode build-paper-risk-profile --base-profile BALANCED_STABLE --risk-audit-dir data\reports\paper_risk --output-dir data\reports\paper_risk
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_risk
```

Use `BALANCED_STABLE_MICRO` only for paper/shadow observation:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE_MICRO --profile-config data\reports\paper_risk\balanced_stable_micro.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --cycle-seconds 30
```

If `paper-risk-status` says `PAPER_RISK_BLOCKED`, do not resume blindly. Inspect the `blocking_reason`: max open trades, daily trade limit, cooldown, or paper drawdown halt. These are paper-only controls and do not authorize demo/live execution.

## Phase 39B Paper Risk Clearance

When the block is `PAPER_DRAWDOWN_HALT_BLOCK`, create a formal manual review before any micro resume:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-review --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --output-dir data\reports\paper_risk_review
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-clearance --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --output-dir data\reports\paper_risk_review --reason "Manual review after PAPER_DAILY_DRAWDOWN_HALT; resume only with BALANCED_STABLE_MICRO"
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --profile-config data\reports\paper_risk\balanced_stable_micro.ini --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --output-dir data\reports\paper_risk
```

Clearance requires zero open paper trades, clean or false-positive-only execution evidence, telemetry acceptance clear, an existing `balanced_stable_micro.ini`, and a `PAPER_SHADOW_READY` stable gate. It clears only `BALANCED_STABLE_MICRO` for paper/shadow. `BALANCED_STABLE` remains blocked by the halt, and demo/live stays prohibited.

If profile matching looks wrong, run the Phase 39C check:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-clearance-check --profile BALANCED_STABLE_MICRO --profile-config data\reports\paper_risk\balanced_stable_micro.ini --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --output-dir data\reports\paper_risk_review
```

The check reports the requested profile, canonical requested profile, cleared profile, canonical cleared profile, stale status, and mismatch reason. It treats casing and spaces safely, but it never lets a micro clearance unblock the normal `BALANCED_STABLE` profile.

Forward-shadow micro now requires the ledger:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE_MICRO --profile-config data\reports\paper_risk\balanced_stable_micro.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --paper-risk-clearance data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --cycle-seconds 30
```

## Phase 40 Daily Paper Risk State

If `paper-risk-clearance-check` is clean but `paper-risk-status` still shows `PAPER_DRAWDOWN_HALT_BLOCK`, audit daily risk state:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-daily-risk-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_daily_risk
```

If the audit reports only stale halts before clearance, create a daily risk ledger:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-daily-risk-clear --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_daily_risk --reason "Clear stale paper drawdown halt after manual review and micro clearance"
```

This ledger does not delete or rewrite evidence. It only records that halts before the latest micro clearance were reviewed for `BALANCED_STABLE_MICRO`. A halt after the ledger or after the micro clearance still blocks.

## Paper PnL Root-Cause Audit

When `paper-risk-status` reports `PAPER_DRAWDOWN_HALT_BLOCK` after a valid micro clearance, first run `scripts\paper_pnl_audit.ps1`, then `scripts\paper_risk_recommendation.ps1`. Do not delete logs, reset PnL, or issue another clearance until the recommendation is reviewed.

Recommended actions:
- `FIX_PAPER_PNL_SCALING`: repair sign/point/pip/contract scaling before any new clearance.
- `REDUCE_MICRO_RISK_FURTHER`: the micro profile still produced a valid halt; keep blocked or create a stricter research-only profile.
- `READY_FOR_NEW_MICRO_CLEARANCE`: only applicable when the root cause is a reviewed daily-window/history leak.
- `KEEP_BLOCKED`: evidence is inconclusive.

All commands are offline/read-only except report generation and keep `execution_attempted=false`.

## Paper PnL Scaling Check

After the FASE 41 fix, use `scripts\paper_pnl_scaling_check.ps1` to confirm `PAPER_RISK_MULTIPLIER=0.1` is present and the current engine is ready. Use `scripts\paper_risk_post_fix_gate.ps1` before any new micro clearance. A clearance is not acceptable when the scaling status is `PAPER_PNL_SCALING_NOT_FIXED` or `PAPER_PNL_SCALING_CONFIG_MISSING`.

`raw_pnl` is audit-only. `scaled_paper_pnl` is the basis for paper drawdown and paper risk blocks. This does not authorize demo/live trading.

## Phase 42 Legacy Drawdown Quarantine

If `paper-risk-status` still reports `PAPER_DRAWDOWN_HALT_BLOCK` with `root_cause=DRAWDOWN_HISTORY_LEAK` after PnL scaling is fixed, audit legacy drawdown evidence:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-legacy-drawdown-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --daily-risk-dir data\reports\paper_daily_risk --pnl-audit-dir data\reports\paper_pnl_audit --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_daily_risk
```

Interpretation:

- `LEGACY_DRAWDOWN_QUARANTINED`: historical or unscaled halts are preserved as evidence but no longer contaminate active micro risk state.
- `ACTIVE_SCALED_DRAWDOWN_BLOCK`: a real scaled paper halt occurred after the ledger; keep shadow blocked.
- `LEGACY_DRAWDOWN_REVIEW_REQUIRED`: review the source rows before any resume.

Resume `BALANCED_STABLE_MICRO` only when clearance, daily risk ledger, PnL scaling check and legacy drawdown audit all agree that there is no active scaled halt. This is still paper/shadow only and does not authorize demo/live execution.

## Phase 42B Telemetry Quarantine Alignment

If `forward-acceptance` returns `NEEDS_TELEMETRY_REVIEW` with `active_blocking_count=0`, close the remaining historical timestamp issues through the quarantine ledger:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode quarantine-telemetry-issues --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair --reason "Historical invalid timestamps reviewed after paper reset"
py -m agi_style_forex_bot_mt5.cli --mode telemetry-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
py -m agi_style_forex_bot_mt5.cli --mode telemetry-acceptance-policy --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
```

Acceptance may advance only when `historical_unreviewed_count=0`, `unknown_requires_review=0`, `active_blocking_count=0`, and `telemetry_acceptance_clear=true`. The ledger is auditable and idempotent; rerunning quarantine does not duplicate reviewed issues.

## Phase 42C Telemetry Drift Prevention

If forward evidence keeps rediscovering historical timestamp examples, run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode telemetry-drift-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --telemetry-dir data\reports\telemetry_repair --output-dir data\reports\telemetry_repair
```

Expected healthy result: `telemetry_drift_status=TELEMETRY_DRIFT_CONTAINED`, `active_blocking_count=0`, `historical_unreviewed_count=0`, and `telemetry_acceptance_clear=true`. Derived examples in evidence reports and legacy redacted timestamps remain visible in CSV/HTML reports, but they do not block acceptance unless they are active forward telemetry or unknown review-required evidence.

## Phase 42D Acceptance Drawdown Policy

Forward acceptance now distinguishes raw drawdown flags from active scaled drawdown evidence. If `forward-acceptance` reports `acceptance_drawdown_blocking=false`, the paper drawdown condition is not the reason for blocking. Use:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode acceptance-drawdown-policy-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --daily-risk-dir data\reports\paper_daily_risk --pnl-audit-dir data\reports\paper_pnl_audit --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\forward_evidence
```

`LEGACY_DRAWDOWN_NOT_BLOCKING` means the historical halt is still visible but no active scaled drawdown event exists. `ACTIVE_SCALED_DRAWDOWN_BLOCK` means keep shadow paused. This policy is for paper/shadow evidence only and does not enable demo/live execution.

## Phase 42E Paper State Recovery

If status shows `halt_reason=PAPER_STATE_ERROR`, `latest_exit_reason=CONFIG_ERROR`, or `paper_clean_state=false`, do not resume blindly. First run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-state-recovery-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --daily-risk-dir data\reports\paper_daily_risk --pnl-audit-dir data\reports\paper_pnl_audit --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --output-dir data\reports\paper_state_recovery
py -m agi_style_forex_bot_mt5.cli --mode paper-state-recovery-plan --output-dir data\reports\paper_state_recovery
```

If the plan recommends `CLOSE_STALE_OPEN_PAPER_TRADE_PAPER_ONLY`, close only after review:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-close-stale-open-trade --sqlite data\sqlite\forward-shadow-stable.sqlite3 --output-dir data\reports\paper_state_recovery --confirm-paper-only true --reason "manual paper-only recovery after stale open trade review"
```

This command only updates paper/shadow SQLite state. It never closes MT5 positions, never calls `order_send`, and never calls `order_check`. Valid open paper trades are not closed automatically.

## Phase 42F Config Error Root Cause

If `paper-state-recovery-audit` reports `unknown_config_error`, run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode config-error-root-cause-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --daily-risk-dir data\reports\paper_daily_risk --pnl-audit-dir data\reports\paper_pnl_audit --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --output-dir data\reports\config_error_recovery
py -m agi_style_forex_bot_mt5.cli --mode config-error-fix-plan --output-dir data\reports\config_error_recovery
```

The root-cause audit checks input paths, profile schema, stable gate, paper-risk clearance, daily-risk ledger, operational state, recent logs and open paper trade consistency. It classifies one primary cause such as `MISSING_PROFILE_CONFIG`, `PROFILE_MISMATCH`, `INVALID_DAILY_RISK_LEDGER_SCHEMA` or `FORWARD_SHADOW_CONFIG_EXCEPTION`.

When the evidence says an open paper trade has invalid risk distance, keep shadow paused and review paper state. The plan is advisory only; it does not close trades, delete evidence, or touch MT5.

## Phase 42G Invalid Open Paper Trade Recovery

If root-cause evidence shows an open paper trade with `entry_price == sl_price` or another invalid risk distance, audit the open trades:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode invalid-open-paper-trade-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\paper_state_recovery
```

After manual review, close only the invalid paper trade in SQLite:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-close-invalid-open-trade --sqlite data\sqlite\forward-shadow-stable.sqlite3 --trade-id <TRADE_ID> --confirm-paper-only true --reason "Close invalid paper trade with zero risk distance after audit" --output-dir data\reports\paper_state_recovery
```

This is not a broker close. It writes `invalid_trade_close_summary.json`, `invalid_trade_close_event.json`, and `invalid_trade_close_ledger.json`, then clears the paper-state CONFIG_ERROR only when no invalid open paper trades remain. Closed historical trades are not modified.

## Phase 43 Offline Research Candidate Ranking

When paper/shadow is blocked by cooldown or another operational gate, use offline ranking instead of resuming:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode research-candidate-ranking --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\research_candidate_ranking
```

The ranking reads SQLite, logs and reports, then writes only to `data\reports\research_candidate_ranking`. It scores symbols and strategies by signal quality, blockers, regime/session context, and paper performance. It does not alter configs, ledgers, risk state, telemetry state, paper trades, or forward-shadow status.

Use this report to decide what to inspect next in research. It does not replace forward acceptance and does not authorize demo/live execution.

## Phase 44 Forward Sufficiency Audit

When `forward-acceptance` returns `NEEDS_MORE_FORWARD_DATA`, use the sufficiency audit to determine whether the blocker is only time/trade count or whether the micro profile is throttling activity:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-sufficiency-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\forward_sufficiency
```

The audit writes only to `data\reports\forward_sufficiency`. It reports observation hours, closed paper trades, estimated time to 10 closed trades, rejection and blocker funnels, symbol activity, and profile throttle counts for session, score, spread, regime, liquidity, cooldown, paper risk, and data quality. It does not change runtime filters, pause/resume shadow, modify SQLite, or replace forward-acceptance.

## Phase 45 Micro Frequency Calibration

If the 24h requirement is already satisfied but the observation still has fewer than 10 closed paper trades, run the offline micro frequency calibration:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode micro-frequency-calibration --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\micro_frequency_calibration
```

This mode diagnoses rejection pressure, score/session/regime/spread/cooldown bottlenecks, symbol conversion, and paper exit latency. It creates `balanced_stable_micro_v2_candidate.ini` as a non-active research artifact only. It does not replace `balanced_stable_micro.ini`, does not change stable gate or ledgers, and does not approve forward acceptance.

## Phase 46 Micro V2 Manual Review

Review the non-active candidate before any future dry-run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode micro-v2-review --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --base-profile-config data\reports\paper_risk\balanced_stable_micro.ini --candidate-profile-config data\reports\micro_frequency_calibration\balanced_stable_micro_v2_candidate.ini --output-dir data\reports\micro_v2_review
```

The review compares base vs candidate, audits risk, cooldown, session, threshold, symbol and paper-limit changes, and writes reports to `data\reports\micro_v2_review`. It creates `data\reports\paper_risk\balanced_stable_micro_v2.ini` only when the candidate has conservative actionable changes and all safety constraints pass. A created V2 remains inactive and is approved only for a later explicit paper dry-run phase.

## Phase 47 Controlled Micro Frequency Proposal

If the Phase 46 candidate has no actionable changes, build a new offline proposal from real bottlenecks and existing profile keys only:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode micro-frequency-proposal --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --base-profile-config data\reports\paper_risk\balanced_stable_micro.ini --frequency-dir data\reports\micro_frequency_calibration --v2-review-dir data\reports\micro_v2_review --output-dir data\reports\micro_frequency_proposal
```

The proposal may reduce `COOLDOWN_AFTER_LOSS_MINUTES` by at most 10% or 15 minutes and may raise `MAX_PAPER_TRADES_PER_DAY` only up to 3, if those keys already exist. It never reduces drawdown halt cooldown, never increases risk, never raises open trade limits, and never invents missing regime/liquidity/stale/signal-score parameters. The proposed profile is not active and must go through a later review/dry-run phase.

## Phase 48 Micro V2 Proposed Review

Review the proposed profile before creating the final V2 paper dry-run artifact:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode micro-v2-proposed-review --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --base-profile-config data\reports\paper_risk\balanced_stable_micro.ini --proposed-profile-config data\reports\micro_frequency_proposal\balanced_stable_micro_v2_proposed.ini --output-dir data\reports\micro_v2_review_proposed
```

Approval creates `data\reports\paper_risk\balanced_stable_micro_v2.ini` with `APPROVED_FOR_PAPER_DRY_RUN_ONLY=true`, `APPROVED_FOR_DEMO=false`, and `APPROVED_FOR_LIVE=false`. It does not activate forward-shadow, does not change the active micro profile, and still requires a later explicit phase before any paper dry-run.

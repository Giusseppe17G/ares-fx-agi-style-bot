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

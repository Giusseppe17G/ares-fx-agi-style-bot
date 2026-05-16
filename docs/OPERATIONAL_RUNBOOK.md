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

## Safety

Operational controls are shadow-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

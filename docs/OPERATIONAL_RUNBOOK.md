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

## Safety

Operational controls are shadow-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`


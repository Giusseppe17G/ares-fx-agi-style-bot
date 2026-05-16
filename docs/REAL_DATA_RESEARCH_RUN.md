# Real Data Research Run

Phase 17 adds a master research run that coordinates MT5 read-only diagnostics, historical export, offline validation, strategy research, benchmarking, and full validation into one timestamped folder.

It does not enable demo/live execution and never calls `order_send` or `order_check`.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode real-data-research --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --bars 50000 --output-root data\runs
```

Windows script:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_real_data_research.ps1
```

## Run Folder

Each run creates:

```text
data/runs/YYYYMMDD-HHMMSS-real-data-research/
  logs/
  historical/
  reports/
  sqlite/
  final_summary.json
  final_summary.html
```

## Stages

The runner executes:

- `MT5_DIAGNOSE`
- `EXPORT_HISTORY`
- `DATA_QUALITY`
- `BROKER_COST_PROFILE`
- `STRUCTURE_REPORT`
- `STRATEGY_DIAGNOSE`
- `BACKTEST`
- `WALK_FORWARD`
- `MONTE_CARLO`
- `STRESS_TEST`
- `RESEARCH`
- `BENCHMARK`
- `COMPETITIVE_SCORECARD`
- `FULL_VALIDATION`

Historical export targets are conservative:

- `M5`: 50000 bars
- `M15`: 30000 bars
- `H1`: 10000 bars

If any required symbol/timeframe has fewer bars, the final decision is `NEEDS_MORE_DATA`.

## Final Summary

`final_summary.json` includes:

- symbols exported
- bars by symbol/timeframe
- data quality status
- broker cost status
- strategy diagnostics
- backtest summary
- walk-forward summary
- Monte Carlo summary
- stress summary
- research summary
- benchmark comparison
- competitive scorecard
- full validation decision
- top blocking issues
- recommended next actions

## Decisions

- `NEEDS_MORE_DATA`: export more history, check MT5 symbols, and rerun.
- `NEEDS_STRATEGY_RESEARCH`: inspect research ablations, baselines, and strategy versions.
- `NEEDS_BROKER_FIX`: inspect broker quality, spread, tick freshness, and symbol readiness.
- `NEEDS_COST_RECALIBRATION`: increase spread/slippage/commission assumptions and compare paper-vs-backtest.
- `CONTINUE_FORWARD_SHADOW`: keep collecting paper evidence.
- `REJECTED`: do not promote the current candidate set.

No decision authorizes demo or live execution.

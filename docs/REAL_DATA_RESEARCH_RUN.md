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
  final_summary_compact.json
  final_summary_compact.txt
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

`final_summary_compact.json` is the operator view. It includes:

- `run_id`
- `final_decision`
- `symbols_exported`
- `bars_by_symbol_timeframe`
- `total_trades`
- `benchmark_status`
- `benchmark_classification`
- `zero_trade_detected`
- `likely_next_step`
- `stages_passed`
- `stages_warning`
- `stages_failed`
- `stages_skipped`
- `top_issues`
- `recommended_next_actions`
- `execution_attempted=false`
- `order_send_called=false`
- `order_check_called=false`

Read the newest compact summary with:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode latest-run-summary --runs-root data\runs
```

## No-Trade Stages

`SKIPPED_NO_TRADES` means a downstream statistical stage needed closed simulated trades, but `reports/backtests/trades.csv` was missing or empty. It is not a trading error and it does not imply execution. It means the current strategy/data combination did not produce enough simulated trades for that validation method.

If backtest generates `0` trades:

- Inspect `reports/strategy_diagnostics`.
- Check whether market-structure, session, spread, or setup-score filters are too strict.
- Confirm exported history has enough bars and realistic spread columns.
- Keep final decision at `NEEDS_MORE_DATA` or `NEEDS_STRATEGY_RESEARCH`.
- If data quality is `OK`, `likely_next_step` becomes `Run FASE 18: Signal Frequency Calibration`.

Run calibration:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode signal-calibration --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\calibration
py -m agi_style_forex_bot_mt5.cli --mode threshold-sweep --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\calibration --profiles CONSERVATIVE,BALANCED,ACTIVE,RESEARCH_ONLY
```

If a calibration report exists under the run reports folder, `final_summary_compact.json` includes recommended profile, expected signal frequency, suggested threshold changes, and top blockers.

Phase 18B also exposes these fields through `latest-run-summary`:

- `calibration_status`
- `recommended_profile`
- `signals_found`
- `near_misses`
- `top_blocking_reasons`
- `suggested_threshold_changes`

Use `--runs-root data\runs` with calibration commands when the root `data\historical` folder is empty. The CLI will prefer the newest `data\runs\<run_id>\historical` directory with CSV files.

If threshold sweep returns `RESEARCH_ONLY`, treat it as a diagnosis state, not an execution profile. Inspect `blocking_reasons.csv`, `near_misses.csv`, and the strategy diagnostics before changing thresholds.

Phase 18C adds `HISTORICAL_DATA_AUDIT` before strategy diagnostics and backtesting. `latest-run-summary` now also exposes:

- `historical_data_status`
- `missing_timeframes`
- `insufficient_timeframes`
- `feature_availability_status`
- `main_data_blocker`
- `recommended_next_action`

If `main_data_blocker=INSUFFICIENT_H1_BARS`, export more H1 bars or lower only the calibration diagnostic minimum for research. If historical data is sufficient and zero trades remain, the next step becomes `Run FASE 19: Strategy Threshold Application / Balanced Profile Backtest.`

Phase 18D adds timestamp normalization diagnostics. `time` from MT5 is acceptable when parseable; the pipeline normalizes it into `timestamp_utc` before features. If `timestamp_status=FAILED`, re-export history or run:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode timestamp-audit --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\runs\<RUN_ID>\historical --report-dir data\runs\<RUN_ID>\reports\timestamp_audit
```

If `h1_bars_status=CALIBRATION_ONLY`, threshold calibration may continue, but full validation still needs more H1 history.

If Monte Carlo is skipped:

- First fix backtest trade generation.
- Do not interpret missing Monte Carlo as approval.
- Keep the symbol/strategy blocked from any future demo execution review.

If Research returns `NEEDS_MORE_DATA`:

- Confirm M5 CSVs exist for each symbol.
- Rerun data-quality and broker cost profile.
- Inspect rejected candidates and ablation reports once enough data exists.

If Benchmark returns `NEEDS_MORE_DATA`:

- Confirm M5 files exist and are non-empty for all configured symbols.
- Inspect `reports/benchmarks/baselines.csv` for skipped baselines and skip reasons.
- Do not use the competitive scorecard as approval until benchmark data is sufficient.

## Decisions

- `NEEDS_MORE_DATA`: export more history, check MT5 symbols, and rerun.
- `NEEDS_STRATEGY_RESEARCH`: inspect research ablations, baselines, and strategy versions.
- `NEEDS_BROKER_FIX`: inspect broker quality, spread, tick freshness, and symbol readiness.
- `NEEDS_COST_RECALIBRATION`: increase spread/slippage/commission assumptions and compare paper-vs-backtest.
- `CONTINUE_FORWARD_SHADOW`: keep collecting paper evidence.
- `REJECTED`: do not promote the current candidate set.

No decision authorizes demo or live execution.

# Full Validation Pipeline

`full-validation` coordinates the research and operational validation stack into one reproducible run.

It does not enable demo/live execution and never calls `order_send` or `order_check`.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`

## Stages

- `EXPORT_HISTORY`
- `DATA_QUALITY`
- `BROKER_COST_PROFILE`
- `BACKTEST`
- `WALK_FORWARD`
- `MONTE_CARLO`
- `STRESS_TEST`
- `RESEARCH`
- `BENCHMARK`
- `COMPETITIVE_SCORECARD`
- `BROKER_QUALITY`
- `SIMULATION_CALIBRATION`
- `PAPER_VS_BACKTEST`
- `VALIDATION_REPORT`
- `MASTER_DECISION`

Each stage records status, timestamps, duration, inputs, outputs, summary, error message, and `execution_attempted=false`.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode full-validation --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\full_validation --skip-export-history
```

Use `--run-export-history` only when MT5 is installed and read-only history export is intended.

## Reports

- `data/reports/full_validation/pipeline_summary.json`
- `data/reports/full_validation/stage_results.csv`
- `data/reports/full_validation/master_decision.json`
- `data/reports/full_validation/master_decision.csv`
- `data/reports/full_validation/report.html`

## Locking

The pipeline creates `.pipeline.lock` under the output directory. A second run fails fast while the lock exists.

## Real Data Research Wrapper

Phase 17 adds `real-data-research` as a higher-level wrapper around the full validation stack. It first runs MT5 read-only diagnostics and real historical export into a timestamped run folder, then runs data quality, cost profile, market-structure reports, strategy diagnostics, backtest, walk-forward, Monte Carlo, stress, research, benchmarks, competitive scorecard, and `full-validation`.

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode real-data-research --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --bars 50000 --output-root data\runs
```

If exported history is insufficient, the wrapper returns `NEEDS_MORE_DATA` even if later stages are skipped or mocked. It remains read-only/research-only and does not call `order_send` or `order_check`.

The wrapper also writes `final_summary_compact.json` and `final_summary_compact.txt` under the run folder. Use:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode latest-run-summary --runs-root data\runs
```

Stages that depend on closed simulated trades may report `SKIPPED_NO_TRADES` when `reports/backtests/trades.csv` is missing or empty. That is a blocking research condition, not approval.

If benchmark reports `NEEDS_MORE_DATA`, the competitive scorecard and master decision remain blocked. If data quality is OK but backtest has zero trades, the master decision should move toward `NEEDS_STRATEGY_RESEARCH`, which is the expected path into signal frequency calibration.

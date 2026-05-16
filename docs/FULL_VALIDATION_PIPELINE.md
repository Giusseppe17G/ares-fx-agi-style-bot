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


# Validation Pipeline

The validation pipeline combines base backtest, walk-forward, Monte Carlo, and stress testing before any strategy can be considered for prolonged shadow observation.

This pipeline does not enable real trading or demo execution.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Full Sequence

1. Export history from MT5:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode export-history --symbols EURUSD,GBPUSD,USDJPY --timeframes M5,M15,H1 --bars 50000 --output-dir data\historical
```

2. Run base backtest:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode backtest --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\backtests
```

3. Validate data quality and broker costs:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode data-quality --data-dir data\historical --report-dir data\reports\data_quality
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode build-cost-profile --data-dir data\historical --report-dir data\reports\broker_costs
```

4. Run walk-forward:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode walk-forward --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\walk_forward
```

5. Run Monte Carlo:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode monte-carlo --trades data\reports\backtests\trades.csv --report-dir data\reports\monte_carlo --simulations 2000 --seed 42
```

6. Run stress test:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode stress-test --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\stress
```

7. Run benchmarks and competitive scorecard:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode benchmark --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\benchmarks
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode competitive-scorecard --reports-root data\reports --output-dir data\reports\competitive_scorecard
```

8. Run strategy research:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode research --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --reports-root data\reports --output-dir data\reports\research --max-candidates 100
```

9. Run broker quality and readiness audit:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode broker-quality --symbols EURUSD,GBPUSD,USDJPY --log-dir data\logs\broker-quality --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\broker_quality
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode readiness-report --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\readiness
```

10. Run execution simulation and paper-vs-backtest calibration:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode simulation-calibration --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\execution_simulation
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode paper-vs-backtest --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\paper_vs_backtest
```

11. Build master validation report:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode validation-report --reports-root data\reports --output-dir data\reports\validation
```

## Master Report

Files:

- `data/reports/validation/master_validation_report.json`
- `data/reports/validation/master_validation_report.csv`
- `data/reports/validation/master_validation_report.html`

The master report includes broker quality, execution readiness, forward-shadow, execution simulation, and paper-vs-backtest summaries when available. Operational decisions include `CONTINUE_FORWARD_SHADOW`, `NEEDS_MORE_DATA`, `NEEDS_BROKER_FIX`, `NEEDS_STRATEGY_FIX`, and `NOT_READY`.

## Blocking Criteria

Demo execution remains blocked when:

- Base backtest does not meet minimum metrics.
- Data quality is rejected or broker cost profile is missing.
- Strategy does not beat simple baselines after realistic costs.
- Competitive scorecard is not acceptable.
- Strategy research has no approved/watchlist candidates.
- Walk-forward test is negative or too sparse.
- Monte Carlo shows excessive risk of ruin.
- Stress test collapses under spread `x2`.
- Removing the top `5%` of trades destroys profitability.
- Results are concentrated by hour, day, session, regime, or week.
- Execution simulation reports `COST_ASSUMPTION_TOO_LOW`.
- Paper-vs-backtest reports `BACKTEST_TOO_OPTIMISTIC` or `COST_ASSUMPTION_TOO_LOW`.

Backtest positivity alone is never enough.

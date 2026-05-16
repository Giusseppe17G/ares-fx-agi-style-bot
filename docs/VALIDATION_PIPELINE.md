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

3. Run walk-forward:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode walk-forward --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\walk_forward
```

4. Run Monte Carlo:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode monte-carlo --trades data\reports\backtests\trades.csv --report-dir data\reports\monte_carlo --simulations 2000 --seed 42
```

5. Run stress test:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode stress-test --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\stress
```

6. Build master validation report:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode validation-report --reports-root data\reports --output-dir data\reports\validation
```

## Master Report

Files:

- `data/reports/validation/master_validation_report.json`
- `data/reports/validation/master_validation_report.csv`
- `data/reports/validation/master_validation_report.html`

## Blocking Criteria

Demo execution remains blocked when:

- Base backtest does not meet minimum metrics.
- Walk-forward test is negative or too sparse.
- Monte Carlo shows excessive risk of ruin.
- Stress test collapses under spread `x2`.
- Removing the top `5%` of trades destroys profitability.
- Results are concentrated by hour, day, session, regime, or week.

Backtest positivity alone is never enough.

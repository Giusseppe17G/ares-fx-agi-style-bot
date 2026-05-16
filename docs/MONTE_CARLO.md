# Monte Carlo Validation

Monte Carlo validation estimates sequence risk by reordering or bootstrapping simulated trades with a reproducible seed.

It does not call MT5, does not create orders, and does not enable demo/live execution.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Command

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode monte-carlo --trades data\reports\backtests\trades.csv --report-dir data\reports\monte_carlo --simulations 2000 --seed 42
```

## Metrics

The report includes:

- Final equity percentiles.
- Max drawdown percentiles.
- Longest losing streak distribution.
- `probability_of_ruin`.
- 5th percentile return.
- 95th percentile drawdown.

## Reports

Files:

- `data/reports/monte_carlo/summary.json`
- `data/reports/monte_carlo/simulations.csv`

## Interpretation

Low average drawdown is not enough. A strategy can have a positive backtest and still fail if random trade ordering creates unacceptable drawdowns or risk of ruin. If risk of ruin is excessive, the strategy must remain `REJECTED` or `WATCHLIST`.

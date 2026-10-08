# Monte Carlo Validation

Monte Carlo estimates fixed-PnL sequence risk by reordering or bootstrapping closed trade profits with a reproducible seed. Evidence version 2.0 uses an integer trade index and an explicit initial-capital baseline; it does not invent historical timestamps or recompute fills.

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
- `probability_of_ruin`, retained as a percent-valued compatibility field: the event is maximum peak drawdown reaching the configured threshold, not insolvency.
- 5th percentile return.
- 95th percentile drawdown.

## Reports

Files:

- `data/reports/monte_carlo/summary.json`
- `data/reports/monte_carlo/simulations.csv`
- `data/reports/monte_carlo/inputs.json`

Summary includes effective balance, threshold, sampling method, seed, runtime versions and a `RunManifest` with input/configuration/source hashes and commit. A hash does not authenticate upstream strategy or broker evidence. Missing upstream provenance stays `UNKNOWN`.

## Interpretation

Low average drawdown is not enough. A positive backtest can produce unacceptable sequence drawdowns. IID bootstrap assumes independent trade draws; neither it nor permutation models changed sizing, serial market dependence or execution. Legacy classifications are observational diagnostics only, and all reports explicitly disable promotion. See [the evidence contract](decisions/2026-10-05-sequence-and-post-trade-evidence.md) and [verification](testing/monte-carlo-stress-evidence.md).

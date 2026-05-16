# Correlation Guard

Correlation Guard prevents the bot from treating highly related Forex pairs as independent opportunities.

It is read-only and shadow-only. It never calls `order_send`.

## Calculation

The current implementation reads historical CSV closes and computes rolling return correlation for files like:

- `EURUSD_M5.csv`
- `GBPUSD_M5.csv`
- `USDJPY_M5.csv`

Default window: `300` bars.

Signals are blocked or reduced when absolute correlation is above `0.85` with active exposure.

If correlation is required but unavailable, the system should classify the candidate as `WATCHLIST` or reject fail-closed rather than assuming independence.

## Report Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode correlation-report --data-dir data\historical --output-dir data\reports\portfolio
```

The report writes:

- `correlation_matrix.csv`
- `correlation_clusters.csv`

## Safety

`CORRELATION_REJECTED` is an audit event only. It does not enable or authorize demo execution.


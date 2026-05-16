# Data Pipeline

Fase 6 adds a real historical-data quality pipeline for MT5-exported CSV files. This is research-only and does not enable demo or live execution.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Export Data From MT5

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode export-history --symbols EURUSD,GBPUSD,USDJPY --timeframes M5,M15,H1 --bars 50000 --output-dir data\historical
```

Expected CSV columns:

```text
time,open,high,low,close,tick_volume,spread
```

## Validate Data Quality

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode data-quality --data-dir data\historical --report-dir data\reports\data_quality
```

Checks:

- Required columns.
- UTC timestamp parsing.
- Timestamp sorting.
- Duplicate timestamps.
- Gaps by timeframe.
- Invalid OHLC candles.
- Non-positive prices.
- Extreme spreads.
- Dataset fingerprint.

Reports:

- `data/reports/data_quality/summary.json`
- `data/reports/data_quality/by_symbol_timeframe.csv`
- `data/reports/data_quality/gaps.csv`
- `data/reports/data_quality/anomalies.csv`
- `data/reports/data_quality/dataset_manifest.json`

If data is missing, corrupt, sparse, or unrealistic, downstream validation must remain `WATCHLIST`, `NEEDS_MORE_DATA`, or `REJECTED`.

## Broker Cost Profile

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode build-cost-profile --data-dir data\historical --report-dir data\reports\broker_costs
```

The profile includes average, median, p95 and p99 spread by symbol plus spread by session, hour UTC, and day. Future realized slippage fields are present but remain empty until real execution data exists.

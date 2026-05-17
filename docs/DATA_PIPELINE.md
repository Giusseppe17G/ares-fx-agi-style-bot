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
time,timestamp_utc,open,high,low,close,tick_volume,spread
```

`timestamp_utc` is preferred, but Phase 18D can normalize any of these timestamp inputs: `timestamp_utc`, `timestamp`, `datetime`, `date`, or `time`. MT5 exports may contain only `time`; that is valid when it can be parsed as UTC.

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

## Historical Data Audit

Phase 18C adds explicit historical file resolution before threshold tuning. Run:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode historical-data-audit --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\runs\<RUN_ID>\historical --report-dir data\runs\<RUN_ID>\reports\data_audit
```

The resolver accepts these layouts:

- `EURUSD_M5.csv`
- `EURUSD-M5.csv`
- `EURUSD_M5_rates.csv`
- `EURUSD__M5.csv`
- `M5\EURUSD.csv`
- `EURUSD\M5.csv`

Audit reports:

- `historical_data_audit.json`
- `historical_data_audit.csv`
- `missing_data.csv`
- `feature_availability.json`
- `feature_availability.csv`
- `report.html`

Timestamp audit:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode timestamp-audit --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\runs\<RUN_ID>\historical --report-dir data\runs\<RUN_ID>\reports\timestamp_audit
```

This writes `timestamp_audit.json`, `timestamp_audit.csv`, and `report.html`.

Specific data blockers include `MISSING_M5_FILE`, `MISSING_M15_FILE`, `MISSING_H1_FILE`, `MISSING_REQUIRED_COLUMNS`, `INSUFFICIENT_M5_BARS`, `INSUFFICIENT_M15_BARS`, `INSUFFICIENT_H1_BARS`, `EMPTY_CSV`, `CSV_PARSE_ERROR`, and `TIMEFRAME_PATH_NOT_FOUND`.

Full validation keeps the original recommended minimums: M5 50000 bars, M15 30000 bars, H1 10000 bars. Calibration uses diagnostic minimums: M5 1000, M15 500, H1 200. If H1 is below full-validation requirements but above diagnostic minimum, calibration can continue and reports `DATA_PARTIAL_BUT_USABLE_FOR_CALIBRATION`.

If `TIMESTAMP_PARSE_ERROR` appears, re-export history or repair the timestamp column before running strategy diagnostics. If H1 has a few hundred bars, calibration can continue, but full validation still needs more H1 history.

## Broker Cost Profile

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode build-cost-profile --data-dir data\historical --report-dir data\reports\broker_costs
```

The profile includes average, median, p95 and p99 spread by symbol plus spread by session, hour UTC, and day. Future realized slippage fields are present but remain empty until real execution data exists.

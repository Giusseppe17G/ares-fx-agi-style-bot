# Live Feature Pipeline

Phase 30 repairs the forward-shadow runtime feature path. MT5 live bars now pass through the same OHLCV contract used by historical CSV research before indicators, market structure, regime detection or strategies see the data.

## Canonical Contract

Every live and historical feature frame must include:

- `timestamp_utc`
- `time`
- `open`
- `high`
- `low`
- `close`
- `tick_volume`
- `spread`
- `real_volume`

`open`, `high`, `low`, `close`, `tick_volume`, `spread` and `real_volume` are numeric. `timestamp_utc` is datetime-like UTC, rows are sorted ascending, duplicate timestamps are removed and reported, and `real_volume=0` is used when MT5 does not provide it.

## Runtime Bars

Forward live diagnostics use research-safe minimums:

- M5: 200 bars
- M15: 200 bars
- H1: 100 bars

The live MT5 reader asks for larger configurable windows so feature builders have enough context without pulling full research history:

- `LIVE_M5_BARS=1000`
- `LIVE_M15_BARS=1000`
- `LIVE_H1_BARS=500`

## CLI Audit

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode live-feature-contract --symbols EURUSD,GBPUSD,USDJPY --output-dir data\reports\forward_diagnostics
```

Reports:

- `live_feature_contract_summary.json`
- `live_feature_contract_by_symbol.csv`

`forward-signal-diagnose` also writes `feature_build_errors.csv` and `feature_sample_<SYMBOL>.csv`.

## Error Classes

Phase 30 replaces generic `FEATURE_BUILD_FAILED` diagnostics with specific blockers when possible:

- `LIVE_SCHEMA_MISMATCH`
- `LIVE_TIMESTAMP_NOT_DATETIME`
- `LIVE_MISSING_REQUIRED_COLUMNS`
- `LIVE_INSUFFICIENT_ROWS_FOR_FEATURES`
- `LIVE_NUMERIC_CAST_FAILED`
- `LIVE_DUPLICATE_TIMESTAMPS`
- `LIVE_RATES_EMPTY`
- `FEATURE_ENGINE_EXCEPTION`

Do not relax thresholds while these errors are present. Fix the data contract first, then rerun `forward-signal-diagnose`.

## Safety

This feature path remains read-only and paper/shadow only. It does not call `order_send`, does not call `order_check`, does not enable demo/live execution, and all summaries keep `execution_attempted=false`.

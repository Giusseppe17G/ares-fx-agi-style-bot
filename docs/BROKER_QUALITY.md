# Broker Quality

Broker Quality is a read-only audit of the MT5 broker/server environment.

It does not enable demo execution, live execution, `order_check`, or `order_send`.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## What It Measures

Per symbol:

- canonical and broker symbol mapping
- visibility and trade mode metadata
- bid, ask, spread points
- point, digits, tick value, tick size and contract size
- volume min, max and step
- stops level and freeze level
- filling mode metadata
- tick UTC time and tick age
- market probably closed flag
- M5, M15 and H1 rates availability
- read latency for tick and rates
- readiness score and reasons

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode broker-quality --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --log-dir data\logs\broker-quality --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\broker_quality
```

## Reports

- `data/reports/broker_quality/summary.json`
- `data/reports/broker_quality/by_symbol.csv`
- `data/reports/broker_quality/spread_by_session.csv`
- `data/reports/broker_quality/tick_freshness.csv`
- `data/reports/broker_quality/latency.csv`
- `data/reports/broker_quality/readiness_score.csv`
- `data/reports/broker_quality/report.html`

## Interpretation

`EXECUTION_READY_SHADOW_ONLY` means the symbol appears suitable for continued shadow observation. It does not authorize demo execution.

`WATCHLIST` means the broker environment is incomplete or borderline.

`NOT_READY` means the symbol must not move toward execution planning.


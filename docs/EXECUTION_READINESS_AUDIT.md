# Execution Readiness Audit

Execution Readiness consolidates broker-quality evidence before any future demo execution discussion.

This phase is read-only:

- no `order_send`
- no `order_check`
- no demo orders
- no live orders
- `execution_attempted=false`

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode readiness-report --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\readiness
```

## Reports

- `data/reports/readiness/execution_readiness_report.json`
- `data/reports/readiness/execution_readiness_report.csv`
- `data/reports/readiness/execution_readiness_report.html`

## Decisions

- `CONTINUE_FORWARD_SHADOW`
- `NEEDS_MORE_DATA`
- `NEEDS_BROKER_FIX`
- `NEEDS_STRATEGY_FIX`
- `NOT_READY`

`CONTINUE_FORWARD_SHADOW` is still paper-only. It confirms that observation may continue; it does not approve broker execution.

## Before Future Demo Execution

Review:

- spread p95/p99 versus backtest assumptions
- tick freshness stability
- MT5 read latency
- stops and freeze levels
- filling mode metadata
- volume constraints
- forward drift
- Strategy Promotion Gate
- Telegram/SQLite/JSONL stability


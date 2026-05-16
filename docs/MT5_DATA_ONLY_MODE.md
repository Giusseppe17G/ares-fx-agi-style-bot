# MT5 Data-Only Mode

`mt5-data` mode connects to MetaTrader 5 only to read market/account data and drive the existing shadow pipeline. It never sends broker orders.

## What It Does

- Initializes the MetaTrader5 Python adapter.
- Reads `account_info`.
- Reads `symbol_info` and `symbol_info_tick`.
- Reads bars for `M5`, `M15`, and `H1` with `copy_rates_from_pos`.
- Validates symbol properties, tick freshness, and market data quality.
- Computes indicators, features, and regime labels.
- Runs the strategy ensemble in shadow mode.
- Runs the RiskEngine.
- Creates a `ShadowOrder` only after accepted risk.
- Persists audit events to JSONL and SQLite.
- Optionally sends Telegram notifications through the fail-safe notifier.

## What It Does Not Do

- It does not call `order_send`.
- It does not call `order_check`.
- It does not place demo orders.
- It does not place live orders.
- It does not treat `--mode demo` as permission to execute.
- It does not store credentials or Telegram secrets.

## Command

PowerShell:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode mt5-data --log-dir data\logs\mt5-data-smoke --sqlite data\sqlite\mt5-data-smoke.sqlite3
```

Optional symbols:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode mt5-data --symbols EURUSD,GBPUSD --bars 300 --log-dir data\logs\mt5-data-smoke --sqlite data\sqlite\mt5-data-smoke.sqlite3
```

Optional Telegram:

```powershell
$env:TELEGRAM_BOT_TOKEN="..."
$env:TELEGRAM_CHAT_ID="..."
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode mt5-data --telegram --log-dir data\logs\mt5-data-smoke --sqlite data\sqlite\mt5-data-smoke.sqlite3
```

## Expected Summary

The final JSON always includes:

```json
{
  "mode": "mt5-data",
  "mt5_connected": true,
  "symbols_seen": 1,
  "symbols_rejected": 0,
  "signals_detected": 1,
  "signals_rejected": 0,
  "risk_rejected": 0,
  "shadow_orders_created": 1,
  "execution_attempted": false
}
```

If MT5 is unavailable, the mode fails closed with `mt5_connected=false` and `execution_attempted=false`.

## Verifying No `order_send`

- Review CLI output: `execution_attempted` must be `false`.
- Search JSONL for `SHADOW_ORDER_CREATED`; this is a simulated order.
- There should be no `ORDER_SENT` event from `mt5-data`.
- Tests use an MT5 mock that raises if `order_send` is called.

## Reviewing SQLite

Open the configured SQLite file and inspect:

- `events`: lifecycle, MT5, strategy, risk, Telegram, and shadow events.
- `orders`: shadow orders only, with `mode=shadow` and `status=created`.
- `telegram_outbox`: durable Telegram attempts when Telegram is configured.

## Reviewing JSONL

JSONL files are written under the provided `--log-dir`, one JSON object per line. Important event types:

- `BOT_STARTED`
- `MT5_CONNECTED`
- `MT5_CONNECTION_FAILED`
- `ACCOUNT_SNAPSHOT`
- `ACCOUNT_REAL_DETECTED_READ_ONLY`
- `SYMBOL_REJECTED`
- `MARKET_DATA_READ`
- `SIGNAL_DETECTED`
- `SIGNAL_REJECTED`
- `RISK_REJECTED`
- `SHADOW_ORDER_CREATED`
- `BOT_STOPPED`
- `CRITICAL_ERROR`
- `TELEGRAM_ERROR`

## Risks Pending

- Live/demo order execution remains out of scope.
- Broker fill quality is not proven by shadow orders.
- MQL5/Python JSON adapter tests still need to be added before any MT5-side EA integration.
- Real-account detection in `mt5-data` is read-only and stops before symbols, but users should still prefer demo terminals.

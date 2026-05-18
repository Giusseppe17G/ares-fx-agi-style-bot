# MT5 Data-Only Mode

`mt5-data` mode connects to MetaTrader 5 only to read market/account data and drive the existing shadow pipeline. It never sends broker orders.

## What It Does

- Initializes the MetaTrader5 Python adapter.
- Reads `account_info`.
- Reads `symbol_info` and `symbol_info_tick`.
- Resolves canonical symbols such as `EURUSD` to broker symbols such as `EURUSDm`, `EURUSD.r`, `EURUSD.raw`, `EURUSDpro`, or `EURUSD.` when exposed by `symbols_get()`.
- Reads bars for `M5`, `M15`, and `H1` with `copy_rates_from_pos`, then falls back to `copy_rates_range` when the first read is empty.
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
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode mt5-data --symbols EURUSD,GBPUSD,USDJPY --bars 300 --log-dir data\logs\mt5-data-smoke --sqlite data\sqlite\mt5-data-smoke.sqlite3
```

Default symbols are:

```text
EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF, AUDUSD, EURJPY, NZDUSD
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

## MT5 Diagnose Mode

Use `mt5-diagnose` when a symbol is rejected before signals, especially with `reject_reason="tick is stale"`:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --log-dir data\logs\mt5-diagnose --sqlite data\sqlite\mt5-diagnose.sqlite3
```

This mode connects to MT5, reads account/symbol/tick data, audits `MT5_DIAGNOSTIC`, and prints per-symbol diagnostics. It does not generate signals, does not create shadow orders, does not call `order_check`, and does not call `order_send`.

Each diagnostic includes:

- `canonical_symbol` and `broker_symbol`.
- `bid`, `ask`, and `spread_points`.
- Raw `tick.time` and `tick.time_msc`.
- UTC interpretations: `tick_time_utc`, `tick_time_msc_utc`, and `now_utc`.
- `tick_age_seconds`, `tick_age_seconds_from_time`, and `tick_age_seconds_from_time_msc`.
- `mt5.last_error()`.
- `market_is_probably_closed`.
- `status`, `reject_code`, and `reject_reason`.

## Diagnosing `tick is stale`

`tick_age_seconds` is the difference between `now_utc` and the selected MT5 tick timestamp. The bot prefers `tick.time_msc` when it is present and valid, because it avoids precision loss and reduces false stale readings. It uses `tick.time` only as a fallback.

When a stale tick happens:

- Check that MT5 is connected and logged into the demo account.
- Open Market Watch and make sure the broker symbol is visible.
- Confirm the symbol name: some brokers expose `EURUSDm`, `EURUSD.r`, `EURUSD.raw`, `EURUSDpro`, or `EURUSD.`.
- Check whether Forex is closed. Weekend closure is normally Friday late UTC through Sunday before the open.
- Compare `tick_age_seconds_from_time` vs `tick_age_seconds_from_time_msc`. If only one is stale, it may be a timestamp-source issue.
- Verify `execution_attempted=false` in the CLI summary and JSONL.

If the market is probably closed or the symbol has no fresh ticks, the bot rejects with:

```json
{
  "reject_code": "MARKET_CLOSED_OR_NO_TICKS",
  "reject_reason": "market appears closed or symbol has no fresh ticks"
}
```

That is not a critical bot error; it is a safe read-only rejection.

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
# Phase 28 Timestamp Normalization

`mt5-data` and `mt5-diagnose` now normalize MT5 broker/server tick timestamps before freshness checks. This protects local Windows and AWS EC2 deployments from rejecting valid ticks when a broker reports server time such as UTC+2 or UTC+3.

The diagnostic payload includes raw and normalized timestamps, detected offset, host clock audit fields, and `tick_time_status`. The local OS timezone is not used for trading decisions.

Read-only safety remains unchanged: `execution_attempted=false`, `order_send` is not called, and `order_check` is not called.

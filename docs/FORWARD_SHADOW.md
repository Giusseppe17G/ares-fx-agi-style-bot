# Forward Shadow Mode

`forward-shadow` is the 24/7 observation mode for real market data and paper trade lifecycle management.

It reads MT5 data, updates paper trades, writes SQLite/JSONL audit records, sends optional Telegram notifications, and exports forward reports. It does not send broker orders.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## What It Does

- Connects to MetaTrader 5 in read-only mode.
- Validates symbol snapshots through the MT5 adapter.
- Loads open paper trades from SQLite at startup.
- Updates open paper trades each cycle.
- Simulates SL, TP, break-even, trailing, and optional time-stop exits.
- Records paper events in `paper_trade_events`.
- Writes summary reports under `data/reports/forward_shadow`.
- Keeps Telegram optional and fail-safe.

## What It Does Not Do

- It does not call `order_send`.
- It does not place demo orders.
- It does not place live orders.
- It does not approve strategy promotion by itself.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --log-dir data\logs\forward-shadow --sqlite data\sqlite\forward-shadow.sqlite3 --cycle-seconds 30
```

Smoke test:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD --log-dir data\logs\forward-shadow-smoke --sqlite data\sqlite\forward-shadow-smoke.sqlite3 --cycle-seconds 0 --max-cycles 1
```

Example cycle summary:

```json
{
  "mode": "forward-shadow",
  "mt5_connected": true,
  "cycles_completed": 1,
  "open_trades": 0,
  "paper_trades_opened": 0,
  "paper_trades_closed": 0,
  "heartbeat_written": true,
  "alerts_emitted": 0,
  "telegram_commands_processed": 0,
  "shadow_paused": false,
  "execution_attempted": false
}
```

## Observability

Each cycle now writes a persistent heartbeat, evaluates operational alert rules, respects `shadow_paused`, and can process safe Telegram commands when Telegram is enabled.

Use:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode status --sqlite data\sqlite\forward-shadow.sqlite3
py -m agi_style_forex_bot_mt5.cli --mode health --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow
py -m agi_style_forex_bot_mt5.cli --mode daily-summary --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\forward_shadow\daily
```

## Reports

The forward report writer creates:

- `summary.json`
- `trades.csv`
- `equity_curve.csv`
- `by_symbol.csv`
- `by_strategy.csv`
- `by_regime.csv`
- `by_session.csv`
- `rejections.csv`
- `report.html`

## Verification

Check JSONL and SQLite:

```powershell
Get-ChildItem data\logs\forward-shadow -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 20
```

Confirm:

- no `ORDER_SENT`
- no `order_send`
- `execution_attempted=false`
- paper lifecycle events only

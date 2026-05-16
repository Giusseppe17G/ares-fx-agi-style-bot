# Observability

The observability layer supports 24/7 `forward-shadow` operations without enabling broker execution.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Signals Collected

- Bot uptime proxy and last heartbeat.
- `mt5_connected`.
- Symbols seen and rejected.
- Signal detections and rejection reasons.
- Open and closed paper trades.
- Paper winrate, expectancy R, profit factor and drawdown.
- Recent critical errors.
- SQLite status.
- JSONL status.
- Telegram command status.

## Heartbeat

Each `forward-shadow` cycle writes a `HEARTBEAT` event and a SQLite row in `heartbeats`.

Heartbeat fields include:

- `timestamp_utc`
- `mode`
- `mt5_connected`
- `symbols_seen`
- `symbols_rejected`
- `open_paper_trades`
- `closed_paper_trades_today`
- `last_error`
- `shadow_paused`
- `execution_attempted=false`

Example:

```json
{
  "mode": "forward-shadow",
  "mt5_connected": true,
  "symbols_seen": 8,
  "symbols_rejected": 0,
  "open_paper_trades": 2,
  "closed_paper_trades_today": 1,
  "shadow_paused": false,
  "execution_attempted": false
}
```

## Alerts

Alert rows are stored in `alerts` and deduplicated by alert code.

Implemented rules include:

- `MT5_DISCONNECTED`
- `ALL_SYMBOLS_REJECTED`
- `PAPER_DAILY_DRAWDOWN`
- `PERFORMANCE_DRIFT`
- `SQLITE_UNAVAILABLE`
- `JSONL_UNAVAILABLE`

Every alert includes severity, code, message, recommended action and `execution_attempted=false`.

## CLI

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode status --sqlite data\sqlite\forward-shadow.sqlite3

$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode health --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow

$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode daily-summary --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\forward_shadow\daily
```


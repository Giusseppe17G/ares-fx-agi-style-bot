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
- ML prediction status.
- ML approvals/rejections and average probability.
- Portfolio risk percentage and available risk budget.
- Currency exposure and concentration flags.

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
- `CURRENCY_EXPOSURE_HIGH`
- `CORRELATION_CLUSTER_HIGH`
- `PORTFOLIO_RISK_BUDGET_LOW`
- `DYNAMIC_RISK_REDUCED`
- `STRATEGY_CONCENTRATION_HIGH`
- `REGIME_CONCENTRATION_HIGH`

Every alert includes severity, code, message, recommended action and `execution_attempted=false`.

## ML Metrics

Status and daily summaries include:

- `ml_predictions_today`
- `ml_rejected_signals_today`
- `ml_approved_signals_today`
- `avg_probability_today`
- `model_id`
- `model_status`

## Portfolio Metrics

Status, heartbeat context, and daily summaries can include:

- `portfolio_risk_pct`
- `available_risk_budget_pct`
- `currency_exposure`
- `concentration_flags`

These metrics are advisory for shadow/paper mode only and never authorize broker execution.

## CLI

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode status --sqlite data\sqlite\forward-shadow.sqlite3

$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode health --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow

$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode daily-summary --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\forward_shadow\daily
```

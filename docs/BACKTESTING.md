# Backtesting

Phase 4 adds research-only backtesting for `AGI_STYLE_FOREX_BOT_MT5`. It does not enable demo or live order execution.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

Good backtest results do not guarantee future profitability. They are only evidence for whether a symbol/strategy deserves longer shadow observation.

## Historical CSV Format

Place local CSV files under `data/historical`.

Minimum columns:

```text
time,open,high,low,close,tick_volume
```

Optional:

```text
spread
```

Recommended filenames:

```text
EURUSD_M5.csv
GBPUSD_M5.csv
USDJPY_M5.csv
```

The loader validates required columns, empty files, timestamp ordering, duplicates, large gaps, and corrupt OHLC values. Data quality and fingerprints are written into `summary.json`.

## Export History From MT5

This mode uses MT5 read-only APIs and writes CSV files. It does not generate signals, create shadow orders, call `order_check`, or call `order_send`.

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode export-history --symbols EURUSD,GBPUSD,USDJPY --timeframes M5,M15,H1 --bars 50000 --output-dir data\historical --log-dir data\logs\export-history
```

If SQLite auditing is desired:

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode export-history --symbols EURUSD,GBPUSD,USDJPY --timeframes M5,M15,H1 --bars 50000 --output-dir data\historical --log-dir data\logs\export-history --sqlite data\sqlite\export-history.sqlite3
```

## Run A Single-Symbol Backtest

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode backtest --symbol EURUSD --data-dir data\historical --report-dir data\reports\backtests
```

## Run A Multi-Symbol Backtest

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode backtest --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\backtests
```

Cost knobs:

```powershell
--spread-points 10 --slippage-points 1 --commission 0
```

The simulator applies spread, slippage, commission, SL/TP, break-even from `0.6R`, trailing from `0.8R`, and an optional time stop through backtest settings.

## Reports

Files written under `data/reports/backtests`:

- `summary.json`
- `summary.csv`
- `trades.csv`
- `equity_curve.csv`
- `by_symbol.csv`
- `by_regime.csv`
- `by_session.csv`
- `by_weekday.csv`
- `by_hour_utc.csv`
- `report.html`

These report symbols, sessions, regimes, weekdays, UTC hours, data quality, reproducibility metadata, and Strategy Promotion Gate status.

## Key Metrics

Read these first:

- `total_trades`
- `net_return_pct`
- `profit_factor`
- `max_drawdown_pct`
- `winrate`
- `expectancy_r`
- `sharpe`
- `sortino`

Then inspect:

- `trades.csv` for MAE/MFE, duration, SL/TP exits, break-even/trailing outcomes.
- `by_symbol.csv` for symbol concentration.
- `by_regime.csv` for whether edge exists only in one market condition.
- `by_session.csv`, `by_weekday.csv`, and `by_hour_utc.csv` for time concentration.

## Promotion Gate

Backtest output labels each symbol:

- `APPROVED_FOR_SHADOW_OBSERVATION`
- `WATCHLIST`
- `REJECTED`

See `docs/STRATEGY_PROMOTION_GATE.md` for the full policy. Approval is not permission to trade. It only means the strategy/symbol can be considered for prolonged shadow/demo observation.

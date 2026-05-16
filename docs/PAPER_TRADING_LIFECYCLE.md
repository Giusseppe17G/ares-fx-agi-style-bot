# Paper Trading Lifecycle

Paper trading is the simulated trade lifecycle used before any demo execution is considered.

It persists every paper trade in SQLite and records lifecycle events so forward performance can be audited independently from MT5 execution.

## PaperTrade Fields

Required fields include:

- `paper_trade_id`
- `signal_id`
- `idempotency_key`
- `symbol`
- `broker_symbol`
- `direction`
- `entry_time_utc`
- `entry_price`
- `sl_price`
- `tp_price`
- `lot`
- `risk_pct`
- `risk_amount`
- `strategy_name`
- `strategy_version`
- `regime`
- `session`
- `score`
- `reasons`
- `status`

Closure fields:

- `exit_time_utc`
- `exit_price`
- `exit_reason`
- `profit`
- `r_multiple`
- `mae`
- `mfe`
- `spread_at_exit`

## Fill Rules

- BUY market entry uses ask.
- SELL market entry uses bid.
- BUY exit uses bid.
- SELL exit uses ask.
- Slippage and commission are configurable.
- High spread rejects the paper fill.

## Management Rules

- SL and TP are mandatory.
- Break-even is triggered at `0.6R`.
- Trailing starts at `0.8R`.
- Trailing stop must never retreat.
- Time-stop can close stale paper trades when configured.
- Idempotency prevents duplicate paper trades for the same accepted signal.

## SQLite Tables

Forward shadow adds:

- `paper_trades`
- `paper_trade_events`
- `paper_performance_snapshots`
- `forward_shadow_sessions`

If SQLite is unavailable, paper lifecycle must fail closed. A paper trade without durable audit is not acceptable.


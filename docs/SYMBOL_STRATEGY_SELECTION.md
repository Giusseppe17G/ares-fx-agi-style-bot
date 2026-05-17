# Symbol And Strategy Selection

Phase 20 classifies symbols and strategies from existing backtest/research artifacts without rerunning heavy validation.

It remains research-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- no `order_send`
- no `order_check`

## Symbol Decisions

Symbols are classified as:

- `KEEP`: enough trades, positive expectancy, profit factor above 1.10, and no obvious payoff problem.
- `WATCHLIST`: incomplete or marginal evidence.
- `REDUCE`: enough evidence to reduce exposure or priority.
- `REJECT`: clearly negative expectancy, weak profit factor, or excessive drawdown where available.

Initial thresholds:

- `KEEP` requires at least 30 trades, `expectancy_r > 0`, and `profit_factor > 1.10`.
- `WATCHLIST` requires at least 20 trades with expectancy near zero and profit factor between 0.95 and 1.10.
- `REJECT` is used when expectancy is clearly negative or `profit_factor < 0.90`.

If metrics are missing, the selector cannot return `KEEP`.

If only trade counts are available, symbols are marked `WATCHLIST_COUNTS_ONLY`. That means the symbol generated enough simulated opportunities, but there is not enough PnL evidence to keep or reject it.

## Strategy Decisions

Strategies are classified as:

- `KEEP`
- `WATCHLIST`
- `DISABLE_IN_BALANCED`
- `RESEARCH_ONLY`

The selector considers trades, expectancy, profit factor, win rate, blockers, setup quality when present, and accepted/rejected ratio when available.

Strategies currently expected by the report:

- `trend_pullback`
- `mean_reversion`
- `breakout_compression`
- `liquidity_sweep`
- `session_momentum`
- `volatility_expansion`

Unknown strategy names are kept in the report as `UNKNOWN` rather than dropped.

If only counts are available, strategies are marked `WATCHLIST_COUNTS_ONLY` instead of being disabled. Disabling a strategy requires actual performance evidence, not just missing metrics.

## Session And Regime Decisions

Sessions and regimes are grouped from `trades.csv` when those columns exist. Missing columns become `UNKNOWN`.

`ROLLOVER` is blocked by default when results are negative or cost-sensitive. Spread and cost blockers should not be relaxed; they point to broker profile or execution-simulation work instead.

## Config Suggestions

`balanced_filtered.ini` is a research suggestion, not a trading permission file. It may reduce the symbol, strategy, or session set, but it must not change global risk limits.

`research_active.ini` is for diagnostics only and is explicitly `NOT FOR DEMO/LIVE EXECUTION`.

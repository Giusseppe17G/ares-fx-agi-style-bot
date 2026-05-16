# Regime Strategy Selection

The regime selector assigns conservative strategy weights based on market condition.

## Regime Rules

- `TREND_UP`: prioritize Trend Pullback, Session Momentum, Breakout Compression.
- `TREND_DOWN`: prioritize Trend Pullback, Session Momentum, Breakout Compression.
- `RANGE`: prioritize Mean Reversion and Liquidity Sweep.
- `HIGH_VOLATILITY`: reduce exposure; only Volatility Expansion may remain if spread is normal.
- `LOW_VOLATILITY`: wait for compression confirmation or block.
- `MARKET_CLOSED_OR_NO_TICKS`, `SPREAD_DANGER`, `LIQUIDITY_THIN`: block.

The selector returns weights and reasons. These are research inputs, not execution authorization.

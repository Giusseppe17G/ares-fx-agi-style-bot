# Dynamic Risk Allocation

Dynamic risk allocation is defensive. It can reduce or maintain paper risk, but it cannot increase risk above global limits.

Default rule:

- `risk_multiplier <= 1.0`

This remains true while:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`

## Initial Multipliers

- Normal conditions: `1.0`
- Drawdown warning: `0.5`
- Loss streak `>= 3`: `0.25`
- Severe broker degradation: `0.0`
- Borderline ML probability: `0.5`
- High correlation: `0.5`
- Watchlist symbol or candidate: `0.5`

The final multiplier is the most defensive applicable value.

## Audit

Every adjustment is recorded as `DYNAMIC_RISK_ADJUSTED`.

If the multiplier becomes `0.0`, the candidate is rejected as `DYNAMIC_RISK_ZERO` and no paper trade is opened.

## Non-Goals

Dynamic risk does not:

- Enable real trading.
- Enable demo execution.
- Modify `DEMO_ONLY`.
- Modify `LIVE_TRADING_APPROVED`.
- Increase lot size beyond RiskEngine output.


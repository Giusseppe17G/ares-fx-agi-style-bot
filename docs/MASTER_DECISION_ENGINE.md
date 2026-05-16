# Master Decision Engine

The Master Decision Engine consolidates validation evidence into one operational decision.

Final decisions:

- `CONTINUE_FORWARD_SHADOW`
- `NEEDS_MORE_DATA`
- `NEEDS_STRATEGY_RESEARCH`
- `NEEDS_BROKER_FIX`
- `NEEDS_COST_RECALIBRATION`
- `REJECTED`

## Rules

- If data-quality fails or is missing: `NEEDS_MORE_DATA`.
- If broker costs are missing: `NEEDS_MORE_DATA`.
- If backtest has insufficient trades: `NEEDS_STRATEGY_RESEARCH`.
- If walk-forward OOS is negative: `NEEDS_STRATEGY_RESEARCH`.
- If Monte Carlo risk of ruin is high: `REJECTED`.
- If stress collapses: `NEEDS_COST_RECALIBRATION`.
- If benchmarks are not beaten: `NEEDS_STRATEGY_RESEARCH`.
- If broker readiness is not ready: `NEEDS_BROKER_FIX`.
- If paper-vs-backtest is optimistic or costs are too low: `NEEDS_COST_RECALIBRATION`.
- If forward data is still sparse but other checks are acceptable: `CONTINUE_FORWARD_SHADOW`.

No decision authorizes demo or live execution.


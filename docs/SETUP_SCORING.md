# Setup Scoring

Phase 16 adds explainable setup scoring to strategy outputs.

Each strategy can include:

- `component_scores`
- `setup_quality_score`
- `setup_quality`: `A`, `B`, `C`, or `D`
- `blocking_reasons`
- `required_data_missing`
- `regime`
- `session`
- `spread_points`
- `strategy_version`

## Components

- `regime_fit`
- `structure_fit`
- `momentum_fit`
- `volatility_fit`
- `cost_fit`
- `session_fit`
- `liquidity_fit`
- `risk_reward_fit`
- `broker_fit`
- `portfolio_fit`

The score explains why a setup is tradable in shadow, watchlisted, or blocked.

Scoring never changes risk and never enables execution.


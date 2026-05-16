# ML Meta-Filter

The ML Meta-Filter is a shadow-only layer above the strategy ensemble and risk gate.

It is not the primary strategy. It can reject weak paper-trade candidates, but it cannot increase risk, enable demo execution, enable live execution, or call broker order APIs.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Runtime Behavior

The forward-shadow loop asks the ML filter after:

1. strategy signal is directional
2. risk gate accepts the candidate
3. audit is available

If no approved model exists, the decision is:

```json
{"ml_status": "ML_DISABLED", "execution_attempted": false}
```

If probability is below threshold, the signal is rejected for paper trade creation only.

Initial thresholds:

- minimum probability for shadow trade: `0.58`
- high quality threshold: `0.68`
- reject below: `0.55`

## Outputs

- `probability_of_success`
- `expected_r`
- `mae_risk`
- `mfe_potential`
- `setup_quality`
- `ML_DISABLED`, `ML_APPROVED`, `ML_REJECTED`, or `ML_ERROR`

Every prediction is stored in `model_predictions` and audited as `ML_PREDICTION`.


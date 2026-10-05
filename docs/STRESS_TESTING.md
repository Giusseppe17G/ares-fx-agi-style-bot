# Stress Testing

Evidence version 2.0 applies post-trade monetary and concentration approximations to supplied closed trades. It does not rerun a strategy, fills or risk decisions. Operational scenarios requiring explicit quote replay are reported as `NOT_MODELED` with null metrics.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Command

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode stress-test --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\stress
```

## Scenarios

The stress runner evaluates:

- Spread multipliers: `x1.0`, `x1.5`, `x2.0`, `x3.0`.
- Slippage multipliers: `x1.0`, `x1.5`, `x2.0`, `x3.0`.
- Commission multipliers: `x1.0`, `x1.5`, `x2.0`.
- Removal of best `1%`, `5%`, and `10%` of trades.
- Artificial losing streaks.
- Periodic trade omission, without claiming missing-bar or fill-rate behavior.
- Fixed 5% absolute-profit haircut, without claiming delayed entries.

Entry delay, session shift, fill rate and missing bars are explicitly unmodeled. Only `COMPLETED` scenarios count as completed; empty/all-zero evidence cannot fabricate successful checks or loss magnitudes. Synthetic loss streaks append PnL on an integer index, with no historical calendar metrics.

## Reports

Files:

- `data/reports/stress/summary.json`
- `data/reports/stress/scenarios.csv`
- `data/reports/stress/scenarios.json`
- `data/reports/stress/inputs.json`

Summary includes scenario scopes/counts, exact assumptions, input/configuration/source hashes, commit and runtime versions. The inputs reproduce consumed economic fields; arbitrary metadata is excluded. Extra spread is charged once, extra slippage per side and input commission is assumed round trip. R retains its original risk denominator after every monetary penalty.

## Interpretation

The legacy diagnostic classification still uses spread `x2` and removal of the top `5%`, with unchanged cutoffs. It authorizes no promotion or execution. Passing these approximations does not prove operational robustness. See [the evidence contract](decisions/2026-10-05-sequence-and-post-trade-evidence.md) and [verification](testing/monte-carlo-stress-evidence.md).

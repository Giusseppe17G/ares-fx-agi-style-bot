# Execution Simulation

Phase 14 refines paper fills so forward-shadow does not rely on perfect or optimistic execution.

This phase is still read-only/shadow-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send` is not called
- `order_check` is not called

## Why Perfect Fills Are Dangerous

Backtests and paper systems can look better than reality if they assume:

- BUY entries at mid/close instead of ask.
- SELL entries at mid/close instead of bid.
- Exits without bid/ask spread.
- No slippage.
- No commission.
- SL and TP resolution in the best possible intrabar order.
- No gap through stop loss.

Phase 14 makes those assumptions explicit and conservative.

## Models

- `FillModel`: market entry/exit, spread gates, stale tick gates and fill quality.
- `SpreadModel`: current spread, broker cost profile, p95/p99 fallback.
- `SlippageModel`: fixed, spread percentile, volatility/session/readiness penalties and stress multiplier.
- `CommissionModel`: zero, round-turn, per-side and profile-based commission.
- `LatencyModel`: read-only delay assumptions.
- `GapModel`: gap through SL and same-bar SL/TP ambiguity.
- `PartialFillModel`: full fill by default, with structures for low-liquidity rejections.

## Fill Quality

Paper trades now include execution metadata:

- `execution_simulation_version`
- `spread_model_used`
- `slippage_model_used`
- `commission_model_used`
- `latency_assumption`
- `ambiguity_flags`
- `fill_quality`: `GOOD`, `ACCEPTABLE`, `POOR`, or `REJECTED`

## Calibration Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode simulation-calibration --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\execution_simulation
```

Outputs:

- `simulation_calibration.json`
- `fill_quality.csv`
- `spread_slippage_assumptions.csv`
- `ambiguous_events.csv`
- `report.html`


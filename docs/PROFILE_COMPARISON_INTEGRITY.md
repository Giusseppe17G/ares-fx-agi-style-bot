# Profile Comparison Integrity

Phase 22 validates whether profile comparison evidence can be trusted before using BALANCED or ACTIVE conclusions.

This is research-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- no `order_send`
- no `order_check`

## Commands

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode profile-integrity --profile-runs-dir data\reports\profile_runs --output-dir data\reports\profile_validation
```

## What It Checks

Threshold comparison:

- `ensemble_min_score`
- `min_component_score`
- `min_setup_score`
- `cost_fit_min`
- `session_fit_min`
- `structure_fit_min`
- `volatility_fit_min`
- `not_for_demo_live`
- `allowed_for_shadow`
- `profile_hash`

Metric comparison:

- `trades_generated`
- `signals_generated`
- `winrate`
- `expectancy_r`
- `profit_factor`
- `net_profit`
- `max_drawdown_pct`
- blockers when available

## IDENTICAL_METRICS

If ACTIVE and BALANCED have exactly identical metrics, the report returns `IDENTICAL_METRICS`. Possible causes:

- profile thresholds were not applied
- strategies ignore profile thresholds
- ACTIVE profile is effectively the same as BALANCED
- candidate generation is capped identically

Do not use ACTIVE conclusions until this is investigated.

## Outputs

- `profile_integrity.json`
- `profile_threshold_diff.csv`
- `profile_metric_comparison.csv`
- `report.html`

`profile_integrity_status=FAILED` blocks the BALANCED candidate gate.

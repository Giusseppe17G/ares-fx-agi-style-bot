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
py -m agi_style_forex_bot_mt5.cli --mode profile-threshold-audit --output-dir data\reports\profile_validation

py -m agi_style_forex_bot_mt5.cli --mode profile-integrity --profile-runs-dir data\reports\profile_runs --output-dir data\reports\profile_validation
```

Run `profile-threshold-audit` first when ACTIVE and BALANCED look identical. It writes the effective thresholds and `profile_hash` for every canonical profile without running a backtest.

## Effective Thresholds

The canonical research profiles are intentionally different:

| Profile | Ensemble | Setup | Component | Cost | Session | Structure | Volatility | Near miss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CONSERVATIVE | 70 | 72 | 60 | 70 | 60 | 65 | 65 | 5 |
| BALANCED | 60 | 62 | 50 | 55 | 50 | 50 | 50 | 8 |
| ACTIVE | 50 | 52 | 40 | 45 | 40 | 40 | 40 | 12 |
| RESEARCH_ONLY | 40 | 45 | 30 | 35 | 30 | 30 | 30 | 20 |

`ACTIVE` and `RESEARCH_ONLY` are always `not_for_demo_live=true` and research-only for promotion purposes.

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

## Similarity States

The integrity report separates threshold bugs from strategy sensitivity:

- `IDENTICAL_THRESHOLDS`: profile hashes are the same. Treat as a config/application bug and fail integrity.
- `DIFFERENT_THRESHOLDS_IDENTICAL_METRICS`: hashes differ, but metrics are identical. Integrity is a warning; inspect whether strategies are insensitive to thresholds on this dataset.
- `IDENTICAL_METRICS_WITH_DIFFERENT_SIGNAL_COUNTS`: counts differ but aggregate metrics match. Inspect report aggregation.
- `DIFFERENT_THRESHOLDS_DIFFERENT_METRICS`: comparison is behaving as expected.

Do not use ACTIVE conclusions for operational decisions while integrity is `FAILED`. A `WARNING` means BALANCED can still be evaluated, but the next step is sensitivity/robustness validation.

## Outputs

- `profile_integrity.json`
- `profile_threshold_audit.json`
- `profile_threshold_audit.csv`
- `profile_threshold_diff.csv`
- `profile_metric_comparison.csv`
- `report.html`

`profile_integrity_status=FAILED` blocks the BALANCED candidate gate.

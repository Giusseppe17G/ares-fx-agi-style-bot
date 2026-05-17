# Signal Frequency Calibration

Phase 18 diagnoses why a real-data research run produced too few or zero trades. Zero trades does not automatically mean the whole strategy stack is wrong; it usually means one or more context filters, setup thresholds, cost gates, or ensemble thresholds are too strict for the exported sample.

This phase is research-only. It does not enable demo/live execution and never calls `order_send` or `order_check`.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`

## Profiles

`SIGNAL_PROFILE` can be:

- `CONSERVATIVE`: current/high-quality low-frequency behavior.
- `BALANCED`: moderate thresholds for enough backtest samples.
- `ACTIVE`: more signals for research and shadow diagnostics only.
- `RESEARCH_ONLY`: near-miss diagnostics and threshold discovery only.

`ACTIVE` and `RESEARCH_ONLY` are marked `NOT FOR DEMO/LIVE EXECUTION` in generated config suggestions.

## Commands

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode signal-calibration --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\calibration

py -m agi_style_forex_bot_mt5.cli --mode blocking-reasons --reports-root data\reports --output-dir data\reports\calibration
```

## Reports

- `summary.json`
- `signal_frequency.csv`
- `blocking_reasons.csv`
- `by_symbol.csv`
- `by_strategy.csv`
- `by_regime.csv`
- `by_session.csv`
- `config_suggestions/conservative.ini`
- `config_suggestions/balanced.ini`
- `config_suggestions/active.ini`
- `config_suggestions/research_only.ini`

## Interpretation

Look first at:

- `top_blocking_reasons`
- near misses
- weak component scores
- symbols/sessions/regimes with zero accepted candidates

If `zero_trade_detected=true` and data quality is OK, run threshold sweep next. Do not bypass spread, stale tick, market-closed, broker readiness, risk, ML, or portfolio guards.

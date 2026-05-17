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

py -m agi_style_forex_bot_mt5.cli --mode signal-calibration --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --runs-root data\runs --data-dir data\historical --report-dir data\reports\calibration

py -m agi_style_forex_bot_mt5.cli --mode blocking-reasons --reports-root data\reports --output-dir data\reports\calibration
```

If `data\historical` is empty, calibration can use `--runs-root data\runs` to auto-detect the newest `data\runs\<run_id>\historical` folder from a real-data research run.

## Reports

- `summary.json`
- `signal_frequency.csv`
- `near_misses.csv`
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

## Phase 18B Diagnostics

`blocked_candidates > 0` with an empty `top_blocking_reasons` is a bug because operators cannot tell which filter dominated. Calibration now emits canonical blocker codes even when strategies return `NONE`:

- `DATA_MISSING`
- `REGIME_MISMATCH`
- `SESSION_BLOCK`
- `SPREAD_BLOCK`
- `STRUCTURE_BLOCK`
- `VOLATILITY_BLOCK`
- `ENSEMBLE_SCORE_LOW`
- `UNKNOWN_BLOCKER`

If all profiles still generate zero signals, the recommended profile becomes `RESEARCH_ONLY` and the classification becomes `NEEDS_STRATEGY_RESEARCH`. `RESEARCH_ONLY` is diagnostic only and remains marked `NOT FOR DEMO/LIVE EXECUTION`.

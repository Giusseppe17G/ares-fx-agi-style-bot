# Threshold Sweep

Threshold sweep evaluates controlled setup-score and component-score combinations to find where the system begins producing enough research candidates.

It is not profit optimization and it does not authorize demo/live execution.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode threshold-sweep --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\calibration --profiles CONSERVATIVE,BALANCED,ACTIVE,RESEARCH_ONLY

py -m agi_style_forex_bot_mt5.cli --mode threshold-sweep --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --runs-root data\runs --data-dir data\historical --report-dir data\reports\calibration --profiles CONSERVATIVE,BALANCED,ACTIVE,RESEARCH_ONLY
```

When `data\historical` is empty, `--runs-root data\runs` lets the CLI use the newest `data\runs\<run_id>\historical` folder.

## Swept Values

- `min_setup_score`: 50, 55, 60, 65, 70, 75
- `min_component_score`: 40, 50, 60
- `cost_fit_min`: 40, 50, 60, 70
- `structure_fit_min`: 40, 50, 60, 70
- `volatility_fit_min`: 40, 50, 60, 70
- `session_fit_min`: 40, 50, 60, 70
- `ensemble_min_score`: 50, 55, 60, 65, 70

## Outputs

- `threshold_sweep_summary.json`
- `threshold_sweep.csv`
- `blocking_reasons.csv`
- `near_misses.csv`
- `by_symbol.csv`
- `by_strategy.csv`
- `by_regime.csv`
- `by_session.csv`
- `config_suggestions/*.ini`

The summary always includes `candidates_evaluated`, `accepted_candidates`, `blocked_candidates`, `near_misses`, `signals_found`, `top_blocking_reasons`, `best_profile_by_frequency`, `best_profile_by_quality_proxy`, and `recommended_profile`.

If every profile generates zero signals, the output is:

- `classification=NEEDS_STRATEGY_RESEARCH`
- `recommended_profile=RESEARCH_ONLY`
- `likely_next_step=Relax diagnostic thresholds or inspect data/feature generation`

`RESEARCH_ONLY` helps inspect near-misses and dominant filters; it is not a profile for demo/live execution.

## Guardrails

Sweep suggestions never bypass:

- max spread
- stale tick rejection
- market closed rejection
- broker `NOT_READY`
- risk gate
- ML rejection outside research-only diagnostics
- portfolio guard outside diagnostics

`ACTIVE` and `RESEARCH_ONLY` configs are explicitly marked `NOT FOR DEMO/LIVE EXECUTION`.

## Data Blockers

Phase 18C distinguishes missing data from real strategy filters. If `top_blocking_reasons` shows `MISSING_M5_FILE`, `MISSING_REQUIRED_COLUMNS`, `EMPTY_CSV`, or `CSV_PARSE_ERROR`, fix historical data before changing thresholds.

If H1 is insufficient for full validation but still above the calibration diagnostic minimum, threshold sweep can continue and the run summary will describe the dataset as partial but usable for calibration. That does not make it valid for full validation.

If threshold sweep still returns zero signals after timestamp and feature availability are `OK`, the blocker is strategy context rather than data plumbing. The next step is to test a balanced profile against backtest/research, not to bypass safety gates.

Phase 18E adds diagnostic candidates even when the final action is `NONE`. Every blocked candidate must include `symbol`, strategy/ensemble name, score, threshold, component scores when available, regime/session context, near-miss status, and non-empty blockers. `CSV_PARSE_ERROR` should not appear when `strategy-data-contract` is `OK`.

## Phase 19B Quick Profile Comparison

After a profile begins producing trades, compare profiles without running the full stack every time:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode profile-comparison-run --symbols EURUSD,GBPUSD,USDJPY --data-dir data\runs\<RUN_ID>\historical --output-dir data\reports\profile_runs --compare-profiles CONSERVATIVE,BALANCED,ACTIVE
```

The report compares `signals_generated`, `trades_generated`, sample status, and blockers by profile. `ACTIVE` remains `NOT FOR DEMO/LIVE EXECUTION`.

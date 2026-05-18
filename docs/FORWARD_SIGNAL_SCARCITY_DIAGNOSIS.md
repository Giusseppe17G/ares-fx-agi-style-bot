# Forward Signal Scarcity Diagnosis

Phase 29 adds a read-only diagnostic path for BALANCED_STABLE forward-shadow when MT5 is connected but no forward signals appear.

Zero forward signals can mean either:

- the market simply has not produced a valid setup yet.
- runtime MT5 bars are missing or insufficient.
- feature generation is failing on live candles.
- BALANCED_STABLE filters block the current session/regime/symbol.
- spread/cost conditions differ from backtest.
- thresholds are too selective for current conditions.

The diagnostic mode does not relax thresholds and does not open paper trades.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode forward-signal-diagnose --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE --profile-config data\reports\stability_repair\balanced_stable.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\forward_diagnostics
```

## Reports

The command writes:

- `data/reports/forward_diagnostics/signal_scarcity_summary.json`
- `data/reports/forward_diagnostics/live_data_quality.csv`
- `data/reports/forward_diagnostics/live_feature_contract_summary.json`
- `data/reports/forward_diagnostics/live_feature_contract_by_symbol.csv`
- `data/reports/forward_diagnostics/live_feature_probe.csv`
- `data/reports/forward_diagnostics/feature_build_errors.csv`
- `data/reports/forward_diagnostics/feature_sample_<SYMBOL>.csv`
- `data/reports/forward_diagnostics/live_strategy_probe.csv`
- `data/reports/forward_diagnostics/near_misses.csv`
- `data/reports/forward_diagnostics/stable_filter_audit.json`
- `data/reports/forward_diagnostics/forward_vs_backtest_context.json`
- `data/reports/forward_diagnostics/report.html`

## How To Read It

`live_data_quality.csv` answers whether MT5 runtime data exists and is fresh.

`live_feature_probe.csv` answers whether ATR, RSI, EMA, regime, session, structure and liquidity context can be built from live candles.

`live_strategy_probe.csv` answers what the strategy engine saw, including `threshold_failures`, `component_scores`, child signals and blockers.

`near_misses.csv` lists candidates that were close to a threshold. Suggestions are research-only and must not be applied automatically to forward-shadow.

If classification is `FORWARD_PIPELINE_OK_WAIT_FOR_SETUP`, the data and feature path is healthy and the correct action is continued observation.

If classification is `FEATURE_PIPELINE_NOT_READY`, fix MT5 runtime bars/features before reviewing thresholds.

Phase 30 adds `--mode live-feature-contract` to isolate schema issues from strategy issues:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode live-feature-contract --symbols EURUSD,GBPUSD,USDJPY --output-dir data\reports\forward_diagnostics
```

If the live contract is OK but signals are still zero, blockers should move to strategy/context reasons such as `NO_SETUP_DETECTED`, `ENSEMBLE_SCORE_LOW`, `SESSION_BLOCK`, `REGIME_BLOCK` or `SPREAD_BLOCK`.

If classification is `STABLE_FILTER_TOO_RESTRICTIVE`, rerun stability repair in research only. It is not permission to loosen paper/live controls.

Safety remains unchanged: no `order_send`, no `order_check`, and `execution_attempted=false`.

# Walk-Forward Failure Analysis

Phase 24 analyzes why BALANCED can be profitable in aggregate but unstable out of sample.

This is research/backtest-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- no `order_send`
- no `order_check`

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode walk-forward-failure-analysis --runs-root data\runs --robustness-dir data\reports\robustness --profile-runs-dir data\reports\profile_runs --output-dir data\reports\stability_repair
```

## Fold Diagnostics

Each fold reports start/end time, trades, winrate, profit factor, expectancy R, net profit, drawdown proxy, dominant symbol/strategy/session/regime, and failure reasons.

Failure reasons include `LOW_TRADES_IN_FOLD`, `NEGATIVE_EXPECTANCY`, `PF_BELOW_1`, `DRAWDOWN_SPIKE`, `SYMBOL_CONCENTRATION`, `SESSION_FAILURE`, `REGIME_FAILURE`, and `STRATEGY_FAILURE`.

Positive aggregate metrics are not enough when later folds show negative expectancy. That usually means temporal edge decay, overfitting, or a symbol/session/regime that only worked in one market slice.

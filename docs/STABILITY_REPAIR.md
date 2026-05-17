# Stability Repair

Phase 24 creates a conservative `BALANCED_STABLE` research profile after walk-forward instability.

`BALANCED_STABLE` keeps BALANCED thresholds but adds stability filters for weak symbols, strategies, sessions and regimes. It is marked:

- `PROFILE_TYPE=RESEARCH_BACKTEST_ONLY`
- `NOT_FOR_DEMO_LIVE=true`
- `REQUIRES_ROBUSTNESS_RERUN=true`
- `APPLY_STABILITY_FILTERS=true`

It does not enable forward-shadow, demo or live execution.

`BALANCED_STABLE` must be run with `--profile-config`. If the config is missing, the runner returns `STABLE_PROFILE_CONFIG_REQUIRED`. If the config exists but does not contain actionable stability filters, the runner returns `STABLE_PROFILE_NOT_ACTIONABLE`.

## Commands

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode stability-repair --runs-root data\runs --robustness-dir data\reports\robustness --profile-runs-dir data\reports\profile_runs --output-dir data\reports\stability_repair

py -m agi_style_forex_bot_mt5.cli --mode build-stable-profile --runs-root data\runs --stability-dir data\reports\stability_repair --output-dir data\reports\stability_repair
```

## Rerun With BALANCED_STABLE

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode real-data-research --symbols EURUSD,GBPUSD,USDJPY --bars 20000 --output-root data\runs --signal-profile BALANCED_STABLE --profile-config data\reports\stability_repair\balanced_stable.ini --quick
```

The rerun is still research/backtest only. After it, rerun edge evaluation and `robustness-fast`.

## Stable Shadow Gate

After a profitable `BALANCED_STABLE` rerun, validate it before any prolonged paper/shadow observation:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode robustness-fast --runs-root data\runs --profile-runs-dir data\reports\profile_runs --profile BALANCED_STABLE --profile-config data\reports\stability_repair\balanced_stable.ini --output-dir data\reports\robustness

py -m agi_style_forex_bot_mt5.cli --mode stable-robustness-gate --runs-root data\runs --robustness-dir data\reports\robustness --stability-dir data\reports\stability_repair --profile BALANCED_STABLE --output-dir data\reports\stable_gate
```

`PAPER_SHADOW_READY` means paper observation only. It does not enable demo/live execution.

Stable filters can produce explicit backtest blockers:

- `STABLE_SYMBOL_DISABLED`
- `STABLE_STRATEGY_DISABLED`
- `STABLE_SESSION_BLOCK`
- `STABLE_REGIME_BLOCK`

## Outputs

- `walk_forward_failure_summary.json`
- `fold_diagnostics.csv`
- `by_symbol_stability.csv`
- `by_strategy_stability.csv`
- `by_session_stability.csv`
- `by_regime_stability.csv`
- `edge_decay.json`
- `balanced_stable.ini`
- `balanced_stable.json`
- `stability_filter_diff.json`
- `report.html`

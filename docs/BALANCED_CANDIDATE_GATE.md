# BALANCED Candidate Gate

Phase 22 adds a conservative gate for the BALANCED profile. It can only classify BALANCED as a paper/shadow observation candidate, never as demo/live ready.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode balanced-candidate-gate --runs-root data\runs --profile-runs-dir data\reports\profile_runs --edge-dir data\reports\edge --output-dir data\reports\profile_validation
```

## Decisions

- `BALANCED_FORWARD_SHADOW_CANDIDATE`
- `BALANCED_NEEDS_ROBUSTNESS_VALIDATION`
- `BALANCED_NEEDS_MORE_DATA`
- `BALANCED_REJECTED`
- `BALANCED_METRICS_UNTRUSTED`

The default positive outcome after one quick profile comparison is usually `BALANCED_NEEDS_ROBUSTNESS_VALIDATION`.

## Gate Rules

BALANCED can only pass the first candidate screen if:

- `metrics_status=FULL_EDGE_METRICS`
- `sample_status` is `USABLE_SAMPLE` or `PROMOTION_SAMPLE_SIZE`
- `total_trades >= 100`
- `profit_factor >= 1.20`
- `expectancy_r > 0`
- drawdown is acceptable or explicitly flagged if unknown
- profile integrity is not failed
- BALANCED is allowed for shadow paper observation
- BALANCED is not `NOT_FOR_DEMO_LIVE`

If walk-forward, Monte Carlo, stress, or full validation are missing, the decision remains `BALANCED_NEEDS_ROBUSTNESS_VALIDATION`.

After that decision, use the Phase 23 fast track:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode robustness-fast --runs-root data\runs --profile-runs-dir data\reports\profile_runs --profile BALANCED --output-dir data\reports\robustness
```

`robustness-fast` can return `PAPER_FORWARD_SHADOW_CANDIDATE`, which still means paper/shadow only. If Monte Carlo, stress, walk-forward or costs fail, the next action is more robustness data, cost recalibration, or strategy rework.

## Profile Integrity Dependency

Run threshold and integrity checks before using this gate:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode profile-threshold-audit --output-dir data\reports\profile_validation
py -m agi_style_forex_bot_mt5.cli --mode profile-integrity --profile-runs-dir data\reports\profile_runs --output-dir data\reports\profile_validation
```

`IDENTICAL_THRESHOLDS` fails the gate because BALANCED/ACTIVE comparison is not trustworthy. `DIFFERENT_THRESHOLDS_IDENTICAL_METRICS` is a warning: BALANCED metrics are not automatically rejected, but they still require walk-forward, Monte Carlo, stress, and paper-vs-backtest validation before prolonged forward-shadow observation.

## Safety

`FORWARD_SHADOW_CANDIDATE` and BALANCED candidate language mean paper/shadow observation only. They do not authorize demo/live execution.

# Stable Shadow Readiness Gate

Phase 25 validates `BALANCED_STABLE` after stability repair and decides whether it is worth running prolonged paper-only forward-shadow observation.

`PAPER_SHADOW_READY` means paper/shadow observation only. It does not approve demo or live execution.

## Commands

Run fast robustness for the stable profile:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode robustness-fast --runs-root data\runs --profile-runs-dir data\reports\profile_runs --profile BALANCED_STABLE --profile-config data\reports\stability_repair\balanced_stable.ini --output-dir data\reports\robustness
```

Run the stable gate:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode stable-robustness-gate --runs-root data\runs --robustness-dir data\reports\robustness --stability-dir data\reports\stability_repair --profile BALANCED_STABLE --output-dir data\reports\stable_gate
```

## Decisions

- `PAPER_SHADOW_READY`: stable profile can be observed in paper/shadow mode.
- `NEEDS_MORE_STABLE_DATA`: trade sample or Monte Carlo evidence is insufficient.
- `NEEDS_STABILITY_REWORK`: stability filters or walk-forward behavior are not acceptable.
- `NEEDS_COST_RECALIBRATION`: stress or cost sensitivity damages the edge.
- `REJECT_STABLE_PROFILE`: safety flags or profile identity are invalid.

## Forward Shadow

Only after `PAPER_SHADOW_READY`, run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_forward_shadow_balanced_stable.ps1
```

Stop observation if forward drift, cost drift, drawdown, stale ticks, or SQLite/JSONL audit failures appear.

Safety remains fixed: `DEMO_ONLY=True`, `LIVE_TRADING_APPROVED=False`, `execution_attempted=false`, and no `order_send` or `order_check` calls.

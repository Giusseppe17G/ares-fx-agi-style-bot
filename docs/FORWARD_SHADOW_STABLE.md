# BALANCED_STABLE Forward Shadow

`BALANCED_STABLE` forward-shadow is prolonged paper observation after the stable gate returns `PAPER_SHADOW_READY`.

It does not enable demo or live execution. It only creates and manages paper trades in SQLite/JSONL.

## Required Gate

Before starting:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode stable-robustness-gate --runs-root data\runs --robustness-dir data\reports\robustness --stability-dir data\reports\stability_repair --profile BALANCED_STABLE --output-dir data\reports\stable_gate
```

If the gate is missing, `forward-shadow` returns `STABLE_GATE_REQUIRED`.
If `paper_shadow_ready=false`, it returns `STABLE_PROFILE_NOT_READY`.

## Run

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE --profile-config data\reports\stability_repair\balanced_stable.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --cycle-seconds 30
```

Windows helper:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_forward_shadow_balanced_stable.ps1
```

Watchdog:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\watchdog_forward_shadow_balanced_stable.ps1
```

## Monitor

```powershell
py -m agi_style_forex_bot_mt5.cli --mode stable-health --sqlite data\sqlite\forward-shadow-stable.sqlite3 --stable-gate data\reports\stable_gate\stable_gate_summary.json

py -m agi_style_forex_bot_mt5.cli --mode stable-daily-summary --sqlite data\sqlite\forward-shadow-stable.sqlite3 --report-dir data\reports\forward_shadow_stable\daily
```

Daily reports include open/closed trades, by-symbol, by-strategy, by-session, by-regime, drift and HTML summary.

## Evidence Pack

After several hours or days, consolidate evidence:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-evidence --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\forward_evidence

py -m agi_style_forex_bot_mt5.cli --mode forward-acceptance --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\forward_evidence
```

`CONTINUE_FORWARD_SHADOW` means paper/shadow observation can continue. It is not demo/live approval.

## Pause Rules

Pause stable shadow if:

- `stable_drift_status=CRITICAL_DRIFT`
- `stable_drift_status=PAUSE_STABLE_SHADOW`
- spread or cost drift worsens.
- SQLite/JSONL audit fails.
- MT5 data becomes stale.
- drawdown or loss streak breaches paper limits.

Safety remains fixed: `DEMO_ONLY=True`, `LIVE_TRADING_APPROVED=False`, `execution_attempted=false`, and no `order_send` or `order_check`.
# Phase 28 Stable Tick Time Handling

`BALANCED_STABLE` forward-shadow now requires the stable gate as before and also consumes normalized MT5 tick timestamps. If a broker reports server time ahead of UTC, the bot audits `STABLE_TICK_TIME_NORMALIZED` with the detected offset and normalized tick age.

If the offset cannot be validated or the normalized tick remains stale, the symbol is rejected as market data invalid. This remains paper/shadow only and never enables demo/live execution.

# Phase 29 Signal Scarcity Diagnostics

If forward-shadow is connected but `signals_detected=0`, run `--mode forward-signal-diagnose`. The diagnostic path checks live ticks, runtime M5/M15/H1 bars, feature availability, BALANCED_STABLE filters, strategy threshold failures and near misses.

Phase 30 also adds the narrower `--mode live-feature-contract` audit. Use it when diagnostics show `FEATURE_PIPELINE_NOT_READY`; it verifies the live MT5 OHLCV schema, timestamp parsing, numeric casts, duplicate timestamps and diagnostic bar counts before any strategy threshold is reviewed.

Forward-shadow also emits diagnostic events per evaluated candidate:

- `FORWARD_CANDIDATE_EVALUATED`
- `FORWARD_CANDIDATE_BLOCKED`
- `FORWARD_NEAR_MISS`
- `FORWARD_NO_SIGNAL_DIAGNOSTIC`

These events are read-only and do not create paper trades unless the existing full shadow gates pass.

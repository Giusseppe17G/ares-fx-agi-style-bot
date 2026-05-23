# BALANCED_STABLE Forward Shadow

## Weekend Offline Readiness

When the market is closed, keep BALANCED_STABLE paused and run only offline/read-only checks:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode weekend-readiness --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\weekend_readiness
```

`WEEKEND_SAFE` means the paper state is clean for the next open: no open paper trades, shadow paused, stable gate and `balanced_stable.ini` present, logs parseable, and no real execution flags. It does not start forward-shadow.

Before market open, generate:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode market-open-checklist --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reports-root data\reports --output-dir data\reports\market_open_checklist
```

Use that checklist to run diagnostics first, then resume only paper/shadow if `mt5-diagnose` and `live-feature-contract` pass. `DEMO_ONLY=True` and `LIVE_TRADING_APPROVED=False` remain mandatory.

## EC2 Paper-Shadow Handoff

Generate the EC2 deployment pack before moving BALANCED_STABLE to an EC2 Windows host:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode ec2-deployment-pack --reports-root data\reports --output-dir data\reports\ec2_deployment_pack
```

The pack explains what BALANCED_STABLE is, how to run paper/shadow only, how to collect evidence, how to pause safely, and how to roll back. It does not enable demo/live execution. `paper-close-all` and pause/resume commands remain SQLite paper-state operations only.

## Offline Operator Drill

Before resuming BALANCED_STABLE after a weekend, run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode operator-drill --reports-root data\reports --output-dir data\reports\operator_drill
py -m agi_style_forex_bot_mt5.cli --mode dry-run-market-open --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reports-root data\reports --output-dir data\reports\operator_drill
```

These modes rehearse the opening sequence and validate prerequisites offline. A blocked dry run means keep shadow paused until the reported artifact, paper state or guardrail issue is fixed.

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

If live features are healthy and candidates are blocked by regime or ensemble score, use the Phase 31 research-only replay tools. They read JSONL/CSV/SQLite evidence and write `data\reports\forward_research`, but they do not alter the running BALANCED_STABLE process or create paper trades.

## Paper Drawdown Halt

`PAPER_DAILY_DRAWDOWN` is a critical paper/shadow alert. It means the SQLite paper account has breached the configured paper drawdown threshold. The bot must not open new paper trades until reviewed.

Useful safe commands:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --output-dir data\reports\paper_state
py -m agi_style_forex_bot_mt5.cli --mode paper-open-trades --sqlite data\sqlite\forward-shadow-stable.sqlite3 --output-dir data\reports\paper_state
py -m agi_style_forex_bot_mt5.cli --mode pause-shadow --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "PAPER_DAILY_DRAWDOWN review"
```

To close simulated paper trades only, first run dry-run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-close-all --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "manual paper reset after evidence parsing repair" --output-dir data\reports\paper_state
```

Then, if you intentionally want SQLite paper-only closure:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-close-all --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "manual paper reset after evidence parsing repair" --confirm-paper-only true --output-dir data\reports\paper_state
```

`paper-close-all` never touches MT5 positions, never calls `order_send`, and never calls `order_check`.

Forward-shadow also emits diagnostic events per evaluated candidate:

- `FORWARD_CANDIDATE_EVALUATED`
- `FORWARD_CANDIDATE_BLOCKED`
- `FORWARD_NEAR_MISS`
- `FORWARD_NO_SIGNAL_DIAGNOSTIC`

These events are read-only and do not create paper trades unless the existing full shadow gates pass.

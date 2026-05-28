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

## Operator Dashboard

For daily paper/shadow review:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode operator-dashboard --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reports-root data\reports --log-dir data\logs\forward-shadow-stable --output-dir data\reports\operator_dashboard
py -m agi_style_forex_bot_mt5.cli --mode daily-operator-report --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reports-root data\reports --log-dir data\logs\forward-shadow-stable --output-dir data\reports\daily_operator
```

The dashboard shows safety guardrails, paper state, evidence, diagnostics, EC2 readiness and next commands. It is read-only and does not run forward-shadow.

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

## Paper Risk Calibration And Micro Profile

Repeated `PAPER_DAILY_DRAWDOWN_HALT` is not ignored. It means the paper/shadow observation size or frequency is too aggressive for collecting stable evidence. Run the offline paper risk audit before resuming:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\paper_risk

py -m agi_style_forex_bot_mt5.cli --mode build-paper-risk-profile --base-profile BALANCED_STABLE --risk-audit-dir data\reports\paper_risk --output-dir data\reports\paper_risk

py -m agi_style_forex_bot_mt5.cli --mode paper-risk-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_risk
```

`BALANCED_STABLE_MICRO` keeps the stable strategy filters but reduces paper size, limits open paper trades, limits daily paper entries, adds cooldown after paper losses, blocks auto-resume after drawdown halts and requires manual review. It is `PAPER_ONLY=true`, `NOT_FOR_DEMO_LIVE=true`, and requires both stable gate and explicit `--profile-config`.

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE_MICRO --profile-config data\reports\paper_risk\balanced_stable_micro.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --cycle-seconds 30
```

Paper risk blocks are audited as `PAPER_RISK_LIMIT_BLOCK`, `PAPER_MAX_OPEN_TRADES_BLOCK`, `PAPER_DAILY_TRADE_LIMIT_BLOCK`, `PAPER_COOLDOWN_BLOCK` or `PAPER_DRAWDOWN_HALT_BLOCK`. None of these change demo/live settings or call broker order functions.

## Manual Clearance After Paper Drawdown Halt

`PAPER_DAILY_DRAWDOWN_HALT` requires explicit operator review before `BALANCED_STABLE_MICRO` may resume opening new paper entries. The clearance is a ledger; it does not delete logs, reset PnL, rewrite SQLite, or authorize demo/live execution.

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-review --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --output-dir data\reports\paper_risk_review

py -m agi_style_forex_bot_mt5.cli --mode paper-risk-clearance --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --output-dir data\reports\paper_risk_review --reason "Manual review after PAPER_DAILY_DRAWDOWN_HALT; resume only with BALANCED_STABLE_MICRO"

py -m agi_style_forex_bot_mt5.cli --mode paper-risk-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --profile-config data\reports\paper_risk\balanced_stable_micro.ini --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --output-dir data\reports\paper_risk
```

After clearance, resume shadow state deliberately, then run the cleared micro script:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode resume-shadow --sqlite data\sqlite\forward-shadow-stable.sqlite3 --reason "manual resume after paper risk clearance"

py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE_MICRO --profile-config data\reports\paper_risk\balanced_stable_micro.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --paper-risk-clearance data\reports\paper_risk_review\paper_risk_clearance_ledger.json --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --cycle-seconds 30
```

If a new halt appears after the clearance, the ledger becomes stale and forward-shadow fails closed with `PAPER_RISK_CLEARANCE_STALE`.

Phase 39C adds an explicit profile matching check for the clearance ledger. Use it before resuming if `paper-risk-status` reports `PAPER_RISK_CLEARANCE_PROFILE_MISMATCH`:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-clearance-check --profile BALANCED_STABLE_MICRO --profile-config data\reports\paper_risk\balanced_stable_micro.ini --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --output-dir data\reports\paper_risk_review
```

The matcher normalizes `BALANCED_STABLE_MICRO`, `balanced_stable_micro`, and `Balanced Stable Micro` to the same canonical profile. If an older `balanced_stable_micro.ini` lacks an explicit profile key, the profile can be inferred from the config path and the report will include `PROFILE_INFERRED_FROM_CONFIG_PATH`. This clearance still applies only to `BALANCED_STABLE_MICRO`; `BALANCED_STABLE` remains blocked after a paper drawdown halt.

## Daily Paper Risk State

Phase 40 separates an active paper drawdown halt from a historical halt that was already reviewed. The original SQLite alerts, JSONL logs and reports are not deleted or rewritten. Instead, `paper-daily-risk-clear` creates `data\reports\paper_daily_risk\paper_daily_risk_ledger.json` after verifying zero open paper trades, valid micro clearance, no halt after that clearance, clean execution evidence and clear/quarantined telemetry.

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-daily-risk-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_daily_risk

py -m agi_style_forex_bot_mt5.cli --mode paper-daily-risk-clear --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_daily_risk --reason "Clear stale paper drawdown halt after manual review and micro clearance"

py -m agi_style_forex_bot_mt5.cli --mode paper-risk-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --profile-config data\reports\paper_risk\balanced_stable_micro.ini --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --reports-root data\reports --paper-risk-dir data\reports\paper_risk --output-dir data\reports\paper_risk
```

The expected clear state is `PAPER_RISK_CLEAR_FOR_MICRO_SHADOW` with `daily_drawdown_status=CLEARED_STALE_HALT`. If a new halt appears after the daily ledger, micro fails closed again.

Forward-shadow also emits diagnostic events per evaluated candidate:

- `FORWARD_CANDIDATE_EVALUATED`
- `FORWARD_CANDIDATE_BLOCKED`
- `FORWARD_NEAR_MISS`
- `FORWARD_NO_SIGNAL_DIAGNOSTIC`

These events are read-only and do not create paper trades unless the existing full shadow gates pass.

## FASE 40B: Paper PnL Audit Before New Clearance

If BALANCED_STABLE_MICRO creates a new `PAPER_DAILY_DRAWDOWN_HALT` after manual clearance, do not clear the halt again blindly. Run the offline PnL audit first:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode paper-pnl-audit --sqlite data\sqliteorward-shadow-stable.sqlite3 --log-dir data\logsorward-shadow-stable --reports-root data
eports --paper-risk-dir data
eports\paper_risk --daily-risk-dir data
eports\paper_daily_risk --profile-config data
eports\paper_riskalanced_stable_micro.ini --output-dir data
eports\paper_pnl_audit
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-recommendation --reports-root data
eports --pnl-audit-dir data
eports\paper_pnl_audit --output-dir data
eports\paper_pnl_audit
```

The audit distinguishes formula/scale bugs (`PAPER_PNL_SCALING_BUG`, `MICRO_RISK_NOT_APPLIED`) from real micro losses (`VALID_MICRO_DRAWDOWN_HALT`) and daily-window leaks (`DRAWDOWN_HISTORY_LEAK`). A scaling bug or valid new micro drawdown keeps new clearance blocked.

## FASE 41: Scaled Paper PnL

BALANCED_STABLE_MICRO now uses a central paper PnL engine. New paper closes preserve `raw_pnl` for audit, write `scaled_paper_pnl`, and use the scaled value for paper drawdown, risk status, forward evidence and acceptance. The active drawdown basis is `SCALED_PAPER_PNL`.

Before issuing a new micro clearance after a drawdown halt, run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-pnl-scaling-check --sqlite data\sqliteorward-shadow-stable.sqlite3 --log-dir data\logsorward-shadow-stable --profile-config dataeports\paper_riskalanced_stable_micro.ini --output-dir dataeports\paper_pnl_audit
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-post-fix-gate --reports-root dataeports --output-dir dataeports\paper_pnl_audit
```

Legacy trades without `scaled_paper_pnl` are classified as `LEGACY_UNSCALED_PNL` and remain in evidence. They must not be mixed into the active micro drawdown window after ledger/clearance review.

## FASE 42: Legacy Drawdown Quarantine

`BALANCED_STABLE_MICRO` now separates legacy/unscaled drawdown evidence from active scaled paper risk. Only an `ACTIVE_SCALED_CURRENT_EVENT` after the current clearance and daily risk ledger can trigger a new active `PAPER_DAILY_DRAWDOWN_HALT`.

Run the legacy audit before resuming micro shadow after a post-fix paper PnL repair:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-legacy-drawdown-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --daily-risk-dir data\reports\paper_daily_risk --pnl-audit-dir data\reports\paper_pnl_audit --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\paper_daily_risk
```

Expected safe legacy state:

- `legacy_drawdown_status=LEGACY_DRAWDOWN_QUARANTINED`
- `active_scaled_events_count=0`
- `can_resume_micro_shadow=true`
- `drawdown_basis=SCALED_PAPER_PNL_ONLY`

Historical logs, SQLite rows and evidence are not deleted or rewritten. They remain auditable, but they do not revive active daily drawdown blocks once the post-fix clearance, daily risk ledger and scaled PnL engine are valid. A new scaled halt after the ledger still blocks immediately.

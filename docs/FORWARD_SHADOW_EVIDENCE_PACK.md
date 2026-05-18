# Forward Shadow Evidence Pack

The evidence pack summarizes several days of `BALANCED_STABLE` paper/shadow observation.

It remains read-only and does not enable demo/live execution.

## When To Run

Run after `BALANCED_STABLE` has been running in forward-shadow for several hours or days:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode forward-evidence --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\forward_evidence
```

Then run the operational gate:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-acceptance --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\forward_evidence
```

Windows helpers:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\forward_evidence_stable.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\forward_acceptance_stable.ps1
```

## Reports

The pack writes:

- `evidence_summary.json`
- `forward_metrics.json`
- `drift_summary.json`
- `rejections.csv`
- `paper_trade_audit.json`
- `operational_acceptance.json`
- `report.html`

## Decisions

- `CONTINUE_FORWARD_SHADOW`: paper/shadow observation can continue.
- `PAUSE_FORWARD_SHADOW`: stop stable observation and investigate immediately.
- `NEEDS_MORE_FORWARD_DATA`: no critical issues, but insufficient hours or paper trades.
- `NEEDS_STABILITY_REPAIR`: drift or instability requires research repair.
- `NEEDS_BROKER_FIX`: broker or cost conditions need investigation.
- `NEEDS_TELEMETRY_FIX`: heartbeat, SQLite or JSONL evidence is not trustworthy.

## Minimum Evidence

For operational continuation, collect at least:

- 24 hours observed.
- healthy heartbeat.
- stable gate confirmed.
- no critical drift.
- SQLite/JSONL audit OK.
- paper trade audit OK.
- at least 10 closed paper trades, unless the decision remains `NEEDS_MORE_FORWARD_DATA` without critical issues.

Before any future discussion beyond paper/shadow, collect multiple days and hundreds of paper trades. This phase does not authorize demo/live execution.
# Phase 29 Signal Diagnostics Integration

Forward evidence now includes signal scarcity context when `data/reports/forward_diagnostics/signal_scarcity_summary.json` exists:

- `forward_diagnostics_status`
- `top_forward_blockers`
- `candidate_count`
- `near_miss_count`
- `live_feature_ready_symbols`
- `recommended_signal_diagnosis_action`

Use this when evidence shows many healthy cycles but zero signals. A lack of trades is not automatically a bug; the diagnostics separate "no setup yet" from data, feature, filter, spread, or threshold problems.

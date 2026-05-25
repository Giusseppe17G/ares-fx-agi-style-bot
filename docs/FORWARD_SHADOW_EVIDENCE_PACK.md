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

If acceptance pauses because it detected possible execution evidence, run the execution evidence audit:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode execution-evidence-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\execution_evidence
```

`order_send_called=false`, `order_check_called=false`, and `execution_attempted=false` are safe boolean fields and do not count as execution attempts. Text like `order_send was not called`, documentation snippets, and command references are classified as false positives. Only true boolean fields, or ambiguous evidence that cannot be classified, block acceptance.

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

The execution audit also writes:

- `data\reports\execution_evidence\execution_evidence_summary.json`
- `data\reports\execution_evidence\findings.csv`
- `data\reports\execution_evidence\false_positive_mentions.csv`
- `data\reports\execution_evidence\blocking_findings.csv`
- `data\reports\execution_evidence\report.html`

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

## Invalid Timestamps

If SQLite or JSONL contains corrupted/redacted timestamps, evidence generation returns `PARTIAL_INVALID_TIMESTAMPS` instead of crashing. Review:

- `evidence_parse_status`
- `invalid_timestamp_count`
- `invalid_timestamp_fields`
- `invalid_timestamp_examples`

`PARTIAL_INVALID_TIMESTAMPS` means telemetry must be repaired or isolated before operational acceptance. It does not justify changing strategy thresholds or resuming shadow entries.

## Telemetry Timestamp Quarantine

Phase 38 adds a ledger-only quarantine for historical corrupt timestamps. It never deletes JSONL, SQLite rows, or original reports.

```powershell
py -m agi_style_forex_bot_mt5.cli --mode telemetry-timestamp-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
py -m agi_style_forex_bot_mt5.cli --mode quarantine-telemetry-issues --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair --reason "Historical redacted timestamps reviewed after paper reset"
py -m agi_style_forex_bot_mt5.cli --mode telemetry-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
```

Interpretation:

- `TELEMETRY_ACTIVE_BLOCKING`: recent evidence still has invalid timestamps and acceptance must block.
- `TELEMETRY_HISTORICAL_ISSUES_ONLY`: corrupt timestamps are historical; quarantine/review them before acceptance ignores them.
- `TELEMETRY_HISTORICAL_QUARANTINED`: all historical corrupt timestamps are `QUARANTINED` or `REVIEWED`; acceptance can move on to operational criteria.
- `telemetry_acceptance_clear=true`: historical issues are reviewed/quarantined and forward acceptance may decide on drift, drawdown, hours, trades, paper audit and execution guard.
- `NEEDS_TELEMETRY_FIX`: active timestamp producer must be repaired.
- `NEEDS_TELEMETRY_REVIEW`: historical issues exist but have not been quarantined/reviewed.

Use the policy view when debugging acceptance:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode telemetry-acceptance-policy --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
```

# Phase 29 Signal Diagnostics Integration

Forward evidence now includes signal scarcity context when `data/reports/forward_diagnostics/signal_scarcity_summary.json` exists:

- `forward_diagnostics_status`
- `top_forward_blockers`
- `candidate_count`
- `near_miss_count`
- `live_feature_ready_symbols`
- `recommended_signal_diagnosis_action`

Use this when evidence shows many healthy cycles but zero signals. A lack of trades is not automatically a bug; the diagnostics separate "no setup yet" from data, feature, filter, spread, or threshold problems.

## Paper Risk Evidence

Phase 39 adds paper risk fields to forward evidence when `data\reports\paper_risk` exists:

- `paper_risk_status`
- `paper_risk_profile`
- `paper_risk_blocks`
- `paper_risk_acceptance_clear`

If repeated paper drawdown halts occur, run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-risk-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\paper_risk
py -m agi_style_forex_bot_mt5.cli --mode build-paper-risk-profile --base-profile BALANCED_STABLE --risk-audit-dir data\reports\paper_risk --output-dir data\reports\paper_risk
```

`BALANCED_STABLE_MICRO` is a safer paper observation profile. It reduces paper risk and frequency, but remains `NOT_FOR_DEMO_LIVE=true` and does not affect broker execution.

## Paper Risk Clearance Evidence

Forward evidence and operator reports include manual clearance fields when present:

- `paper_risk_clearance_status`
- `paper_risk_clearance_id`
- `cleared_for_profile`
- `clearance_stale`

The clearance ledger lives at `data\reports\paper_risk_review\paper_risk_clearance_ledger.json`. It is valid only if it was created after the latest paper drawdown halt and only for `BALANCED_STABLE_MICRO` paper/shadow. A stale or missing ledger must block micro forward-shadow before MT5 runtime begins.

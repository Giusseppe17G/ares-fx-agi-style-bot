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

## Daily Paper Risk Evidence

Phase 40 adds daily paper risk fields to forward evidence:

- `paper_daily_risk_status`
- `active_today_halt_count`
- `stale_halt_count`
- `daily_risk_ledger_status`
- `can_resume_micro_shadow`

Historical `PAPER_DAILY_DRAWDOWN_HALT` evidence remains visible. It stops blocking `BALANCED_STABLE_MICRO` only when the profile clearance ledger and daily paper risk ledger are both valid and no newer halt exists.

## Paper PnL Audit Evidence

The evidence pack now surfaces `paper_pnl_audit_status`, `micro_risk_application_status`, `drawdown_root_cause`, and `paper_risk_recommendation` when `data
eports\paper_pnl_audit\paper_pnl_audit_summary.json` exists. Historical evidence is preserved; the audit writes derived reports only.

## Scaled Paper PnL Evidence

Forward evidence and paper state reports now include scaled drawdown context where available: `raw_drawdown`, `scaled_drawdown`, `drawdown_basis`, `legacy_unscaled_trade_count`, and `scaled_trade_count`. Acceptance should treat current micro risk using `scaled_paper_pnl`, while historical legacy rows remain quarantinable evidence rather than active risk state.

## Legacy Drawdown Evidence

Phase 42 adds these evidence fields when `data\reports\paper_daily_risk\legacy_drawdown_audit_summary.json` exists:

- `legacy_drawdown_status`
- `legacy_drawdown_quarantined`
- `legacy_quarantined_halt_count`
- `active_scaled_drawdown_count`
- `can_resume_micro_shadow`
- `drawdown_basis`

The evidence pack keeps historical `PAPER_DAILY_DRAWDOWN_HALT` rows visible. It treats only post-ledger scaled paper PnL events as active drawdown risk. Legacy unscaled rows before the PnL fix, before the clearance, before the daily risk ledger, or with invalid timestamps are reportable evidence, not active risk blockers once quarantined.

## Telemetry Quarantine Alignment

Forward acceptance treats historical timestamp issues as clear only when every historical invalid timestamp is `QUARANTINED` or `REVIEWED` and there are no active or unknown timestamp issues. Use:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode quarantine-telemetry-issues --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair --reason "Historical invalid timestamps reviewed after paper reset"
py -m agi_style_forex_bot_mt5.cli --mode telemetry-status --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
py -m agi_style_forex_bot_mt5.cli --mode telemetry-acceptance-policy --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --output-dir data\reports\telemetry_repair
```

Expected clear state: `telemetry_status=TELEMETRY_HISTORICAL_QUARANTINED`, `historical_unreviewed_count=0`, and `telemetry_acceptance_clear=true`. Original logs, SQLite rows and evidence files are not deleted or rewritten.

## Telemetry Drift Audit

Phase 42C prevents derived report examples and old redacted timestamps from becoming fresh unreviewed blockers after each evidence run. `telemetry-drift-audit` separates active forward telemetry from historical drift:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode telemetry-drift-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --telemetry-dir data\reports\telemetry_repair --output-dir data\reports\telemetry_repair
```

Only `ACTIVE_FORWARD_TELEMETRY_BLOCKING` or unknown review-required issues should block forward acceptance. Historical old heartbeats, old ML predictions, redacted legacy timestamps, and invalid timestamp examples generated by reports are audit-visible but should not create new unreviewed blockers when they are outside the clean evidence window or covered by the quarantine ledger.

## Acceptance Drawdown Policy

Phase 42D aligns forward acceptance with legacy drawdown quarantine. Acceptance no longer pauses only because the raw metrics still say `PAPER_DAILY_DRAWDOWN`; it checks the consolidated drawdown policy:

- `LEGACY_DRAWDOWN_QUARANTINED` with `active_scaled_drawdown_count=0` is not an acceptance drawdown block.
- `ACTIVE_SCALED_DRAWDOWN_BLOCK` or a current `PAPER_DRAWDOWN_HALT_BLOCK` still pauses forward shadow.
- Acceptance reports `acceptance_drawdown_blocking` and `acceptance_blocking_reason` explicitly.

Audit the drawdown decision with:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode acceptance-drawdown-policy-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --daily-risk-dir data\reports\paper_daily_risk --pnl-audit-dir data\reports\paper_pnl_audit --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --output-dir data\reports\forward_evidence
```

## Paper State Recovery Evidence

Phase 42E adds recovery evidence for `PAPER_STATE_ERROR`, `CONFIG_ERROR`, and open paper trades:

- `paper_state_recovery_status`
- `config_error_root_cause`
- `open_paper_trade_audit_status`
- `paper_state_clean_for_observation`
- `recovery_required`
- `recovery_recommended_action`

Run:

```powershell
py -m agi_style_forex_bot_mt5.cli --mode paper-state-recovery-audit --sqlite data\sqlite\forward-shadow-stable.sqlite3 --log-dir data\logs\forward-shadow-stable --reports-root data\reports --paper-risk-dir data\reports\paper_risk --daily-risk-dir data\reports\paper_daily_risk --pnl-audit-dir data\reports\paper_pnl_audit --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json --daily-risk-ledger data\reports\paper_daily_risk\paper_daily_risk_ledger.json --profile-config data\reports\paper_risk\balanced_stable_micro.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --output-dir data\reports\paper_state_recovery
```

Forward acceptance must not advance while config recovery is blocking, or while an open paper trade is stale/orphan and unreviewed. A valid open paper trade can be observed without closing it automatically.

## Config Error Root Cause Evidence

Phase 42F adds `config-error-root-cause-audit` for cases where recovery previously reported `unknown_config_error`. It writes:

- `data/reports/config_error_recovery/config_error_root_cause_summary.json`
- `data/reports/config_error_recovery/config_error_events.csv`
- `data/reports/config_error_recovery/config_input_paths.csv`
- `data/reports/config_error_recovery/config_parser_audit.csv`
- `data/reports/config_error_recovery/forward_shadow_last_errors.csv`

Forward evidence includes `config_error_recommended_fix` and `can_rerun_forward_shadow_after_fix`. A `FORWARD_SHADOW_CONFIG_EXCEPTION` means the exception came from the paper/shadow loop itself, such as an open paper trade with invalid risk distance. Keep the evidence visible and review the paper state; this does not authorize demo/live execution.

## Invalid Open Paper Trade Recovery Evidence

Phase 42G adds explicit evidence for invalid open paper trades:

- `invalid_open_paper_trade_count`
- `zero_risk_distance_count`
- `affected_trade_ids`
- `invalid_open_paper_trade_resolved`
- `config_error_resolved`

`paper-close-invalid-open-trade` can close only an open paper trade that is objectively invalid: missing entry, missing SL, zero/negative risk distance, invalid TP, or invalid direction. It requires `--trade-id`, `--confirm-paper-only true`, and `--reason`. It records a paper-only close event and ledger entry and never calls MT5.

## Offline Research Candidate Ranking

Phase 43 adds `research-candidate-ranking`, which is read-only research. It produces:

- `candidate_ranking_summary.json`
- `candidate_ranking_by_symbol.csv`
- `candidate_ranking_by_strategy.csv`
- `candidate_blockers.csv`
- `candidate_recommendations.md`
- `report.html`

Forward evidence may display `research_candidate_score`, `best_research_symbols`, and `research_recommendation` if this report exists. Those fields are informational only and never bypass paper risk, cooldown, forward acceptance, stable gate, or execution safety rules.

## Forward Sufficiency Audit

Phase 44 adds `forward-sufficiency-audit` for the common `NEEDS_MORE_FORWARD_DATA` state. It writes:

- `forward_sufficiency_summary.json`
- `observation_window.json`
- `trade_frequency_audit.json`
- `rejection_funnel.csv`
- `blocker_funnel.csv`
- `symbol_activity.csv`
- `profile_throttle_audit.json`
- `recommendations.md`
- `report.html`

Forward evidence may show `forward_sufficiency_status`, `forward_sufficiency_hours_observed`, `forward_sufficiency_closed_paper_trades`, `forward_sufficiency_estimated_hours_to_acceptance`, and `forward_sufficiency_recommendation` when this report exists. These fields explain whether more time, more trades, data quality, risk gates, sessions, or filter strictness are limiting the observation. They never bypass acceptance gates or authorize demo/live execution.

## Micro Frequency Calibration

Phase 45 adds `micro-frequency-calibration` for offline review when time is sufficient but closed paper trade count is still below 10. It writes:

- `micro_frequency_summary.json`
- `frequency_bottlenecks.csv`
- `threshold_sensitivity.csv`
- `symbol_frequency.csv`
- `session_opportunity.csv`
- `exit_latency_audit.json`
- `balanced_stable_micro_v2_candidate.ini`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_frequency_status`, `micro_frequency_estimated_hours_to_10_trades_current_profile`, `micro_frequency_top_bottlenecks`, and `micro_frequency_candidate_profile_available`. These fields are advisory only. Any future use of the candidate profile must happen in a separate approved offline phase.

## Micro V2 Review

Phase 46 adds `micro-v2-review`, a manual offline gate for the V2 candidate. It writes:

- `micro_v2_review_summary.json`
- `profile_diff.csv`
- `safety_constraints.json`
- `frequency_gain_estimate.json`
- `rejected_changes.csv`
- `approved_changes.csv`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_review_status`, `micro_v2_candidate_available`, and `micro_v2_profile_created` if the review report exists. These fields remain informational. They do not select a profile, do not skip acceptance, and do not authorize demo/live execution.

## Controlled Micro Frequency Proposal

Phase 47 adds `micro-frequency-proposal`, which creates a non-active `balanced_stable_micro_v2_proposed.ini` only when real bottlenecks can be mapped to existing safe profile parameters. It writes:

- `micro_frequency_proposal_summary.json`
- `proposed_profile_diff.csv`
- `proposed_changes.csv`
- `rejected_possible_changes.csv`
- `safety_audit.json`
- `balanced_stable_micro_v2_proposed.ini` when a safe proposal exists
- `recommendations.md`
- `report.html`

Rejected bottlenecks remain visible when no safe profile key exists. The proposal does not replace the active micro profile and does not affect forward acceptance.

## Micro V2 Proposed Review

Phase 48 adds `micro-v2-proposed-review`. It validates the proposed profile produced by Phase 47, including 10% loss-cooldown reduction maximum, daily paper trade cap <= 3, unchanged drawdown halt cooldown, unchanged risk multiplier, paper-only markers, and stable/clearance/daily-ledger requirements.

If approved, it creates `data/reports/paper_risk/balanced_stable_micro_v2.ini` for future paper dry-run review only. The evidence pack can display `micro_v2_proposed_review_status`, `micro_v2_profile_created`, and `micro_v2_profile_path`, but those fields never activate runtime or bypass acceptance gates.

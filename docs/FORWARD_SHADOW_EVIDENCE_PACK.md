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

## Micro V2 Dry-Run Readiness

Phase 49 adds `micro-v2-dry-run-readiness`, which validates the approved V2 profile and produces an isolated launch pack. It writes:

- `micro_v2_dry_run_readiness_summary.json`
- `v2_profile_guard.json`
- `path_isolation_audit.json`
- `launch_command.txt`
- `launch_checklist.md`
- `rollback_plan.md`
- `monitoring_commands.md`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_dry_run_readiness_status` and `micro_v2_launch_command_available`. These fields are informational and do not execute V2 or bypass any gate.

## Micro V2 Runtime Profile Registration

Phase 50 adds `micro-v2-runtime-profile-check`. It confirms that `BALANCED_STABLE_MICRO_V2` is present in the `--signal-profile` registry and that runtime guards would reject unsafe use before a manual launch.

The check writes:

- `micro_v2_runtime_profile_check_summary.json`
- `signal_profile_registry.json`
- `v2_runtime_guards.json`
- `recommendations.md`
- `report.html`

The acceptance/evidence flow may surface these fields as informational status, but they never skip risk, telemetry, paper-state, daily-risk, or acceptance gates.

## Micro V2 Paper Risk Clearance

Phase 51 adds `micro-v2-paper-risk-clearance`. It validates the final V2 profile, confirms Phase 48 approval and Phase 50 runtime registration, audits the base clearance ledger without changing it, and writes a separate V2-only ledger:

- `micro_v2_clearance_summary.json`
- `paper_risk_clearance_v2_ledger.json`
- `clearance_guard.json`
- `base_clearance_audit.json`
- `recommendations.md`
- `report.html`

The V2 ledger does not authorize `BALANCED_STABLE_MICRO`, demo, or live execution. It is only a paper dry-run prerequisite for `BALANCED_STABLE_MICRO_V2`.

## Micro V2 Clearance Runtime Match

Phase 52 adds `micro-v2-clearance-runtime-check`. It verifies the final runtime matching path without launching forward-shadow. Reports include:

- `micro_v2_clearance_runtime_check_summary.json`
- `clearance_runtime_match.json`
- `requested_vs_cleared_profile.json`
- `guard_trace.json`
- `recommendations.md`
- `report.html`

The check confirms `requested_profile_canonical=BALANCED_STABLE_MICRO_V2`, `cleared_for_profile_canonical=BALANCED_STABLE_MICRO_V2`, `clearance_scope=PAPER_DRY_RUN_ONLY`, demo/live approval flags are false, daily risk ledger exists, and V2 paths are isolated.

## Micro V2 Dry-Run Monitor

Phase 53 adds `micro-v2-dry-run-monitor`, an offline/read-only comparison pack for the isolated V2 dry-run. Reports include:

- `micro_v2_dry_run_monitor_summary.json`
- `heartbeat_audit.json`
- `v2_activity_summary.json`
- `base_vs_v2_comparison.json`
- `base_vs_v2_metrics.csv`
- `v2_rejections.csv`
- `safety_status.json`
- `monitoring_recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_dry_run_monitor_status`, `v2_hours_observed`, `v2_paper_trades_closed`, `v2_signals_detected`, and `v2_recommended_next_action` if the monitor report exists. These fields remain informational and never bypass acceptance, telemetry, paper-risk, or execution guardrails.

## Micro V2 Symbol Rejection Audit

Phase 54 adds `micro-v2-symbol-rejection-audit`. It reads the isolated V2 SQLite/log inputs, V2 profile, stable gate summary, and monitor pack to explain `symbol_rejected` dominance. Reports include:

- `micro_v2_symbol_rejection_summary.json`
- `rejected_symbols.csv`
- `symbol_normalization_audit.json`
- `allowed_universe_audit.json`
- `stable_gate_symbol_audit.json`
- `broker_symbol_mapping_audit.json`
- `symbol_rejection_fix_plan.md`
- `recommendations.md`
- `report.html`

If a safe non-active proposal applies, it may create `balanced_stable_micro_v2_symbol_fix_candidate.ini` with `NOT_ACTIVE_RESEARCH_ONLY=true` and `APPROVED_FOR_PAPER_DRY_RUN_ONLY=false`. Forward evidence may display `micro_v2_symbol_rejection_status`, `symbol_rejection_root_cause`, and `symbol_fix_candidate_available`; these fields are advisory only.

## Rejection Labeling Taxonomy

Phase 55 adds precise labels for future market-data rejections:

- `STALE_TICK_REJECTION`
- `MARKET_CLOSED_REJECTION`
- `FUTURE_SIGNAL_REJECTION`
- `INVALID_MARKET_SNAPSHOT_REJECTION`

`SYMBOL_REJECTED` remains for true symbol availability/universe failures. The `rejection-labeling-audit` report writes `rejection_labeling_summary.json`, `rejection_taxonomy.json`, `suspected_misclassified_rejections.csv`, `legacy_rejections.csv`, `recommendations.md`, and `report.html`. The audit is read-only and does not rewrite legacy events.

## Micro V2 Market Open Readiness

Phase 56 adds `micro-v2-market-open-readiness`, which combines V2 heartbeat, MT5 connection, rejection-label taxonomy, and latest tick evidence to classify whether V2 is waiting for market open or observing fresh ticks. Reports include:

- `micro_v2_market_open_readiness_summary.json`
- `fresh_tick_audit.json`
- `market_closed_audit.json`
- `mt5_connection_audit.json`
- `v2_runtime_state.json`
- `symbol_tick_freshness.csv`
- `recommendations.md`
- `report.html`

Forward evidence may display market-open readiness fields, but they are informational only and never bypass acceptance or risk gates.

## Micro V2 Observation Playbook

Phase 57 adds `micro-v2-observation-playbook`, an offline/read-only pack for operating the next market-open V2 observation window. Reports include:

- `micro_v2_observation_playbook_summary.json`
- `launch_commands.md`
- `monitoring_commands.md`
- `evidence_commands.md`
- `advancement_criteria.md`
- `stop_rollback_criteria.md`
- `observation_schedule.md`
- `operator_checklist.md`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_observation_playbook_status`, `observation_playbook_available`, and `observation_playbook_recommended_next_action`. These fields are advisory only and never activate V2, approve acceptance, or authorize demo/live execution.

## Micro V2 Observation Checkpoint

Phase 58 adds `micro-v2-observation-checkpoint`, a read-only consolidation pack for repeated V2 observation checkpoints. Reports include:

- `micro_v2_observation_checkpoint_summary.json`
- `status_snapshot.json`
- `readiness_snapshot.json`
- `monitor_snapshot.json`
- `rejection_snapshot.json`
- `acceptance_snapshot.json`
- `checkpoint_decision.json`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_checkpoint_status`, `v2_checkpoint_available`, and `v2_checkpoint_recommended_next_action`. These fields are informational only and never bypass forward acceptance, risk gates, telemetry guards, or demo/live restrictions.

## Micro V2 Filter Analysis

Phase 59 adds `micro-v2-filter-analysis`, an offline/read-only rejection analysis for V2 once fresh tick data is present. Reports include:

- `micro_v2_filter_analysis_summary.json`
- `rejection_breakdown.csv`
- `rejection_by_symbol.csv`
- `rejection_by_session.csv`
- `fresh_tick_filter_scope.json`
- `dominant_filter_audit.json`
- `base_vs_v2_filter_comparison.json`
- `filter_tuning_recommendations.md`
- `filter_tuning_candidate.json` when a dominant real filter is found
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_filter_analysis_status`, `dominant_v2_filter`, `filter_tuning_candidate_available`, and `micro_v2_filter_analysis_recommended_next_action`. These fields are advisory only and never activate tuning, bypass gates, or authorize demo/live.

## Micro V2 Risk Block Audit

Phase 60 adds `micro-v2-risk-block-audit`, a read-only root-cause audit for V2 `RISK_REJECTED` evidence. Reports include:

- `micro_v2_risk_block_summary.json`
- `risk_rejections.csv`
- `risk_reason_breakdown.csv`
- `risk_by_symbol.csv`
- `risk_by_session.csv`
- `cooldown_risk_audit.json`
- `trade_limit_audit.json`
- `exposure_risk_audit.json`
- `drawdown_risk_audit.json`
- `invalid_trade_state_audit.json`
- `recommendations.md`
- `risk_block_fix_recommendations.md` and `risk_block_candidate.json` only when a reviewable cause is found
- `report.html`

Forward evidence may display `micro_v2_risk_block_status`, `dominant_risk_block_reason`, `risk_block_candidate_available`, and `micro_v2_risk_block_recommended_next_action`. These fields are informational and never override market-closed dominance, risk gates, or demo/live restrictions.

## Micro V2 Consolidated Risk/Market Audit

Phase 61 adds `micro-v2-consolidated-risk-market-audit`, combining exposure explainability, double-counting detection, risk decision review, and market stability into one offline pack. Reports include:

- `micro_v2_consolidated_audit_summary.json`
- `exposure_explainability.json`
- `exposure_blocks.csv`
- `exposure_by_symbol.csv`
- `exposure_double_counting_audit.json`
- `market_stability_audit.json`
- `risk_decision_audit.json`
- `continue_or_repair_decision.json`
- `recommendations.md`
- optional research-only repair/tuning recommendation markdown files
- `report.html`

Forward evidence may display `consolidated_v2_audit_status`, `exposure_guard_diagnosis`, `market_stability_status`, and `micro_v2_consolidated_recommended_next_action`. These fields are informational only and cannot activate tuning, runtime repair, acceptance, demo, or live trading.

## Micro V2 Stable Market Window

Phase 62 adds `micro-v2-stable-market-window`, an offline/read-only pack that decides whether V2 market evidence is stable enough for the next analysis step. Reports include:

- `micro_v2_stable_market_window_summary.json`
- `fresh_tick_coverage_audit.json`
- `symbol_readiness.csv`
- `market_closed_trend_audit.json`
- `trade_readiness_audit.json`
- `next_decision_gate.json`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_stable_market_window_status`, `stable_window_fresh_tick_coverage_ratio`, `stable_window_market_closed_dominance_ratio`, `stable_window_trade_readiness_status`, and `micro_v2_stable_window_recommended_next_action`. These fields are informational only and never override risk gates, acceptance gates, or demo/live restrictions.

## Micro V2 Lifecycle/Risk Comparison

Phase 63 adds `micro-v2-lifecycle-risk-comparison`, an offline/read-only pack for V2 open trade lifecycle, exit/PnL readiness, drawdown/risk health, preliminary stable comparison, and pre-acceptance blockers. Reports include:

- `micro_v2_lifecycle_risk_comparison_summary.json`
- `open_trades.csv`
- `open_trade_lifecycle_audit.json`
- `exit_readiness_audit.json`
- `pnl_readiness_audit.json`
- `drawdown_health_audit.json`
- `risk_health_audit.json`
- `base_vs_v2_preliminary_comparison.json`
- `frequency_pre_acceptance_audit.json`
- `acceptance_blockers.json`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_lifecycle_risk_comparison_status`, `v2_open_trade_count`, `v2_closed_trade_count`, `v2_acceptance_ready`, `v2_preliminary_comparison_status`, and `micro_v2_lifecycle_recommended_next_action`. These fields are advisory only and cannot close trades, bypass acceptance, or authorize demo/live.

## Micro V2 Invalid Trade Forensics

Phase 64 adds `micro-v2-invalid-trade-forensics`, an offline/read-only forensic pack for invalid open V2 paper trades. Reports include:

- `micro_v2_invalid_trade_forensics_summary.json`
- `invalid_open_trades.csv`
- `invalid_trade_root_cause.json`
- `risk_distance_forensics.json`
- `sl_tp_forensics.json`
- `repair_plan.json`
- `repair_plan.md`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Forward evidence may display `invalid_trade_forensics_status`, `invalid_trade_count`, `invalid_trade_root_cause`, `invalid_trade_repair_plan_available`, and `micro_v2_invalid_trade_recommended_next_action`. These fields are advisory only. The repair plan is always not applied in this phase and cannot modify SQLite or close paper trades.

## Micro V2 Guarded Paper-State Repair

Phase 65 adds `micro-v2-guarded-paper-state-repair`, a protected paper-only repair flow for quarantining a deterministic invalid V2 paper trade. Reports include:

- `micro_v2_guarded_paper_state_repair_summary.json`
- `repair_before_snapshot.json`
- `repair_after_snapshot.json`
- `sqlite_backup_manifest.json`
- `quarantine_event.json`
- `repair_validation.json`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Forward evidence may display `micro_v2_guarded_repair_status`, repaired trade ids, quarantined trade count, backup status, repair applied status, and the recommended next action. The only permitted applied action is quarantine of the invalid V2 paper trade; it does not create a closed trade or realized PnL.

## Micro V2 Post-Repair Resume Guard

Phase 66 adds `micro-v2-post-repair-resume-guard`, an offline/read-only pack and runtime policy for the post-quarantine daily-risk open-trade deadlock. Reports include:

- `micro_v2_post_repair_resume_guard_summary.json`
- `lifecycle_recheck.json`
- `daily_risk_block_diagnosis.json`
- `resume_guard_policy.json`
- `manage_open_trades_only_policy.json`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Forward evidence may display the post-repair resume status, open/invalid trade counts, whether manage-open-trades-only is enabled, whether new entries are blocked, whether paper exit evaluation is allowed, and the recommended next action. The policy is V2-only and does not permit new paper entries or demo/live execution.

## Micro V2 PaperTrade Schema Repair

Phase 67 adds `micro-v2-papertrade-schema-repair`, a dry-run-first report pack for PaperTrade schema compatibility. Reports include:

- `micro_v2_papertrade_schema_repair_summary.json`
- `schema_field_audit.json`
- `papertrade_loader_audit.json`
- `extra_fields_detected.json`
- `post_exit_state_audit.json`
- `sqlite_backup_manifest.json` when apply is used
- `repair_validation.json`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Forward-compatible fields such as `invalid_close`, `quarantine_reason`, `repair_id`, and audit flags are preserved as metadata during loading. They do not authorize execution, do not create paper PnL, and do not change risk/acceptance gates.

## Micro V2 Daily Drawdown State Recovery

Phase 68 adds `micro-v2-daily-drawdown-state-recovery`, an offline/read-only evidence pack for V2 `PAPER_DAILY_DRAWDOWN_HALT` and `PAPER_STATE_ERROR`. Reports include:

- `micro_v2_daily_drawdown_state_recovery_summary.json`
- `daily_risk_ledger_audit.json`
- `paper_state_error_audit.json`
- `closed_trade_integrity_audit.json`
- `open_trade_integrity_audit.json`
- `drawdown_recovery_plan.json`
- `repair_validation.json`
- `sqlite_backup_manifest.json` when apply is used
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

Legitimate drawdown from closed paper losses is not a false positive and must not be cleared automatically. Quarantined trades must not contribute PnL or closed-trade counts. The pack is advisory and cannot authorize demo/live or skip risk gates.

## Micro V2 Guarded Open Trade Integrity Repair

Phase 69 adds `micro-v2-guarded-open-trade-integrity-repair`, a guarded V2-only repair pack for invalid open paper trades. Reports include:

- `micro_v2_guarded_open_trade_integrity_repair_summary.json`
- `repair_before_snapshot.json`
- `repair_after_snapshot.json`
- `invalid_open_trades_targeted.csv`
- `sqlite_backup_manifest.json`
- `quarantine_events.json`
- `repair_validation.json`
- `recommended_commands.md`
- `recommendations.md`
- `report.html`

The only permitted applied action is paper-only quarantine of invalid open trades. It must not create normal close fields, realized PnL, closed paper trades, win/loss counts, or demo/live permissions.

### FASE 70 - Micro V2 Closed Loss Evidence

The evidence pack now includes a read-only Micro V2 closed-loss scope decision. Expected artifacts live in `data/reports/micro_v2_closed_loss_scope_decision/` and include the summary JSON, closed trade attribution CSV, quarantine exclusion audit, drawdown legitimacy audit, daily risk scope audit, next-action decision, recommended commands, and HTML report.

The pack preserves historical evidence and does not rewrite SQLite, logs, ledgers, paper trades, raw PnL, or scaled PnL. It is intended to explain whether an active daily halt is caused by legitimate closed scaled paper losses rather than quarantined or repaired trades.

### FASE 71 - Daily Risk Scope Evidence

The evidence pack includes `data/reports/micro_v2_daily_risk_scope_repair/` with the repair summary, ledger scope audit, repair plan, backup manifest, validation report, recommended commands, recommendations, and HTML report. This evidence proves whether BALANCED_STABLE_MICRO_V2 has isolated daily-risk ledger scope without modifying paper trades or clearing legitimate drawdown halts.

# Operable forward-shadow paper observation

Date: 2026-10-10. Touches: risk evidence for paper decisions, paper lifecycle
control flow, observability and tooling. No order path: broker execution stays
removed (`2026-10-05-broker-execution-release-lock.md`), `DEMO_ONLY=True`.

## Context

An operational audit ran every safe mode and verified each finding
adversarially. Forward-shadow, the mode that must produce the Phase 8 forward
evidence of the Strategy Promotion Gate, could not:

1. Any failure latched `paper_lifecycle_halted` permanently, including a closed
   terminal, a missing `MetaTrader5` package, a weekend without quotes or a
   slow read. Each later run on that SQLite stopped with
   `PAPER_LIFECYCLE_HALTED`; nothing clears the latch.
2. The CLI built `ForwardShadowBot` without a decision evidence provider, so
   every candidate was rejected with `BROKER_EVIDENCE_MISSING` before strategy
   evaluation. No paper trade could ever open.
3. The timestamp audit read the boolean `heartbeat_written` as a timestamp, so
   `forward-acceptance` reported `NEEDS_TELEMETRY_FIX` on every healthy run.
4. Every mode exited 0, so wrappers and watchdogs could not tell a failure.

## Decision

- **Skip before mutation, live only.** The lifecycle writes
  `paper_cycle_in_progress` before the first financial mutation. Failures before
  that point whose codes are in `SKIPPABLE_BEFORE_MUTATION` are audited as
  `PAPER_CYCLE_SKIPPED`, mutate nothing and do not latch; the live run backs off
  (cycle seconds doubling up to 300 s) and retries. The set covers MT5 not
  connected or not installed, unreadable account, stale observation or
  acquisition, no quotes and an open position without a quote. A timestamp
  ahead of the clock under any of these codes is an integrity failure and still
  latches (`PaperCycleRejected.future`). The MT5 connection is (re)established
  inside the loop, so a terminal closed at startup or restarted later is retried
  with the same backoff instead of ending the run. Everything else keeps the
  durable latch: a previous latch or unfinished cycle, a failure to
  audit the skip, real account, invalid or changed account identity, quote
  integrity, reversed or duplicate events, storage and audit failures. The
  stateful replay passes `skip_pre_mutation_failures=False`: a recorded event
  without quotes is an input defect there, and its tests keep halting.
- **Measured decision evidence.** `paper_trading/live_decision_evidence.py`
  (`live_decision_evidence_v1`) is wired by the CLI. Each cycle it records, per
  symbol, the timeframes actually read, the tick and rates read latencies and the
  closed M5 closes (the forming bar is dropped). The readiness score is the
  existing `score_symbol_readiness` over that cycle's quote, metadata, account
  permission, tick age and latencies. The correlation passed to the pipeline is
  the largest-magnitude Pearson correlation of M5 log returns (last 300 closed
  bars, at least 100 overlapping returns) with every exposed symbol; the same
  symbol counts as 1.0. Nothing is defaulted: an unobserved symbol gets no
  evidence and an unmeasurable exposure gets `correlation=None`, which the
  lifecycle rejects. The existing ranker and portfolio guard thresholds decide.
- `score_symbol_readiness` no longer treats a zero stops/freeze level as
  unavailable (it is valid on many brokers) and no longer treats a missing spread
  as zero (it now scores as above the limit).
- Timestamp audit: leaf keys ending in `_written`, `_recent`, `_stale`,
  `_attempted` or `_age_seconds` are not timestamp fields; a boolean in a real
  timestamp field still blocks.
- Exit codes: `forward-shadow` 4 when the lifecycle is latched, 3 without MT5 and
  without completed cycles; `mt5-data`/`mt5-diagnose` 3 without MT5.
- Tooling: `scripts/stop_forward_shadow.ps1` pauses the given SQLite and stops
  the generic watchdog and run; `windows_setup.ps1` resolves the repository root
  and installs with `constraints.txt`, the single list of CI-validated versions;
  the native math runner takes `-PythonVersion` (default `3`); profile names are
  no longer masked by the audit redaction.

## Limits

Paper evidence only. A green forward-shadow run says nothing about live fills.
The readiness score keeps its historical weights, and the correlation uses the
symbols configured for the run: an open position on an unconfigured symbol blocks
new entries until it closes. Latches written before this change are not cleared;
such a SQLite must be replaced or reviewed with the paper-state tools.

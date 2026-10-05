# Shared decision core verification

Scope: strategy orchestration, risk, ML, portfolio, paper limits and durable
forward audit. The core builds candidate signals only. It neither constructs
execution requests nor calls a broker order API. Accepted output remains subject
to final durable decision auditing and paper fill validation.

The API is `core.decision.SharedDecisionPipeline.evaluate(DecisionContext)`.
Every context field is required; unavailable values produce a rejection. The
caller supplies the account, current paper book, both drawdown references,
configuration, timestamps, actual observed spread percentile, broker readiness
and correlation when positions are present. A declared feature availability
time must include all source data used. An approved ML artifact must have been
created by the decision cutoff. `PAPER_ALLOW_DISABLED_ML=False` is the default;
explicit research configuration may permit `ML_DISABLED`. `ML_ERROR` always
rejects. The context policy must agree with configuration.

Feature age may not exceed one declared timeframe duration plus the configured
snapshot tolerance. Thus a fresh quote cannot revive stale historical features.
When feature metadata includes source/open or availability timestamps, they
must agree with the context and the bar duration. Unknown durations reject.

The stage order is inputs, ensemble strategy, profile thresholds, stable filters,
candidate construction, durable signal audit, risk, ML, rank, portfolio, dynamic
risk, paper limits and risk adjustment. Every downstream stage is recorded as
`skipped` with the stopping stage and rejection code. Delegate exceptions reject
without exposing their free-form message. Later rejection revokes any earlier
RiskDecision approval. Successful signal persistence must return literal `True`.

The strategy, risk, ML, ranker, portfolio, dynamic allocator and paper policy are
the existing implementations. Profile/stability policy is shared with historical
research. The pure price builder preserves the existing 100-point minimum stop
and 1.8 reward/risk ratio, with measured closed-bar ATR required. Reduced lots
are rounded down through the existing broker volume helper; preexisting exposure
is not reduced together with the candidate.

The real `ForwardShadowBot._scan_new_paper_trades` now obtains a persisted paper
capital state, calls `_evaluate_paper_decision`, persists the complete decision,
then permits paper fills. Missing quality evidence blocks new entries. The
optional evidence provider has signature `(snapshot, features, open_trades)` and
returns observed `broker_readiness_score`/`correlation`; it must not invent
quality scores. All profiles, including MICRO_V2, run explicit configured paper
trade limits. Paper fills receive the injected clock. Existing books lacking
verifiable capital/PnL provenance require reconciliation; they are never reset
to a fictitious empty account.

All signal-related forward events populate the indexed `signal_id` column and
share `run_id:signal_id` correlation. A canonical payload fingerprint separates
changed reevaluations in the event idempotency key, while identical retries
remain deduplicated. This preserves both an initial approval and a later
rejection of the same candidate.

The forward loop refreshes the complete marked paper book after position
management and new-entry scans on every cycle, including cycles with no valid
signal. Metrics and alerts receive the same injected clock. Failed valuation
refresh explicitly produces `UNKNOWN` and null risk percentages; the previous
legacy-halt override cannot replace current drawdown with zero.

Run from the isolated worktree:

```powershell
py -3.14 -B -m pytest tests/python/test_shared_decision_core.py tests/python/test_recorded_decision_replay.py tests/python/test_phase11_ml_filter.py tests/python/test_phase12_portfolio.py
```

Fixtures cover direct equivalence to existing modules, deterministic identity,
actual forward `_evaluate_paper_decision` and `_scan_new_paper_trades` paths,
durable audit ordering, future feature/state/model cutoffs, absent context,
disabled/error ML, missing profile scores, drawdown rejection, downstream skipped
reasons, zero/invalid multiplier, broker-step rounding and preservation of
preexisting risk. Temporary SQLite/JSONL/model directories are used; no terminal
connection, broker operation or outgoing message is performed.

The recorded-replay differential fixtures call the actual forward adapter and
`backtesting.decision_replay.replay_decisions` with separate temporary stores.
They compare complete decisions and all trace stages for acceptance, spread and
daily drawdown blocks, disabled/error ML, correlation rejection and future data.
These fixtures use the real ensemble and shared candidate builder. Separate
cases verify that failed replay result auditing revokes approval and prevents
evaluation of subsequent records, and that identity/order errors are rejected.

Limitations: the ranker still evaluates one candidate at a time (`top_n=1`),
matching the forward scanning policy; this is not a simultaneous cross-symbol
competition. Dependency injection and a shared trace are not by themselves proof
of parity of complete datasets, model artifacts, persistence, fill timing,
broker metadata or portfolio transitions. Historical callers must independently
supply causally valid state and must not label a component test as complete
pipeline parity. No profitability or promotion claim follows from these tests.

# Stateful explicit-quote replay validation

`backtesting.stateful_replay.run_stateful_replay` drives the actual forward
decision caller, paper position manager, persisted capital ledger, risk limits
and fill simulator with one injected `FrozenClock`. Input is a chronological
sequence of explicit bid/ask observations and optional closed-bar decisions.
Canonical bar columns are `timestamp_utc`, `open`, `high`, `low`, `close`,
`volume`, `spread_points`. Bar extrema are never turned into synthetic ticks.

An isolated, new output directory contains fsynced inputs, instrument snapshot,
effective configuration/model thresholds/fill assumptions, `RunManifest`,
SQLite, JSONL audit and a sealed result. The manifest includes source-tree and
commit provenance, package versions, dataset and instrument hashes. A supplied
model is used explicitly; replay never loads the latest model from another run.
Model availability is checked before inference. Disabled ML requires explicit
research policy. Hashes demonstrate consistency, not instrument authenticity.

The actual pipeline evaluates candidates sequentially. It does not perform a
simultaneous cross-symbol ranking. One created trade consumes its stable
symbol/closed-bar/profile identity, even after closing; a rejected decision can
be retried. Both forward scanning and replay call the same persisted-history
deduplication helper. Direct manager calls continue to reject changed intents.

Every open symbol requires a matching fresh quote with matching frozen metadata
on the observed tick grid before lifecycle mutation. All paper capital and
exposure are computed from that replay's own ledger. Midnight-spanning exposure
requires an explicit event exactly at 00:00 UTC, with every quote exactly at
that boundary; existing references and same-day halts cannot be reset.

Each event has distinct durable received/completed audit records. Signal,
decision and fill-risk audit failures halt the replay and mark audit incomplete.
Aborted-event approvals are revoked in the returned result; decisions from
previous completed events remain intact. A trade persisted before a later audit
failure remains visible as an actual simulated book mutation. No rollback is
falsely claimed. Paper lifecycle audit timestamps use the economic quote time;
database ingestion timestamps may separately use wall time and are not inputs
to the decision logic.

Regression suites (all temporary stores; no terminal or outgoing messages):

```powershell
py -3.14 -B -m pytest tests/python/test_stateful_replay.py tests/python/test_stateful_replay_review.py tests/python/test_paper_daily_boundary.py tests/python/test_stateful_replay_io.py tests/python/test_paper_decision_state.py
py -3.14 -B -m pytest tests/python/test_shared_price_grid.py tests/python/test_paper_fill_risk_reconciliation.py tests/python/test_paper_fill_freshness.py tests/python/test_phase8_forward_shadow.py tests/python/test_phase11_ml_filter.py tests/python/test_phase12_portfolio.py tests/python/test_recorded_decision_replay.py
```

The synthetic oscillating-bar fixture exercises the real feature builder,
ensemble, profile policy, risk and portfolio components, entry, mark, stop exit,
costs and realized capital. Separate cases cover deterministic economic outputs
despite random stored trade IDs, missing/future metadata, missing quotes and
correlation, broker volume and price grids, model cutoff, trade/risk caps,
rollover, storage failure and consumed/retryable identities.

This verifies specified stateful paper paths. It is not historical profitability
evidence, executable demo readiness, full dataset parity, or proof of broker
fill behavior. Sparse quote streams leave the market path between observations
unknown. The legacy OHLC engine retains a separate lifecycle and must not inherit
the replay's validation scope or promotion status.

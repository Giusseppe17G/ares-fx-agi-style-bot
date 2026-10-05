# Causal backtests, spread evidence and honest parity

Date: 2026-10-05. Base: fe73f7cf1f5631e95b71feb73fc589042b1059f2.
Status: implemented for offline research and shared paper fill simulation.
Areas: backtesting, execution simulation, observability. No broker execution changes.

## Context and decision

The phase-82 generator used candle close/high/low and indicators, but timestamped
the candidate at candle open. The default simulator could enter and exit before
the decision inputs existed, recording a previous TP as an achievable profit.

Add optional `TradeCandidate.available_at_utc`. Generated signals always set it
to source open plus explicit fixed timeframe duration. Simulation uses the first
open at or after availability, excluding preceding bars from exits and MAE/MFE.
The final source candle can generate a candidate, but cannot fill without a later
eligible opening. Invalid availability, unknown duration or a historical
entry-price override on these market candidates causes rejection.
Decision sessions use availability. Source time, availability and entry timing
are retained in simulated trade metadata.

Compatibility: external candidates without availability retain event-at-open
semantics and `use_next_bar_open`. When supplied, availability is authoritative;
the switch does not add a second bar of delay. This input contract is not proof
of data provenance. Engine version is 0.2.0; historical results need reevaluation.

The shared spread estimator distinguishes zero from missing data. Supplied values
must be finite and non-negative. Missing/invalid evidence blocks fills with
SPREAD_DATA_MISSING/INVALID. Zero is permitted by the MarketSnapshot contract,
never manufactured from missing data. The configured maximum is inclusive.
The symbols, by_symbol and flat profile formats are resolved correctly.

The backtester passes its configured spread limit to SharedFillModel, replacing
the inflated observed-spread-plus-ten limit. The invented 0.1 zero-spread
workaround is removed. Both entry and exit costs use the shared adapter,
including rounding. Price-only replay uses a fixed epoch, not wall-clock time.
Non-finite lot, SL/TP, cost assumptions and bar spreads cannot produce fills.

## Evidence scope

The parity fixture calls components twice; it does not invoke both complete
decision loops. A 100% comparable-decision score is only a component smoke test.
Overall status is PARITY_INCOMPLETE and full_pipeline_verified=false.
Empty evidence cannot pass; unequal fixture lengths fail instead of truncating.

Market data, persistence and metrics have different implementations. They are
ADAPTER_REQUIRED. The inventory has 5/16 shared implementations (31.25%), eight
one-sided stages and three adapters requiring equivalence evidence. This corrects
the old 8/16 classification; it is not a measured performance regression.
The five shared implementations still require full-loop verification.

## Validation and limits

See ../testing/backtest-causality-validation.md and the regression suite.
No dependencies or third-party code added; no parameter optimization, accounts,
terminal connection, broker orders or Telegram messages used.

This is a bounded hardening step toward phase 82B, not full parity completion.
Pending: shared risk/ML/ranker/portfolio/dynamic-risk/paper-limit stateful path;
profile/stability alignment; point-in-time model artifacts; broker snapshot;
full replay; mark-to-market equity and gap/exit-cost audit. The historical
spread-CSV helper assumes a caller-supplied as-of sample; it does not establish
temporal provenance itself. Synthetic regressions do not prove a trading edge.

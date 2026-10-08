# Backtest correctness validation — 2026-10-05

Work starts from fe73f7cf1f5631e95b71feb73fc589042b1059f2, the phase-82 remote
branch, not the older main checkout. Changes are on codex/backtest-causality.

## Executed checks

- Original phase-82 full suite: 971 tests, exit 0.
- Before production edits, the new 40-case suite had 39 failures and one pass:
  reproduced temporal/spread defects and missing availability contract.
- Final regression file: 54 cases passed within the full suite. Covers actual generated entries, previous-bar
  TP versus next-bar SL, both timing switches, within-bar availability, missing
  next bars, invalid timestamps, price overrides, future perturbation, prefix
  equivalence, real indicators/regimes/ensemble, zero/missing/non-finite spreads,
  CSV input, incomplete profile fallback, profile formats, numeric geometry, shared fill limits/rounding and
  incomplete parity evidence.
- Full suite from repository root: 1025 passed in 39.64s.
- Same suite from an unrelated temporary working directory: 1025 passed in 39.65s.
- Both full runs include the phase-80 sandbox and production-data invariant tests.
- git diff --check: passed.

Commands (PowerShell; replace REPO with the absolute isolated checkout):

```powershell
py -3.14 -B -m pytest -o addopts='' -q --tb=short
py -3.14 -B -m pytest -c 'REPO\pyproject.toml' 'REPO\tests\python' -o addopts='' -q --tb=short
```

Environment used Python 3.14, NumPy 2.4.4, pandas 3.0.2, pytest 9.0.3.
Use -B because the pre-existing repository tracks some bytecode; generated
bytecode from the initial run was restored without altering source changes.

## Assumptions and limits

Tests use synthetic prices and mock MT5 clients where the existing suite requires
execution-adapter coverage. Real MT5 order_send/order_check were not invoked.
No live permissions, account whitelist, risk thresholds or strategies were
enabled/relaxed. No dependency added and no Telegram message sent.

Explicit zero is permitted by the existing MarketSnapshot contract; missing
spread is not zero. Timeframe timestamps denote bar opens. Generated candidates
use close availability. Externally supplied event-at-open candidates retain
compatibility, including the legacy timing switch.

Full-path parity remains unverified: five shared implementations out of sixteen,
eight one-sided stages and three adapter gaps. Comparable component decisions
are not an acceptance gate. Changes do not certify profitability, demo readiness,
all strategy branches, all timeframes, or real broker execution.

## Historical comparison

The original workspace contains historical CSVs under
data/runs/20260517-232501-real-data-research/historical.
No data/runtime/instruments.json snapshot was found there. The isolated checkout
contains no historical CSVs. Originals are used read-only, and outputs go to new
BEFORE and AFTER directories outside production evidence.

The final full comparison used 20,000 M5 bars per symbol (60,000 total), fixed
CONSERVATIVE defaults, one point of slippage and seven account-currency units of
round-trip commission per lot. EURUSD, GBPUSD and USDJPY each produced zero
trades and zero emitted candidates on both revisions. Profit, win rate and
drawdown values of zero in these reports are empty-sample placeholders, not
performance evidence. Status: INSUFFICIENT_TRADES. No thresholds were tuned.

Saved evidence: [before](evidence/2026-10-05-backtest-causality/before.json),
[after](evidence/2026-10-05-backtest-causality/after.json),
[parity](evidence/2026-10-05-backtest-causality/parity.json),
[root suite](evidence/2026-10-05-backtest-causality/tests-root.txt) and
[alternate-CWD suite](evidence/2026-10-05-backtest-causality/tests-alternate-cwd.txt).
All three raw dataset hashes match across BEFORE/AFTER; input histories and
pre-existing reports were not modified.

Reproduction utility: scripts/replay_backtest_correctness.py.
It records source/script/data hashes, configuration, assumed instruments,
cost provenance, rejection reasons and metrics, and refuses an existing output
directory. It always marks results operationally_eligible=false.

```powershell
py -3.14 -B 'REPO\scripts\replay_backtest_correctness.py' --source-root 'REPO' --data-dir 'HISTORY' --output-dir 'NEW_OUTPUT' --code-commit fe73f7cf1f5631e95b71feb73fc589042b1059f2
```

For BEFORE, use an archive of the declared base commit as source-root. For AFTER,
use the changed checkout and compare source_tree_sha256; base_commit identifies
the starting commit, not a claim that uncommitted changes equal that revision.
No metadata or illustrative costs from these diagnostics qualify as verified
broker evidence. Do not tune parameters against these comparisons.

## CLI evidence

backtest-live-parity returned PARITY_INCOMPLETE, decision_parity_status=PARITY_OK,
stage_parity_pct=31.25, decision_parity_pct=100, full_pipeline_verified=false.
execution_attempted, order_send_called and order_check_called were all false.

## Files changed and remaining work

- src/python/agi_style_forex_bot_mt5/backtesting/backtester.py: availability,
  shared entry/exit simulation and invalid-value rejection.
- execution_simulation/spread_model.py and execution_simulation/fill_model.py
  (under that package): spread evidence and rejection details.
- core/parity/pipeline_parity.py and parity_report.py: scope and truthful status.
- tests/python/test_backtest_causality.py and test_phase82_backtest_live_parity.py:
  regressions and corrected parity assertions.
- scripts/replay_backtest_correctness.py: repeatable historical diagnostic.
- PROJECT_SPEC.md, README.md, docs/QA_IMPLEMENTATION_REPORT.md,
  docs/FORWARD_SHADOW_EVIDENCE_PACK.md, the dated benchmark and decision documents,
  and this validation record: contracts, references and evidence limits.

Required next work is full stateful decision-path integration and broker/model
provenance, before strategy performance comparisons can support promotion.
Neither phase 82B nor operational acceptance is marked complete.

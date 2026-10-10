# Native mathematical fixture wrapper

Date: 2026-10-05. Contract: PROJECT_SPEC section 17.11.
Superseded in part on 2026-10-10: wrapper `native_math_harness_v2` adds the
risk gate stage (1433), for four stages, eleven records and 3915 assertions,
staged beside seven harness/fixture files. Counts below describe v1; see
`docs/decisions/2026-10-10-native-math-log-parser.md`.
Scope: test tooling and observability only. Trading release remains blocked.

## Decision

`tests/mt5/NativeMathHarness.mq5` includes the three existing script harnesses
without editing their assertions, fixtures or production implementations.
Temporary, suite-specific macros rename `OnStart`, `Check`, `checks` and
`failures`; every macro is undefined immediately after its include. Generated
fixture includes retain their existing guards and distinct helper names. The
wrapper must be staged beside all five included harness/fixture files so quoted
include paths resolve without transformation. Source hashes at creation are in
the wrapper header; the runner must bind the actual complete include graph and
EX5 in its manifest rather than treating those comments as runtime attestation.

Expected assertions are fixed at observer 31, closed bars 1103 and core
indicators 1348, total 2482. Any changed count requires a reviewed update. The
wrapper adds lifecycle checks separately, never inflating these assertion counts.

The official [preprocessor documentation](https://www.mql5.com/en/docs/basis/preprosessor/compilation)
states that properties inside included files are ignored. In particular the
observer script's `script_show_inputs` is not a wrapper property. Renaming its
`OnStart` leaves callable fixture code; the wrapper supplies the actual Tester
event handlers. Its compatibility still requires compilation of this combined
translation unit.

## Lifecycle and evidence

`OnInit` requires `MQL_TESTER` and rejects optimization, visual, forward and
optimization-frame modes. It runs no fixture yet. `OnTick` only records and
rejects an unexpected tick, without reading prices. `OnTester` revalidates the
context, requires zero delivered ticks, and calls each original suite exactly
once. It returns the logical score 1.0 on full success and 0.0 otherwise; these
values have no financial meaning. `OnDeinit` emits the final result even after
an initialization rejection. A runtime abort that prevents the final message
cannot produce complete evidence.

The documented [MQL program properties](https://www.mql5.com/en/docs/constants/environment_state/mql5_programm_info)
do not provide a property for the selected tester model. `model_verified_in_mql`
therefore remains false. The separate runner must require and verify `Model=3`
in its bound configuration. Zero delivered ticks alone does not prove that mode.
MetaQuotes documents that [mathematical mode](https://www.metatrader5.com/en/terminal/help/algotrading/testing)
does not download history or symbol information and invokes only `OnInit`,
`OnTester` and `OnDeinit`, without tick generation. This describes the intended
execution mode; it is not evidence that a fresh terminal has successfully run it.

Wrapper log records use these unambiguous prefixes:

- `AGI_NATIVE_MATH_BEGIN`: version, expected total and required model.
- `AGI_NATIVE_MATH_STAGE`: observer, closed_bars and core_indicators in that
  order (`name`), each with actual/expected checks, failures and accepted.
- `AGI_NATIVE_MATH_TOTAL`: summed checks/failures, wrapper_failures, stages,
  delivered ticks and accepted, after the three suites return.
- `AGI_NATIVE_MATH_COMPLETE`: completed and accepted separately, the same
  counters, and the deinitialization reason (`reason`). Completed=1 means all
  three suites returned, including a run with assertion failures; only
  accepted=1 means the wrapper checks succeeded. No particular deinitialization
  reason is assumed to prove success; the runner also requires complete process
  evidence and the bound mathematical-mode configuration.
- `AGI_NATIVE_MATH_REJECT`: a controlled context or lifecycle rejection reason.

Every wrapper record includes execution_authorized=false and
full_pipeline_verified=false. Existing assertion diagnostics and suite summaries
are preserved. The runner must require all stages, exact counts, zero failures,
zero wrapper failures, zero ticks, completed=1, accepted=1 and the final
record. Missing, duplicated, inconsistent, truncated or timed-out evidence is
not a pass. A successful compiler exit or Tester score alone is insufficient.

## Capabilities and limits

No account, terminal identity, symbol, history or quote acquisition is called by
the wrapper or invoked fixture paths. There is no network, DLL, file access or
trading call on those paths. The observer harness already includes JsonlAudit
for its pure JSON formatting functions; its file-writing class is not
instantiated or invoked. This is a reachable-call-path restriction, not a claim
that every transitive source file lacks unused storage APIs.

No existing EA, script or public production contract changes. This wrapper adds
no dependencies. Runtime success, if separately established, is limited to these
synthetic fixtures in the bound MQL build. It does not verify broker data,
real-clock provenance, allocation failure, financial performance, operational
readiness, or the Strategy Promotion Gate. Portable storage is not a network
sandbox. Compiler and terminal execution remain separate verification steps.

At implementation handoff the wrapper has not been compiled or executed by its
author. The root agent owns compilation, runner verification, Python guards and
any separately authorized runtime attempt. No terminal/profile data was read or
copied while implementing this wrapper.

# Native math log parser and Python guards

Date: 2026-10-10. Contract: PROJECT_SPEC section 17.11.
Follows: `2026-10-05-native-math-harness.md`.
Scope: test tooling and observability only. Trading release remains blocked.
Touches: backtesting/verification tooling. No strategy, risk, execution or EA
source changes.

## Context

`scripts/run_native_math_harness.ps1` hashes and invokes
`scripts/check_native_math_logs.py`, but that parser was not part of the
previous handoff. The runner therefore threw before launching anything. The
wrapper ADR also left Python guards to the root agent.

## Decision

`check_native_math_logs.py` uses only the standard library and is run as
`py -3.14 -I -B ... --stage <staging> --output <new json>`.

- Sources: every `.log` file inside the staging except the wrapper compile log
  `MQL5/Experts/NativeMathHarness/NativeMathHarness.log`. Files are grouped by
  directory and read in file-name order, so daily rotation inside one directory
  is one logical source. The exact MT5 location of Tester agent and journal
  logs is not assumed. Every source containing records must carry the identical
  record sequence; partial or different mirrors are `LOG_SOURCES_INCONSISTENT`,
  never merged or chosen. Links, junctions, unreadable directories or files,
  more than 256 log files, files over 64 MiB and non-strict decoding fail
  closed instead of being skipped. UTF-16LE with BOM (the MetaEditor
  form preserved in earlier evidence), UTF-16BE/UTF-8 with BOM, BOM-less UTF-16LE
  and strict UTF-8 are accepted.
- Records: a record token starts a line or follows whitespace. Grammar, key
  order and literal values come from the wrapper `PrintFormat` strings and the
  three suite summaries. Unknown `AGI_NATIVE_MATH_*` kinds, extra or reordered
  fields, double spaces, leading zeros, out-of-range integers, a true
  `execution_authorized`/`full_pipeline_verified`/`model_verified_in_mql` or a
  different version/model are `MALFORMED_RECORD`.
- Verdict: one exact nine-record run passes: BEGIN, three suite summaries each
  followed by its accepted stage (31, 1103, 1348), TOTAL 2482 with zero failures,
  ticks and wrapper failures, and COMPLETE with completed=1. The deinitialization
  reason is recorded as any integer and is not success proof. Rejection records,
  assertion failures, missing completion, duplicates, records after completion
  and any field difference fail with a specific reason and first mismatch.
- Configuration: `native-math.ini` in the staging must be strict INI with
  `Model=3`, no optimization, forward, visual, remote or cloud agents, the
  harness expert, live trading and DLL disabled, and no `Login`, `Password`,
  `Server` or `CertPassword` entry anywhere. Sections and keys compare
  case-insensitively, so a differently cased duplicate is invalid rather than
  shadowing a required value. A clean log never overrides an invalid
  configuration.
- Evidence: schema `native_math_log_evidence_v1`, stage-relative paths and
  hashes only, at most 200 records and 100 assertion labels.
  `execution_authorized`, `full_pipeline_verified`, `promotion_eligible` and
  `model_verified_in_mql` are always false. The output is created exclusively;
  an existing path is not overwritten (exit 2). Exit 0 only when passed, else 1.

Runner corrections: the compile check is anchored to
`(?m)^Result: 0 errors, 0 warnings,` because the previous substring also matched
`10 errors, 0 warnings`; the parser runs with `-I` so environment paths and user
site packages cannot affect it.

`tests/python/test_native_math_harness.py` cross-checks parser grammar against
wrapper and suite format strings, expected counts against wrapper constants and
static `Check` calls, the exact macro rename/undef blocks, shared header include
guards, absence of renamed identifiers in shared headers, collision-free suite
definitions, the runner's staged file list, bound configuration, process
ownership and verdict clauses. Header hashes in the wrapper comment match the
committed sources modulo line endings: `ClosedBarWindowHarness.mq5` was hashed as
CRLF bytes, the other four as LF. They remain informational; the runner hashes
the actual staged bytes.

## Limits

No MetaEditor compile or terminal run was performed for this change; the
environment is Linux without MetaTrader. The parser's directory assumptions,
whether the journal mirrors every agent line, whether a portable terminal starts
the math-mode test without an account or symbol, and the real exit code remain
unverified until a separately authorized Windows run. If mirrors differ, the
run fails closed and a reviewed update must choose the authoritative source. A
pass would still only verify these synthetic fixtures in one MQL build; it does
not verify broker data, real clock provenance, allocation failure, financial
performance, execution or the Strategy Promotion Gate.

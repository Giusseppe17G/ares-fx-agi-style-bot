# Native math log parser and Python guards

Date: 2026-10-10. Contract: PROJECT_SPEC section 17.11.
Follows: `2026-10-05-native-math-harness.md`.
Scope: test tooling and observability only. Trading release remains blocked.
Touches: backtesting/verification tooling. No strategy, risk, execution or EA
source changes.

## Context

`scripts/run_native_math_harness.ps1` hashes and invokes
`scripts/check_native_math_logs.py`, but that parser was not part of the
previous handoff. The runner therefore compiled the wrapper and copied the
public binaries into a new staging, then threw while hashing the missing
parser, before starting the terminal. The
wrapper ADR also left Python guards to the root agent.

## Decision

`check_native_math_logs.py` uses only the standard library and is run as
`py -<PythonVersion> -I -S -B ... --stage <staging> --output <new json>` (default `-3`; the stdlib-only parser gives identical evidence on CPython 3.11-3.14, and the manifest records the interpreter version).

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

## Addendum: wrapper v2 and review hardening (2026-10-10)

- The wrapper is now `native_math_harness_v2` with a fourth stage, `risk_gate`
  (1433 assertions, PROJECT_SPEC 17.12). The exact accepted sequence has eleven
  records and TOTAL/COMPLETE carry 3915 checks and four stages. A v1 record is
  malformed for this parser.
- Records in two `Tester/Agent-*/logs` directories are two runs
  (`DUPLICATE_AGENT_RUN`), even if identical; only other directories may mirror.
- The CLI passes `--stage` through `absolute()`, not `resolve()`, so a linked
  stage reaches the link check and reports `STAGE_MISSING`.
- Unreadable directories (`os.walk` errors) and unreadable files fail as
  `LOG_DIRECTORY_UNREADABLE` / `LOG_UNREADABLE` instead of being skipped.
- The runner starts with `#Requires -Version 7.0` because
  `[IO.Path]::GetRelativePath` needs .NET Core; a stop during cleanup of a
  process that already exited is ignored and the re-enumeration decides
  `cleanup_verified`; parser invocation and binding checks are wrapped so a
  missing `py` launcher is recorded; the final reason names the first failed
  gate. `compile_native_observer.ps1` gets the same `#Requires` and anchored
  compile-result check.
- PowerShell syntax of every `scripts/*.ps1` was checked with the PowerShell 7.4.6
  parser. It found a pre-existing parse error in `scripts/healthcheck.ps1`
  (`"$Level: $Message"` is a drive-qualified variable), fixed as
  `"${Level}: $Message"` and guarded by a Python test over all scripts.


# Native compilation evidence: 2026-10-05

Final build time: 2026-10-05T10:04:00.9785507Z.
Compiler: MetaEditor 5.0.0.5833. All three targets reported zero errors and zero
warnings and produced new binaries. The compiler's exit code was 1; success is
based on its diagnostic logs and binary existence, not the exit code alone.

Files are byte-for-byte copies from the retained isolated staging directory:

```text
C:\Users\user\AppData\Local\Temp\agi-native-observer-69a632d3a51b438280eb3f4dccc7804b
```

- `compile-manifest.json`: source/compiler/build-script/binary/raw-log hashes.
- `AGI_STYLE_FOREX_BOT_MT5.log`: unchanged observer EA build.
- `ObservationPolicyHarness.log`: existing observation fixture build.
- `ClosedBarWindowHarness.log`: new closed-bar fixture build.

Raw logs retain MetaEditor's original encoding. Each log basename corresponds
to the same basename in `results[].source` in the manifest; its bytes match
`results[].log_sha256`. All source hashes and the build-script hash matched the
worktree when this evidence was copied. Binaries stay outside the repository.

The new harness contains 64 generated cases, with 1,095 generated assertion
call sites and eight handwritten call sites. **None of these MQL assertions
has been executed.** The separate Python fixture/reference/source suite passed
130 tests, as recorded in the linked testing document. Compiling fixtures is
not evidence that their native behavior passed those assertions.

No terminal was started, no EA or script was installed, no broker connection
was made, and no execution authorization was granted. Release remains BLOCKED;
full pipeline parity, MQL runtime correctness, allocation-failure behavior and
UTC/source authenticity remain unverified by this build.

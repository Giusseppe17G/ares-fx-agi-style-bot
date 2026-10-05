# Core indicator compilation evidence

MetaEditor 5.0.0.5833 compiled four targets with zero errors and zero warnings:
the observer EA, ObservationPolicyHarness, ClosedBarWindowHarness and
CoreIndicatorsHarness. Each produced a new EX5 in a new isolated directory.
The manifest records the exact UTC time, source/build/compiler/binary/log hashes.
Compiler exit code 1 alone is not used as a success or failure indicator.

Root independently verified 21 source hashes, build script, four original logs
and four binaries. The manifest and logs preserve the original bytes from:

```text
C:\Users\user\AppData\Local\Temp\agi-native-observer-7d777595d4294b3a8e2c89e2e0b288dc
```

The new core indicator fixtures contain 49 synthetic cases, 16 histories,
23 expected bundle acceptances, 26 expected rejections and 1,348 generated
assertion call sites. The separate Python suite passed 98 tests and the
generator passed exact-byte `--check`. These tests exercise the actual Python
reference functions and static native restrictions, not the MQL runtime.

The full Python suite passed 2,447 tests in 190.11 seconds, with two expected
warnings in the intentional monetary-overflow rejection regression. Full log:
`../2026-10-05-shared-pipeline/tests-core-indicators-vwap-root.txt`.

No native assertions have been executed. No terminal was started, no account
was used and no binary was installed into a terminal. Execution and promotion
remain blocked. Fixture comparisons do not establish broker provenance,
strategy quality, full feature parity or financial performance.

Compilation sources are byte-bound to this working checkout. Git newline
conversion in another checkout can change a source hash without changing its
logic; recompile there instead of attributing this build to different bytes.

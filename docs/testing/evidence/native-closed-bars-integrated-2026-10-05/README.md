# Integrated native compilation evidence

Source commit: `101b48c9cb0ff0e4fe2eb479e8b2157f7f61165f`.
Build timestamp: 2026-10-05T10:15:28.1810660Z.
MetaEditor 5.0.0.5833 compiled the observer EA and both isolated harnesses with
zero errors and zero warnings, producing a new binary for each target. Process
exit code 1 alone does not establish failure or success; diagnostics and new
binaries were checked.

The manifest and original-encoding logs were copied byte-for-byte from:

```text
C:\Users\user\AppData\Local\Temp\agi-native-observer-51f1e6883b06441dbb29120d68ae4f44
```

Root independently verified all 17 source hashes, the build script, three raw
logs and three binaries. Git line-ending conversion changed some source bytes
after integration; this evidence applies to the integrated checkout. The prior
native-worktree evidence remains unchanged in its separate directory. EX5 files
remain in isolated staging and were not installed into a terminal.

The canonical fixture generator passed `--check`; its focused Python suite
passed 108 tests. The full premerge suite passed 2,323 tests, as preserved in
`../2026-10-05-shared-pipeline/tests-native-closed-bars-root.txt`.

No terminal, broker, account or native harness was run. All MQL assertions are
compiled but unexecuted. Execution remains blocked, and neither source checks
nor compilation establish native runtime correctness or financial readiness.

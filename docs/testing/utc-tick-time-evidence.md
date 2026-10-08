# UTC tick evidence regression

```powershell
py -3.14 -B -m pytest tests/python/test_tick_time_provenance.py tests/python/test_phase28_mt5_time_normalization.py tests/python/test_forward_lifecycle_review.py tests/python/test_paper_managed_stop_grid.py tests/python/test_mt5_data_mode.py -o addopts= -q
```

All inputs and clients are synthetic; no terminal, broker, account session or
network is invoked by these tests. Data is written only to pytest temporary
directories.

At a fixed 12:00 UTC observation:

| Raw timestamp | Evidence | Required result |
| --- | --- | --- |
| 11:00 UTC | Quote aged 3600 seconds | STALE, reject |
| 13:00 UTC | No independent clock evidence | Future, reject |
| 13:00 UTC | Hypothetical offset7200 with real age3600 | Same ambiguous raw input, reject |
| 12:00:00.001 UTC | Future by1ms | Future, reject |
| 11:59:55 UTC | Age5 seconds under default limit | FRESH |

The two 13:00 scenarios intentionally have identical raw input. The system
cannot distinguish their origin and must not fabricate fresh UTC evidence.
Diagnostic suggestions do not authenticate an offset. Existing normalization
flags cannot restore clock conversion; original timestamps remain visible.

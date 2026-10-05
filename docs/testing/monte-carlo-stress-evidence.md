# Monte Carlo and stress evidence verification

Module scope: backtesting. Inputs in this verification are synthetic unit-test
fixtures, not market evidence and not a strategy holdout.

## Reproductions and independent expected results

For PnL `[-100, 200, -100, -100, 200]`, capital 1000 and seed 1,
the permutation is `[4,0,1,2,3]`: equity is
`[1000,1200,1100,1300,1200,1100]`, so maximum drawdown is -15.384615%.
The old implementation sorted original close timestamps and returned -18.181818%.

Appending three worst observed losses to the original chronological sequence
produces equity ending `1100,1000,900,800`, maximum drawdown -27.272727% and a
three-loss streak. The old implementation inserted copies at the first trade's
timestamp, returning -40% and a four-loss streak.

With 10 extra spread points, 3 slippage points per side, point 0.00001,
tick size 0.00005, tick value 2 and lot 0.2, additional round-trip cost is
`(10+2*3)*0.00001/0.00005*2*0.2 = 1.28`. Net PnL 100 becomes 98.72;
initial risk 50 stays 50, so new R is 1.9744.

A single -30 PnL with capital 100 crosses the 30% drawdown threshold in every
simulation, while equity remains 70. Tests explicitly verify that the compatible
`risk_of_ruin_pct` field does not mean insolvency.

## Verification command

```powershell
py -3.14 -B -m pytest tests/python/test_monte_carlo_stress_evidence.py tests/python/test_backtesting.py tests/python/test_phase19b_low_sample_quick.py tests/python/test_validation_report_fail_closed.py tests/python/test_metrics_period_baseline.py -q --disable-warnings --tb=short
```

The added suite covers ordering, both samplers, baseline and monetary recovery,
all invalid numerical/configuration classes, overflow, finite positive instrument
units, chronology, generator grids, occurrence removal, consistent R under
commission/haircut, unsupported checks, empty/all-zero samples, source immutability,
cost/data/config identity, and reproduction from exported inputs. Temporary
reports use pytest `tmp_path`; original research artifacts are not modified.

## Limits

The follow-up production-consumer compatibility suite is:

```powershell
py -3.14 -B -m pytest tests/python/test_phase7_research.py tests/python/test_monte_carlo_stress_evidence.py -q --disable-warnings --tb=short
```

87 tests passed (23 research and 64 sequence/stress). Research cases verify
completed versus unsupported counts, malformed/null/non-finite results, preserved
negative-PnL rejection, exported candidate evidence, and a deliberately favorable
fixture that still cannot become approved. That fixture is supplied directly to
the consumer and says nothing about real strategy performance. The runner's
existing same-sample train/test use and unwired candidate parameters are declared
limitations, not implemented validation.

No quote-level execution stress, session re-evaluation, fill-rate model or
strategy rerun is implemented by these two modules. IID resampling breaks serial
dependence; permutation changes order but preserves terminal total fixed PnL.
No claim of edge or promotion follows from passing software tests or positive
diagnostic classifications. Existing market periods already inspected remain
development/diagnostic data, never final holdout.

# US inflation of the forward tracking from BLS data while the World Bank lags

Date: 2026-10-24, before the first forward day (2026-10-26). Touches:
research only (`research/daily_fx/forward_inflation.py`, `forward_routine.py`).
No file of the frozen forward plan changes: the plan hash, the engine hash and
the pinned code commit stay valid. Nothing reads an account or sends an order.

## Context

The forward plan (`2026-10-23-daily-fx-value-forward-paper.md`) takes each
inflation year after 2024 from a supplement CSV, and uses a year only once
all ten series have it.

- The rebalance of 2026-09-22 needs year 2025.
- On 2026-10-24 the World Bank API (indicator FP.CPI.TOTL.ZG, last updated
  2026-10-08) had 2025 for the nine non-US series but not for the United
  States.
- The record therefore stops on 2026-09-21 and would count no forward day
  until the World Bank publishes the US value. That can take months.

For the United States, FP.CPI.TOTL.ZG is the change of the annual-average
BLS CPI-U. BLS published the 2025 average in January 2026.

## Decision

1. The supplement is written by `forward_inflation fetch-inflation`, in the
   same format the frozen tracker reads.
   - The nine non-US series always come from the World Bank.
   - A US year the World Bank has not published is computed from FRED series
     `CPIAUCNS` (CPI-U, not seasonally adjusted): the change of the
     twelve-month average, from complete years only.
2. **Checked before use.** For every year from 2015 that the World Bank has,
   the BLS value must match it within 0.02 percentage points.
   - Otherwise nothing is written (`US_CPI_MISMATCH`).
   - Published BLS annual averages match the World Bank values for
     2015-2024 within 0.0003 points.
3. **Recorded.** The sidecar JSON lists the US years taken from BLS.
4. **Fixed once used.** The tracker fixes a year's values the first time
   it uses them. A later World Bank value for the same year is ignored, as for
   any revision.

## Consequences

- The forward record starts on schedule. The indicator is the same; only the
  publisher of its US value changes, and the change was decided before any
  forward day existed.
- If the two sources ever disagree on the checked years, the download fails
  closed and the record waits, as before.
- `forward_runner fetch-inflation` (frozen) still works and still waits for
  the World Bank.

## Verification

`tests/python/test_daily_fx_forward_inflation.py`, synthetic data only. It
checks:

- complete-year averaging;
- filling a missing US year;
- keeping a published World Bank value;
- refusing a mismatch;
- the exit codes and that an existing file is never overwritten.

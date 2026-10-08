# Paper managed protection validation

Run without MT5 or network access:

```powershell
py -3.14 -B -m pytest tests/python/test_paper_managed_stop_grid.py tests/python/test_paper_accounting_and_stops.py tests/python/test_paper_decision_state.py tests/python/test_paper_fill_risk_reconciliation.py tests/python/test_forward_lifecycle_review.py -o addopts= -q
```

The focused group passed 111 tests. The real run-loop test obtains deterministic
market snapshots through a read-only fake client; only bar acquisition is
injected. Features, strategy, risk, fills, management and SQLite are real.

For initial risk of 101 ticks and excursion of 91 ticks, trailing distance
0.5R proposes 40.5 ticks of protected gain. The persisted protection is 40
ticks for BUY and SELL, never the more favorable 41 ticks. The same assertions
cover tick sizes 0.00001 and 0.00005 with point 0.00001. Break-even stays at
entry and later trailing still uses the original 101-tick risk distance.

Invalid persisted open protection is rejected without rewriting the trade.
Closed historical records are preserved. A valid grid is one prerequisite;
these tests do not demonstrate broker fills, liquidity, profitability or a
successful Strategy Promotion Gate.

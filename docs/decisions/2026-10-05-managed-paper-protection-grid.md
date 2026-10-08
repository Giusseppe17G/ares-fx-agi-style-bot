# Managed paper protection uses the broker tick grid

Status: accepted for paper research; no execution authorization.

An entry with a risk distance of 101 executable ticks and a trailing distance
of 0.5R produced a stop halfway between ticks. The initial protection/fill grid
checks did not cover later stop modifications. A real `ForwardShadowBot.run()`
episode reproduced SELL entry 1.09945, original SL 1.10046 and managed SL
1.099045 on a 0.00001 grid.

The manager now calculates excursions and trailing prices with decimal price
arithmetic. It aligns a managed BUY stop downward and a SELL stop upward to
`tick_size`. This is conservative relative to the proposed simulated profit;
it never loosens an existing valid stop. Break-even retains the executable
entry price, and subsequent trailing continues to use the original distance.
The persisted original risk amount/distance and approved lot are unchanged.

Management validates instrument price metadata and rejects existing entry,
SL or TP values outside the observed grid before a position mutation. The
paper decision-state builder also rejects such open positions with
`PAPER_PROTECTION_GRID_INVALID`. It does not round historical evidence or
restate closed trades. Invalid existing protection needs explicit review.

Public method signatures are unchanged. Previously accepted off-grid open
history now fails closed; reports from the previous behavior remain historical.
This changes paper risk/execution simulation, not strategy thresholds, trade
promotion, broker execution capability or ML models.

Verification: `test_paper_managed_stop_grid.py` covers both directions, grids
larger than `point`, break-even followed by trailing, preservation of original
risk, retracement, persisted invalid protection and invalid broker metadata.
`test_forward_lifecycle_review.py` retains the actual run-loop reproducer.

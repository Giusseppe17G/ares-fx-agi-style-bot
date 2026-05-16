# Overfit Guard

`OverfitGuard` blocks fragile candidates before they can be considered for shadow observation.

It detects:

- Train very positive while test is negative.
- Profit factor exaggerated with too few trades.
- More than `40%` of gains concentrated in the top `5%` trades.
- Performance concentrated in fewer than three days.
- Performance concentrated in one session.
- Parameter sensitivity.
- Too few trades per validation window.
- Strong stress-test deterioration.

Output:

- `overfit_risk`: `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`.
- `reasons`.
- `recommended_status`.

If risk is `HIGH` or `CRITICAL`, the candidate is rejected. If evidence is incomplete, the candidate remains `WATCHLIST` or `REJECTED`.

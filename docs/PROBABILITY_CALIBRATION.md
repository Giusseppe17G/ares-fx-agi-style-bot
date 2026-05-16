# Probability Calibration

The ML filter calibrates raw probabilities with a sigmoid calibrator using the validation/calibration split.

It reports:

- Brier score before calibration
- Brier score after calibration
- calibration error
- confusion matrix
- profit-aware metric

If calibration or sample requirements are not acceptable, the model is saved as `WATCHLIST` and is not approved for shadow filtering.

Calibration does not authorize demo execution.


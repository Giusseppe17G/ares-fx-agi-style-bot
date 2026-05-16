# Walk-Forward Validation

Walk-forward validation checks whether a strategy remains stable through time. It prevents selecting parameters on the same data used for final evaluation.

Safety remains unchanged:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Command

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode walk-forward --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\walk_forward
```

Optional window controls:

```powershell
--train-days 90 --validation-days 30 --test-days 30 --step-days 30
```

## Method

Each window is split in strict chronological order:

1. Train: parameter candidates are evaluated.
2. Validation: the best candidate is selected.
3. Test: the selected candidate is evaluated once, without re-selection.

The test window is never used to choose parameters. If data is insufficient or metrics cannot be calculated, the result is classified as `WATCHLIST` or `REJECTED`, never approved.

## Reports

Files:

- `data/reports/walk_forward/summary.json`
- `data/reports/walk_forward/windows.csv`
- `data/reports/walk_forward/selected_params.csv`
- `data/reports/walk_forward/by_symbol.csv`

Interpretation:

- Stable positive test windows matter more than strong train windows.
- Large train-to-test deterioration is an overfitting warning.
- Few trades in test windows should block approval.

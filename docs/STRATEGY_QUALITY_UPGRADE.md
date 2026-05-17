# Strategy Quality Upgrade

Phase 16 strengthens strategy context before signals reach risk, ML, portfolio, or paper trading.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send` is not called
- `order_check` is not called

## Strategy Improvements

- Trend Pullback now blocks weak/non-trend regimes, overextended price and high spread percentile.
- Mean Reversion now requires `RANGE`, rejects fresh breakout context and uncontrolled high volatility.
- Breakout Compression requires compression and candle body quality.
- Liquidity Sweep requires sweep/reclaim context and wick rejection.
- Session Momentum requires London/NY/overlap and respects H1 bias when available.
- Volatility Expansion requires real expansion and blocks spread expansion.

## Diagnostics

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode strategy-diagnose --symbol EURUSD --data-dir data\historical --report-dir data\reports\strategy_diagnostics
```

The diagnostic report shows signal, score, reasons, component scores, blocking reasons and market-structure metadata.

## Research

Research reports now include:

- `ablation_results.csv`
- `strategy_version_comparison.csv`

These compare the old reference behavior against the new context-aware strategy version and filter ablations.

## Phase 18 Calibration

If the upgraded strategy stack produces zero trades on real exported data, run signal calibration before loosening rules manually:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode signal-calibration --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\calibration
py -m agi_style_forex_bot_mt5.cli --mode threshold-sweep --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\calibration --profiles CONSERVATIVE,BALANCED,ACTIVE,RESEARCH_ONLY
```

Calibration compares profiles and explains near misses without disabling safety gates.

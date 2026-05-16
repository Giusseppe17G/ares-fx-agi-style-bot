# Market Structure

Phase 16 adds market-structure context for strategy quality checks.

The layer is research/shadow-only and cannot enable demo or live execution.

## Calculations

- Swing highs and lows.
- Higher high / higher low and lower high / lower low structure.
- Break of structure (`BULLISH`, `BEARISH`, `NONE`).
- Change of character.
- Previous day high/low.
- Asian, London and New York session ranges.
- Liquidity sweeps above/below recent highs/lows.
- Equal highs/lows approximation.
- ATR percentile, compression and expansion candles.
- Wick rejection and candle body quality.
- Distance to EMA/VWAP when available.

## Reports

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode structure-report --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\market_structure
```

Outputs:

- `structure_summary.json`
- `structure_summary.csv`
- `report.html`

If OHLC data is missing, the report fails closed rather than fabricating structure.


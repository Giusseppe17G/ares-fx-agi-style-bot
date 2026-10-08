# Corrected diagnostic: engine 0.3.1

Code: `7abf90e4cc1cc35c9c66ce8d7f215cf7145ae1d3`.
Python source SHA256: `c3cb1003ffdd9c9dd783a859c5cd601430c986428bcc70e1befcc2be4fd797d7`.
All source, script and original dataset hashes were verified after the run.
The diagnostic ran from outside the checkout with an explicit source root.

| Symbol | Trades | Net profit | Profit factor | Worst month % | Recovery |
| --- | ---: | ---: | ---: | ---: | ---: |
| EURUSD | 173 | -970 | 0.865892 | -5.9300 | -0.510258 |
| GBPUSD | 256 | -3625 | 0.720939 | -24.7371 | -0.700483 |
| USDJPY | 215 | -2095 | 0.805605 | -20.9983 | -0.606895 |

These PnL amounts use assumed account units and independent fixed-lot candidates.
They are not account returns under the full portfolio risk pipeline. Assumed
instruments and illustrative commission/slippage are not broker-verified. Input
spread statistics, effective configuration and parameters are in summary.json.
These inspected datasets are development data, never a final holdout.

Each trade CSV is identical byte-for-byte to the preserved diagnostic-9aba352
CSV. Changes here correct metric measurement and disclose evidence limits;
they do not improve fills, trade selection or net profit. No strategy is
promoted, no terminal is started and no broker order is built or sent.

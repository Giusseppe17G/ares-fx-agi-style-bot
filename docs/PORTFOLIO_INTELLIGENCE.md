# Portfolio Intelligence

Phase 12 adds a portfolio-aware layer above strategy, ML, and risk gates for `forward-shadow`.

It does not enable real trading, demo execution, or `order_send`.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- Dynamic risk never exceeds `1.0` by default.

## What It Controls

- Open paper risk across all symbols.
- Open paper trades per symbol.
- Currency exposure by base and quote currency.
- Concentration by strategy and regime.
- Correlation risk between symbols.
- Ranking when multiple signals appear in the same cycle.
- Defensive risk reduction after drawdown, loss streaks, high spread, weak broker readiness, borderline ML probability, or watchlist status.

## Forward-Shadow Flow

1. Strategy ensemble generates a signal.
2. RiskEngine validates SL, TP, spread, lot, account, audit availability, drawdown, and open risk.
3. ML Meta-Filter may reject weak setups.
4. SignalRanker ranks candidates.
5. PortfolioGuard checks exposure, correlation, concentration, and risk budget.
6. DynamicRiskAllocator reduces or maintains shadow risk.
7. Only accepted candidates become paper trades.

Audited events include:

- `SIGNAL_RANKED`
- `PORTFOLIO_DECISION`
- `CORRELATION_REJECTED`
- `EXPOSURE_REJECTED`
- `DYNAMIC_RISK_ADJUSTED`

## Reports

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode portfolio-status --sqlite data\sqlite\forward-shadow.sqlite3 --reports-root data\reports

py -m agi_style_forex_bot_mt5.cli --mode exposure-report --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\portfolio

py -m agi_style_forex_bot_mt5.cli --mode correlation-report --data-dir data\historical --output-dir data\reports\portfolio
```

Outputs include `portfolio_status.json`, `currency_exposure.csv`, `correlation_matrix.csv`, `correlation_clusters.csv`, `signal_ranking.csv`, `portfolio_decisions.csv`, and `report.html`.


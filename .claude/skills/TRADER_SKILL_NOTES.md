# Trader skill pack (vendored, research only)

Source: github.com/Jakeschincariol/trader-skill (MIT, see TRADER_SKILL_LICENSE).

These ten skills are US-equity research tools: 13F copying, Congress
disclosures, news, earnings, screening, budget sizing, risk checks, rebalancing,
tax lots and price alerts. They stand apart from the forex bot and never touch
its code, its frozen forward plan or its MT5 demo executor.

Local changes from the upstream pack:

- trader-broker is not included. It prepares orders for live brokerage
  accounts (Alpaca, Interactive Brokers), which this project does not allow
  (AGENTS.md: no live trading route). Every order the other skills write to
  the trader folder is a proposal only; nothing in this repository can send
  it.
- One backticked settings path in a skill text was unquoted for the docs lint.

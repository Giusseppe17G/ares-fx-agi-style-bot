# Demo-only MT5 execution of the forward value book

Date: 2026-10-30. Decided by the project owner. Touches: execution and risk
(`execution/release_policy.py`, `execution/value_demo_executor.py`,
`config.py`, `research/daily_fx/forward_trades.py`, `forward_routine.py`,
`forward_telegram.py`).

## Context

The release lock (`2026-10-05-broker-execution-release-lock.md`) removed every
broker execution path. The forward value book runs on paper since
2026-10-26. The owner wants that book to open and close orders on a demo
account automatically, so its behaviour can be watched in MT5.

The book has **not** passed the Strategy Promotion Gate. Plan v2 rejected it
at the deflated Sharpe gate, and the forward record has only just started.
This decision is an explicit owner exception to `AGENTS.md`, limited to a
demo account. No result of this demo authorises live trading.

## Decision

1. **Generic execution stays locked.** `execution_block_reason`,
   `ExecutionEngine` and `MT5Connector` keep refusing every order, unchanged.
2. **One gate, demo only: `demo_release_gate`.** It opens only when all of
   these hold:
   - `validate_safety` passes, with `DEMO_ONLY=True` and
     `LIVE_TRADING_APPROVED=False`;
   - `DEMO_EXECUTION_ENABLED=True` is set in the operator's configuration
     (the default is False);
   - the connected account's trade mode is demo;
   - its login is in `ALLOWED_ACCOUNT_LOGINS`;
   - the terminal and the account allow automated trading.

   A real or contest account is refused whatever the configuration. The gate
   is checked again before every order.
3. **The paper record decides; the executor only mirrors it.**
   `ValueDemoExecutor` reconciles the demo account with the book's open paper
   trades. It:
   - opens new trades;
   - closes positions whose paper trade closed;
   - moves stop loss and take-profit after a re-anchor.

   A position the broker closed (its stop loss or take-profit hit) is never
   reopened.
4. **Every order is checked before it is sent.**
   - **Stops:** the stop loss and the take-profit are always set, on the
     right side of the price, outside the stops level.
   - **Lot:** sized by `PositionSizer`: `capital × risk% / risk per lot`,
     rounded down. The risk is the paper trade's risk, capped at 0.5%.
   - **Exposure limits:**
     - open risk of the book at most 5%;
     - at most 10 positions on the account;
     - no new position past the floating or daily drawdown limits.
   - **Spread:** at most 5% of the stop distance. A fixed point limit would
     block the Scandinavian pairs of a monthly book.
5. **Audit.** Every request is appended to `data/runtime/forward/demo/demo_journal.jsonl`
   and fsynced before it is sent. Its result follows it. A state file maps
   paper trade ids to tickets. Every order and every refusal is sent to
   Telegram.

## Consequences

- MT5 triggers stops intraday, while the paper book checks them on daily
  closes. Demo and paper results can therefore differ. The paper record stays
  the evidence the decision rule uses.
- The book places few orders: it rebalances about once a month.
- Positions the book already held at the first run are opened at the current
  price, with the latest levels. A trade whose price is already beyond its
  levels waits (`LEVELS_INVALID`).

## Verification

`tests/python/test_value_demo_executor.py` runs against a fake MT5 client
only. It checks:

- the gate refuses real and contest accounts, a login that is not whitelisted,
  a disabled flag, Algo Trading turned off and unsafe configurations;
- each order's stop loss, take-profit and lot;
- the journal written before every send;
- reruns, broker closes, paper closes and re-anchors;
- the unsafe-order skips, the exposure limits and rejected orders;
- JPY pairs, sizing time and messages.

A routine test checks that execution stays off unless it is enabled, and that
a real account is refused end to end. The existing release-lock tests still
pass unchanged. No real terminal was used.

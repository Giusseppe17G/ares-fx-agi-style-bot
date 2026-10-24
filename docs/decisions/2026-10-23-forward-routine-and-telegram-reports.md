# Weekly routine and Telegram trade reports of the forward paper tracking

Date: 2026-10-23. Touches: research and observability only
(`src/python/agi_style_forex_bot_mt5/research/daily_fx/forward_trades.py`,
`forward_telegram.py`, `forward_routine.py`, `TelegramNotifier.send_text`,
`TelemetryDatabase.telegram_status`, `scripts/run_forward_tracking.ps1`,
`scripts/install_forward_tracking_task.ps1`). No strategy, risk, execution,
Expert or production behaviour changes. No file of the frozen forward plan
(`2026-10-23-daily-fx-value-forward-paper.md`) changes, so the plan hash,
the engine hash and the pinned code commit stay valid. Execution stays
removed (release-lock ADR).

## Context

The forward tracking needs a weekly run for up to ten years. That run has
three manual commands and a hand-picked inflation file. A missed week costs
nothing, but a run that is forgotten for months, or run with a stale export,
loses broker-swap coverage the confirmation rule needs.

The operator also asked for reports like those of public trading channels:
which trade opened, which closed and how, how the week ended, and wins and
losses. The ledger seals returns, closes and decisions, but no trades.

## Decision

1. **One command.** `forward_routine` runs, in order:
   - the export of the nine pairs, stopping unless all nine files were
     written;
   - the swap capture, whose failure only lowers coverage;
   - the inflation download, only when the year the signal needs is missing;
   - the tracker, from the worktree pinned at the freeze commit, with its
     own `PYTHONPATH`.

   It keeps every step's output under `data/runtime/forward/runs`.
   - Only one routine runs at a time (a lock file, replaced after three
     hours), so two runs never append to the ledger together.
   - A missing worktree, a report that cannot be written and an unsent
     Telegram message each raise an alert and a non-zero exit code. None of
     them is silent.
   - `scripts/run_forward_tracking.ps1` wraps it.
     `scripts/install_forward_tracking_task.ps1` registers a weekly Windows
     task, on Monday by default. The tracker always drops the last bar (it
     may be forming), so on Monday it counts up to Friday. On Saturday it
     would stop on Thursday.
   - The task runs only while the operator is logged on, because MT5 needs
     the desktop session. A missed run starts when the PC is next
     available.
2. **Trades from the record, checked.** `forward_trades` re-runs the book on
   the same exports and the inflation years the ledger fixed.
   - Every sealed return must be reproduced within the tracker's tolerance.
     Otherwise it refuses (`RECORD_MISMATCH`), and the frozen plan hash must
     match the ledger.
   - It then derives trades from the engine's own positions:
     - a trade opens at a rebalance;
     - it re-anchors at a later rebalance only when the engine resizes it (a
       loss halt that keeps the weight keeps the old levels);
     - it closes on a stop loss, a take-profit or a signal change.
   - The derived stop-loss and take-profit closes must equal the engine's
     counts. Otherwise it refuses (`TRADES_MISMATCH`).
   - Stop loss and take-profit are the engine's levels, shown as MT5 pair
     prices.
   - A trade's result is its gross contribution to equity on forward days
     only. Positions open before 2026-10-26 are flagged, and their pips count
     from the last close before that day, like their result.
   - The trades' results add up to the book's gross return; a test checks it.
3. **Messages.** `forward_telegram` writes:
   - the start message, and each trade opened and closed;
   - one summary per complete week:
     - the week's and the cumulative result, from the sealed net returns;
     - closed trades, wins, losses, win rate and profit factor;
     - maximum drawdown and open positions;
     - the rule's status and the broker-swap coverage;
   - the annual looks and the final status;
   - alerts that say what to do.

   Every message says it is paper and carries a disclaimer: costs are
   estimated, it is not real money and not a recommendation.
4. **Delivery once.** Each message has a stable key and goes through the
   existing durable outbox (`TelegramNotifier.send_text`).
   - It is sent once and in order, about 3 seconds apart (groups and
     channels accept about 20 messages a minute).
   - The first failure stops the run, and the rest wait for the next one.
     The channel never shows a close before its open. A retry sends the
     text stored when the message was first queued, so the outbox holds what
     was delivered.
   - Nothing is queued while Telegram is off. Turning it on later sends every
     pending message from the start, so one run without `--telegram` cannot
     suppress a message for good.
   - Text is redacted, and credentials come only from the environment.
   - Every message, with its status, is also written to
     `data/runtime/forward/telegram_messages.txt`.
   - `--test-telegram` (`-TestTelegram`) sends one test message to check the
     setup.

## Consequences

- Telegram is off unless the operator passes `--telegram` (`-Telegram`) or
  sets `TELEGRAM_ENABLED=True`. The configuration must keep `DEMO_ONLY=True`.
- Trade results are gross (before costs and swap); the weekly figures are net
  of the study's costs. The messages say which is which.
- A report refusal never touches the ledger. The tracker's record stays the
  only evidence, and the messages only describe it.
- The routine's own code runs from `main`, so it can be improved without
  re-freezing the plan. The tracker itself always runs from the pinned
  worktree.

## Verification

`tests/python/test_daily_fx_forward_reports.py` uses synthetic data only. It
checks:

- that the trades rebuild the sealed record and add up;
- that a crash against a position closes it at its stop;
- that loss halts keep a position's levels, as the engine does;
- the `NO_RECORD`, `RECORD_MISMATCH` and `LEDGER_MISMATCH` refusals;
- the message contents, and pips from the start for older positions;
- that each message is sent once, in order and spaced out;
- that the first failure stops the run, the retry sends the stored text, and
  nothing is queued while Telegram is off;
- the routine's success, stop and waiting paths, with MT5 and the network
  replaced by fakes;
- the lock, the missing worktree, the report failure and the Telegram
  failure exit codes.

The PowerShell scripts are thin wrappers and were not run in CI (no
PowerShell there).

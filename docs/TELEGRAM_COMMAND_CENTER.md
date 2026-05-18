# Telegram Command Center

The Telegram Command Center provides safe operational controls for shadow/paper mode only.

It cannot enable real trading, demo execution, `DEMO_ONLY=False`, `LIVE_TRADING_APPROVED=True`, or broker `order_send`.

## Security

- Only `TELEGRAM_ALLOWED_CHAT_ID` is accepted.
- If `TELEGRAM_ALLOWED_CHAT_ID` is missing, `TELEGRAM_CHAT_ID` is used as the fallback allowlist.
- Unauthorized commands are ignored and audited as `UNAUTHORIZED_TELEGRAM_COMMAND`.
- Every accepted command is stored in `telegram_commands`.
- All responses include `execution_attempted=false` at the system level.

Do not commit Telegram tokens, chat IDs, or secrets.

## Commands

- `/status`
- `/health`
- `/summary`
- `/open_trades`
- `/today`
- `/symbols`
- `/rejections`
- `/drift`
- `/pause_shadow`
- `/resume_shadow`
- `/help`
- `/broker`
- `/readiness`
- `/spreads`
- `/latency`
- `/ml`
- `/ml_status`
- `/portfolio`
- `/exposure`
- `/correlation`
- `/risk`
- `/db`
- `/backup`
- `/replay`
- `/outbox`
- `/fills`
- `/costs`
- `/paper_vs_backtest`
- `/validation`
- `/pipeline`

## Pause And Resume

`/pause_shadow` pauses only new signals and new paper trades. Existing paper trades continue to be managed for SL, TP, break-even, trailing and time stop.

`/resume_shadow` resumes new paper trade creation.

Neither command can enable broker execution.

## Broker Quality Commands

`/broker`, `/readiness`, `/spreads`, and `/latency` are read-only. They summarize broker-quality records and readiness reports. They cannot call `order_check`, `order_send`, or change trading permissions.

## ML Commands

`/ml` and `/ml_status` are read-only. They return the latest ML prediction status or `ML_DISABLED` if no approved model is active. They cannot approve execution or change risk.

## Portfolio Commands

`/portfolio`, `/exposure`, `/correlation`, and `/risk` are read-only. They summarize portfolio risk, currency exposure, correlation report availability, and risk budget state.

They cannot enable demo/live execution, cannot change `DEMO_ONLY`, cannot change `LIVE_TRADING_APPROVED`, and cannot call `order_send`.

## Persistence Commands

`/db` returns SQLite health.

`/backup` creates a local safe backup of SQLite. It does not copy `.env` or secrets.

`/replay` generates an audit replay report.

`/outbox` attempts a safe Telegram outbox flush without duplicating delivered messages.

Stable profile commands are read-only:

- `/stable`
- `/stable_gate`
- `/shadow_stable`
- `/stable_status`
- `/stable_trades`
- `/stable_drift`
- `/stable_today`
- `/pause_stable_shadow`
- `/resume_stable_shadow`

They return stable gate, drift and paper-trade status or pause/resume paper entries only. They never enable demo/live execution.

Forward evidence commands are read-only:

- `/evidence`
- `/acceptance`
- `/stable_report`
- `/paper_audit`

They generate or read the evidence pack and operational acceptance report. They never send broker orders.

These commands are operational only and cannot enable trading.

## Execution Simulation Commands

`/fills` and `/costs` generate a read-only execution simulation calibration summary.

`/paper_vs_backtest` generates a read-only forward paper versus backtest comparison.

They cannot call `order_send`, cannot call `order_check`, and cannot change risk settings.

## Full Validation Commands

`/validation` and `/pipeline` read the latest full-validation summary or master decision from local reports.

They are read-only and cannot start a pipeline, cannot enable demo/live execution, and cannot change strategy/risk settings.

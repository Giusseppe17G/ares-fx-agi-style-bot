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

"""Release policy: no generic broker execution; one demo-only path for the forward value book.

``execution_block_reason`` keeps every generic execution API blocked (release
lock, 2026-10-05). ``demo_release_gate`` is the only gate that can open broker
execution, and only for the demo executor of the forward value book (decision
2026-10-30-demo-execution-value-book). It opens only when all of these hold,
and is checked again before every order:

- ``DEMO_ONLY=True`` and ``LIVE_TRADING_APPROVED=False`` (``validate_safety``);
- ``DEMO_EXECUTION_ENABLED=True`` in the operator's configuration;
- the connected account reports the MT5 demo trade mode;
- its login is listed in ``ALLOWED_ACCOUNT_LOGINS``;
- the terminal and the account allow automated trading.

A real or contest account is always refused, whatever the configuration.
"""

from __future__ import annotations

from typing import Any

from agi_style_forex_bot_mt5.config import BotConfig

ACCOUNT_TRADE_MODE_DEMO = 0  # MetaTrader5.ACCOUNT_TRADE_MODE_DEMO


def execution_block_reason(config: BotConfig) -> tuple[str, str]:
    """Return an unconditional block; no flag or caller evidence grants access."""
    if config.shadow_mode is not False:
        return "SHADOW_MODE_BLOCKED", "shadow mode cannot construct, check or send broker orders"
    return "EXECUTION_NOT_RELEASED", "broker execution is unavailable until a separately reviewed release"


def demo_release_gate(config: BotConfig, account: Any, terminal: Any,
                      demo_mode: int = ACCOUNT_TRADE_MODE_DEMO) -> tuple[bool, str, str]:
    """``(allowed, code, reason)`` for the demo executor; anything uncertain is refused."""

    try:
        config.validate_safety()
    except ValueError as error:
        return False, "CONFIG_UNSAFE", str(error)
    if config.demo_only is not True or config.live_trading_approved is not False:
        return False, "CONFIG_UNSAFE", "DEMO_ONLY must be True and LIVE_TRADING_APPROVED False"
    if config.demo_execution_enabled is not True:
        return False, "DEMO_EXECUTION_DISABLED", "set DEMO_EXECUTION_ENABLED=True to execute on the demo account"
    if account is None or terminal is None:
        return False, "MT5_UNAVAILABLE", "no account or terminal information"
    trade_mode = getattr(account, "trade_mode", None)
    if type(trade_mode) is not int or trade_mode != demo_mode:
        return False, "REAL_ACCOUNT_BLOCKED", f"account trade mode {trade_mode!r} is not demo"
    login = getattr(account, "login", None)
    if type(login) is not int or login not in config.allowed_account_logins:
        return False, "ACCOUNT_NOT_WHITELISTED", "the demo login is not listed in ALLOWED_ACCOUNT_LOGINS"
    if getattr(terminal, "trade_allowed", False) is not True:
        return False, "ALGO_TRADING_DISABLED", "enable Algo Trading in the MT5 terminal"
    if getattr(account, "trade_allowed", False) is not True or getattr(account, "trade_expert", True) is not True:
        return False, "ACCOUNT_TRADING_DISABLED", "the account does not allow automated trading"
    return True, "DEMO_RELEASED", "demo account verified"

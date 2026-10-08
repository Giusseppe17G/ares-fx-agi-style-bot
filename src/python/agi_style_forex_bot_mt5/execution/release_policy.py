"""This release exposes data and paper simulation, never broker execution."""

from agi_style_forex_bot_mt5.config import BotConfig


def execution_block_reason(config: BotConfig) -> tuple[str, str]:
    """Return an unconditional block; no flag or caller evidence grants access."""
    if config.shadow_mode is not False:
        return "SHADOW_MODE_BLOCKED", "shadow mode cannot construct, check or send broker orders"
    return "EXECUTION_NOT_RELEASED", "broker execution is unavailable until a separately reviewed release"

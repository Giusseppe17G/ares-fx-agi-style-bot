from dataclasses import replace

import pytest

from agi_style_forex_bot_mt5.config import BotConfig, load_config


@pytest.mark.parametrize("field", ["max_open_risk_pct", "max_risk_per_trade_pct", "max_daily_drawdown_pct", "max_floating_drawdown_pct", "max_market_snapshot_age_seconds", "max_tick_age_seconds", "max_signal_age_seconds", "paper_risk_multiplier", "max_spread_points_default"])
@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), "5"])
def test_risk_and_cost_limits_reject_invalid_numbers(field, value):
    with pytest.raises(ValueError):
        replace(BotConfig(), **{field: value}).validate_safety()


@pytest.mark.parametrize("field,value", [("max_open_trades", 11), ("max_open_trades", 1.5), ("max_open_paper_trades", 11), ("max_daily_drawdown_pct", 3.1), ("max_floating_drawdown_pct", 5.1), ("max_tick_age_seconds", 6), ("demo_only", "True"), ("live_trading_approved", 0), ("require_sl", 1)])
def test_mandatory_limits_cannot_be_bypassed_by_configuration(field, value):
    with pytest.raises(ValueError):
        replace(BotConfig(), **{field: value}).validate_safety()


def test_defaults_and_more_conservative_config_remain_valid():
    BotConfig().validate_safety()
    replace(BotConfig(), max_open_trades=1, max_daily_drawdown_pct=1., max_risk_per_trade_pct=.1).validate_safety()


@pytest.mark.parametrize("key", ["DEMO_ONLY", "LIVE_TRADING_APPROVED", "REQUIRE_SL", "REQUIRE_TP", "PAPER_ALLOW_DISABLED_ML"])
def test_boolean_typos_cannot_enable_policy(tmp_path, key):
    path = tmp_path / "bad.ini"
    path.write_text(f"{key}=misspelled\n")
    with pytest.raises(ValueError, match="explicit boolean"):
        load_config(path)

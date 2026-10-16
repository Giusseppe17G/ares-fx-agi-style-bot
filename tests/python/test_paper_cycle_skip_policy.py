"""Which pre-mutation failures a live paper run may skip; never an order path."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState, MarketSnapshot
from agi_style_forex_bot_mt5.paper_trading.lifecycle import (SKIPPABLE_BEFORE_MUTATION, PaperAccountObservation,
    PaperCycleRejected, skippable_before_mutation, validate_account, validate_quotes)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
LIVE = SimpleNamespace(skip_pre_mutation_failures=True, paper_lifecycle_halted=False, audit_failed=False)


def _quote(at):
    return MarketSnapshot(symbol="EURUSD", timeframe="M5", timestamp_utc=at, bid=1.1, ask=1.10010, spread_points=10.0,
        digits=5, point=1e-5, tick_value=1.0, tick_size=1e-5, volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=0, freeze_level_points=0)


def _account():
    return AccountState(login=123456, trade_mode="DEMO", balance=10_000.0, equity=10_000.0, margin_free=9_000.0,
        currency="USD", is_demo=True, trade_allowed=True)


@pytest.mark.parametrize("delta,skippable", ((timedelta(seconds=-30), True), (timedelta(seconds=5), False)))
def test_stale_quote_is_skippable_but_a_future_quote_latches(delta, skippable):
    with pytest.raises(PaperCycleRejected) as rejected:
        validate_quotes({"EURUSD": _quote(NOW + delta)}, (), NOW, BotConfig())
    assert rejected.value.code == "QUOTE_TIME_INVALID"
    assert skippable_before_mutation(LIVE, rejected.value) is skippable


@pytest.mark.parametrize("delta,skippable", ((timedelta(seconds=-30), True), (timedelta(seconds=3), False)))
def test_stale_account_observation_is_skippable_but_a_future_one_latches(delta, skippable):
    observation = PaperAccountObservation(_account(), NOW + delta, True)
    with pytest.raises(PaperCycleRejected) as rejected:
        validate_account(observation, NOW, BotConfig())
    assert rejected.value.code == "ACCOUNT_OBSERVATION_STALE"
    assert skippable_before_mutation(LIVE, rejected.value) is skippable


def test_skip_policy_is_opt_in_and_never_covers_integrity_or_prior_latches():
    stale = PaperCycleRejected("EVENT_QUOTES_MISSING", "closed market")
    assert skippable_before_mutation(LIVE, stale)
    assert not skippable_before_mutation(SimpleNamespace(), stale)
    assert not skippable_before_mutation(SimpleNamespace(**{**vars(LIVE), "skip_pre_mutation_failures": False}), stale)
    assert not skippable_before_mutation(SimpleNamespace(**{**vars(LIVE), "paper_lifecycle_halted": True}), stale)
    assert not skippable_before_mutation(SimpleNamespace(**{**vars(LIVE), "audit_failed": True}), stale)
    assert not skippable_before_mutation(LIVE, PaperCycleRejected("EVENT_TIME_INVALID", "future", future=True))
    for code in ("ACCOUNT_REAL_DETECTED_READ_ONLY", "ACCOUNT_INFO_INVALID", "ACCOUNT_CHANGED", "QUOTE_GRID_INVALID",
                 "QUOTE_SPREAD_MISMATCH", "EVENT_ID_INVALID", "EVENT_TIME_REVERSED", "PAPER_LIFECYCLE_HALTED"):
        assert code not in SKIPPABLE_BEFORE_MUTATION
        assert not skippable_before_mutation(LIVE, PaperCycleRejected(code, "latch"))
    assert not skippable_before_mutation(LIVE, OSError("storage"))

"""An offset inferred from one tick cannot prove that tick's freshness."""

from datetime import datetime, timedelta, timezone

import pytest

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.execution.mt5_time_normalizer import normalize_tick_time, classify_tick_time


NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("source_offset,real_age", [(3600, 0), (7200, 3600)])
def test_inferred_hour_offset_cannot_authorize_unknown_or_old_tick(source_offset, real_age):
    # These two sources emit the SAME raw epoch. With no independent offset
    # evidence, the second source's hour-old quote cannot be distinguished.
    raw = NOW + timedelta(seconds=source_offset - real_age)
    diagnostic = normalize_tick_time(int(raw.timestamp()), int(raw.timestamp() * 1000), NOW, BotConfig())
    assert diagnostic["reject_code"] == "MARKET_DATA_INVALID"
    assert diagnostic["timestamp_normalized"] is False
    assert diagnostic["selected_tick_time_utc"] == raw.isoformat()


@pytest.mark.parametrize("future_seconds", (.001, 2, 5, 3600, 10800))
def test_any_future_utc_tick_fails_closed(future_seconds):
    raw = NOW + timedelta(seconds=future_seconds)
    diagnostic = normalize_tick_time(int(raw.timestamp()), int(raw.timestamp() * 1000), NOW, BotConfig())
    assert diagnostic["reject_code"] == "MARKET_DATA_INVALID"
    assert diagnostic["tick_age_seconds"] < 0
    assert diagnostic["timestamp_normalized"] is False


@pytest.mark.parametrize("age,accepted", [(0, True), (5, True), (5.001, False), (3600, False)])
def test_only_raw_utc_age_in_closed_interval_is_fresh(age, accepted):
    raw = NOW - timedelta(seconds=age)
    diagnostic = normalize_tick_time(int(raw.timestamp()), int(raw.timestamp() * 1000), NOW, BotConfig())
    assert (diagnostic["reject_code"] is None) is accepted
    assert diagnostic["timestamp_normalized"] is False


def test_classifier_cannot_trust_supplied_fresh_normalized_timestamp():
    assert classify_tick_time(NOW + timedelta(hours=1), NOW, NOW, 5, 21600) != "NORMALIZED_FRESH"


@pytest.mark.parametrize("flag", ("normalize_broker_time", "broker_time_offset_detection"))
def test_legacy_flags_cannot_enable_clock_conversion(flag):
    from dataclasses import replace
    raw = NOW + timedelta(hours=1)
    for enabled in (False, True):
        diagnostic = normalize_tick_time(int(raw.timestamp()), int(raw.timestamp() * 1000), NOW,
            replace(BotConfig(), **{flag: enabled}))
        assert diagnostic["reject_code"] == "MARKET_DATA_INVALID"
        assert diagnostic["timestamp_normalized"] is False

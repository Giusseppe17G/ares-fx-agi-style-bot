"""Declared MT5 server clock (MT5_SERVER_TIME) converted to UTC at the read boundary."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.config import BotConfig, load_config
from agi_style_forex_bot_mt5.data_pipeline.live_data_contract import normalize_ohlcv_contract
from agi_style_forex_bot_mt5.execution.mt5_time_normalizer import normalize_tick_time
from agi_style_forex_bot_mt5.utils.mt5_server_time import (parse_server_time, server_offset_seconds,
    eu_dst_bounds_utc, server_series_to_utc, server_wall_to_utc, us_dst_bounds_utc, utc_to_server_wall)

NEW_YORK = ZoneInfo("America/New_York")


@pytest.mark.parametrize("value,expected", (("utc", "UTC"), (" ny_close ", "NY_CLOSE"), ("eet", "EET"), ("UTC+03:00", "UTC+03:00"),
                                            ("UTC-05:30", "UTC-05:30"), ("UTC+00:00", "UTC+00:00"), ("UTC+14:00", "UTC+14:00")))
def test_parse_accepts_documented_conventions(value, expected):
    assert parse_server_time(value) == expected


@pytest.mark.parametrize("value", ("", None, "EEST", "UTC+3", "UTC+03:60", "UTC+15:00", "GMT+02:00", "AUTO"))
def test_parse_rejects_anything_else(value):
    with pytest.raises(ValueError):
        parse_server_time(value)


def test_ny_close_offset_follows_new_york_dst_for_every_year_of_the_rule():
    for year in range(2007, 2041):
        start, end = us_dst_bounds_utc(year)
        probes = [start + timedelta(hours=h) for h in range(-30, 31)] + [end + timedelta(hours=h) for h in range(-30, 31)]
        probes += [datetime(year, month, 15, 12, tzinfo=timezone.utc) for month in range(1, 13)]
        for instant in probes:
            expected = int(instant.astimezone(NEW_YORK).utcoffset().total_seconds()) + 7 * 3600
            assert server_offset_seconds("NY_CLOSE", instant) == expected, instant


def test_eet_offset_follows_european_summer_time():
    athens = ZoneInfo("Europe/Athens")  # EET/EEST, European rule
    for year in range(1996, 2041):
        start, end = eu_dst_bounds_utc(year)
        for instant in [start + timedelta(hours=h) for h in range(-30, 31)] + [end + timedelta(hours=h) for h in range(-30, 31)]:
            assert server_offset_seconds("EET", instant) == int(instant.astimezone(athens).utcoffset().total_seconds()), instant
    # The two conventions differ for a few weeks each year: a wrong choice is visible then.
    between = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    assert server_offset_seconds("NY_CLOSE", between) == 10800 and server_offset_seconds("EET", between) == 7200
    walls = pd.Series(pd.date_range("2026-03-01", "2026-11-30", freq="11h", tz="UTC"))
    walls = walls[[server_wall_to_utc(value.to_pydatetime(), "EET") is not None for value in walls]].reset_index(drop=True)
    assert [value.to_pydatetime() for value in server_series_to_utc(walls, "EET")] == [
        server_wall_to_utc(value.to_pydatetime(), "EET") for value in walls]


def test_round_trip_and_rejected_gap_and_overlap():
    for instant in (datetime(2026, 7, 1, 9, 30, tzinfo=timezone.utc), datetime(2026, 1, 14, 22, 5, tzinfo=timezone.utc)):
        wall = utc_to_server_wall(instant, "NY_CLOSE")
        assert wall - instant == timedelta(hours=3 if instant.month == 7 else 2)
        assert server_wall_to_utc(wall, "NY_CLOSE") == instant
    start, end = us_dst_bounds_utc(2026)
    # Spring forward: server wall 09:00-10:00 on that Sunday never exists.
    assert server_wall_to_utc(start + timedelta(hours=2, minutes=30), "NY_CLOSE") is None
    # Fall back: server wall 08:00-09:00 happens twice.
    assert server_wall_to_utc(end + timedelta(hours=2, minutes=30), "NY_CLOSE") is None
    assert server_wall_to_utc(datetime(2005, 6, 1, tzinfo=timezone.utc), "NY_CLOSE") is None
    assert server_wall_to_utc(datetime(2026, 7, 1, 12, tzinfo=timezone.utc), "UTC+03:00") == datetime(2026, 7, 1, 9, tzinfo=timezone.utc)
    assert server_wall_to_utc(datetime(2026, 7, 1, 12, tzinfo=timezone.utc), "UTC") == datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def test_series_conversion_matches_scalar_and_fails_closed():
    walls = pd.Series(pd.date_range("2026-03-01", "2026-11-30", freq="7h", tz="UTC"))
    walls = walls[[server_wall_to_utc(value.to_pydatetime(), "NY_CLOSE") is not None for value in walls]]
    converted = server_series_to_utc(walls.reset_index(drop=True), "NY_CLOSE")
    expected = [server_wall_to_utc(value.to_pydatetime(), "NY_CLOSE") for value in walls]
    assert [value.to_pydatetime() for value in converted] == expected
    start, _ = us_dst_bounds_utc(2026)
    with pytest.raises(ValueError, match="gap or overlap"):
        server_series_to_utc(pd.Series([pd.Timestamp(start + timedelta(hours=2, minutes=30))]), "NY_CLOSE")
    with pytest.raises(ValueError):
        server_series_to_utc(pd.Series([pd.Timestamp("2006-06-01", tz="UTC")]), "NY_CLOSE")


def test_ny_close_tick_three_hours_ahead_is_fresh_and_utc_default_rejects_it():
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    wall = now + timedelta(hours=3) - timedelta(seconds=1)
    declared = normalize_tick_time(int(wall.timestamp()), int(wall.timestamp() * 1000), now, BotConfig(mt5_server_time="NY_CLOSE"))
    assert declared["tick_time_status"] == "FRESH" and declared["tick_age_seconds"] == 1.0
    assert declared["mt5_server_time"] == "NY_CLOSE" and declared["server_time_offset_seconds"] == 10800
    default = normalize_tick_time(int(wall.timestamp()), int(wall.timestamp() * 1000), now, BotConfig())
    assert default["tick_time_status"] == "FUTURE_TOO_FAR"
    assert default["suggested_broker_time_offset_seconds"] == 10800
    # A wrong declaration makes a UTC broker look three hours stale: rejected, never fresh.
    utc_tick = now - timedelta(seconds=1)
    wrong = normalize_tick_time(int(utc_tick.timestamp()), None, now, BotConfig(mt5_server_time="NY_CLOSE"))
    assert wrong["tick_time_status"] == "STALE"


def test_live_bars_are_converted_before_the_contract_checks():
    walls = pd.date_range("2026-06-10 09:00", periods=250, freq="5min", tz="UTC")
    raw = pd.DataFrame({"time": [int(value.timestamp()) for value in walls], "open": 1.1, "high": 1.2, "low": 1.0,
                        "close": 1.1, "tick_volume": 10, "spread": 5, "real_volume": 0})
    result = normalize_ohlcv_contract(raw, source="live_mt5", symbol="EURUSD", timeframe="M5", server_time="NY_CLOSE")
    assert result.diagnostics["status"] == "OK"
    assert result.frame["timestamp_utc"].iloc[0] == pd.Timestamp("2026-06-10 06:00", tz="UTC")
    assert result.frame["time"].iloc[0] == "2026-06-10T06:00:00Z"
    unchanged = normalize_ohlcv_contract(raw, source="live_mt5", symbol="EURUSD", timeframe="M5")
    assert unchanged.frame["timestamp_utc"].iloc[0] == pd.Timestamp("2026-06-10 09:00", tz="UTC")


def test_config_declares_server_time_and_tolerates_a_bom(tmp_path):
    path = tmp_path / "bot.ini"
    path.write_bytes("﻿MAX_SPREAD_POINTS_DEFAULT=10\nMT5_SERVER_TIME=ny_close\n".encode("utf-8"))
    config = load_config(path)
    assert config.max_spread_points_default == 10.0 and config.mt5_server_time == "NY_CLOSE"
    assert load_config(None).mt5_server_time == "UTC"
    path.write_text("MT5_SERVER_TIME=auto\n", encoding="utf-8")
    with pytest.raises(ValueError, match="MT5_SERVER_TIME"):
        load_config(path)
    with pytest.raises(ValueError):
        BotConfig(mt5_server_time="ny_close")


def test_range_fallback_queries_on_the_server_clock(monkeypatch):
    from agi_style_forex_bot_mt5 import mt5_data_bot

    seen = []
    bot = SimpleNamespace(config=BotConfig(mt5_server_time="UTC+03:00"), bars=10, _live_bars_for=lambda timeframe: 10,
        connector=SimpleNamespace(mt5=SimpleNamespace(copy_rates_range=lambda *args: seen.append(args) or [])))
    before = datetime.now(timezone.utc)
    mt5_data_bot.MT5DataOnlyBot._copy_rates_range_fallback(bot, "EURUSD", 5, "M5")
    after = datetime.now(timezone.utc)
    date_to = seen[0][3]
    assert before + timedelta(hours=3) <= date_to <= after + timedelta(hours=3)


def test_diagnose_hint_names_the_missing_or_wrong_declaration():
    from agi_style_forex_bot_mt5.mt5_data_bot import _server_time_hint

    ahead = SimpleNamespace(suggested_broker_time_offset_seconds=10800, tick_age_seconds=-10799.0)
    assert "MT5_SERVER_TIME=UTC" in _server_time_hint(ahead, "UTC") and "NY_CLOSE" in _server_time_hint(ahead, "UTC")
    behind = SimpleNamespace(suggested_broker_time_offset_seconds=None, tick_age_seconds=7201.0)
    assert "check that declaration" in _server_time_hint(behind, "NY_CLOSE")
    fresh = SimpleNamespace(suggested_broker_time_offset_seconds=None, tick_age_seconds=1.0)
    assert _server_time_hint(fresh, "NY_CLOSE") == "" and _server_time_hint(None, "UTC") == ""

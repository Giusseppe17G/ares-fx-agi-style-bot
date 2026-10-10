"""Measured paper decision evidence on synthetic data; never an order path."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.paper_trading.lifecycle import PaperCycleRejected, validate_evidence
from agi_style_forex_bot_mt5.paper_trading.live_decision_evidence import LiveDecisionEvidence

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _snapshot(symbol="EURUSD", *, spread=10.0, at=NOW):
    return MarketSnapshot(symbol=symbol, timeframe="M5", timestamp_utc=at, bid=1.1, ask=1.1 + spread * 1e-5,
        spread_points=spread, digits=5, point=1e-5, tick_value=1.0, tick_size=1e-5, volume_min=0.01,
        volume_max=100.0, volume_step=0.01, stops_level_points=0, freeze_level_points=0)


def _bars(closes):
    times = pd.date_range(NOW - timedelta(minutes=5 * len(closes)), periods=len(closes), freq="5min", tz="UTC")
    return pd.DataFrame({"timestamp_utc": times, "close": closes})


def _walk(seed, count=320):
    steps = np.random.default_rng(seed).normal(0, 1e-4, count)
    return 1.1 * np.exp(np.cumsum(steps))


def _provider(clock=None):
    provider = LiveDecisionEvidence(max_spread_points=25, clock=clock or FrozenClock(NOW))
    provider.begin_cycle(account_trade_allowed=True)
    return provider


def _observe(provider, symbol, closes, timeframes=("M5", "M15", "H1"), tick_ms=5, rates_ms=50):
    frames = {tf: _bars(closes) for tf in timeframes}
    provider.observe_symbol(symbol, frames, tick_latency_ms=tick_ms, rates_latency_ms=rates_ms)


def test_no_evidence_without_this_cycles_observation():
    provider = LiveDecisionEvidence(max_spread_points=25, clock=FrozenClock(NOW))
    assert provider(_snapshot(), {}, ()) is None
    provider.begin_cycle(account_trade_allowed=True)
    assert provider(_snapshot(), {}, ()) is None
    with pytest.raises(PaperCycleRejected, match="dated broker quality") as missing:
        validate_evidence(None, NOW, BotConfig(), has_exposure=False)
    assert missing.value.code == "BROKER_EVIDENCE_MISSING"
    _observe(provider, "EURUSD", _walk(1))
    provider.begin_cycle(account_trade_allowed=True)
    assert provider(_snapshot(), {}, ()) is None


def test_score_comes_from_measured_quote_metadata_and_latency():
    provider = _provider()
    _observe(provider, "EURUSD", _walk(1))
    evidence = provider(_snapshot(), {}, ())
    assert evidence["broker_readiness_score"] == 100.0 and evidence["readiness_reasons"] == []
    assert evidence["correlation"] is None and evidence["observed_at_utc"] == NOW
    assert validate_evidence(evidence, NOW, BotConfig(), has_exposure=False).broker_readiness_score == 100.0
    assert provider(_snapshot(spread=30.0), {}, ())["broker_readiness_score"] == 50.0
    _observe(provider, "EURUSD", _walk(1), timeframes=("M5",), rates_ms=2500)
    degraded = provider(_snapshot(), {}, ())
    assert degraded["broker_readiness_score"] == 70.0
    assert set(degraded["readiness_reasons"]) == {"rates unavailable", "read latency high"}
    blocked = LiveDecisionEvidence(max_spread_points=25, clock=FrozenClock(NOW))
    blocked.begin_cycle(account_trade_allowed=False)
    _observe(blocked, "EURUSD", _walk(1))
    assert blocked(_snapshot(), {}, ())["broker_readiness_score"] == 80.0


def test_tick_age_is_measured_against_the_clock():
    provider = _provider(FrozenClock(NOW + timedelta(seconds=10)))
    _observe(provider, "EURUSD", _walk(1))
    evidence = provider(_snapshot(), {}, ())
    assert "tick stale or unavailable" in evidence["readiness_reasons"]
    assert evidence["broker_readiness_score"] == 75.0


def test_correlation_is_measured_for_every_exposure_or_left_unverified():
    provider = _provider()
    base = _walk(1)
    noise = np.exp(np.cumsum(np.random.default_rng(9).normal(0, 2e-5, len(base))))
    _observe(provider, "EURUSD", base)
    _observe(provider, "GBPUSD", base * noise)
    _observe(provider, "USDJPY", 1 / base)
    assert provider(_snapshot(), {}, [{"symbol": "EURUSD"}])["correlation"] == 1.0
    assert provider(_snapshot(), {}, [{"symbol": "GBPUSD"}])["correlation"] > 0.85
    assert provider(_snapshot(), {}, [{"symbol": "USDJPY"}])["correlation"] == pytest.approx(-1.0)
    unmeasured = provider(_snapshot(), {}, [{"symbol": "GBPUSD"}, {"symbol": "AUDUSD"}])
    assert unmeasured["correlation"] is None
    with pytest.raises(PaperCycleRejected) as rejected:
        validate_evidence(unmeasured, NOW, BotConfig(), has_exposure=True)
    assert rejected.value.code == "CORRELATION_UNVERIFIED"


@pytest.mark.parametrize("closes", [_walk(2, 60), np.full(320, 1.1), np.r_[_walk(2, 300), 0.0, _walk(3, 19)]])
def test_short_flat_or_invalid_series_give_no_correlation(closes):
    provider = _provider()
    _observe(provider, "EURUSD", _walk(1))
    _observe(provider, "GBPUSD", closes)
    assert provider(_snapshot(), {}, [{"symbol": "GBPUSD"}])["correlation"] is None


def test_forming_bar_is_excluded_from_correlation():
    provider = _provider()
    base = _walk(1)
    _observe(provider, "EURUSD", base)
    # Only the last (forming) bar differs; closed bars are identical.
    _observe(provider, "GBPUSD", np.r_[base[:-1], base[-1] * 1.5])
    assert provider(_snapshot(), {}, [{"symbol": "GBPUSD"}])["correlation"] == pytest.approx(1.0)


@pytest.mark.parametrize("value", (0, -1, float("nan"), float("inf")))
def test_rejects_invalid_spread_limit(value):
    with pytest.raises(ValueError):
        LiveDecisionEvidence(max_spread_points=value)

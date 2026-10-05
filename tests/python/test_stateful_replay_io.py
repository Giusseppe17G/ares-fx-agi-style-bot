from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting.stateful_replay_io import (
    ReplayInputError, event_from_mapping, load_replay_events,
)
from agi_style_forex_bot_mt5.ml import MLFilter


def event_payload():
    return {
        "event_id": "quote-a", "timestamp_utc": "2026-01-05T12:00:00+00:00",
        "quotes": {"EURUSD": {
            "symbol": "EURUSD", "timeframe": "M5", "timestamp_utc": "2026-01-05T12:00:00+00:00",
            "bid": 1.1, "ask": 1.1001, "spread_points": 10., "digits": 5,
            "point": .00001, "tick_value": 1., "tick_size": .00001,
            "volume_min": .01, "volume_max": 100., "volume_step": .01,
            "stops_level_points": 10, "freeze_level_points": 5,
        }},
        "decisions": [{"symbol": "EURUSD", "timeframe": "M5", "bars": [{
            "timestamp_utc": "2026-01-05T11:55:00+00:00", "open": 1.1,
            "high": 1.101, "low": 1.099, "close": 1.1, "volume": 100., "spread_points": 10.,
        }]}],
        "evidence": {"EURUSD": {"observed_at_utc": "2026-01-05T12:00:00+00:00",
                                 "broker_readiness_score": 85., "correlation": None}},
    }


def test_transport_preserves_canonical_closed_bars_and_quotes(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(event_payload()) + "\n", encoding="utf-8")
    event, = load_replay_events(path)
    assert event.event_id == "quote-a"
    assert event.quotes["EURUSD"].spread_points == 10.
    assert event.evidence["EURUSD"].correlation is None
    bars = event.decisions[0].bars
    assert isinstance(bars["timestamp_utc"].dtype, pd.DatetimeTZDtype)
    assert bars.iloc[0]["timestamp_utc"].isoformat() == "2026-01-05T11:55:00+00:00"
    assert bars.iloc[0]["volume"] == 100.


@pytest.mark.parametrize("raw", ["", "\n", '{"event_id":"one","event_id":"two"}',
                                  '{"value": NaN}', '{"value": Infinity}', '[1,2]', 'null'])
def test_invalid_jsonl_is_not_silently_repaired(tmp_path, raw):
    path = tmp_path / "events.jsonl"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ReplayInputError):
        list(load_replay_events(path))


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(timestamp_utc="2026-01-05T12:00:00"),
    lambda p: p.update(unrecognized="secret"),
    lambda p: p["quotes"]["EURUSD"].update(bid=float("nan")),
    lambda p: p["quotes"]["EURUSD"].update(digits=True),
    lambda p: p["quotes"]["EURUSD"].update(bid="1.1"),
    lambda p: p["quotes"]["EURUSD"].update(symbol="USDJPY"),
    lambda p: p["decisions"][0]["bars"][0].update(timeframe="H1"),
    lambda p: p["decisions"][0]["bars"][0].update(volume=True),
    lambda p: p["evidence"]["EURUSD"].update(broker_readiness_score=True),
    lambda p: p["evidence"]["EURUSD"].pop("observed_at_utc"),
])
def test_ambiguous_fields_fail_closed(mutation):
    payload = deepcopy(event_payload())
    mutation(payload)
    with pytest.raises(ValueError):
        event_from_mapping(payload)


def test_explicit_disabled_ml_never_loads_local_models(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("filesystem model load attempted")
    monkeypatch.setattr("agi_style_forex_bot_mt5.ml.ml_filter.load_model_bundle", forbidden)
    model = MLFilter.disabled_for_research()
    assert model.bundle is None
    assert model.approve_or_reject(None, {}).ml_status == "ML_DISABLED"


@pytest.mark.parametrize("future_metadata", [False, True])
def test_offline_cli_isolated_from_cwd_and_halted_exit_is_nonzero(tmp_path, future_metadata):
    from agi_style_forex_bot_mt5.core.instruments import (
        InstrumentRegistry, InstrumentRegistrySnapshot, assumed_fx_spec,
    )
    # Synthetic test metadata, never published as observed broker evidence.
    spec = replace(assumed_fx_spec("EURUSD"), source="mt5:symbol_info")
    snapshot = InstrumentRegistrySnapshot(
        InstrumentRegistry.from_specs([spec]),
        datetime(2027 if future_metadata else 2025, 1, 1, tzinfo=timezone.utc),
    )
    metadata_path = tmp_path / "test-instruments.json"
    snapshot.write(metadata_path)
    payload = event_payload()
    payload.update(decisions=[], evidence={})
    events_path = tmp_path / "test-events.jsonl"
    events_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    config_path = tmp_path / "research.ini"
    config_path.write_text("PAPER_ALLOW_DISABLED_ML=True\n", encoding="utf-8")
    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "result"
    command = [sys.executable, "-B", str(project_root / "scripts" / "replay_stateful_quotes.py"),
               "--source-root", str(project_root), "--events", str(events_path),
               "--instrument-snapshot", str(metadata_path), "--config", str(config_path),
               "--output-dir", str(output), "--initial-balance", "10000", "--currency", "USD",
               "--slippage-points", "1", "--commission-per-lot-round-turn", "7", "--without-ml"]
    process = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=45)
    assert process.returncode == (2 if future_metadata else 0), process.stderr
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert result["halted"] is future_metadata
    assert result["execution_attempted"] is False
    assert result["events_completed"] == (0 if future_metadata else 1)
    assert result["trades"] == []

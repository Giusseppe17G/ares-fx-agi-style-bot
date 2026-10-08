"""Read-only metadata capture, strict inputs and immutable evidence sidecars."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5.core.instruments import (
    InstrumentRegistry,
    InstrumentRegistrySnapshot,
    assumed_fx_spec,
    instrument_metadata_hash,
    spec_from_mapping,
    spec_from_symbol_info,
)
from agi_style_forex_bot_mt5.core.operational_state.errors import InstrumentError
from agi_style_forex_bot_mt5.instrument_registry_builder import build_instrument_registry_snapshot


CAPTURED = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
INFO = {
    "name": "EURUSD.raw", "digits": 5, "point": 0.00001,
    "trade_tick_size": 0.00001, "trade_tick_value": 0.97,
    "trade_contract_size": 100000.0, "volume_min": 0.01,
    "volume_max": 100.0, "volume_step": 0.01,
    "trade_stops_level": 0, "trade_freeze_level": 3,
    "currency_base": "EUR", "currency_profit": "USD", "currency_margin": "EUR",
}


class ReadOnlyClient:
    def __init__(self, infos=None):
        self.infos = {"EURUSD.raw": SimpleNamespace(**INFO)} if infos is None else infos
        self.calls = []

    def symbol_info(self, symbol):
        self.calls.append(symbol)
        return self.infos[symbol]

    def __getattr__(self, name):
        raise AssertionError(f"unexpected client capability: {name}")


def capture(info=None, **kwargs):
    client = ReadOnlyClient() if info is None else ReadOnlyClient({"EURUSD.raw": info})
    return build_instrument_registry_snapshot(client=client, symbols={"EURUSD": "EURUSD.raw"}, captured_at_utc=kwargs.get("captured_at_utc", CAPTURED))


def test_capture_only_reads_symbol_info_and_whitelists_fields():
    # These fields must not be copied into the artifact or hashed.
    info = {**INFO, "login": "PRIVATE_LOGIN", "server": "PRIVATE_SERVER", "token": "PRIVATE_TOKEN", "path": "PRIVATE_PATH"}
    client = ReadOnlyClient({"EURUSD.raw": SimpleNamespace(**info)})
    snapshot = build_instrument_registry_snapshot(client=client, symbols={"eurusd": "EURUSD.raw"}, captured_at_utc=CAPTURED)
    assert client.calls == ["EURUSD.raw"]
    spec = snapshot.registry.get("EURUSD")
    assert (spec.broker_symbol, spec.currency_quote, spec.currency_margin) == ("EURUSD.raw", "USD", "EUR")
    assert (spec.min_volume, spec.max_volume, spec.tick_value, spec.freeze_level_points) == (0.01, 100.0, 0.97, 3)
    assert "PRIVATE" not in json.dumps(snapshot.as_dict())
    assert snapshot.metadata_hash == capture().metadata_hash


def test_round_trip_verifies_hashes_through_existing_registry_api(tmp_path):
    snapshot = capture()
    path = snapshot.write(tmp_path / "instruments.json")
    assert InstrumentRegistrySnapshot.read(path) == snapshot
    loaded = InstrumentRegistry.from_dataset(tmp_path)
    assert loaded.as_dict() == snapshot.registry.as_dict()
    assert instrument_metadata_hash(loaded) == snapshot.metadata_hash
    assert len(snapshot.metadata_hash) == len(snapshot.snapshot_hash) == 64


def test_hashes_are_reproducible_across_ordering_timezones_and_locations(tmp_path):
    gbp = {**INFO, "name": "GBPUSD.raw", "currency_base": "GBP"}
    client = ReadOnlyClient({"GBPUSD.raw": gbp, "EURUSD.raw": INFO})
    symbols = {"GBPUSD": "GBPUSD.raw", "EURUSD": "EURUSD.raw"}
    first = build_instrument_registry_snapshot(client=client, symbols=symbols, captured_at_utc=CAPTURED)
    local_time = CAPTURED.astimezone(timezone(timedelta(hours=-5)))
    second = build_instrument_registry_snapshot(client=client, symbols=dict(reversed(list(symbols.items()))), captured_at_utc=local_time)
    assert first.as_dict() == second.as_dict()
    assert client.calls == ["EURUSD.raw", "GBPUSD.raw"] * 2
    assert first.write(tmp_path / "first.json").read_bytes() == second.write(tmp_path / "second.json").read_bytes()


def test_metadata_and_snapshot_hashes_have_distinct_time_semantics():
    first = capture()
    later = capture(captured_at_utc=CAPTURED + timedelta(seconds=1))
    changed = capture({**INFO, "trade_tick_value": 0.98})
    assert first.metadata_hash == later.metadata_hash
    assert first.snapshot_hash != later.snapshot_hash
    assert first.metadata_hash != changed.metadata_hash
    assert first.snapshot_hash != changed.snapshot_hash


def test_snapshot_and_registry_cannot_be_mutated():
    snapshot = capture()
    with pytest.raises(FrozenInstanceError):
        snapshot.captured_at_utc = CAPTURED + timedelta(days=1)
    with pytest.raises(TypeError):
        snapshot.registry.specs["GBPUSD"] = assumed_fx_spec("GBPUSD")
    with pytest.raises(FrozenInstanceError):
        snapshot.registry.get("EURUSD").tick_value = 4
    detached = snapshot.as_dict()
    detached["instruments"]["EURUSD"]["tick_value"] = 4
    assert snapshot.metadata_hash == capture().metadata_hash
    entries = dict(snapshot.registry.specs)
    registry = InstrumentRegistry(entries)
    entries.clear()
    assert registry.symbols() == ["EURUSD"]


def test_write_never_overwrites_existing_evidence(tmp_path):
    destination = tmp_path / "instruments.json"
    destination.write_bytes(b"prior evidence")
    with pytest.raises(InstrumentError, match="destination must be new"):
        capture().write(destination)
    assert destination.read_bytes() == b"prior evidence"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["instruments.json"]


def test_write_failure_leaves_no_partial_snapshot(tmp_path, monkeypatch):
    import agi_style_forex_bot_mt5.core.instruments.snapshot as module

    def fail_link(*args):
        raise OSError("sensitive local path")

    monkeypatch.setattr(module.os, "link", fail_link)
    with pytest.raises(InstrumentError) as caught:
        capture().write(tmp_path / "instruments.json")
    assert "sensitive" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field", [key for key in INFO if key != "currency_margin"])
def test_missing_required_mt5_attribute_rejects_entire_capture(field):
    with pytest.raises(InstrumentError):
        capture({key: value for key, value in INFO.items() if key != field})


def test_optional_margin_currency_is_not_guessed():
    snapshot = capture({key: value for key, value in INFO.items() if key != "currency_margin"})
    assert snapshot.registry.get("EURUSD").currency_margin is None
    assert snapshot.as_dict()["instruments"]["EURUSD"]["currency_margin"] is None


@pytest.mark.parametrize("field,value", [
    ("digits", True), ("digits", 5.5), ("digits", "5"), ("digits", -1), ("digits", 10**400),
    ("point", float("nan")), ("point", float("inf")), ("point", "0.00001"),
    ("trade_tick_value", float("inf")), ("trade_tick_value", 0),
    ("trade_contract_size", True), ("trade_contract_size", -1),
    ("volume_min", 200), ("volume_step", 200), ("volume_max", None),
    ("trade_stops_level", 0.5), ("trade_freeze_level", False),
    ("currency_base", None), ("currency_profit", "JPY"), ("currency_margin", ""),
    ("name", "GBPUSD.raw"), ("point", 0.0001), ("trade_tick_size", 0.000015),
])
def test_invalid_metadata_fails_closed(field, value):
    with pytest.raises(InstrumentError):
        capture({**INFO, field: value})


@pytest.mark.parametrize("symbols", [
    {}, [], {"EURUSD": ""}, {"eurusd": "EURUSD.raw", "EURUSD": "EURUSD"},
    {"EURUSD": "EURUSD.raw", "GBPUSD": "EURUSD.raw"},
    {" EURUSD": "EURUSD.raw"}, {"EURUSD": "EURUSD\nraw"},
    {"EURUSD": None}, {None: "EURUSD"}, {"EURUSD": "terminal:password=value"},
])
def test_invalid_aliases_reject_before_any_client_call(symbols):
    client = ReadOnlyClient()
    with pytest.raises(InstrumentError):
        build_instrument_registry_snapshot(client=client, symbols=symbols, captured_at_utc=CAPTURED)
    assert client.calls == []


@pytest.mark.parametrize("timestamp", [None, "2026-10-05", CAPTURED.replace(tzinfo=None)])
def test_invalid_capture_time_rejects_before_client_call(timestamp):
    client = ReadOnlyClient()
    with pytest.raises(InstrumentError):
        build_instrument_registry_snapshot(client=client, symbols={"EURUSD": "EURUSD.raw"}, captured_at_utc=timestamp)
    assert client.calls == []


def test_none_from_client_is_not_a_snapshot():
    with pytest.raises(InstrumentError):
        build_instrument_registry_snapshot(client=ReadOnlyClient({"EURUSD.raw": None}), symbols={"EURUSD": "EURUSD.raw"}, captured_at_utc=CAPTURED)


def test_client_errors_are_sanitized_and_not_chained():
    class BrokenClient:
        def symbol_info(self, symbol):
            raise RuntimeError("password=PRIVATE server=PRIVATE account=PRIVATE")

    with pytest.raises(InstrumentError) as caught:
        build_instrument_registry_snapshot(client=BrokenClient(), symbols={"EURUSD": "EURUSD.raw"}, captured_at_utc=CAPTURED)
    assert "PRIVATE" not in json.dumps(caught.value.as_dict())
    assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize("field", ["tick_value", "broker_symbol", "currency_margin", "digits", "volume_step"])
def test_tampered_instrument_metadata_rejected_on_load(field):
    payload = capture().as_dict()
    original = payload["instruments"]["EURUSD"][field]
    payload["instruments"]["EURUSD"][field] = original + 1 if isinstance(original, (int, float)) else "XXX"
    with pytest.raises(InstrumentError):
        InstrumentRegistry.from_mapping(payload)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "9.0"), ("source", "manual"), ("captured_at_utc", "2026-10-06T12:00:00+00:00"),
    ("captured_at_utc", "2026-10-05T12:00:00"), ("instrument_count", True),
    ("symbols", ["GBPUSD"]), ("instruments", []),
    ("metadata_hash", "0" * 64), ("snapshot_hash", "0" * 64),
])
def test_tampered_snapshot_envelope_rejected(field, value):
    payload = capture().as_dict()
    payload[field] = value
    with pytest.raises(InstrumentError):
        InstrumentRegistrySnapshot.from_mapping(payload)


@pytest.mark.parametrize("field", list(capture().as_dict()))
def test_incomplete_snapshot_cannot_silently_become_legacy(field):
    payload = capture().as_dict()
    del payload[field]
    with pytest.raises(InstrumentError):
        InstrumentRegistry.from_mapping(payload)


def test_unknown_fields_and_duplicate_json_keys_are_rejected(tmp_path):
    payload = capture().as_dict()
    payload["untrusted_field"] = "PRIVATE"
    with pytest.raises(InstrumentError):
        InstrumentRegistrySnapshot.from_mapping(payload)
    payload = capture().as_dict()
    payload["instruments"]["EURUSD"]["untrusted_field"] = "PRIVATE"
    with pytest.raises(InstrumentError):
        InstrumentRegistrySnapshot.from_mapping(payload)
    path = tmp_path / "instruments.json"
    path.write_text('{"instruments": {}, "instruments": {}}', encoding="utf-8")
    with pytest.raises(InstrumentError):
        InstrumentRegistry.from_dataset(tmp_path)
    with pytest.raises(InstrumentError):
        InstrumentRegistrySnapshot.read(path)


def test_legacy_sidecar_remains_loadable_but_not_claimed_as_capture(tmp_path):
    spec = assumed_fx_spec("EURUSD")
    path = tmp_path / "instruments.json"
    path.write_text(json.dumps({"EURUSD": spec.as_dict()}), encoding="utf-8")
    assert InstrumentRegistry.from_dataset(tmp_path).get("EURUSD") == spec
    with pytest.raises(InstrumentError):
        InstrumentRegistrySnapshot.read(path)
    with pytest.raises(InstrumentError):
        InstrumentRegistrySnapshot(InstrumentRegistry.from_specs([spec]), CAPTURED)


def test_registry_rejects_duplicates_nonfinite_values_and_bad_types():
    spec = assumed_fx_spec("EURUSD")
    for field, value in [("tick_value", float("inf")), ("point", True), ("digits", 5.5), ("currency_quote", None)]:
        with pytest.raises(InstrumentError):
            replace(spec, **{field: value}).validate()
        with pytest.raises(InstrumentError):
            spec_from_mapping("EURUSD", {**spec.as_dict(), field: value})
    with pytest.raises(InstrumentError):
        InstrumentRegistry.from_specs([spec, spec])
    with pytest.raises(InstrumentError):
        InstrumentRegistry.from_mapping({"GBPUSD": spec.as_dict()})
    with pytest.raises(InstrumentError):
        InstrumentRegistry.from_mapping({"EURUSD": "invalid"})


def test_registry_uses_reported_alias_without_guessing():
    registry = InstrumentRegistry.from_symbol_info({"EURUSD": INFO})
    assert registry.get("EURUSD").broker_symbol == "EURUSD.raw"
    with pytest.raises(InstrumentError):
        spec_from_symbol_info("EURUSD", INFO, broker_symbol="EURUSD.other")

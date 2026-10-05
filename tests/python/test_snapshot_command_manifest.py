import json
from datetime import datetime, timezone

import pytest

from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.run_manifest import RunManifest
from agi_style_forex_bot_mt5.core.workspace import WorkspacePaths
from agi_style_forex_bot_mt5.instrument_snapshot_command import capture_instrument_snapshot
from agi_style_forex_bot_mt5.core.instruments.snapshot import InstrumentRegistrySnapshot


NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


class MetadataClient:
    def __init__(self):
        self.calls = []

    def initialize(self):
        self.calls.append("initialize")
        return True

    def symbol_info(self, symbol):
        self.calls.append(("symbol_info", symbol))
        return dict(name=symbol, digits=5, point=0.00001, trade_tick_size=0.00001, trade_tick_value=1.,
                    trade_contract_size=100000., volume_min=0.01, volume_max=100., volume_step=0.01,
                    trade_stops_level=0, trade_freeze_level=0, currency_base="EUR", currency_profit="USD")

    def shutdown(self):
        self.calls.append("shutdown")

    def __getattr__(self, name):
        raise AssertionError(f"unexpected broker method {name}")


def test_capture_is_read_only_frozen_and_non_overwriting(tmp_path):
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"EURUSD": "EURUSD.raw"}))
    output = tmp_path / "instruments.json"
    client = MetadataClient()
    result = capture_instrument_snapshot(client=client, symbol_map_path=mapping, output_path=output, clock=FrozenClock(NOW))
    assert client.calls == ["initialize", ("symbol_info", "EURUSD.raw"), "shutdown"]
    assert result["instrument_snapshot_hash"] == InstrumentRegistrySnapshot.read(output).snapshot_hash
    assert result["execution_attempted"] is False
    assert result["historical_metadata_verified"] is False
    with pytest.raises(FileExistsError):
        capture_instrument_snapshot(client=client, symbol_map_path=mapping, output_path=output)
    assert len(client.calls) == 3


def test_capture_failure_disconnects_without_partial_artifact(tmp_path):
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"EURUSD": "EURUSD.raw"}))
    output = tmp_path / "instruments.json"
    client = MetadataClient()
    client.symbol_info = lambda symbol: None
    with pytest.raises(Exception):
        capture_instrument_snapshot(client=client, symbol_map_path=mapping, output_path=output)
    assert client.calls[-1] == "shutdown"
    assert not output.exists()


def test_manifest_identity_changes_for_dirty_code_and_broker_snapshot(tmp_path):
    source = tmp_path / "src" / "engine.py"
    source.parent.mkdir()
    source.write_text("version = 1\n")
    workspace = WorkspacePaths.resolve(project_root=tmp_path, data_root=tmp_path / "data")
    kwargs = dict(mode="test", clock=FrozenClock(NOW), workspace=workspace,
                  config={"profile": "CONSERVATIVE"}, dataset_hash="dataset", seed=82)
    first = RunManifest.build(**kwargs, instrument_snapshot_hash="a" * 64)
    assert first.as_dict() == RunManifest.build(**kwargs, instrument_snapshot_hash="a" * 64).as_dict()
    second = RunManifest.build(**kwargs, instrument_snapshot_hash="b" * 64)
    assert first.run_id != second.run_id
    source.write_text("version = 2\n")
    third = RunManifest.build(**kwargs, instrument_snapshot_hash="a" * 64)
    assert first.run_id != third.run_id and first.source_tree_hash != third.source_tree_hash
    assert third.manifest_version == "1.1"


@pytest.mark.parametrize("digest", ["bad", "../secret", "g" * 64])
def test_manifest_rejects_malformed_metadata_digest(digest):
    with pytest.raises(ValueError):
        RunManifest.build(mode="test", clock=FrozenClock(NOW), instrument_snapshot_hash=digest)

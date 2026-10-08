"""Conversion must preserve inspected evidence and never relabel it holdout."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_inspected_development_study.py"
spec = importlib.util.spec_from_file_location("prepare_inspected_development_study", SCRIPT)
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


def _inputs(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    for symbol in converter.SYMBOLS:
        times = pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC").map(lambda x: x.isoformat())
        pd.DataFrame({"time": times, "timestamp_utc": times,
            "open": [1.1] * 4, "high": [1.1001] * 4,
            "low": [1.0998] * 4, "close": [1.10005] * 4,
            "tick_volume": [13, 0, 24, 91], "real_volume": [0] * 4,
            "spread": [0, 0.5, 1, 12]}).to_csv(source / f"{symbol}_M5.csv", index=False)
    return source


def test_conversion_preserves_effective_values_and_unknown_provenance(tmp_path):
    source = _inputs(tmp_path)
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    output = tmp_path / "converted"
    payload = json.loads(converter.prepare(source, output).read_text())
    assert payload["data_role"] == "DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED"
    assert payload["denomination_currency"] == "USD" and payload["lot"] == 0.1
    for symbol, item in payload["datasets"].items():
        values = pd.read_csv(output / item["path"], float_precision="round_trip")
        original = pd.read_csv(source / item["path"], float_precision="round_trip")
        for new, old in [("open", "open"), ("close", "close"), ("volume", "tick_volume"), ("spread_points", "spread")]:
            assert values[new].tolist() == original[old].tolist()
        quality = item["quality_report"]
        assert quality["original_source_sha256"] == sha256(before[item["path"]]).hexdigest()
        assert quality["discarded_rows"] == 0 and quality["zero_spread_rows"] == 1
        assert quality["final_holdout"] == "NOT_AVAILABLE" and quality["cost_verified"] is False
        assert item["tick_value_status"] == item["cost_provenance"]["status"] == "ASSUMED"
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}


@pytest.mark.parametrize("case", ["time_disagreement", "duplicate", "unsorted", "naive"])
def test_invalid_history_is_not_repaired_or_partially_exported(tmp_path, case):
    source = _inputs(tmp_path)
    path = source / "GBPUSD_M5.csv"
    frame = pd.read_csv(path)
    if case == "time_disagreement":
        frame.loc[0, "time"] = frame.loc[1, "time"]
    elif case == "duplicate":
        frame.loc[1, ["time", "timestamp_utc"]] = frame.loc[0, ["time", "timestamp_utc"]]
    elif case == "unsorted":
        frame = frame.iloc[::-1]
    else:
        for column in ("time", "timestamp_utc"):
            frame[column] = frame[column].str.replace("+00:00", "", regex=False)
    frame.to_csv(path, index=False)
    output = tmp_path / "converted"
    with pytest.raises(ValueError):
        converter.prepare(source, output)
    assert not output.exists()


def test_converter_cannot_overwrite_prior_evidence(tmp_path):
    source = _inputs(tmp_path)
    output = tmp_path / "converted"
    converter.prepare(source, output)
    before = (output / "inputs.json").read_bytes()
    with pytest.raises(FileExistsError):
        converter.prepare(source, output)
    assert (output / "inputs.json").read_bytes() == before

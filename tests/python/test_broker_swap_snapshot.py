"""Read-only broker swap snapshot, per-symbol fail-closed capture and measured carry."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.broker_swap_snapshot import (
    DAY_OF_WEEK_NAMES,
    SWAP_MODE_NAMES,
    annualised_swap_carry,
    build_swap_snapshot,
    read_swap_snapshot,
    snapshot_carry,
    verify_swap_snapshot,
    write_swap_snapshot,
)
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.instruments import derive_tick_value
from agi_style_forex_bot_mt5.core.operational_state.errors import InstrumentError
from agi_style_forex_bot_mt5.swap_snapshot_command import capture_swap_snapshot


CAPTURED = datetime(2026, 10, 22, 21, 30, tzinfo=timezone.utc)
SYMBOLS = {"EURUSD": "EURUSD.raw", "USDJPY": "USDJPY.raw"}
EURUSD = {
    "name": "EURUSD.raw", "swap_long": -6.5, "swap_short": 1.2, "swap_mode": 1, "swap_rollover3days": 3,
    "currency_base": "EUR", "currency_profit": "USD", "currency_margin": "EUR",
    "trade_contract_size": 100000.0, "point": 0.00001, "digits": 5, "spread": 12,
    # Real symbol_info fields that the snapshot must not copy.
    "bid": 1.1, "ask": 1.10012, "trade_tick_value": 0.97, "volume_min": 0.01,
}
USDJPY = {**EURUSD, "name": "USDJPY.raw", "swap_long": 15.0, "swap_short": -32.0, "currency_base": "USD",
          "currency_profit": "JPY", "currency_margin": "USD", "point": 0.001, "digits": 3, "spread": 9}


class SwapTerminal:
    """Fake read-only terminal: any capability other than these three is a test failure."""

    def __init__(self, infos=None, *, connected=True):
        self.infos = {"EURUSD.raw": SimpleNamespace(**EURUSD), "USDJPY.raw": SimpleNamespace(**USDJPY)} if infos is None else infos
        self.connected = connected
        self.calls = []

    def initialize(self):
        self.calls.append("initialize")
        return self.connected

    def symbol_info(self, symbol):
        self.calls.append(("symbol_info", symbol))
        value = self.infos[symbol]
        if isinstance(value, Exception):
            raise value
        return value

    def shutdown(self):
        self.calls.append("shutdown")

    def __getattr__(self, name):
        raise AssertionError(f"unexpected terminal capability: {name}")


def build(infos=None, symbols=None, captured_at_utc=CAPTURED, server_time="NY_CLOSE"):
    client = SwapTerminal(infos)
    payload = build_swap_snapshot(client=client, symbols=SYMBOLS if symbols is None else symbols,
                                  captured_at_utc=captured_at_utc, mt5_server_time=server_time)
    return payload, client


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


# --------------------------------------------------------------------------- capture


def test_capture_reads_only_symbol_info_and_records_whitelisted_terms():
    infos = {"EURUSD.raw": SimpleNamespace(**EURUSD, login="PRIVATE_LOGIN", server="PRIVATE_SERVER"),
             "USDJPY.raw": dict(USDJPY)}
    payload, client = build(infos)
    assert client.calls == [("symbol_info", "EURUSD.raw"), ("symbol_info", "USDJPY.raw")]
    assert payload["instruments"]["EURUSD"] == {
        "canonical_symbol": "EURUSD", "broker_symbol": "EURUSD.raw", "status": "CAPTURED",
        "swap_long": -6.5, "swap_short": 1.2, "swap_mode": 1, "swap_mode_name": "POINTS",
        "swap_rollover3days": 3, "swap_rollover3days_name": "WEDNESDAY",
        "currency_base": "EUR", "currency_profit": "USD", "currency_margin": "EUR",
        "trade_contract_size": 100000.0, "point": 0.00001, "digits": 5, "spread_points": 12,
    }
    assert payload["status"] == "CAPTURED"
    assert (payload["instrument_count"], payload["captured_count"], payload["unavailable_count"]) == (2, 2, 0)
    assert payload["symbols"] == ["EURUSD", "USDJPY"]
    assert payload["captured_at_utc"] == "2026-10-22T21:30:00+00:00"
    assert payload["mt5_server_time"] == "NY_CLOSE"
    assert payload["source"] == "mt5:symbol_info" and payload["schema_version"] == "broker_swap_snapshot_v1"
    assert payload["account_data_read"] is False
    assert payload["execution_attempted"] is False and payload["order_send_called"] is False
    assert payload["order_check_called"] is False and payload["demo_only"] is True
    assert payload["live_trading_approved"] is False
    text = json.dumps(payload)
    for leaked in ("PRIVATE", "bid", "ask", "trade_tick_value", "volume_min", "login"):
        assert leaked not in text


def test_swap_mode_and_rollover_names_cover_the_mt5_enums():
    assert dict(SWAP_MODE_NAMES) == {
        0: "DISABLED", 1: "POINTS", 2: "CURRENCY_SYMBOL", 3: "CURRENCY_MARGIN", 4: "CURRENCY_DEPOSIT",
        5: "INTEREST_CURRENT", 6: "INTEREST_OPEN", 7: "REOPEN_CURRENT", 8: "REOPEN_BID",
    }
    assert dict(DAY_OF_WEEK_NAMES) == {0: "SUNDAY", 1: "MONDAY", 2: "TUESDAY", 3: "WEDNESDAY",
                                       4: "THURSDAY", 5: "FRIDAY", 6: "SATURDAY"}
    for code, name in SWAP_MODE_NAMES.items():
        payload, _ = build({"EURUSD.raw": {**EURUSD, "swap_mode": code}}, {"EURUSD": "EURUSD.raw"})
        assert payload["instruments"]["EURUSD"]["swap_mode_name"] == name


def _missing(field):
    return {key: value for key, value in EURUSD.items() if key != field}


@pytest.mark.parametrize("info,reason", [
    (None, "SYMBOL_INFO_MISSING"),
    (RuntimeError("password=PRIVATE server=PRIVATE"), "SYMBOL_INFO_FAILED"),
    ({**EURUSD, "name": "GBPUSD.raw"}, "BROKER_NAME_MISMATCH"),
    ({**EURUSD, "name": None}, "FIELD_INVALID:name"),
    (_missing("name"), "FIELD_MISSING:name"),
    (_missing("swap_long"), "FIELD_MISSING:swap_long"),
    (_missing("spread"), "FIELD_MISSING:spread"),
    (_missing("currency_margin"), "FIELD_MISSING:currency_margin"),
    ({**EURUSD, "swap_long": float("nan")}, "FIELD_INVALID:swap_long"),
    ({**EURUSD, "swap_short": float("inf")}, "FIELD_INVALID:swap_short"),
    ({**EURUSD, "swap_long": "1.0"}, "FIELD_INVALID:swap_long"),
    ({**EURUSD, "swap_long": True}, "FIELD_INVALID:swap_long"),
    ({**EURUSD, "swap_long": 10**400}, "FIELD_INVALID:swap_long"),
    ({**EURUSD, "swap_mode": 9}, "SWAP_MODE_UNKNOWN"),
    ({**EURUSD, "swap_mode": -1}, "SWAP_MODE_UNKNOWN"),
    ({**EURUSD, "swap_mode": True}, "FIELD_INVALID:swap_mode"),
    ({**EURUSD, "swap_mode": 1.0}, "FIELD_INVALID:swap_mode"),
    ({**EURUSD, "swap_rollover3days": 7}, "FIELD_INVALID:swap_rollover3days"),
    ({**EURUSD, "swap_rollover3days": None}, "FIELD_INVALID:swap_rollover3days"),
    ({**EURUSD, "currency_base": "EU"}, "FIELD_INVALID:currency_base"),
    ({**EURUSD, "currency_margin": ""}, "FIELD_INVALID:currency_margin"),
    ({**EURUSD, "currency_profit": "JPY"}, "CURRENCY_MISMATCH"),
    ({**EURUSD, "trade_contract_size": 0}, "FIELD_INVALID:trade_contract_size"),
    ({**EURUSD, "trade_contract_size": -1.0}, "FIELD_INVALID:trade_contract_size"),
    ({**EURUSD, "point": 0.0}, "FIELD_INVALID:point"),
    ({**EURUSD, "digits": 5.0}, "FIELD_INVALID:digits"),
    ({**EURUSD, "digits": -1}, "FIELD_INVALID:digits"),
    ({**EURUSD, "point": 0.0001}, "POINT_DIGITS_MISMATCH"),
    ({**EURUSD, "spread": -1}, "FIELD_INVALID:spread"),
    ({**EURUSD, "spread": 1.5}, "FIELD_INVALID:spread"),
    ({**EURUSD, "spread": False}, "FIELD_INVALID:spread"),
])
def test_an_invalid_symbol_is_recorded_unavailable_and_the_rest_is_captured(info, reason):
    payload, client = build({"EURUSD.raw": info, "USDJPY.raw": dict(USDJPY)})
    assert payload["instruments"]["EURUSD"] == {"canonical_symbol": "EURUSD", "broker_symbol": "EURUSD.raw",
                                                "status": "UNAVAILABLE", "reason": reason}
    assert payload["instruments"]["USDJPY"]["status"] == "CAPTURED"
    assert payload["status"] == "PARTIAL"
    assert (payload["captured_count"], payload["unavailable_count"]) == (1, 1)
    assert client.calls == [("symbol_info", "EURUSD.raw"), ("symbol_info", "USDJPY.raw")]
    assert "PRIVATE" not in json.dumps(payload)
    assert verify_swap_snapshot(payload) == payload


def test_a_snapshot_with_nothing_captured_says_unavailable():
    payload, _ = build({"EURUSD.raw": None, "USDJPY.raw": RuntimeError("down")})
    assert payload["status"] == "UNAVAILABLE"
    assert (payload["captured_count"], payload["unavailable_count"]) == (0, 2)


@pytest.mark.parametrize("symbols", [
    {}, [], {"EURUSD": ""}, {"eurusd": "EURUSD.raw", "EURUSD": "EURUSD"},
    {"EURUSD": "EURUSD.raw", "GBPUSD": "EURUSD.raw"}, {" EURUSD": "EURUSD.raw"},
    {"EURUSD": "EURUSD\nraw"}, {"EURUSD": None}, {None: "EURUSD"}, {"EURUSD": "terminal:password=value"},
])
def test_invalid_symbol_maps_reject_before_any_client_call(symbols):
    client = SwapTerminal()
    with pytest.raises(InstrumentError):
        build_swap_snapshot(client=client, symbols=symbols, captured_at_utc=CAPTURED, mt5_server_time="UTC")
    assert client.calls == []


@pytest.mark.parametrize("captured_at_utc,server_time", [
    (None, "UTC"), ("2026-10-22", "UTC"), (CAPTURED.replace(tzinfo=None), "UTC"),
    (CAPTURED, "AUTO"), (CAPTURED, ""), (CAPTURED, None),
])
def test_invalid_time_inputs_reject_before_any_client_call(captured_at_utc, server_time):
    client = SwapTerminal()
    with pytest.raises((InstrumentError, ValueError)):
        build_swap_snapshot(client=client, symbols=SYMBOLS, captured_at_utc=captured_at_utc, mt5_server_time=server_time)
    assert client.calls == []


def test_mt5_enum_constants_are_checked_statically_and_a_mismatch_refuses_capture():
    class TerminalWithConstants(SwapTerminal):
        SYMBOL_SWAP_MODE_DISABLED = 0
        SYMBOL_SWAP_MODE_POINTS = 1
        SYMBOL_SWAP_MODE_REOPEN_BID = 8
        DAY_OF_WEEK_WEDNESDAY = 3

    client = TerminalWithConstants()
    payload = build_swap_snapshot(client=client, symbols=SYMBOLS, captured_at_utc=CAPTURED, mt5_server_time="UTC")
    assert payload["enum_constants_checked"] is True
    assert build()[0]["enum_constants_checked"] is False

    class MismatchedTerminal(SwapTerminal):
        SYMBOL_SWAP_MODE_POINTS = 2

    client = MismatchedTerminal()
    with pytest.raises(InstrumentError, match="disagree"):
        build_swap_snapshot(client=client, symbols=SYMBOLS, captured_at_utc=CAPTURED, mt5_server_time="UTC")
    assert client.calls == []


# --------------------------------------------------------------------------- hashes and files


def test_payload_hash_is_the_sha256_of_the_canonical_payload_and_reproducible():
    first, _ = build()
    reversed_map = dict(reversed(list(SYMBOLS.items())))
    second, _ = build(symbols=reversed_map, captured_at_utc=CAPTURED.astimezone(timezone(timedelta(hours=-4))))
    assert first == second
    content = {key: value for key, value in first.items() if key != "payload_sha256"}
    assert first["payload_sha256"] == hashlib.sha256(canonical(content).encode("utf-8")).hexdigest()
    assert len(first["swap_terms_hash"]) == 64


def test_terms_hash_ignores_capture_time_and_spread_but_not_swap_terms():
    base, _ = build()
    later, _ = build(captured_at_utc=CAPTURED + timedelta(days=1))
    wider, _ = build({"EURUSD.raw": {**EURUSD, "spread": 40}, "USDJPY.raw": dict(USDJPY)})
    repriced, _ = build({"EURUSD.raw": {**EURUSD, "swap_long": -7.1}, "USDJPY.raw": dict(USDJPY)})
    assert base["swap_terms_hash"] == later["swap_terms_hash"] == wider["swap_terms_hash"]
    assert base["payload_sha256"] != later["payload_sha256"]
    assert base["payload_sha256"] != wider["payload_sha256"]
    assert repriced["swap_terms_hash"] != base["swap_terms_hash"]


def test_write_publishes_exclusively_and_round_trips(tmp_path):
    payload, _ = build()
    path = write_swap_snapshot(payload, tmp_path / "swap.json")
    assert path.read_bytes() == (canonical(payload) + "\n").encode("utf-8")
    assert read_swap_snapshot(path) == payload
    with pytest.raises(FileExistsError):
        write_swap_snapshot(payload, path)
    assert read_swap_snapshot(path) == payload
    assert sorted(item.name for item in tmp_path.iterdir()) == ["swap.json"]


def test_write_failure_is_sanitized_and_leaves_nothing(tmp_path, monkeypatch):
    import agi_style_forex_bot_mt5.broker_swap_snapshot as module

    def fail_link(*_args):
        raise OSError("sensitive local path")

    monkeypatch.setattr(module.os, "link", fail_link)
    with pytest.raises(OSError) as caught:
        write_swap_snapshot(build()[0], tmp_path / "swap.json")
    assert "sensitive" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


def _tamper(payload, path, value):
    target = payload
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return payload


@pytest.mark.parametrize("path,value", [
    (("instruments", "EURUSD", "swap_long"), -1.0),
    (("instruments", "EURUSD", "swap_mode_name"), "DISABLED"),
    (("instruments", "EURUSD", "digits"), 5.0),
    (("instruments", "EURUSD", "status"), "UNAVAILABLE"),
    (("instruments", "EURUSD", "extra"), "PRIVATE"),
    (("instruments", "EURUSD", "spread_points"), KeyError),
    (("instruments", "EURUSD", "canonical_symbol"), "GBPUSD"),
    (("status",), "CAPTURED"),
    (("captured_count",), 2),
    (("instrument_count",), True),
    (("payload_sha256",), "0" * 64),
    (("swap_terms_hash",), "0" * 64),
    (("captured_at_utc",), "2026-10-22T21:30:00"),
    (("captured_at_utc",), "yesterday"),
    (("mt5_server_time",), "AUTO"),
    (("schema_version",), "broker_swap_snapshot_v0"),
    (("source",), "manual"),
    (("execution_attempted",), True),
    (("account_data_read",), True),
    (("enum_constants_checked",), "yes"),
    (("untrusted",), "PRIVATE"),
    (("symbols",), KeyError),
])
def test_tampered_or_incomplete_snapshots_are_rejected(path, value):
    payload, _ = build({"EURUSD.raw": dict(EURUSD), "USDJPY.raw": None})
    with pytest.raises(InstrumentError):
        verify_swap_snapshot(_tamper(json.loads(json.dumps(payload)), path, value))


@pytest.mark.parametrize("reason", ["free text with password=PRIVATE", "FIELD_INVALID:Swap Long", ""])
def test_unavailable_reasons_are_closed_codes(reason):
    payload, _ = build({"EURUSD.raw": None, "USDJPY.raw": dict(USDJPY)})
    payload["instruments"]["EURUSD"]["reason"] = reason
    with pytest.raises(InstrumentError):
        verify_swap_snapshot(payload)


def test_read_rejects_duplicate_keys_and_invalid_json(tmp_path):
    path = tmp_path / "swap.json"
    path.write_text('{"status": "CAPTURED", "status": "PARTIAL"}', encoding="utf-8")
    with pytest.raises(InstrumentError):
        read_swap_snapshot(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(InstrumentError):
        read_swap_snapshot(path)
    with pytest.raises(InstrumentError):
        read_swap_snapshot(tmp_path / "missing.json")


# --------------------------------------------------------------------------- command


def _map(tmp_path, content='{"EURUSD": "EURUSD.raw", "USDJPY": "USDJPY.raw"}', bom=False):
    path = tmp_path / "symbol_map.json"
    path.write_bytes(("﻿" if bom else "").encode("utf-8") + content.encode("utf-8"))
    return path


def test_command_is_read_only_sealed_and_never_overwrites(tmp_path):
    client = SwapTerminal()
    output = tmp_path / "swap.json"
    summary = capture_swap_snapshot(client=client, symbol_map_path=_map(tmp_path, bom=True), output_path=output,
                                    mt5_server_time="NY_CLOSE", clock=FrozenClock(CAPTURED))
    assert client.calls == ["initialize", ("symbol_info", "EURUSD.raw"), ("symbol_info", "USDJPY.raw"), "shutdown"]
    stored = read_swap_snapshot(output)
    assert summary["mode"] == "capture-swap-snapshot" and summary["status"] == "CAPTURED"
    assert summary["payload_sha256"] == stored["payload_sha256"]
    assert summary["swap_terms_hash"] == stored["swap_terms_hash"]
    assert summary["mt5_server_time"] == "NY_CLOSE" and summary["unavailable"] == {}
    assert summary["account_data_read"] is False and summary["output"] == str(output)
    for flag, value in (("execution_attempted", False), ("order_send_called", False), ("order_check_called", False),
                        ("demo_only", True), ("live_trading_approved", False)):
        assert summary[flag] is value
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        capture_swap_snapshot(client=client, symbol_map_path=_map(tmp_path), output_path=output, mt5_server_time="UTC")
    assert output.read_bytes() == before and len(client.calls) == 4


def test_command_reports_partial_captures_with_reasons(tmp_path):
    client = SwapTerminal({"EURUSD.raw": dict(EURUSD), "USDJPY.raw": None})
    summary = capture_swap_snapshot(client=client, symbol_map_path=_map(tmp_path), output_path=tmp_path / "swap.json",
                                    mt5_server_time="UTC", clock=FrozenClock(CAPTURED))
    assert summary["status"] == "PARTIAL" and summary["unavailable"] == {"USDJPY": "SYMBOL_INFO_MISSING"}
    assert read_swap_snapshot(tmp_path / "swap.json")["status"] == "PARTIAL"


@pytest.mark.parametrize("content,error", [
    ("not json", ValueError), ("[]", ValueError), ("{}", ValueError),
    ('{"EURUSD": "EURUSD.raw", "EURUSD": "EURUSD"}', ValueError),
    ('{"EURUSD": "terminal:password=value"}', InstrumentError),
])
def test_command_rejects_invalid_maps_before_touching_the_terminal(tmp_path, content, error):
    client = SwapTerminal()
    with pytest.raises(error):
        capture_swap_snapshot(client=client, symbol_map_path=_map(tmp_path, content), output_path=tmp_path / "swap.json",
                              mt5_server_time="UTC")
    assert client.calls == [] and not (tmp_path / "swap.json").exists()


def test_command_rejects_bad_destinations_and_server_time_before_touching_the_terminal(tmp_path):
    client = SwapTerminal()
    symbol_map = _map(tmp_path)
    with pytest.raises(ValueError):
        capture_swap_snapshot(client=client, symbol_map_path=symbol_map, output_path=tmp_path / "missing" / "swap.json",
                              mt5_server_time="UTC")
    with pytest.raises(ValueError):
        capture_swap_snapshot(client=client, symbol_map_path=tmp_path / "no_map.json", output_path=tmp_path / "swap.json",
                              mt5_server_time="UTC")
    with pytest.raises(ValueError):
        capture_swap_snapshot(client=client, symbol_map_path=symbol_map, output_path=tmp_path / "swap.json",
                              mt5_server_time="AUTO")
    assert client.calls == []


def test_command_with_a_closed_terminal_raises_without_artifact(tmp_path):
    client = SwapTerminal(connected=False)
    with pytest.raises(RuntimeError):
        capture_swap_snapshot(client=client, symbol_map_path=_map(tmp_path), output_path=tmp_path / "swap.json",
                              mt5_server_time="UTC")
    assert client.calls == ["initialize"] and not (tmp_path / "swap.json").exists()

    class ExplodingTerminal(SwapTerminal):
        def initialize(self):
            self.calls.append("initialize")
            raise OSError("password=PRIVATE")

    client = ExplodingTerminal()
    with pytest.raises(RuntimeError) as caught:
        capture_swap_snapshot(client=client, symbol_map_path=_map(tmp_path), output_path=tmp_path / "swap.json",
                              mt5_server_time="UTC")
    assert "PRIVATE" not in str(caught.value) and caught.value.__suppress_context__ is True
    assert not (tmp_path / "swap.json").exists()


def test_command_shuts_down_after_a_write_failure(tmp_path, monkeypatch):
    import agi_style_forex_bot_mt5.broker_swap_snapshot as module

    def fail_link(*_args):
        raise OSError("disk")

    monkeypatch.setattr(module.os, "link", fail_link)
    client = SwapTerminal()
    with pytest.raises(OSError):
        capture_swap_snapshot(client=client, symbol_map_path=_map(tmp_path), output_path=tmp_path / "swap.json",
                              mt5_server_time="UTC")
    assert client.calls[-1] == "shutdown"
    assert not (tmp_path / "swap.json").exists()


# --------------------------------------------------------------------------- CLI


def _terminal_module(infos=None, *, connected=True, **constants):
    terminal = SwapTerminal(infos, connected=connected)
    module = SimpleNamespace(initialize=terminal.initialize, symbol_info=terminal.symbol_info,
                             shutdown=terminal.shutdown, **constants)
    return module, terminal


def _last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_cli_capture_writes_a_snapshot_with_the_declared_server_clock(monkeypatch, tmp_path, capsys):
    config = tmp_path / "bot.ini"
    config.write_text("MT5_SERVER_TIME=NY_CLOSE\n", encoding="utf-8")
    module, terminal = _terminal_module(SYMBOL_SWAP_MODE_POINTS=1, SYMBOL_SWAP_MODE_INTEREST_OPEN=6)
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    output = tmp_path / "swap.json"
    code = cli.main(["--mode", "capture-swap-snapshot", "--broker-symbol-map", str(_map(tmp_path, bom=True)),
                     "--swap-snapshot-output", str(output), "--config", str(config)])
    summary = _last_json(capsys)
    assert code == 0 and summary["status"] == "CAPTURED"
    assert summary["enum_constants_checked"] is True and summary["mt5_server_time"] == "NY_CLOSE"
    assert summary["execution_attempted"] is False and summary["order_send_called"] is False
    assert read_swap_snapshot(output)["payload_sha256"] == summary["payload_sha256"]
    assert terminal.calls == ["initialize", ("symbol_info", "EURUSD.raw"), ("symbol_info", "USDJPY.raw"), "shutdown"]


def test_cli_partial_capture_still_exits_zero_with_reasons(monkeypatch, tmp_path, capsys):
    module, _ = _terminal_module({"EURUSD.raw": dict(EURUSD), "USDJPY.raw": {**USDJPY, "swap_mode": 42}})
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    code = cli.main(["--mode", "capture-swap-snapshot", "--broker-symbol-map", str(_map(tmp_path)),
                     "--swap-snapshot-output", str(tmp_path / "swap.json")])
    summary = _last_json(capsys)
    assert code == 0 and summary["status"] == "PARTIAL" and summary["unavailable"] == {"USDJPY": "SWAP_MODE_UNKNOWN"}


def test_cli_exit_codes(monkeypatch, tmp_path, capsys):
    output = tmp_path / "swap.json"
    arguments = ["--mode", "capture-swap-snapshot", "--broker-symbol-map", str(_map(tmp_path)),
                 "--swap-snapshot-output", str(output)]
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    assert cli.main(arguments) == cli.EXIT_MT5_UNAVAILABLE
    assert _last_json(capsys)["status"] == "MT5_UNAVAILABLE"
    module, terminal = _terminal_module(connected=False)
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    assert cli.main(arguments) == cli.EXIT_MT5_UNAVAILABLE
    assert _last_json(capsys)["status"] == "MT5_UNAVAILABLE" and terminal.calls == ["initialize"]
    module, terminal = _terminal_module(SYMBOL_SWAP_MODE_POINTS=5)
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    assert cli.main(arguments) == cli.EXIT_INVALID_ARGUMENTS
    assert _last_json(capsys)["status"] == "CAPTURE_REFUSED" and terminal.calls == []
    output.write_text("{}", encoding="utf-8")
    # Arguments are validated before MetaTrader5 is imported, so this is 2 even without it.
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    assert cli.main(arguments) == cli.EXIT_INVALID_ARGUMENTS
    assert _last_json(capsys)["status"] == "OUTPUT_EXISTS"
    bad_map = _map(tmp_path, '{"EURUSD": "EURUSD.raw", "EURUSD": "EURUSD"}')
    assert cli.main(["--mode", "capture-swap-snapshot", "--broker-symbol-map", str(bad_map),
                     "--swap-snapshot-output", str(tmp_path / "other.json")]) == cli.EXIT_INVALID_ARGUMENTS
    assert _last_json(capsys)["status"] == "INVALID_ARGUMENTS"
    with pytest.raises(SystemExit) as caught:
        cli.main(["--mode", "capture-swap-snapshot", "--broker-symbol-map", str(bad_map)])
    assert caught.value.code == cli.EXIT_INVALID_ARGUMENTS


def test_cli_write_failure_is_refused_without_paths_and_still_shuts_down(monkeypatch, tmp_path, capsys):
    import agi_style_forex_bot_mt5.broker_swap_snapshot as module

    def fail_link(*_args):
        raise PermissionError("C:/private/path denied")

    monkeypatch.setattr(module.os, "link", fail_link)
    module_client, terminal = _terminal_module()
    monkeypatch.setitem(sys.modules, "MetaTrader5", module_client)
    code = cli.main(["--mode", "capture-swap-snapshot", "--broker-symbol-map", str(_map(tmp_path)),
                     "--swap-snapshot-output", str(tmp_path / "swap.json")])
    summary = _last_json(capsys)
    assert code == cli.EXIT_INVALID_ARGUMENTS and summary["status"] == "OUTPUT_NOT_WRITABLE"
    assert "private" not in json.dumps(summary) and summary["execution_attempted"] is False
    assert terminal.calls[-1] == "shutdown" and not (tmp_path / "swap.json").exists()


def test_instrument_registry_snapshot_format_and_hash_are_unchanged():
    # Values computed with the builder at d6c8fe4, before validate_symbol_map was shared.
    from agi_style_forex_bot_mt5.instrument_registry_builder import build_instrument_registry_snapshot

    info = {"name": "EURUSD.raw", "digits": 5, "point": 0.00001, "trade_tick_size": 0.00001, "trade_tick_value": 0.97,
            "trade_contract_size": 100000.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
            "trade_stops_level": 0, "trade_freeze_level": 3,
            "currency_base": "EUR", "currency_profit": "USD", "currency_margin": "EUR"}
    jpy = {**info, "name": "USDJPY.raw", "digits": 3, "point": 0.001, "trade_tick_size": 0.001, "trade_tick_value": 0.67,
           "currency_base": "USD", "currency_profit": "JPY", "currency_margin": "USD"}

    class Client:
        def symbol_info(self, symbol):
            return SimpleNamespace(**{"EURUSD.raw": info, "USDJPY.raw": jpy}[symbol])

    snapshot = build_instrument_registry_snapshot(client=Client(), symbols={"EURUSD": "EURUSD.raw", "usdjpy": "USDJPY.raw"},
                                                  captured_at_utc=CAPTURED)
    assert snapshot.metadata_hash == "6040d57a0dfa0df691dc2298d1e6eaad1179cc552fb45d6c0fd3c7f0359aa5b6"
    assert snapshot.snapshot_hash == "8f7cb82bdff5ffcf8a903eacc241be895c5861cab7fa557356b48744ac0a4cdb"


# --------------------------------------------------------------------------- measured carry


def _record(payload, symbol):
    return payload["instruments"][symbol]


def test_points_swap_is_annualised_from_broker_terms_for_a_usd_quoted_pair():
    record = _record(build()[0], "EURUSD")
    carry = annualised_swap_carry(record, price=1.10)
    assert carry["carry_status"] == "OBSERVED" and carry["carry_assumed"] is False
    assert carry["carry_source"] == "mt5:symbol_info"
    assert carry["usd_per_point_per_lot"] == derive_tick_value(currency_base="EUR", currency_quote="USD",
                                                               tick_size=0.00001, contract_size=100000.0, price=1.10)
    assert carry["notional_usd_per_lot"] == pytest.approx(110000.0)
    assert carry["long_usd_per_lot_per_day"] == pytest.approx(-6.5)
    assert carry["short_usd_per_lot_per_day"] == pytest.approx(1.2)
    assert carry["long_annual_percent_of_notional"] == pytest.approx(-6.5 * 365 / 110000.0 * 100)
    assert carry["short_annual_percent_of_notional"] == pytest.approx(1.2 * 365 / 110000.0 * 100)
    expected_markup = -(carry["long_annual_percent_of_notional"] + carry["short_annual_percent_of_notional"]) / 2 * 100
    assert carry["implied_symmetric_markup_bps_per_year"] == pytest.approx(expected_markup)
    assert carry["days_per_year"] == 365 and carry["price"] == 1.10


def test_points_swap_is_annualised_for_a_usd_base_pair_with_its_own_price():
    carry = annualised_swap_carry(_record(build()[0], "USDJPY"), price=150.0)
    assert carry["usd_per_point_per_lot"] == pytest.approx(0.001 * 100000.0 / 150.0)
    assert carry["notional_usd_per_lot"] == pytest.approx(100000.0)
    assert carry["long_usd_per_lot_per_day"] == pytest.approx(10.0)
    assert carry["long_annual_percent_of_notional"] == pytest.approx(3.65)
    assert carry["short_annual_percent_of_notional"] == pytest.approx(-32.0 * 0.001 * 365 / 150.0 * 100)
    # Contract size cancels: the annual rate is swap points times point, over price, per year.
    assert carry["long_annual_percent_of_notional"] == pytest.approx(15.0 * 0.001 / 150.0 * 365 * 100)


@pytest.mark.parametrize("mode", [code for code in SWAP_MODE_NAMES if code != 1])
def test_modes_other_than_points_are_not_converted(mode):
    payload, _ = build({"EURUSD.raw": {**EURUSD, "swap_mode": mode}}, {"EURUSD": "EURUSD.raw"})
    with pytest.raises(InstrumentError, match=SWAP_MODE_NAMES[mode]):
        annualised_swap_carry(_record(payload, "EURUSD"), price=1.1)


@pytest.mark.parametrize("day", [0, 6])
def test_a_weekend_triple_swap_day_is_not_annualised(day):
    payload, _ = build({"EURUSD.raw": {**EURUSD, "swap_rollover3days": day}}, {"EURUSD": "EURUSD.raw"})
    with pytest.raises(InstrumentError):
        annualised_swap_carry(_record(payload, "EURUSD"), price=1.1)


def test_a_cross_has_no_usd_conversion_and_fails_closed():
    eurjpy = {**EURUSD, "name": "EURJPY.raw", "currency_profit": "JPY", "point": 0.001, "digits": 3}
    payload, _ = build({"EURJPY.raw": eurjpy}, {"EURJPY": "EURJPY.raw"})
    with pytest.raises(InstrumentError, match="cross"):
        annualised_swap_carry(_record(payload, "EURJPY"), price=160.0)


@pytest.mark.parametrize("price", [None, 0, -1.1, float("nan"), float("inf"), True, "1.1"])
def test_an_invalid_price_fails_closed(price):
    with pytest.raises(InstrumentError):
        annualised_swap_carry(_record(build()[0], "EURUSD"), price=price)


def test_unavailable_or_altered_records_are_not_converted():
    payload, _ = build({"EURUSD.raw": None, "USDJPY.raw": dict(USDJPY)})
    with pytest.raises(InstrumentError):
        annualised_swap_carry(_record(payload, "EURUSD"), price=1.1)
    altered = {**_record(payload, "USDJPY"), "swap_long": float("nan")}
    with pytest.raises(InstrumentError):
        annualised_swap_carry(altered, price=150.0)
    with pytest.raises(InstrumentError):
        annualised_swap_carry(["not", "a", "record"], price=150.0)


def test_snapshot_carry_fails_closed_per_symbol_and_keeps_provenance():
    eurjpy = {**EURUSD, "name": "EURJPY.raw", "currency_profit": "JPY", "point": 0.001, "digits": 3}
    payload, _ = build({"EURUSD.raw": dict(EURUSD), "USDJPY.raw": dict(USDJPY), "EURJPY.raw": eurjpy, "GBPUSD.raw": None},
                       {"EURUSD": "EURUSD.raw", "USDJPY": "USDJPY.raw", "EURJPY": "EURJPY.raw", "GBPUSD": "GBPUSD.raw"})
    report = snapshot_carry(payload, {"EURUSD": 1.10, "EURJPY": 160.0, "GBPUSD": 1.3})
    assert report["payload_sha256"] == payload["payload_sha256"]
    assert report["captured_at_utc"] == payload["captured_at_utc"]
    carry = report["carry"]
    assert carry["EURUSD"] == annualised_swap_carry(payload["instruments"]["EURUSD"], price=1.10)
    assert carry["USDJPY"] == {"carry_status": "UNAVAILABLE", "reason": "PRICE_MISSING"}
    assert carry["GBPUSD"] == {"carry_status": "UNAVAILABLE", "reason": "SYMBOL_INFO_MISSING"}
    assert carry["EURJPY"] == {"carry_status": "UNAVAILABLE", "reason": "CROSS_WITHOUT_USD_RATE"}
    assert report["schema_version"] == "broker_swap_carry_v1" and report["swap_terms_hash"] == payload["swap_terms_hash"]
    assert report["execution_attempted"] is False and report["account_data_read"] is False
    with pytest.raises(InstrumentError):
        snapshot_carry(payload, {"EURUSD": 1.10, "eurusd": 1.30})
    payload["instruments"]["EURUSD"]["swap_long"] = 99.0
    with pytest.raises(InstrumentError):
        snapshot_carry(payload, {"EURUSD": 1.10})


def test_carry_values_are_finite_numbers():
    carry = annualised_swap_carry(_record(build()[0], "EURUSD"), price=1.10)
    for key, value in carry.items():
        if isinstance(value, float):
            assert math.isfinite(value), key

"""CLI exit codes the scripts and the usage guide rely on; no MT5 terminal needed."""
import json
import sys
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_forward_shadow_preflight_with_zero_cycles_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    code = cli.main(["--mode", "forward-shadow", "--symbols", "EURUSD", "--sqlite", str(tmp_path / "f.sqlite3"),
                     "--log-dir", str(tmp_path / "logs"), "--max-cycles", "0"])
    summary = _last_json(capsys)
    assert code == 0 and summary["cycles_completed"] == 0 and summary["lifecycle_halted"] is False


def test_forward_shadow_without_mt5_and_bounded_cycles_exits_three(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    code = cli.main(["--mode", "forward-shadow", "--symbols", "EURUSD", "--sqlite", str(tmp_path / "f.sqlite3"),
                     "--log-dir", str(tmp_path / "logs"), "--max-cycles", "1", "--cycle-seconds", "0"])
    summary = _last_json(capsys)
    assert code == cli.EXIT_MT5_UNAVAILABLE and summary["skip_reason"] == "MT5_CONNECT_FAILED"
    assert summary["lifecycle_halted"] is False


def test_forward_shadow_integrity_stop_exits_five(monkeypatch, tmp_path):
    class IntegrityStopBot:
        def __init__(self, **_kwargs):
            pass

        def run(self):
            return SimpleNamespace(mode="forward-shadow", mt5_connected=True, cycles_completed=0, open_trades=0,
                paper_trades_opened=0, paper_trades_closed=0, execution_attempted=False, lifecycle_halted=False,
                exit_reason="MARKET_DATA_INTEGRITY_FAILED")

    monkeypatch.setattr(cli, "ForwardShadowBot", IntegrityStopBot)
    assert cli.main(["--mode", "forward-shadow", "--sqlite", str(tmp_path / "f.sqlite3"), "--max-cycles", "1"]) == cli.EXIT_MARKET_DATA_INTEGRITY


def test_export_history_without_mt5_exits_three(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    code = cli.main(["--mode", "export-history", "--symbols", "EURUSD", "--output-dir", str(tmp_path / "hist"),
                     "--log-dir", str(tmp_path / "logs")])
    assert code == cli.EXIT_MT5_UNAVAILABLE and _last_json(capsys)["mt5_connected"] is False


def test_export_history_with_a_disconnected_terminal_exits_three(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "MetaTrader5", SimpleNamespace(initialize=lambda: False, last_error=lambda: (1, "no")))
    code = cli.main(["--mode", "export-history", "--symbols", "EURUSD", "--output-dir", str(tmp_path / "hist"),
                     "--log-dir", str(tmp_path / "logs")])
    assert code == cli.EXIT_MT5_UNAVAILABLE and _last_json(capsys)["mt5_connected"] is False


def test_instrument_registry_exit_codes(monkeypatch, tmp_path, capsys):
    symbol_map = tmp_path / "symbol_map.json"
    symbol_map.write_bytes('﻿{"EURUSD": "EURUSD"}'.encode("utf-8"))
    output = tmp_path / "registry.json"
    arguments = ["--mode", "build-instrument-registry", "--broker-symbol-map", str(symbol_map),
                 "--instrument-registry-output", str(output)]
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    assert cli.main(arguments) == cli.EXIT_MT5_UNAVAILABLE
    assert _last_json(capsys)["status"] == "MT5_UNAVAILABLE"
    # The BOM no longer breaks the map; a closed terminal is reported, not a traceback.
    monkeypatch.setitem(sys.modules, "MetaTrader5", SimpleNamespace(initialize=lambda: False, shutdown=lambda: None))
    assert cli.main(arguments) == cli.EXIT_MT5_UNAVAILABLE
    output.write_text("{}", encoding="utf-8")
    assert cli.main(arguments) == cli.EXIT_INVALID_ARGUMENTS
    assert _last_json(capsys)["status"] == "OUTPUT_EXISTS"


def test_invalid_config_exits_two_without_running_the_mode(tmp_path, capsys):
    config = tmp_path / "bot.ini"
    config.write_text("DEMO_ONLY=False\n", encoding="utf-8")
    assert cli.main(["--mode", "core-invariants", "--config", str(config)]) == cli.EXIT_INVALID_ARGUMENTS
    assert _last_json(capsys)["status"] == "CONFIG_INVALID"


def test_stop_shadow_records_a_request_that_resume_clears(tmp_path, capsys):
    sqlite = str(tmp_path / "f.sqlite3")
    assert cli.main(["--mode", "stop-shadow", "--sqlite", sqlite, "--reason", "maintenance"]) == 0
    assert _last_json(capsys)["stop_requested"] is True
    database = TelemetryDatabase(sqlite)
    try:
        assert database.get_operational_state()["forward_shadow_stop_requested"]
    finally:
        database.close()
    assert cli.main(["--mode", "resume-shadow", "--sqlite", sqlite]) == 0
    database = TelemetryDatabase(sqlite)
    try:
        assert not database.get_operational_state()["forward_shadow_stop_requested"]
    finally:
        database.close()


def test_paper_state_report_names_the_permanent_latch(tmp_path, capsys):
    sqlite = str(tmp_path / "f.sqlite3")
    database = TelemetryDatabase(sqlite)
    try:
        database.update_operational_state({"paper_lifecycle_halted": True, "halt_reason": "ACCOUNT_REAL_DETECTED_READ_ONLY"})
        database.set_shadow_paused(True, reason="ACCOUNT_REAL_DETECTED_READ_ONLY", paused_by="paper_lifecycle")
    finally:
        database.close()
    assert cli.main(["--mode", "paper-state-report", "--sqlite", sqlite, "--output-dir", str(tmp_path / "report")]) == 0
    summary = _last_json(capsys)
    assert summary["halt_reason"] == "PAPER_LIFECYCLE_HALTED"
    assert "new --sqlite" in summary["recommended_action"]


def test_operator_scripts_match_the_exit_code_contract():
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    run = (scripts / "run_forward_shadow.ps1").read_text(encoding="utf-8")
    watchdog = (scripts / "watchdog_forward_shadow.ps1").read_text(encoding="utf-8")
    stop = (scripts / "stop_forward_shadow.ps1").read_text(encoding="utf-8")
    for text in (run, watchdog, stop):
        # Unknown or positional arguments fail instead of binding to a parameter or being ignored.
        assert text.startswith("[CmdletBinding(PositionalBinding = $false)]")
    assert '"--config", $Config' in run and '"--telegram"' in run
    assert "already running on $SqlitePath" in run
    # The watchdog never relaunches a deliberate stop, bad arguments, a latch or an integrity stop.
    assert "$exitCode -in @(0, 2, 4, 5)" in watchdog and "forward-shadow-watchdog.stop" in watchdog
    # The stop is cooperative; a kill needs -Force after the timeout.
    assert "--mode stop-shadow" in stop and "if (-not $Force)" in stop
    assert stop.index("if (-not $Force)") < stop.index("Stop-Process")

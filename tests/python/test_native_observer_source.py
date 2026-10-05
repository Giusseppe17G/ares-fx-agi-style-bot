"""Source safety guards only; these do not execute MQL assertions or a terminal."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "src/mt5"
SOURCES = tuple(sorted(path for path in NATIVE.rglob("*") if path.suffix.lower() in {".mq5", ".mqh"}))
FORBIDDEN = {
    "OrderSend", "OrderSendAsync", "OrderCheck", "CTrade", "MqlTradeRequest", "MqlTradeResult",
    "WebRequest", "SendMail", "SendNotification", "SocketCreate", "SocketConnect", "TerminalClose",
    "FileCopy", "FileDelete", "FileMove", "FolderClean", "FolderDelete", "FILE_COMMON",
    "FILE_SHARE_WRITE", "ACCOUNT_LOGIN", "ACCOUNT_NAME", "ACCOUNT_SERVER", "ACCOUNT_COMPANY",
    "TERMINAL_DATA_PATH", "TERMINAL_COMMONDATA_PATH", "AccountInfoString", "AccountInfoDouble",
}


def tokens(source):
    # Strings/comments cannot smuggle executable APIs and should not cause
    # false positives when documenting their absence. Preserve preprocessor.
    clean = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/', " ", source)
    return set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", clean))


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.relative_to(NATIVE).as_posix())
def test_native_sources_have_no_execution_network_or_sensitive_account_capability(path):
    names = tokens(path.read_text(encoding="utf-8-sig"))
    assert not names & FORBIDDEN
    assert "import" not in names


def test_guard_ignores_comments_and_string_literals_but_detects_executable_calls():
    assert not tokens('// OrderSend();\nPrint("WebRequest is unavailable"); /* CTrade */') & FORBIDDEN
    assert tokens("void Unsafe() { OrderSend(request,result); }") & FORBIDDEN == {"OrderSend"}


def test_every_native_include_resolves_to_owned_repository_source():
    for path in SOURCES:
        for reference in re.findall(r"#include\s*[<\"]([^>\"]+)[>\"]", path.read_text()):
            target = (NATIVE / "Include" / reference.replace("\\", "/")).resolve()
            assert target.is_relative_to((NATIVE / "Include").resolve())
            assert target in SOURCES


def test_release_gate_has_no_configurable_acceptance_branch():
    gate = (NATIVE / "Include/Execution/ReleaseGate.mqh").read_text()
    assert re.findall(r"return\s+(true|false)\s*;", gate) == ["false"]
    assert 'reason="EXECUTION_NOT_RELEASED"' in gate
    assert "NativeExecutionGate" in (NATIVE / "Experts/AGI_STYLE_FOREX_BOT_MT5.mq5").read_text()


def test_defaults_require_explicit_clock_and_audit_before_initialization():
    source = (NATIVE / "Experts/AGI_STYLE_FOREX_BOT_MT5.mq5").read_text()
    assert "input bool DEMO_ONLY=true;" in source
    assert "input bool UTC_CLOCK_CONFIRMED=false;" in source
    assert "SERVER_UTC_OFFSET_SECONDS=2147483647" in source
    init = source.split("int OnInit(void)", 1)[1].split("void ObservationHalt", 1)[0]
    assert init.index("observation_audit.Open()") < init.index("NativeReadAccount(reason)")
    assert init.index("observation_audit.Append") < init.index("EventSetTimer") < init.index("return INIT_SUCCEEDED")


def test_each_observation_revalidates_account_and_audit_failure_stops_observation():
    source = (NATIVE / "Experts/AGI_STYLE_FOREX_BOT_MT5.mq5").read_text()
    timer = source.split("void OnTimer(void)", 1)[1].split("void OnDeinit", 1)[0]
    assert timer.index("NativeReadAccount(reason)") < timer.index("NativeReadSnapshot(")
    assert "observation_audit.SetDemoVerified(false); ObservationHalt(reason);" in timer
    assert 'ObservationHalt("AUDIT_PERSISTENCE_FAILED")' in timer
    halt = source.split("void ObservationHalt", 1)[1].split("void OnTimer", 1)[0]
    assert "observation_active=false" in halt and "EventKillTimer()" in halt and "ExpertRemove()" in halt


def test_native_clock_never_guesses_server_offset_and_rejects_tester_utc():
    source = (NATIVE / "Include/Core/NativeClock.mqh").read_text()
    assert "MQL_TESTER" in source and "MQL_OPTIMIZATION" in source
    assert "TimeGMT()" in source
    assert "TimeTradeServer" not in tokens(source)
    policy = (NATIVE / "Include/Core/ObservationPolicy.mqh").read_text()
    assert "utc_clock_confirmed" in policy and "offset_valid_until_utc" in policy
    assert "upper_now-normalized" in policy


def test_audit_has_persistence_checks_and_no_shared_or_supplied_path():
    source = (NATIVE / "Include/Telemetry/JsonlAudit.mqh").read_text()
    names = tokens(source)
    assert {"FileWriteArray", "FileFlush", "FileReadArray", "FileSize", "FileTell", "CP_UTF8"} <= names
    assert "verified[i]!=bytes[i]" in source
    assert "50*1024*1024" in source
    assert "NATIVE_OBSERVATION_ONLY" in source and "execution_authorized\\\":false" in source
    assert "clock_authenticity_verified\\\":false" in source


def test_build_script_only_compiles_to_new_isolated_staging_and_records_scope():
    source = (ROOT / "scripts/compile_native_observer.ps1").read_text()
    assert "-WindowStyle Hidden" in source
    assert "Staging must not already exist" in source
    assert "'/compile:" in source and "'/include:" in source
    assert "0 errors, 0 warnings" in source
    assert "harness_executed = $false" in source and "installed_to_terminal = $false" in source
    assert "terminal64.exe" not in source.lower()

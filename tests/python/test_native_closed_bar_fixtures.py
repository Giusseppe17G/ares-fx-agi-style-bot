"""Real Python references plus source guards; no MQL runtime or market access."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate_native_closed_bar_fixtures.py"
FIXTURES = ROOT / "tests/fixtures/native_closed_bar_cases.json"
GENERATED = ROOT / "tests/mt5/GeneratedClosedBarFixtures.mqh"
DOCUMENT = json.loads(FIXTURES.read_text(encoding="utf-8"))
CASES = DOCUMENT["cases"]
BY_ID = {case["case_id"]:case for case in CASES}


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("native_closed_bar_fixture_generator",SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("case",CASES,ids=lambda case:case["case_id"])
def test_frozen_fixture_records_actual_python_selector_and_core_inputs(generator,case):
    # These observations are obtained from production functions, not a port of
    # the MQL algorithm or a surrogate timestamp predicate.
    before = deepcopy(case)
    assert generator.python_reference(case) == case["python_reference"]
    assert case == before


@pytest.mark.parametrize("case",[x for x in CASES if x["comparison_scope"]=="COMPARABLE"],ids=lambda case:case["case_id"])
def test_comparable_native_expectations_match_executed_python_functions(case):
    reference,expected=case["python_reference"],case["expected_native"]
    python_valid=reference["selector"]["valid"] and reference["temporal_at_clock_start"]["status"]=="VALID" and reference["temporal_at_clock_upper"]["status"]=="VALID"
    assert expected["valid"] is python_valid
    if python_valid:
        for name in ("closed_count","source_bar_timestamp_utc_msc","available_at_utc_msc"):
            assert expected[name] == reference["selector"][name]
        assert [case["bars"][i]["timestamp_utc_msc"] for i in expected["selected_indices"]] == reference["selector"]["source_timestamps_utc_msc"]


@pytest.mark.parametrize("case_id",("future_duplicate_invalidates_batch","future_reversed_invalidates_batch",
    "invalid_future_ohlc_invalidates_batch","invalid_forming_spread_invalidates_batch","closed_intervals_overlap_one_millisecond"))
def test_native_additional_validation_is_an_explicit_difference(case_id):
    case=BY_ID[case_id]
    assert not case["expected_native"]["valid"]
    assert case["python_reference"]["selector"]["valid"]
    assert case["python_reference"]["temporal_at_clock_upper"]["status"]=="VALID"
    assert case["comparison_scope"].startswith("NATIVE_") and case["difference_note"]


def test_clock_interval_conservatism_is_not_claimed_as_same_instant_parity():
    stale=BY_ID["second_clock_ambiguous_stale"]
    assert stale["python_reference"]["temporal_at_clock_start"]["status"]=="VALID"
    assert stale["python_reference"]["temporal_at_clock_upper"]["code"]=="MARKET_DATA_INVALID"
    assert stale["expected_native"]["reason"]=="STALE_SNAPSHOT"
    future=BY_ID["second_clock_possibly_future"]
    assert future["python_reference"]["temporal_at_clock_start"]["code"]=="MARKET_DATA_INVALID"
    assert future["python_reference"]["temporal_at_clock_upper"]["status"]=="VALID"
    assert future["expected_native"]["reason"]=="FUTURE_SNAPSHOT"
    bar=BY_ID["second_clock_bar_age_ambiguous"]
    assert bar["python_reference"]["temporal_at_clock_start"]["status"]=="VALID"
    assert bar["python_reference"]["temporal_at_clock_upper"]["code"]=="STALE_FEATURES"
    assert bar["expected_native"]["reason"]=="STALE_CLOSED_BARS"


def test_minimum_history_is_native_policy_not_python_helper_result():
    case=BY_ID["history_below_declared_minimum"]
    assert case["python_reference"]["selector"]["valid"]
    assert case["expected_native"]["reason"]=="INSUFFICIENT_CLOSED_BARS"
    assert case["comparison_scope"]=="NATIVE_REQUEST_CONSTRAINT"


def test_python_references_call_production_implementations(generator,monkeypatch):
    selector_calls=[]; context_calls=[]
    selector=generator.closed_strategy_bars
    context_validator=generator.SharedDecisionPipeline._validate_context
    def tracked_selector(*args,**kwargs):
        selector_calls.append(1)
        return selector(*args,**kwargs)
    def tracked_context(*args,**kwargs):
        context_calls.append(1)
        return context_validator(*args,**kwargs)
    monkeypatch.setattr(generator,"closed_strategy_bars",tracked_selector)
    monkeypatch.setattr(generator.SharedDecisionPipeline,"_validate_context",tracked_context)
    assert generator.fixture_document()==DOCUMENT
    assert len(selector_calls)>=50 and len(context_calls)>=40


def test_generation_is_reproducible_and_harness_binds_exact_json(generator,tmp_path):
    assert generator.canonical_bytes(generator.fixture_document())==FIXTURES.read_bytes()
    assert generator.render_mql(DOCUMENT).encode()==GENERATED.read_bytes()
    digest=sha256(FIXTURES.read_bytes()).hexdigest()
    assert f"Authoritative fixture SHA256: {digest}" in GENERATED.read_text()
    json_output,include_output=tmp_path/"cases.json",tmp_path/"fixtures.mqh"
    assert generator.main(["--json-output",str(json_output),"--mql-output",str(include_output)])==0
    assert json_output.read_bytes()==FIXTURES.read_bytes()
    assert include_output.read_bytes()==GENERATED.read_bytes()
    assert generator.main(["--check","--json-output",str(json_output),"--mql-output",str(include_output)])==0
    include_output.write_text("stale",encoding="utf-8")
    assert generator.main(["--check","--json-output",str(json_output),"--mql-output",str(include_output)])==1


def test_generator_cli_works_outside_checkout_without_market_or_terminal(tmp_path):
    command=[sys.executable,"-B",str(SCRIPT),"--json-output",str(tmp_path/"cases.json"),"--mql-output",str(tmp_path/"fixtures.mqh")]
    result=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert "MQL assertions NOT EXECUTED" in result.stdout
    assert (tmp_path/"cases.json").read_bytes()==FIXTURES.read_bytes()
    assert (tmp_path/"fixtures.mqh").read_bytes()==GENERATED.read_bytes()


def test_artifact_discloses_reference_scope_and_every_rejection_resets_output():
    assert DOCUMENT["scope"]=="SYNTHETIC_FUNCTION_REFERENCE_ONLY"
    assert not DOCUMENT["native_runtime_executed"] and not DOCUMENT["execution_authorized"] and not DOCUMENT["full_pipeline_verified"]
    assert len(BY_ID)==len(CASES)
    generated=GENERATED.read_text()
    assert "does not execute these assertions" in generated
    for case in CASES:
        expected=case["expected_native"]
        assert not expected["execution_authorized"] and not expected["full_pipeline_verified"]
        if expected["valid"]:
            for suffix in ("reset_reject","reset_window","reset_availability","reset_flags"):
                assert f'{case["case_id"]}:{suffix}' in generated
        else:
            assert expected["selected_indices"]==[]
            assert all(expected[key]==0 for key in ("closed_count","excluded_count","source_bar_timestamp_utc_msc","available_at_utc_msc"))


def _code_tokens(source):
    clean=re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/'," ",source)
    return set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b",clean))


@pytest.mark.parametrize("relative",("Contracts/ClosedBarContract.mqh","Core/ClosedBarWindow.mqh"))
def test_selector_contract_sources_have_no_io_clock_account_or_execution_capability(relative):
    tokens=_code_tokens((ROOT/"src/mt5/Include"/relative).read_text())
    forbidden={"OrderSend","OrderSendAsync","OrderCheck","CTrade","MqlTradeRequest","MqlTradeResult","import",
        "WebRequest","SendMail","SendNotification","SocketCreate","TerminalClose","Print","PrintFormat","Alert","Comment",
        "TimeGMT","TimeCurrent","TimeLocal","TimeTradeServer","GetTickCount","GetTickCount64","GetMicrosecondCount",
        "CopyRates","CopySeries","CopyTicks","CopyTicksRange","CopyBuffer","iTime","iOpen","iClose","iHigh","iLow",
        "FileOpen","FileWrite","FileWriteString","FileWriteArray","FileReadString","FileReadArray","FileDelete","FileCopy",
        "FileMove","FileFindFirst","FolderCreate","FolderDelete","GlobalVariableSet","GlobalVariableGet",
        "AccountInfoInteger","AccountInfoDouble","AccountInfoString","SymbolInfoTick","SymbolInfoInteger","SymbolInfoDouble",
        "SymbolInfoString","TerminalInfoInteger","TerminalInfoString","TerminalInfoDouble","ChartOpen","ExpertRemove",
        "EventSetTimer","EventSetMillisecondTimer","EventKillTimer","Sleep","MathRand","MathSrand"}
    assert not tokens&forbidden
    assert not any(token.startswith(("File","Socket","AccountInfo","SymbolInfo","TerminalInfo","History","PositionGet","OrderGet","Copy","iTime","iOpen","iClose","iHigh","iLow")) for token in tokens)


def test_selector_cannot_authorize_flags_or_be_integrated_into_current_ea():
    source=(ROOT/"src/mt5/Include/Core/ClosedBarWindow.mqh").read_text()
    clean=re.sub(r'//[^\n]*|/\*[\s\S]*?\*/'," ",source)
    for field in ("execution_authorized","full_pipeline_verified"):
        assert re.findall(rf"\b{field}\s*=(?!=)\s*([^;]+);",clean)==["false"]
    assert "const NativeClosedBarRequest &request" in clean and "const NativeClosedBar &bars[]" in clean
    ea=(ROOT/"src/mt5/Experts/AGI_STYLE_FOREX_BOT_MT5.mq5").read_text()
    assert "NativeSelectClosedBars" not in _code_tokens(ea)
    assert "ClosedBarWindow.mqh" not in ea


def test_source_guard_is_not_fooled_by_comments_and_strings():
    assert "OrderSend" not in _code_tokens('/* OrderSend(); */ Print("OrderSend");')
    assert "OrderSend" in _code_tokens("void unsafe(){OrderSend(request,result);}")

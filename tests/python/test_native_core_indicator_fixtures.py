"""Python differential oracles and source guards; MQL is never run here."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate_native_core_indicator_fixtures.py"
FIXTURES = ROOT / "tests/fixtures/native_core_indicator_cases.json"
GENERATED = ROOT / "tests/mt5/GeneratedCoreIndicatorFixtures.mqh"
HARNESS = ROOT / "tests/mt5/CoreIndicatorsHarness.mq5"
DOCUMENT = json.loads(FIXTURES.read_text(encoding="utf-8"))
CASES = DOCUMENT["cases"]
BY_ID = {case["case_id"]:case for case in CASES}
FIELDS = ("ema20","ema50","ema200","rsi14","atr14")


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("native_core_fixture_generator",SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("case",CASES,ids=lambda case:case["case_id"])
def test_frozen_oracle_is_actual_python_on_identical_closed_input(generator,case):
    before = deepcopy(case)
    assert generator.python_reference(DOCUMENT["histories"],case) == case["python_reference"]
    binding={"request":case["request"],"bars":generator.resolve_bars(DOCUMENT["histories"],case)}
    assert sha256(generator.canonical_bytes(binding)).hexdigest() == case["input_sha256"]
    assert case == before


@pytest.mark.parametrize("case",[case for case in CASES if case["expected_native"]["valid"]],ids=lambda case:case["case_id"])
def test_all_accepted_native_oracles_have_finite_python_values_and_full_bundle(case):
    reference,expected=case["python_reference"],case["expected_native"]
    assert reference["selector_status"] == "VALID"
    assert reference["bars_count"] >= max(200,case["request"]["minimum_bars"])
    for field in FIELDS:
        assert reference["values"][field]["status"] == "FINITE"
        assert expected[field] == reference["values"][field]["value"]
        assert math.isfinite(expected[field])
    assert expected["ema20"] > 0 and expected["ema50"] > 0 and expected["ema200"] > 0
    assert expected["atr14"] >= 0 and 0 <= expected["rsi14"] <= 100
    assert not expected["execution_authorized"] and not expected["full_pipeline_verified"]


def _values(case_id):
    return BY_ID[case_id]["python_reference"]["values"]


def test_future_mutation_and_prefix_extraction_do_not_change_past_values():
    baseline=_values("mixed_prefix_250")
    assert _values("same_250_prefix_without_future") == baseline
    assert _values("future_mutation_preserves_prefix") == baseline
    assert _values("zero_volume_spread_do_not_change_indicators") == baseline
    assert _values("different_symbol_same_numeric_input") == baseline


def test_every_prefix_matches_production_series_at_that_position(generator):
    frame=generator._frame(DOCUMENT["histories"]["mixed"])
    close=frame["close"]
    full={"ema20":generator.ema(close,20),"ema50":generator.ema(close,50),"ema200":generator.ema(close,200),
          "rsi14":generator.rsi(close,14),"atr14":generator.atr(frame,14)}
    for count in (1,13,14,15,19,20,21,49,50,51,199,200,201,250,400):
        for field in FIELDS:
            assert _values(f"mixed_prefix_{count}")[field] == generator._number(full[field].iloc[count-1])


def test_min_periods_masks_output_and_never_replaces_recursive_seed(generator):
    assert generator.ema(pd.Series([1.,2.,3.]),3).tolist()[-1] == 2.25
    assert generator.rsi(pd.Series([1.,2.,1.,2.]),3).iloc[-1] == pytest.approx(77.77777777777777)
    bars=generator._frame(generator._bars([10.,10.,10.],widths=[1.,2.,4.]))
    assert generator.atr(bars,3).iloc[-1] == pytest.approx(4.444444444444444)
    observed=BY_ID["mixed_prefix_250"]["python_reference"]["first_valid_position"]
    assert observed == {"ema20":19,"ema50":49,"ema200":199,"rsi14":14,"atr14":13}
    for count in (199,200,250):
        expected=BY_ID[f"mixed_prefix_{count}"]["expected_native"]
        assert expected["valid"] is (count >= 200)
    assert BY_ID["minimum_request_precedes_bundle"]["expected_native"]["reason"] == "INSUFFICIENT_CLOSED_BARS"


def test_calendar_gaps_do_not_invent_observations_or_extra_decay():
    assert _values("gapped_mixed") == _values("mixed_prefix_250")
    ordinary=BY_ID["mixed_prefix_250"]["expected_native"]
    gapped=BY_ID["gapped_mixed"]["expected_native"]
    assert ordinary["bars_count"] == gapped["bars_count"] == 250
    assert ordinary["available_at_utc_msc"] != gapped["available_at_utc_msc"]


def test_timeframes_change_availability_but_not_observation_based_indicator_values():
    for case_id,timeframe,duration in (("m15_same_observations","M15",900000),("h1_same_observations","H1",3600000)):
        assert _values(case_id) == _values("mixed_prefix_250")
        result=BY_ID[case_id]["expected_native"]
        assert result["timeframe"] == timeframe
        assert result["available_at_utc_msc"]-result["source_bar_timestamp_utc_msc"] == duration
    before=BY_ID["one_millisecond_before_200th_close"]
    assert before["python_reference"]["bars_count"] == 199
    assert before["expected_native"]["reason"] == "INSUFFICIENT_INDICATOR_WARMUP"


def test_history_origin_is_part_of_identity_and_250_warmup_is_not_equivalence():
    full=BY_ID["mixed_prefix_400"]["expected_native"]
    tail=BY_ID["tail_250_has_different_history_origin"]["expected_native"]
    assert full["available_at_utc_msc"] == tail["available_at_utc_msc"]
    assert full["history_start_utc_msc"] != tail["history_start_utc_msc"]
    assert abs(full["ema200"]-tail["ema200"]) > 1e-3
    assert full["bars_count"] == 400 and tail["bars_count"] == 250


@pytest.mark.parametrize("case_id,rsi_expected,atr_expected",(
    ("constant",50.,0.),("constant_range",50.,.5),("increasing",100.,None),
    ("decreasing",0.,None),("large_constant",50.,0.),("small_constant",50.,0.),("subnormal_constant",50.,0.)))
def test_mathematical_degenerate_cases_are_not_fabricated_signal_approvals(case_id,rsi_expected,atr_expected):
    result=BY_ID[case_id]["expected_native"]
    assert result["rsi14"] == rsi_expected
    if atr_expected is not None:
        assert result["atr14"] == atr_expected
    assert not result["execution_authorized"] and not result["full_pipeline_verified"]


def test_numeric_strictness_is_explicit_instead_of_claiming_saturated_python_parity():
    case=BY_ID["rsi_ratio_overflow"]
    assert case["python_reference"]["selector_status"] == "VALID"
    assert case["python_reference"]["values"]["rsi14"] == {"status":"FINITE","value":100.}
    assert case["comparison_scope"] == "NATIVE_NUMERIC_STRICTER" and case["difference_note"]
    assert case["expected_native"]["reason"] == "INDICATOR_ARITHMETIC_INVALID"
    close=pd.Series([2e-308,1e-308]+[1e308]*198)
    delta=close.diff()
    gain=delta.clip(lower=0.).ewm(alpha=1/14,adjust=False,min_periods=14).mean().iloc[-1]
    loss=(-delta.clip(upper=0.)).ewm(alpha=1/14,adjust=False,min_periods=14).mean().iloc[-1]
    assert gain > sys.float_info.max*loss > 0


@pytest.mark.parametrize("case_id",("invalid_future_ohlc","invalid_forming_nan","overlapping_closed"))
def test_native_global_interval_validation_is_declared_as_stricter_than_python(case_id):
    case=BY_ID[case_id]
    assert case["python_reference"]["selector_status"] == "VALID"
    assert not case["expected_native"]["valid"]
    assert case["comparison_scope"].startswith("NATIVE_") and case["difference_note"]


def test_tolerances_are_predeclared_scaled_and_finite_at_extremes(generator):
    policy=DOCUMENT["tolerance_policy"]
    assert policy == {"price_max_ulps":512,"price_relative_cap":1e-12,"price_absolute_floor":0.,
        "zero_price_exact":True,"rsi_absolute":1e-10,"scope":"REGRESSION_BUDGET_NOT_A_UNIVERSAL_ERROR_BOUND"}
    for case in CASES:
        for field,budget in case["absolute_tolerances"].items():
            assert math.isfinite(budget) and budget >= 0
            if not case["expected_native"]["valid"]:
                assert budget == 0
            elif field == "rsi14":
                assert budget == 1e-10
            else:
                expected=case["expected_native"][field]
                assert budget == generator.price_tolerance(expected)
                assert budget <= 512*math.ulp(expected)
                assert budget <= abs(expected)*1e-12
                if expected == 0:
                    assert budget == 0
    assert generator.price_tolerance(5e-324) == 0
    assert generator.price_tolerance(1e308) < 1e296


def test_reference_calls_real_functions_and_generation_binds_versions(generator,monkeypatch):
    counts={"ema":0,"rsi":0,"atr":0,"closed_strategy_bars":0}
    # Inspect source hashes before wrapping: the wrappers are intentionally not
    # treated as authoritative production source provenance.
    for name in counts:
        original=getattr(generator,name)
        def tracked(*args,_name=name,_original=original,**kwargs):
            counts[_name]+=1
            return _original(*args,**kwargs)
        monkeypatch.setattr(generator,name,tracked)
    for case in CASES:
        assert generator.python_reference(DOCUMENT["histories"],case) == case["python_reference"]
    assert counts["closed_strategy_bars"] == len(CASES)
    assert counts["rsi"] == counts["atr"] >= 35
    assert counts["ema"] == 3*counts["rsi"]
    assert DOCUMENT["reference_runtime"]["pandas"] == pd.__version__
    assert DOCUMENT["reference_runtime"]["numpy"] == np.__version__
    assert len(DOCUMENT["python_function_sha256"]) == 5


def test_generation_is_exact_and_stale_files_are_detected(generator,tmp_path):
    assert generator.canonical_bytes(generator.fixture_document()) == FIXTURES.read_bytes()
    assert generator.render_mql(DOCUMENT).encode() == GENERATED.read_bytes()
    assert f"Authoritative fixture SHA256: {sha256(FIXTURES.read_bytes()).hexdigest()}" in GENERATED.read_text()
    json_path,include_path=tmp_path/"cases.json",tmp_path/"cases.mqh"
    args=["--json-output",str(json_path),"--mql-output",str(include_path)]
    assert generator.main(args) == 0
    assert json_path.read_bytes() == FIXTURES.read_bytes()
    assert include_path.read_bytes() == GENERATED.read_bytes()
    assert generator.main([*args,"--check"]) == 0
    include_path.write_text("stale",encoding="utf-8")
    assert generator.main([*args,"--check"]) == 1


def test_generator_runs_outside_repository_without_terminal_or_market_access(tmp_path):
    result=subprocess.run([sys.executable,"-B",str(SCRIPT),"--json-output",str(tmp_path/"cases.json"),
        "--mql-output",str(tmp_path/"cases.mqh")],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode == 0,result.stderr
    assert "MQL assertions NOT EXECUTED" in result.stdout
    assert (tmp_path/"cases.json").read_bytes() == FIXTURES.read_bytes()
    assert (tmp_path/"cases.mqh").read_bytes() == GENERATED.read_bytes()


def test_every_rejection_resets_every_field_and_harness_exercises_success_then_failure():
    generated=GENERATED.read_text()
    assert not DOCUMENT["native_runtime_executed"] and not DOCUMENT["full_pipeline_verified"] and not DOCUMENT["execution_authorized"]
    assert DOCUMENT["scope"] == "SYNTHETIC_FUNCTION_REFERENCE_ONLY"
    assert len(BY_ID) == len(CASES)
    for case in CASES:
        expected=case["expected_native"]
        assert expected["version"] == "native_core_indicators_v1"
        if expected["valid"]:
            for field in (*FIELDS,"bars_count","history_start_utc_msc","snapshot_utc_msc","clock_start_utc_msc",
                          "clock_resolution_msc","source_bar_timestamp_utc_msc","available_at_utc_msc","identity","flags","status"):
                assert f'{case["case_id"]}:reset_{field}' in generated
        else:
            assert expected["symbol"] == expected["timeframe"] == ""
            assert all(value == 0 for key,value in expected.items() if key not in {"symbol","timeframe","reason","version"})
    assert "NativeCoreFixturePoison(result);" in generated
    assert "Compilation does not execute these assertions" in generated
    assert '#include "GeneratedCoreIndicatorFixtures.mqh"' in HARNESS.read_text()
    assert "RunGeneratedCoreIndicatorFixtures();" in HARNESS.read_text()


def _code(source):
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/'," ",source)


@pytest.mark.parametrize("relative",("Contracts/CoreIndicatorContract.mqh","Core/CoreIndicators.mqh"))
def test_native_sources_have_no_io_terminal_builtin_indicators_orders_or_mutable_state(relative):
    source=(ROOT/"src/mt5/Include"/relative).read_text()
    tokens=set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b",_code(source)))
    forbidden={"OrderSend","OrderSendAsync","OrderCheck","CTrade","MqlTradeRequest","MqlTradeResult","import",
        "WebRequest","SendMail","SendNotification","Print","PrintFormat","Alert","Comment","Sleep",
        "TimeGMT","TimeCurrent","TimeLocal","TimeTradeServer","GetTickCount","GetTickCount64","GetMicrosecondCount",
        "MathRand","MathSrand","NormalizeDouble","static","iMA","iRSI","iATR","iCustom","IndicatorCreate",
        "GlobalVariableGet","GlobalVariableSet","EventSetTimer","EventSetMillisecondTimer","ChartOpen","ExpertRemove"}
    assert not tokens & forbidden
    assert not any(token.startswith(("File","Socket","AccountInfo","SymbolInfo","TerminalInfo","History",
        "PositionGet","OrderGet","Copy","iTime","iOpen","iClose","iHigh","iLow")) for token in tokens)


def test_core_revalidates_locally_never_authorizes_and_is_not_integrated_in_ea():
    source=(ROOT/"src/mt5/Include/Core/CoreIndicators.mqh").read_text()
    clean=re.sub(r'//[^\n]*|/\*[\s\S]*?\*/'," ",source)
    assert "NativeSelectClosedBars(request,bars," in re.sub(r"\s+","",clean)
    for field in ("execution_authorized","full_pipeline_verified"):
        assignments=re.findall(rf"\b{field}\s*=(?!=)\s*([^;]+);",clean)
        assert assignments and set(assignments) == {"false"}
    assert "const NativeClosedBarRequest &request" in clean
    assert "const NativeClosedBar &bars[]" in clean
    ea=(ROOT/"src/mt5/Experts/AGI_STYLE_FOREX_BOT_MT5.mq5").read_text()
    assert "NativeCalculateCoreIndicators" not in _code(ea)
    assert "CoreIndicators.mqh" not in ea


def test_harness_cannot_read_terminal_files_or_send_orders():
    tokens=set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b",_code(HARNESS.read_text()+GENERATED.read_text())))
    assert not any(token.startswith(("Order","Position","SymbolInfo","AccountInfo","TerminalInfo","Copy","File","Socket")) for token in tokens)
    assert not tokens & {"WebRequest","CTrade","iMA","iATR","iRSI","TimeCurrent","TimeGMT","TimeTradeServer","import"}

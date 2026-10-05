"""Freeze synthetic Python indicator references and generate MQL assertions.

This script never compiles or runs MQL, accesses a terminal, or reads market data.
Native rejection expectations are declared against PROJECT_SPEC 17.9; numeric
references come only from the production Python functions, not a Python MQL port.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import inspect
import json
import math
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/python"))

import numpy as np
import pandas as pd

from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.data.indicators import atr, ema, rsi
from agi_style_forex_bot_mt5.data.market_data import validate_ohlcv_frame
from agi_style_forex_bot_mt5.data.strategy_features import closed_strategy_bars

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
BASE = 1767614400000  # 2026-01-05 12:00:00 UTC, synthetic only.
DURATION = 300000
DURATIONS = {"M5":300000,"M15":900000,"H1":3600000}
VERSION = "native_core_indicators_v1"
FIELDS = ("ema20", "ema50", "ema200", "rsi14", "atr14")
NUMERIC_RESULT_FIELDS = ("bars_count", "history_start_utc_msc", "source_bar_timestamp_utc_msc",
    "available_at_utc_msc", "snapshot_utc_msc", "clock_start_utc_msc", "clock_resolution_msc", *FIELDS)
SPECIAL_NUMBERS = {"NAN": float("nan"), "POS_INF": float("inf"), "NEG_INF": float("-inf")}
DEFAULT_JSON = ROOT / "tests/fixtures/native_core_indicator_cases.json"
DEFAULT_INCLUDE = ROOT / "tests/mt5/GeneratedCoreIndicatorFixtures.mqh"
PRICE_ULPS = 512
PRICE_RELATIVE_CAP = 1e-12
RSI_ABSOLUTE_TOLERANCE = 1e-10


def _datetime(ms):
    return EPOCH + timedelta(milliseconds=ms)


def _bars(closes, *, widths=None, gap=False, duration=DURATION):
    rows = []
    for i, close in enumerate(closes):
        width = 0.0 if widths is None else widths[i]
        extra = (int(i >= 80) * 7 + int(i >= 150) * 288) if gap else 0
        rows.append(dict(timestamp_utc_msc=BASE+(i+extra)*duration,
            open=close, high=close+width, low=close-width, close=close,
            volume=100.0+i, spread_points=5.0))
    return rows


def declared_inputs():
    """Declare input families and native policies before observing outputs."""
    mixed = [10.0+(i % 11)*.125+(i // 11)*.03125+(i % 2)*.0625 for i in range(400)]
    widths = [.125*(1+i % 3) for i in range(400)]
    histories = {
        "mixed": _bars(mixed, widths=widths),
        "constant": _bars([1.25]*250),
        "constant_range": _bars([1.25]*250, widths=[.25]*250),
        "increasing": _bars([10.+i*.125 for i in range(250)], widths=[.0625]*250),
        "decreasing": _bars([50.-i*.125 for i in range(250)], widths=[.0625]*250),
        "alternating": _bars([10.+(i % 2)*.25 for i in range(250)]),
        "impulse": _bars([100.]+[10.]*198+[50.]+[10.]*50),
        "gapped_mixed": _bars(mixed[:250], widths=widths[:250], gap=True),
        "m15_mixed": _bars(mixed[:250], widths=widths[:250], duration=DURATIONS["M15"]),
        "h1_mixed": _bars(mixed[:250], widths=widths[:250], duration=DURATIONS["H1"]),
        "large_constant": _bars([1e308]*200),
        "small_constant": _bars([1e-300]*200),
        "subnormal_constant": _bars([float.fromhex("0x0.01p-1022")]*200),
        "rsi_ratio_overflow": _bars([2e-308, 1e-308]+[1e308]*198),
        "near_constant": _bars([1.+(i % 3)*2.0**-45 for i in range(250)]),
        "empty": [],
    }
    cases = []

    def add(case_id, history="mixed", *, start=0, stop=None, count=None,
            request=None, overrides=None, reason="CORE_INDICATORS_VALID",
            scope="COMPARABLE", note=""):
        rows = histories[history][start:stop]
        closed_count = len(rows) if count is None else count
        duration = DURATIONS[(request or {}).get("timeframe","M5")]
        snapshot = rows[closed_count-1]["timestamp_utc_msc"]+duration if closed_count else BASE
        req = dict(symbol="SYNTHETIC", timeframe="M5", snapshot_utc_msc=snapshot,
            clock_start_utc_msc=snapshot, clock_resolution_msc=1, minimum_bars=1,
            max_snapshot_age_msc=5000)
        req.update(request or {})
        cases.append(dict(case_id=case_id, history_id=history, slice_start=start,
            slice_stop=len(histories[history]) if stop is None else stop,
            bar_overrides=deepcopy(overrides or []), request=req, native_reason=reason,
            comparison_scope=scope, difference_note=note))

    for n in (1, 13, 14, 15, 19, 20, 21, 49, 50, 51, 199, 200, 201, 250, 400):
        add(f"mixed_prefix_{n}", count=n,
            reason="CORE_INDICATORS_VALID" if n >= 200 else "INSUFFICIENT_INDICATOR_WARMUP",
            scope="COMPARABLE" if n >= 200 else "NATIVE_BUNDLE_WARMUP",
            note="The scalar bundle publishes no partial indicators before 200 closed bars." if n < 200 else "")
    add("same_250_prefix_without_future", stop=250)
    add("one_millisecond_before_200th_close", count=200,
        request={"snapshot_utc_msc":BASE+200*DURATION-1,"clock_start_utc_msc":BASE+200*DURATION-1},
        reason="INSUFFICIENT_INDICATOR_WARMUP",scope="NATIVE_BUNDLE_WARMUP",
        note="The 200th bar remains forming until its exact close; only199 are available.")
    add("tail_250_has_different_history_origin", start=150)
    add("m15_same_observations", "m15_mixed", request={"timeframe":"M15"})
    add("h1_same_observations", "h1_mixed", request={"timeframe":"H1"})
    for history in ("constant", "constant_range", "increasing", "decreasing", "alternating",
                    "impulse", "gapped_mixed", "large_constant", "small_constant",
                    "subnormal_constant", "near_constant"):
        add(history, history)
    mutations = [{"index":i, "close":1000.+i, "open":1000.+i, "high":1001.+i,
                  "low":999.+i, "volume":1e6, "spread_points":99.} for i in range(250, 400)]
    add("future_mutation_preserves_prefix", count=250, overrides=mutations)
    add("zero_volume_spread_do_not_change_indicators", count=250,
        overrides=[{"index":i,"volume":0.,"spread_points":0.} for i in range(400)])
    add("different_symbol_same_numeric_input", count=250, request={"symbol":"SECOND_SYNTHETIC"})
    add("minimum_request_precedes_bundle", count=200, request={"minimum_bars":201},
        reason="INSUFFICIENT_CLOSED_BARS", scope="NATIVE_REQUEST_CONSTRAINT",
        note="Python helper has no minimum_bars argument.")
    add("request_250_history_250", count=250, request={"minimum_bars":250})
    add("stale_snapshot", count=250,
        request={"clock_start_utc_msc":BASE+250*DURATION+5001}, reason="STALE_SNAPSHOT",
        scope="NATIVE_REQUEST_CONSTRAINT", note="Indicator references do not assert snapshot clock freshness.")
    add("future_snapshot", count=250,
        request={"clock_start_utc_msc":BASE+250*DURATION-1}, reason="FUTURE_SNAPSHOT",
        scope="NATIVE_REQUEST_CONSTRAINT", note="The supplied clock precedes snapshot.")
    add("empty_history", "empty", reason="EMPTY_HISTORY")
    add("zero_minimum", count=250, request={"minimum_bars":0}, reason="REQUEST_LIMITS_INVALID",
        scope="NATIVE_REQUEST_CONSTRAINT", note="Native request requires a positive minimum.")
    add("invalid_future_ohlc", count=250, overrides=[{"index":399,"high":0.}],
        reason="BAR_VALUES_INVALID", scope="NATIVE_GLOBAL_VALIDATION",
        note="Native validates excluded rows too; Python validates the closed subset.")
    add("invalid_forming_nan", count=250, overrides=[{"index":250,"close":"NAN"}],
        reason="BAR_VALUES_INVALID", scope="NATIVE_GLOBAL_VALIDATION",
        note="Native validates excluded rows too; Python validates the closed subset.")
    for field, value, label in (("close", "NAN", "nan_close"), ("high", "POS_INF", "infinite_high"),
                                ("volume", -1., "negative_volume"), ("low", -1., "negative_low")):
        add(label, count=250, overrides=[{"index":1,field:value}], reason="BAR_VALUES_INVALID")
    add("duplicate_closed", count=250, overrides=[{"index":2,"timestamp_utc_msc":BASE+DURATION}],
        reason="BAR_TIME_ORDER_INVALID")
    add("overlapping_closed", count=250, overrides=[{"index":2,"timestamp_utc_msc":BASE+DURATION+1}],
        reason="BAR_INTERVAL_OVERLAP", scope="NATIVE_INTERVAL_VALIDATION",
        note="Python checks unique ordering but not full interval overlap.")
    add("rsi_ratio_overflow", "rsi_ratio_overflow", reason="INDICATOR_ARITHMETIC_INVALID",
        scope="NATIVE_NUMERIC_STRICTER",
        note="Finite OHLC produces an unrepresentable gain/loss quotient. Pandas saturates RSI to100; native rejects before division.")
    return histories, cases


def resolve_bars(histories, case):
    rows = deepcopy(histories[case["history_id"]][case["slice_start"]:case["slice_stop"]])
    for override in case["bar_overrides"]:
        index = override["index"]
        rows[index].update({key:value for key,value in override.items() if key != "index"})
    return rows


def _frame(rows):
    return pd.DataFrame([{"timestamp_utc":_datetime(row["timestamp_utc_msc"]),
        **{key:SPECIAL_NUMBERS.get(value,value) if isinstance(value,str) else value
           for key,value in row.items() if key != "timestamp_utc_msc"}} for row in rows],
        columns=("timestamp_utc","open","high","low","close","volume","spread_points"))


def _number(value):
    value = float(value)
    return {"status":"FINITE","value":value} if math.isfinite(value) else {
        "status":"NAN" if math.isnan(value) else "POS_INF" if value > 0 else "NEG_INF", "value":None}


def python_reference(histories, case):
    request = case["request"]
    snapshot = MarketSnapshot(request["symbol"],request["timeframe"],_datetime(request["snapshot_utc_msc"]),
        10.,10.05,5.,2,.01,1.,.01,.01,100.,.01,0,0)
    try:
        frame = closed_strategy_bars(_frame(resolve_bars(histories,case)),snapshot)
    except (ValueError,TypeError,OverflowError) as error:
        return {"selector_status":"REJECTED","error_type":type(error).__name__,"values":{}}
    close = frame["close"]
    with np.errstate(over="ignore",invalid="ignore",divide="ignore",under="ignore"):
        series = {"ema20":ema(close,20), "ema50":ema(close,50), "ema200":ema(close,200),
                  "rsi14":rsi(close,14), "atr14":atr(frame,14)}
    timestamps = [int((value.to_pydatetime()-EPOCH).total_seconds()*1000) for value in frame["timestamp_utc"]]
    return {"selector_status":"VALID", "bars_count":len(frame),
        "history_start_utc_msc":timestamps[0], "source_bar_timestamp_utc_msc":timestamps[-1],
        "available_at_utc_msc":timestamps[-1]+DURATIONS[request["timeframe"]],
        "first_valid_position":{key:None if values.first_valid_index() is None else int(values.first_valid_index())
                                for key,values in series.items()},
        "values":{key:_number(values.iloc[-1]) for key,values in series.items()}}


def price_tolerance(value):
    """Predeclared regression budget, no absolute floor and exact zero."""
    return min(PRICE_ULPS*math.ulp(value), PRICE_RELATIVE_CAP*abs(value)) if value else 0.0


def expected_native(case, reference):
    passed = case["native_reason"] == "CORE_INDICATORS_VALID"
    result = dict(valid=passed, reason=case["native_reason"], version=VERSION,
        symbol="",timeframe="",execution_authorized=False,full_pipeline_verified=False,
        **{name:0 for name in NUMERIC_RESULT_FIELDS})
    if passed:
        if reference["selector_status"] != "VALID" or any(reference["values"][key]["status"] != "FINITE" for key in FIELDS):
            raise ValueError(f"declared valid fixture has no finite Python reference: {case['case_id']}")
        for key in ("bars_count","history_start_utc_msc","source_bar_timestamp_utc_msc","available_at_utc_msc"):
            result[key] = reference[key]
        for key in ("symbol","timeframe","snapshot_utc_msc","clock_start_utc_msc","clock_resolution_msc"):
            result[key] = case["request"][key]
        result.update({key:reference["values"][key]["value"] for key in FIELDS})
    return result


def fixture_document():
    histories, cases = declared_inputs()
    for case in cases:
        case["input_sha256"] = sha256(canonical_bytes({"request":case["request"],"bars":resolve_bars(histories,case)})).hexdigest()
        case["python_reference"] = python_reference(histories,case)
        case["expected_native"] = expected_native(case,case["python_reference"])
        case["absolute_tolerances"] = {key:(RSI_ABSOLUTE_TOLERANCE if key=="rsi14" else price_tolerance(case["expected_native"][key]))
                                      if case["expected_native"]["valid"] else 0.0 for key in FIELDS}
    functions = (ema,rsi,atr,closed_strategy_bars,validate_ohlcv_frame)
    return {"schema_version":"native_core_indicator_fixtures_v1", "indicator_version":VERSION,
        "scope":"SYNTHETIC_FUNCTION_REFERENCE_ONLY", "native_runtime_executed":False,
        "full_pipeline_verified":False, "execution_authorized":False,
        "reference_runtime":{"python":platform.python_version(),"pandas":pd.__version__,"numpy":np.__version__,
            "float_mant_dig":sys.float_info.mant_dig,"float_max_exp":sys.float_info.max_exp},
        "python_function_sha256":{f"{fn.__module__}.{fn.__name__}":sha256(inspect.getsource(fn).encode()).hexdigest() for fn in functions},
        "tolerance_policy":{"price_max_ulps":PRICE_ULPS,"price_relative_cap":PRICE_RELATIVE_CAP,
            "price_absolute_floor":0.,"zero_price_exact":True,"rsi_absolute":RSI_ABSOLUTE_TOLERANCE,
            "scope":"REGRESSION_BUDGET_NOT_A_UNIVERSAL_ERROR_BOUND"},
        "histories":histories,"cases":cases}


def canonical_bytes(document):
    return (json.dumps(document,indent=2,sort_keys=True,allow_nan=False)+"\n").encode("utf-8")


def _mql_literal(value):
    if value == "NAN": return "NativeCoreFixtureNonfinite(0)"
    if value == "POS_INF": return "NativeCoreFixtureNonfinite(1)"
    if value == "NEG_INF": return "NativeCoreFixtureNonfinite(-1)"
    if isinstance(value,str): return json.dumps(value)
    if isinstance(value,bool): return "true" if value else "false"
    if isinstance(value,float) and 0 < abs(value) < sys.float_info.min:
        return f"(DBL_MIN*{value/sys.float_info.min!r})"
    return str(value)


def render_mql(document):
    digest = sha256(canonical_bytes(document)).hexdigest()
    lines = ["// Generated by scripts/generate_native_core_indicator_fixtures.py; do not edit.",
        f"// Authoritative fixture SHA256: {digest}",
        "// Compilation does not execute these assertions or establish runtime parity.",
        "#ifndef AGI_GENERATED_CORE_INDICATOR_FIXTURES_MQH", "#define AGI_GENERATED_CORE_INDICATOR_FIXTURES_MQH",
        "double NativeCoreFixtureNonfinite(const int kind)","  {",
        "   double argument=(kind==0 ? -1.0 : 1000.0);",
        "   if(kind==0) return MathSqrt(argument);",
        "   double infinite=MathExp(argument); return kind<0 ? -infinite : infinite;","  }",
        "bool NativeCoreFixtureNear(const double actual,const double expected,const double budget)","  {",
        "   if(!MathIsValidNumber(actual) || !MathIsValidNumber(expected) || !MathIsValidNumber(budget) || budget<0.0) return false;",
        "   if(actual==expected) return true;",
        "   if(actual<0.0 || expected<0.0) return false;",
        "   return MathAbs(actual-expected)<=budget;","  }",
        "void NativeCoreFixtureBar(NativeClosedBar &bar,const long timestamp,const double opened,const double high,const double low,const double close,const double volume,const double spread)","  {",
        "   bar.timestamp_utc_msc=timestamp; bar.open=opened; bar.high=high; bar.low=low;",
        "   bar.close=close; bar.volume=volume; bar.spread_points=spread;","  }"]
    history_numbers = {name:index for index,name in enumerate(sorted(document["histories"]))}
    for name, index in history_numbers.items():
        rows = document["histories"][name]
        lines += [f"void NativeCoreLoadHistory{index}(NativeClosedBar &bars[])","  {",f"   ArrayResize(bars,{len(rows)});"]
        for i,row in enumerate(rows):
            values = [row[key] for key in ("timestamp_utc_msc","open","high","low","close","volume","spread_points")]
            lines.append(f"   NativeCoreFixtureBar(bars[{i}],"+",".join(_mql_literal(value) for value in values)+");")
        lines += ["  }"]
    lines += ["void NativeCoreFixturePoison(NativeCoreIndicatorResult &result)","  {",
        '   result.valid=true; result.reason="OLD"; result.version="OLD"; result.symbol="OLD"; result.timeframe="OLD";',
        "   result.execution_authorized=true; result.full_pipeline_verified=true;"]
    lines += [f"   result.{key}=777;" for key in NUMERIC_RESULT_FIELDS]
    lines += ["  }"]
    for index,case in enumerate(document["cases"]):
        name,expected=case["case_id"],case["expected_native"]
        lines += [f"void NativeCoreRunCase{index}(NativeCoreIndicatorResult &result)","  {",
            f"   // {name}: {case['comparison_scope']}",
            "   NativeClosedBarRequest request; NativeClosedBar source[]; NativeClosedBar bars[];",
            f"   NativeCoreLoadHistory{history_numbers[case['history_id']]}(source);"]
        count=case["slice_stop"]-case["slice_start"]
        lines += [f"   ArrayResize(bars,{count});",f"   for(int i=0;i<{count};i++) bars[i]=source[i+{case['slice_start']}];"]
        for override in case["bar_overrides"]:
            for key,value in sorted(override.items()):
                if key != "index": lines.append(f"   bars[{override['index']}].{key}={_mql_literal(value)};")
        for key,value in sorted(case["request"].items()): lines.append(f"   request.{key}={_mql_literal(value)};")
        lines += ["   NativeCoreFixturePoison(result);", "   bool accepted=NativeCalculateCoreIndicators(request,bars,result);",
            f'   Check(accepted=={_mql_literal(expected["valid"])},"{name}:return");']
        for key,value in sorted(expected.items()):
            if key in FIELDS and expected["valid"]:
                budget=case["absolute_tolerances"][key]
                lines.append(f'   Check(NativeCoreFixtureNear(result.{key},{_mql_literal(value)},{_mql_literal(budget)}),"{name}:{key}");')
            else: lines.append(f'   Check(result.{key}=={_mql_literal(value)},"{name}:{key}");')
        if expected["valid"]:
            lines += ["   request.minimum_bars=0;",
                f'   Check(!NativeCalculateCoreIndicators(request,bars,result),"{name}:reset_return");',
                f'   Check(!result.valid && result.reason=="REQUEST_LIMITS_INVALID" && result.version=="{VERSION}","{name}:reset_status");',
                f'   Check(result.symbol=="" && result.timeframe=="","{name}:reset_identity");',
                f'   Check(!result.execution_authorized && !result.full_pipeline_verified,"{name}:reset_flags");']
            for key in NUMERIC_RESULT_FIELDS:
                lines.append(f'   Check(result.{key}==0,"{name}:reset_{key}");')
        lines += ["  }"]
    lines += ["void RunGeneratedCoreIndicatorFixtures(void)","  {","   NativeCoreIndicatorResult result;"]
    lines += [f"   NativeCoreRunCase{i}(result);" for i in range(len(document["cases"]))]
    lines += ["  }","#endif",""]
    return "\n".join(lines)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output",type=Path,default=DEFAULT_JSON)
    parser.add_argument("--mql-output",type=Path,default=DEFAULT_INCLUDE)
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args(argv)
    document=fixture_document()
    outputs=((args.json_output,canonical_bytes(document)),(args.mql_output,render_mql(document).encode("utf-8")))
    if args.check:
        return 0 if all(path.is_file() and path.read_bytes()==data for path,data in outputs) else 1
    for path,data in outputs:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    print(f"Generated {len(document['cases'])} synthetic indicator fixtures; MQL assertions NOT EXECUTED.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())

"""Generate synthetic fixture evidence and MQL assertions; never run a terminal.

Native expectations are manually declared against PROJECT_SPEC 17.8. Python
observations execute the actual selector and core input validator; there is no
Python reimplementation of NativeSelectClosedBars in this generator.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/python"))

import pandas as pd

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState, MarketSnapshot
from agi_style_forex_bot_mt5.core.decision.pipeline import DecisionContext, InputRejected, SharedDecisionPipeline
from agi_style_forex_bot_mt5.data.strategy_features import closed_strategy_bars
from agi_style_forex_bot_mt5.risk import RiskEngine, RiskRuntimeState

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
BASE = int((datetime(2026, 1, 5, 12, tzinfo=timezone.utc) - EPOCH).total_seconds()) * 1000
MAX_MSC = 32535215999999
DURATIONS = {"M5": 300000, "M15": 900000, "H1": 3600000}
NUMBER_FIELDS = ("open", "high", "low", "close", "volume", "spread_points")
SPECIAL_NUMBERS = {"NAN": float("nan"), "POS_INF": float("inf"), "NEG_INF": float("-inf")}
DEFAULT_JSON = ROOT / "tests/fixtures/native_closed_bar_cases.json"
DEFAULT_INCLUDE = ROOT / "tests/mt5/GeneratedClosedBarFixtures.mqh"


def _datetime(ms):
    return EPOCH + timedelta(milliseconds=ms)


def _milliseconds(value):
    delta = value.to_pydatetime() - EPOCH if isinstance(value, pd.Timestamp) else value - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _bar(timestamp, index=0):
    opened = 10.0 + index * .125
    return dict(timestamp_utc_msc=timestamp, open=opened, high=opened+.5,
                low=opened-.5, close=opened+.25, volume=100.+index, spread_points=5.)


def declared_cases():
    """Named boundary oracles, not an executable copy of the native selector."""
    default_request = dict(symbol="SYNTHETIC", timeframe="M5", snapshot_utc_msc=BASE,
        clock_start_utc_msc=BASE, clock_resolution_msc=1, minimum_bars=3, max_snapshot_age_msc=5000)
    default_bars = [_bar(BASE+i*300000, n) for n, i in enumerate((-3,-2,-1,0,1))]
    cases = []

    def add(case_id, *, request=None, bars=None, reason="CLOSED_BARS_VALID", selected=(0,1,2), scope="COMPARABLE", note=""):
        req, rows = {**default_request, **(request or {})}, deepcopy(default_bars if bars is None else bars)
        passed = reason == "CLOSED_BARS_VALID"
        indices = list(selected) if passed else []
        expected = dict(valid=passed, reason=reason, input_count=len(rows), closed_count=len(indices),
            excluded_count=len(rows)-len(indices) if passed else 0,
            source_bar_timestamp_utc_msc=rows[indices[-1]]["timestamp_utc_msc"] if passed else 0,
            available_at_utc_msc=rows[indices[-1]]["timestamp_utc_msc"]+DURATIONS[req["timeframe"]] if passed else 0,
            timeframe="" if reason in {"SYMBOL_INVALID","TIMEFRAME_INVALID"} else req["timeframe"],
            execution_authorized=False, full_pipeline_verified=False, selected_indices=indices)
        cases.append(dict(case_id=case_id, comparison_scope=scope, difference_note=note,
                          request=req, bars=rows, expected_native=expected))

    add("m5_exact_close_with_forming_and_future")
    for timeframe, duration in (("M15",900000),("H1",3600000)):
        add(f"{timeframe.lower()}_exact_close", request={"timeframe":timeframe},
            bars=[_bar(BASE+i*duration,n) for n,i in enumerate((-3,-2,-1,0,1))])
    add("one_millisecond_before_close", request={"snapshot_utc_msc":BASE-1,"minimum_bars":2}, selected=(0,1))
    add("one_millisecond_after_close", request={"snapshot_utc_msc":BASE+1,"clock_start_utc_msc":BASE+1})
    add("zero_volume_and_spread_preserved", bars=[{**x,"volume":0.,"spread_points":0.} for x in default_bars])
    add("gaps_preserved", bars=[_bar(BASE+i*300000,n) for n,i in enumerate((-5,-3,-1,0,2))])
    add("snapshot_age_exact_5000", request={"clock_start_utc_msc":BASE+5000})
    add("snapshot_age_5001", request={"clock_start_utc_msc":BASE+5001}, reason="STALE_SNAPSHOT")
    add("snapshot_age_exact_one_millisecond", request={"clock_start_utc_msc":BASE+1,"max_snapshot_age_msc":1})
    add("snapshot_age_two_exceeds_one_millisecond", request={"clock_start_utc_msc":BASE+2,"max_snapshot_age_msc":1}, reason="STALE_SNAPSHOT")
    add("second_clock_cannot_satisfy_one_millisecond_age", request={"clock_resolution_msc":1000,"max_snapshot_age_msc":1},
        reason="STALE_SNAPSHOT",scope="NATIVE_CLOCK_INTERVAL",note="Requested age is finer than clock certainty; start alone cannot establish freshness.")
    add("snapshot_future_one_millisecond", request={"snapshot_utc_msc":BASE+1}, reason="FUTURE_SNAPSHOT")
    add("second_clock_fresh_boundary", request={"clock_start_utc_msc":BASE+4001,"clock_resolution_msc":1000})
    add("second_clock_ambiguous_stale", request={"clock_start_utc_msc":BASE+4002,"clock_resolution_msc":1000},
        reason="STALE_SNAPSHOT", scope="NATIVE_CLOCK_INTERVAL", note="Python at clock start passes; upper endpoint rejects.")
    add("second_clock_possibly_future", request={"snapshot_utc_msc":BASE+1,"clock_resolution_msc":1000},
        reason="FUTURE_SNAPSHOT", scope="NATIVE_CLOCK_INTERVAL", note="Native requires snapshot <= clock start; upper-end Python alone would pass.")
    old = [_bar(BASE+i*300000,n) for n,i in enumerate((-4,-3,-2))]
    add("bar_age_exact_duration_plus_5000", request={"snapshot_utc_msc":BASE+5000,"clock_start_utc_msc":BASE+5000}, bars=old)
    add("bar_age_one_millisecond_stale", request={"snapshot_utc_msc":BASE+5001,"clock_start_utc_msc":BASE+5001},
        bars=old, reason="STALE_CLOSED_BARS")
    add("second_clock_bar_age_exact", request={"snapshot_utc_msc":BASE+4001,"clock_start_utc_msc":BASE+4001,"clock_resolution_msc":1000}, bars=old)
    add("second_clock_bar_age_ambiguous", request={"snapshot_utc_msc":BASE+4002,"clock_start_utc_msc":BASE+4002,"clock_resolution_msc":1000},
        bars=old, reason="STALE_CLOSED_BARS", scope="NATIVE_CLOCK_INTERVAL", note="Fresh at start, stale at upper endpoint.")
    add("closed_duplicate", bars=[default_bars[0],default_bars[1],default_bars[1]], reason="BAR_TIME_ORDER_INVALID")
    add("closed_reversed", bars=list(reversed(default_bars[:3])), reason="BAR_TIME_ORDER_INVALID")
    add("future_duplicate_invalidates_batch", bars=default_bars+[deepcopy(default_bars[-1])], reason="BAR_TIME_ORDER_INVALID",
        scope="NATIVE_GLOBAL_VALIDATION", note="Python excludes future rows before checking order.")
    add("future_reversed_invalidates_batch", bars=default_bars[:3]+list(reversed(default_bars[3:])), reason="BAR_TIME_ORDER_INVALID",
        scope="NATIVE_GLOBAL_VALIDATION", note="Python excludes future rows before checking order.")
    overlap = deepcopy(default_bars[:3]); overlap[1]["timestamp_utc_msc"] += 1
    add("closed_intervals_overlap_one_millisecond", bars=overlap, reason="BAR_INTERVAL_OVERLAP",
        scope="NATIVE_INTERVAL_VALIDATION", note="Python selector checks unique sorted timestamps, not interval overlap.")
    for label, changes in (("zero_open",{"open":0.}), ("negative_close",{"close":-1.}),
                           ("inconsistent_high",{"high":1.}), ("inconsistent_low",{"low":99.}),
                           ("negative_volume",{"volume":-1.}), ("negative_spread",{"spread_points":-1.}),
                           ("nan_open",{"open":"NAN"}), ("positive_infinite_high",{"high":"POS_INF"}),
                           ("negative_infinite_spread",{"spread_points":"NEG_INF"})):
        bad = deepcopy(default_bars); bad[0].update(changes)
        add(f"closed_{label}", bars=bad, reason="BAR_VALUES_INVALID")
    bad = deepcopy(default_bars); bad[-1]["high"] = -1.
    add("invalid_future_ohlc_invalidates_batch", bars=bad, reason="BAR_VALUES_INVALID",
        scope="NATIVE_GLOBAL_VALIDATION", note="Python validates only selected closed subset.")
    bad = deepcopy(default_bars); bad[-2]["spread_points"] = "NAN"
    add("invalid_forming_spread_invalidates_batch", bars=bad, reason="BAR_VALUES_INVALID",
        scope="NATIVE_GLOBAL_VALIDATION", note="Python validates only selected closed subset.")
    add("empty_history", bars=[], reason="EMPTY_HISTORY")
    add("all_forming_future", bars=default_bars[3:], reason="NO_CLOSED_BARS")
    add("history_below_declared_minimum", request={"minimum_bars":4}, reason="INSUFFICIENT_CLOSED_BARS",
        scope="NATIVE_REQUEST_CONSTRAINT", note="Python helper has no minimum-history argument.")
    for field,value in (("minimum_bars",0),("minimum_bars",-1),("max_snapshot_age_msc",0),
                        ("max_snapshot_age_msc",5001),("clock_resolution_msc",0),("clock_resolution_msc",2)):
        add(f"invalid_{field}_{value}", request={field:value}, reason="REQUEST_LIMITS_INVALID", scope="NATIVE_REQUEST_CONSTRAINT")
    add("empty_symbol", request={"symbol":""}, reason="SYMBOL_INVALID", scope="NATIVE_REQUEST_CONSTRAINT")
    add("blank_symbol", request={"symbol":" "}, reason="SYMBOL_INVALID", scope="NATIVE_REQUEST_CONSTRAINT")
    for timeframe in ("PERIOD_M5","m5","M30",""):
        add(f"noncanonical_timeframe_{timeframe or 'empty'}", request={"timeframe":timeframe}, reason="TIMEFRAME_INVALID", scope="NATIVE_REQUEST_CONSTRAINT")
    for label,values in (("snapshot_zero",{"snapshot_utc_msc":0}), ("clock_zero",{"clock_start_utc_msc":0}),
                         ("snapshot_calendar_overflow",{"snapshot_utc_msc":MAX_MSC+1,"clock_start_utc_msc":MAX_MSC}),
                         ("clock_interval_calendar_overflow",{"clock_start_utc_msc":MAX_MSC,"clock_resolution_msc":1000})):
        add(label,request=values,reason="REQUEST_TIMESTAMP_INVALID",scope="NATIVE_CALENDAR_CONSTRAINT")
    for label,timestamp in (("zero_open_timestamp",0),("negative_open_timestamp",-1),("bar_close_calendar_overflow",MAX_MSC-299999)):
        bad = deepcopy(default_bars)
        bad[0 if timestamp<=0 else -1]["timestamp_utc_msc"] = timestamp
        add(label,bars=bad,reason="BAR_TIMESTAMP_INVALID",scope="NATIVE_CALENDAR_CONSTRAINT")
    add("native_calendar_exact_last_millisecond",request={"snapshot_utc_msc":MAX_MSC,"clock_start_utc_msc":MAX_MSC},
        bars=[_bar(MAX_MSC+i*300000,n) for n,i in enumerate((-3,-2,-1))],
        scope="NATIVE_CALENDAR_CONSTRAINT",note="Native permits a closing timestamp equal to the documented calendar ceiling; Pandas range is not assumed equivalent.")
    for label,values in (("snapshot_long_max",{"snapshot_utc_msc":2**63-1}),
                         ("snapshot_long_min",{"snapshot_utc_msc":-(2**63)}),
                         ("clock_long_max",{"clock_start_utc_msc":2**63-1})):
        add(label,request=values,reason="REQUEST_TIMESTAMP_INVALID",scope="NATIVE_CALENDAR_CONSTRAINT")
    for label,timestamp,index in (("bar_open_long_min",-(2**63),0),("bar_open_long_max",2**63-1,-1)):
        bad=deepcopy(default_bars); bad[index]["timestamp_utc_msc"]=timestamp
        add(label,bars=bad,reason="BAR_TIMESTAMP_INVALID",scope="NATIVE_CALENDAR_CONSTRAINT")
    return cases


def python_reference(case):
    """Observe production Python functions; no strategy, broker, audit or file path."""
    request = case["request"]
    try:
        snapshot_time = _datetime(request["snapshot_utc_msc"])
    except OverflowError:
        return {"selector":{"valid":False,"error_type":"OUTSIDE_PYTHON_DATETIME_RANGE"},
                "temporal_at_clock_start":{"status":"NOT_EVALUATED"},
                "temporal_at_clock_upper":{"status":"NOT_EVALUATED"}}
    snapshot = MarketSnapshot(request["symbol"],request["timeframe"],snapshot_time,
        10.,10.05,5.,2,.01,1.,.01,.01,100.,.01,0,0)
    try:
        rows = [{"timestamp_utc":_datetime(x["timestamp_utc_msc"]),
                 **{name:SPECIAL_NUMBERS.get(x[name],x[name]) if isinstance(x[name],str) else x[name] for name in NUMBER_FIELDS}}
                for x in case["bars"]]
        frame = pd.DataFrame(rows,columns=("timestamp_utc",*NUMBER_FIELDS))
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"],utc=True)
        for name in NUMBER_FIELDS: frame[name] = frame[name].astype(float)
        closed = closed_strategy_bars(frame,snapshot)
    except (ValueError, OverflowError, TypeError) as error:
        return {"selector":{"valid":False,"error_type":type(error).__name__},
                "temporal_at_clock_start":{"status":"NOT_EVALUATED"},
                "temporal_at_clock_upper":{"status":"NOT_EVALUATED"}}
    selected = [_milliseconds(value) for value in closed["timestamp_utc"]]
    duration = pd.Timedelta(request["timeframe"][1:]+{"M":"min","H":"h","D":"D"}.get(request["timeframe"][:1],"min"))
    available = (closed.iloc[-1]["timestamp_utc"]+duration).to_pydatetime()
    source = closed.iloc[-1]["timestamp_utc"].to_pydatetime()
    observation = {"selector":{"valid":True,"closed_count":len(closed),"source_timestamps_utc_msc":selected,
                    "source_bar_timestamp_utc_msc":_milliseconds(source),"available_at_utc_msc":_milliseconds(available)}}
    config = BotConfig(paper_allow_disabled_ml=True,max_market_snapshot_age_seconds=request["max_snapshot_age_msc"]/1000)
    # Invoke the REAL input-validation method without constructing unrelated ML,
    # storage or strategy dependencies. It reads only risk_engine.config on self.
    validator_receiver = SimpleNamespace(risk_engine=RiskEngine(config))
    for label,now_ms in (("temporal_at_clock_start",request["clock_start_utc_msc"]),
                         ("temporal_at_clock_upper",request["clock_start_utc_msc"]+request["clock_resolution_msc"]-1)):
        try:
            now = _datetime(now_ms)
        except OverflowError:
            observation[label]={"status":"NOT_EVALUATED","code":"OUTSIDE_PYTHON_DATETIME_RANGE"}
            continue
        context = DecisionContext(decision_id=case["case_id"],config=config,snapshot=snapshot,
            features={"session":"SYNTHETIC","regime":"RANGE","spread_percentile":50.,
                      "source_bar_timestamp_utc":source.isoformat(),"available_at_utc":available.isoformat()},
            features_available_at_utc=available,state_available_at_utc=now,
            account=AccountState(0,"DEMO",10000.,10000.,10000.,is_demo=True,trade_allowed=False),
            risk_state=RiskRuntimeState(daily_equity_reference=10000.,floating_drawdown_reference=10000.,open_positions=(),snapshots_by_symbol={}),
            open_trades=(),broker_symbol="SYNTHETIC",broker_readiness_score=80.,correlation=None,
            shadow_paused=False,consecutive_losses=0,allow_disabled_ml=True,ml_model_available_at_utc=None)
        try:
            SharedDecisionPipeline._validate_context(validator_receiver,context,now)
        except InputRejected as error:
            observation[label] = {"status":"REJECTED","code":error.code}
        else:
            observation[label] = {"status":"VALID","code":"INPUTS_VALID"}
    return observation


def fixture_document():
    cases = declared_cases()
    for case in cases:
        case["python_reference"] = python_reference(case)
    return {"schema_version":"native_closed_bar_fixtures_v1","scope":"SYNTHETIC_FUNCTION_REFERENCE_ONLY",
        "native_runtime_executed":False,"full_pipeline_verified":False,"execution_authorized":False,
        "python_functions":["data.strategy_features.closed_strategy_bars","core.decision.pipeline.SharedDecisionPipeline._validate_context"],
        "cases":cases}


def canonical_bytes(document):
    return (json.dumps(document,indent=2,sort_keys=True,allow_nan=False)+"\n").encode("utf-8")


def _mql_literal(value):
    if value=="NAN": return "NativeFixtureNonfinite(0)"
    if value=="POS_INF": return "NativeFixtureNonfinite(1)"
    if value=="NEG_INF": return "NativeFixtureNonfinite(-1)"
    if isinstance(value,str): return json.dumps(value)
    if isinstance(value,bool): return "true" if value else "false"
    if value==-(2**63): return "(-9223372036854775807-1)"
    return str(value)


def render_mql(document):
    digest = sha256(canonical_bytes(document)).hexdigest()
    lines = ["// Generated by scripts/generate_native_closed_bar_fixtures.py; do not edit.",
        f"// Authoritative fixture SHA256: {digest}",
        "// Compilation does not execute these assertions or establish runtime parity.",
        "#ifndef AGI_GENERATED_CLOSED_BAR_FIXTURES_MQH", "#define AGI_GENERATED_CLOSED_BAR_FIXTURES_MQH",
        "double NativeFixtureNonfinite(const int kind)","  {",
        "   double argument=(kind==0 ? -1.0 : 1000.0);",
        "   if(kind==0) return MathSqrt(argument);",
        "   double infinite=MathExp(argument); return kind<0 ? -infinite : infinite;","  }",
        "void RunGeneratedClosedBarFixtures(void)","  {",
        "   NativeClosedBarRequest request; NativeClosedBar bars[]; NativeClosedBarResult result;",
        "   result.valid=true; result.execution_authorized=true; result.full_pipeline_verified=true;",
        "   result.source_bar_timestamp_utc_msc=777; result.available_at_utc_msc=888;",
        "   result.closed_count=2; result.excluded_count=2; ArrayResize(result.closed_bars,2);",
        "   result.closed_bars[0].close=123.0; result.closed_bars[1].close=456.0;",
        "   bool accepted=false;"]
    for case in document["cases"]:
        name, expected = case["case_id"],case["expected_native"]
        lines.append(f"   // Fixture: {name} ({case['comparison_scope']})")
        for key,value in sorted(case["request"].items()): lines.append(f"   request.{key}={_mql_literal(value)};")
        lines.append(f"   ArrayResize(bars,{len(case['bars'])});")
        for index,bar in enumerate(case["bars"]):
            for key,value in sorted(bar.items()): lines.append(f"   bars[{index}].{key}={_mql_literal(value)};")
        lines.append("   accepted=NativeSelectClosedBars(request,bars,result);")
        lines.append(f'   Check(accepted=={_mql_literal(expected["valid"])},"{name}:return");')
        for key,value in sorted(expected.items()):
            if key=="selected_indices": continue
            lines.append(f'   Check(result.{key}=={_mql_literal(value)},"{name}:{key}");')
        lines.append(f'   Check(ArraySize(result.closed_bars)=={expected["closed_count"]},"{name}:output_size");')
        for out_index,in_index in enumerate(expected["selected_indices"]):
            for field in ("timestamp_utc_msc",*NUMBER_FIELDS):
                lines.append(f'   if(ArraySize(result.closed_bars)>{out_index}) Check(result.closed_bars[{out_index}].{field}==bars[{in_index}].{field},"{name}:preserved_{out_index}_{field}");')
        if expected["valid"]:
            lines.extend(["   request.minimum_bars=0;",
                f'   Check(!NativeSelectClosedBars(request,bars,result),"{name}:reset_reject");',
                f'   Check(!result.valid && result.reason=="REQUEST_LIMITS_INVALID" && ArraySize(result.closed_bars)==0,"{name}:reset_window");',
                f'   Check(result.closed_count==0 && result.excluded_count==0 && result.source_bar_timestamp_utc_msc==0 && result.available_at_utc_msc==0,"{name}:reset_availability");',
                f'   Check(!result.execution_authorized && !result.full_pipeline_verified,"{name}:reset_flags");'])
    lines += ['   string canonical="OLD";']
    for raw,canonical in (("M5","M5"),("PERIOD_M5","M5"),("M15","M15"),("PERIOD_M15","M15"),("H1","H1"),("PERIOD_H1","H1"),("m5",""),("M30",""),("","")):
        lines.append(f'   Check(NativeNormalizeClosedBarTimeframe({_mql_literal(raw)},canonical)=={_mql_literal(bool(canonical))} && canonical=={_mql_literal(canonical)},"normalize:{raw or "empty"}");')
    lines.extend(["  }","#endif",""])
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
    print(f"Generated {len(document['cases'])} synthetic fixtures; MQL assertions NOT EXECUTED.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())

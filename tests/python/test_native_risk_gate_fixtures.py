"""Python differential oracles and source guards for the native risk gate; MQL is never run here."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import pytest

from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.risk.position_sizer import normalize_lot_down

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate_native_risk_gate_fixtures.py"
FIXTURES = ROOT / "tests/fixtures/native_risk_gate_cases.json"
GENERATED = ROOT / "tests/mt5/GeneratedRiskGateFixtures.mqh"
HARNESS = ROOT / "tests/mt5/RiskGateHarness.mq5"
GATE = ROOT / "src/mt5/Include/Risk/NativeRiskGate.mqh"
CONTRACT = ROOT / "src/mt5/Include/Contracts/RiskContract.mqh"
DOCUMENT = json.loads(FIXTURES.read_text(encoding="utf-8"))
CASES = DOCUMENT["cases"]
EXPECTED_ASSERTIONS = 1433
AMOUNTS = ("risk_amount", "risk_pct", "open_risk_pct_after", "daily_drawdown_pct", "floating_drawdown_pct")


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("native_risk_fixture_generator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code(source):
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/', " ", source)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_frozen_oracle_is_the_production_risk_engine_on_identical_inputs(generator, case):
    before = deepcopy(case)
    assert sha256(generator.canonical_bytes(case["inputs"])).hexdigest() == case["input_sha256"]
    assert generator.python_reference(case) == case["python_reference"]
    assert case == before


@pytest.mark.parametrize("case", [c for c in CASES if c["comparison_scope"].startswith("COMPARABLE")],
                         ids=lambda case: case["case_id"])
def test_comparable_expectations_copy_python_without_adjustment(case):
    reference, expected = case["python_reference"], case["expected_native"]
    assert reference["status"] == "EVALUATED"
    assert expected["accepted"] is reference["accepted"]
    assert expected["reject_code"] == reference["reject_code"]
    for key in ("approved_lot", *AMOUNTS):
        assert reference[key]["status"] == "FINITE" and expected[key] == reference[key]["value"]
    budgets = case["absolute_tolerances"]
    if case["comparison_scope"] == "COMPARABLE":
        assert case["tick_value_on_lattice"] is True and set(budgets.values()) == {0.0}
    else:
        assert case["tick_value_on_lattice"] is False
        assert all(budgets[key] == 4 * math.ulp(expected[key]) for key in AMOUNTS)


@pytest.mark.parametrize("case", [c for c in CASES if not c["comparison_scope"].startswith("COMPARABLE")],
                         ids=lambda case: case["case_id"])
def test_native_only_expectations_are_declared_rejections_that_differ_from_python(case):
    expected, reference = case["expected_native"], case["python_reference"]
    assert case["declared_native_reason"] and case["difference_note"]
    assert expected["accepted"] is False and expected["reject_code"] == case["declared_native_reason"]
    assert expected["approved_lot"] == 0.0 and all(expected[key] == 0.0 for key in AMOUNTS)
    if reference["status"] == "EVALUATED":
        assert (reference["accepted"], reference["reject_code"]) != (False, case["declared_native_reason"])
    else:
        assert case["comparison_scope"] == "NATIVE_CONTRACT"


def test_every_native_rejection_path_and_every_python_code_is_exercised():
    gate = GATE.read_text()
    native_codes = set(re.findall(r'NativeRiskReject\(decision,"([A-Z_]+)"', gate))
    native_codes |= {"MISSING_SL", "MISSING_TP"}
    covered = {case["expected_native"]["reject_code"] for case in CASES} - {""}
    # MAX_RISK_PER_TRADE is unreachable after the sizer's own risk ceiling check;
    # it stays as a defensive guard exactly as in Python.
    assert native_codes - covered == {"MAX_RISK_PER_TRADE"}
    assert covered <= native_codes
    assert sum(case["expected_native"]["accepted"] for case in CASES) >= 30
    scopes = {case["comparison_scope"] for case in CASES}
    assert scopes == {"COMPARABLE", "COMPARABLE_NON_LATTICE_TICK_VALUE", "NATIVE_LIMITS_CODE",
                      "NATIVE_LIMITS_STRICTER", "NATIVE_STATE_STRICTER", "NATIVE_GRID_STRICTER",
                      "NATIVE_NUMERIC_STRICTER", "NATIVE_CONTRACT"}


def test_document_never_authorizes_and_binds_production_sources(generator):
    assert DOCUMENT["execution_authorized"] is False and DOCUMENT["full_pipeline_verified"] is False
    assert DOCUMENT["native_runtime_executed"] is False
    for case in CASES:
        assert case["expected_native"]["execution_authorized"] is False
        assert case["expected_native"]["full_pipeline_verified"] is False
        assert case["expected_native"]["version"] == "native_risk_gate_v1"
    import inspect
    from agi_style_forex_bot_mt5.risk import risk_engine
    digest = sha256(inspect.getsource(risk_engine.RiskEngine).encode()).hexdigest()
    assert DOCUMENT["python_source_sha256"]["agi_style_forex_bot_mt5.risk.risk_engine.RiskEngine"] == digest


def test_generation_is_exact_and_stale_files_are_detected(tmp_path):
    json_copy, mql_copy = tmp_path / "cases.json", tmp_path / "fixtures.mqh"
    run = [sys.executable, "-B", str(SCRIPT), "--json-output", str(json_copy), "--mql-output", str(mql_copy)]
    assert subprocess.run(run, capture_output=True, text=True, timeout=300).returncode == 0
    assert json_copy.read_bytes() == FIXTURES.read_bytes() and mql_copy.read_bytes() == GENERATED.read_bytes()
    assert subprocess.run(run + ["--check"], capture_output=True, timeout=300).returncode == 0
    mql_copy.write_bytes(mql_copy.read_bytes().replace(b'"OLD"', b'"STALE"', 1))
    assert subprocess.run(run + ["--check"], capture_output=True, timeout=300).returncode == 1


def test_generator_runs_outside_repository_without_terminal_or_market_access(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--check"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    source = SCRIPT.read_text()
    assert not re.search(r"\b(MetaTrader5|requests|socket|urllib|subprocess)\b", source)


def test_mql_fixtures_render_every_expectation_and_reset(generator):
    rendered = GENERATED.read_text()
    assert rendered == generator.render_mql(DOCUMENT)
    for index, case in enumerate(CASES):
        assert f"void NativeRiskRunCase{index}(NativeRiskDecision &decision)" in rendered
        assert f'"{case["case_id"]}:reject_code"' in rendered
    accepted = sum(case["expected_native"]["accepted"] for case in CASES)
    assert rendered.count(":reset_flags") == accepted


def test_static_assertion_count_is_the_reviewed_total():
    code = _code(HARNESS.read_text() + GENERATED.read_text())
    calls = len(re.findall(r"\bCheck\s*\(", code)) - len(re.findall(r"\bvoid\s+Check\s*\(", code))
    assert calls == EXPECTED_ASSERTIONS
    for line in _code(GENERATED.read_text()).splitlines():
        assert not re.search(r"\b(for|while|do)\b", line)


def _lattice_units(value):
    decimal = Decimal(repr(float(value)))
    scaled = decimal * Decimal(100000000)
    return int(scaled) if scaled == scaled.to_integral_value() and float(value) <= 1e6 else None


def test_hand_written_lattice_literals_match_the_decimal_reference():
    source = HARNESS.read_text()
    lattice = re.findall(r"(!?)NativeRiskLatticeUnits\(([0-9.e+-]+),units\) && units==(\d+)", source)
    assert len(lattice) == 4
    for negated, value, units in lattice:
        expected = _lattice_units(value)
        if negated:
            assert expected is None and int(units) == 0
        else:
            assert expected == int(units)
    floors = re.findall(r"NativeRiskFloorUnits\(([0-9.e+-]+),units\) && units==(\d+)", source)
    assert len(floors) == 3
    for value, units in floors:
        exact = (Decimal(repr(float(value))) * Decimal(100000000)).to_integral_value(rounding=ROUND_FLOOR)
        assert int(exact) == int(units)
    normalized = re.findall(r"NativeRiskNormalizeLotDown\(([0-9.e+-]+),(\d+),(\d+),(\d+)\)==([0-9.]+)", source)
    assert len(normalized) == 3
    base = MarketSnapshot("SYN", "M5", None, 1.0, 1.0, 0.0, 5, 1e-5, 1.0, 1e-5, 1.0, 1.0, 1.0, 0, 0)
    for lot, minimum, maximum, step, expected in normalized:
        snapshot = replace(base, volume_min=int(minimum) / 1e8, volume_max=int(maximum) / 1e8, volume_step=int(step) / 1e8)
        assert normalize_lot_down(float(lot), snapshot) == float(expected)


@pytest.mark.parametrize("path", (CONTRACT, GATE), ids=lambda path: path.name)
def test_native_sources_have_no_io_clock_account_symbol_or_trading_capability(path):
    tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", _code(path.read_text())))
    forbidden = {"OrderSend", "OrderSendAsync", "OrderCheck", "CTrade", "MqlTradeRequest", "MqlTradeResult", "import",
                 "WebRequest", "SendMail", "SendNotification", "Print", "PrintFormat", "Alert", "Comment", "Sleep",
                 "TimeGMT", "TimeCurrent", "TimeLocal", "TimeTradeServer", "GetTickCount", "GetTickCount64",
                 "GetMicrosecondCount", "MathRand", "MathSrand", "NormalizeDouble", "static", "EventSetTimer",
                 "GlobalVariableGet", "GlobalVariableSet", "ExpertRemove", "TerminalClose"}
    assert not tokens & forbidden
    assert not any(token.startswith(("File", "Socket", "AccountInfo", "SymbolInfo", "TerminalInfo", "History",
                                     "PositionGet", "PositionSelect", "OrderGet", "Copy", "Chart")) for token in tokens)


def test_gate_never_authorizes_and_is_not_yet_wired_into_the_expert():
    clean = _code(GATE.read_text())
    for field in ("execution_authorized", "full_pipeline_verified"):
        assignments = re.findall(rf"\b{field}\s*=(?!=)\s*([^;]+);", clean)
        assert assignments and set(assignments) == {"false"}
    expert = (ROOT / "src/mt5/Experts/AGI_STYLE_FOREX_BOT_MT5.mq5").read_text()
    assert "NativeRiskGate.mqh" not in expert and "NativeEvaluateRisk" not in _code(expert)


def test_limit_ceilings_match_the_python_safety_policy():
    clean = re.sub(r"\s+", "", _code(GATE.read_text()))
    for clause in ("limits.demo_only&&!limits.live_trading_approved", "limits.max_risk_per_trade_pct<=0.5",
                   "limits.max_open_risk_pct<=5.0", "limits.max_open_trades<=10", "limits.max_daily_drawdown_pct<=3.0",
                   "limits.max_floating_drawdown_pct<=5.0", "limits.max_spread_points<=25.0",
                   "limits.max_signal_age_seconds<=30", "limits.max_snapshot_age_seconds<=5"):
        assert clause in clean
    from agi_style_forex_bot_mt5.config import BotConfig
    config = BotConfig()
    assert (config.max_risk_per_trade_pct, config.max_open_risk_pct, config.max_open_trades,
            config.max_daily_drawdown_pct, config.max_floating_drawdown_pct, config.max_spread_points_default,
            config.max_signal_age_seconds, config.max_market_snapshot_age_seconds) == (0.5, 5.0, 10, 3.0, 5.0, 25.0, 30, 5)


def test_gate_checks_follow_the_python_risk_engine_order():
    gate = _code(GATE.read_text())
    body = gate[gate.index("bool NativeEvaluateRisk("):]
    codes = re.findall(r'"([A-Z_]{4,})"', GATE.read_text()[GATE.read_text().index("bool NativeEvaluateRisk("):])
    order = ["RISK_LIMITS_INVALID", "RISK_STATE_INVALID", "ACCOUNT_TYPE_UNKNOWN", "DEMO_ONLY_REAL_ACCOUNT",
             "ACCOUNT_TRADE_DISABLED", "RISK_CALCULATION_UNCERTAIN", "EMERGENCY_KILL_SWITCH", "SYMBOL_NOT_ALLOWED",
             "MARKET_DATA_INVALID", "STALE_SIGNAL", "MARKET_DATA_INVALID", "MISSING_SL", "MISSING_TP",
             "MARKET_DATA_INVALID", "INTERNAL_ERROR", "HIGH_SPREAD", "DAILY_DRAWDOWN_REFERENCE_MISSING",
             "DAILY_DRAWDOWN_LIMIT", "RISK_CALCULATION_UNCERTAIN", "FLOATING_DRAWDOWN_LIMIT",
             "CONSECUTIVE_LOSS_LIMIT", "COOLDOWN_ACTIVE", "RISK_CALCULATION_UNCERTAIN", "INVALID_LOT", "INVALID_LOT",
             "INVALID_LOT", "INVALID_LOT", "MAX_RISK_PER_TRADE", "MAX_OPEN_TRADES", "MAX_OPEN_TRADES_PER_SYMBOL",
             "RISK_CALCULATION_UNCERTAIN", "RISK_CALCULATION_UNCERTAIN", "RISK_CALCULATION_UNCERTAIN", "MAX_OPEN_RISK"]
    assert codes == order
    assert "ArraySize(positions)" in body

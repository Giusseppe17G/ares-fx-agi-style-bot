"""C++ emulation of pure native modules; not MetaTrader runtime evidence."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_native_cpp_emulation.py"
COMPILER = shutil.which("g++")
needs_compiler = pytest.mark.skipif(COMPILER is None, reason="g++ is not installed")


@pytest.fixture(scope="module")
def emulation():
    spec = importlib.util.spec_from_file_location("native_cpp_emulation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_sources(tmp_path):
    root = tmp_path / "copy"
    shutil.copytree(ROOT / "src/mt5/Include", root / "src/mt5/Include")
    shutil.copytree(ROOT / "tests/mt5", root / "tests/mt5")
    return root


def test_translation_rewrites_only_array_syntax_and_rejects_terminal_apis(emulation):
    source = ("#property strict\nbool F(const NativeClosedBar &bars[],NativeRiskPosition &out[])\n"
              "  { NativeClosedBar local[]; NativeClosedBar one[1]; double values[]; return true; }\n")
    text = emulation.translate(source, "sample.mqh")
    assert "#property" not in text
    assert "const MqlArray<NativeClosedBar> &bars" in text and "MqlArray<NativeRiskPosition> &out" in text
    assert "MqlArray<NativeClosedBar> local;" in text and "MqlArray<NativeClosedBar> one(1);" in text
    assert "MqlArray<double> values;" in text
    for api in ("AccountInfoDouble(ACCOUNT_EQUITY)", "SymbolInfoTick(s,t)", "TimeCurrent()", "FileOpen(x,0)",
                "OrderSend(r,q)", "MQLInfoInteger(MQL_TESTER)"):
        with pytest.raises(ValueError, match="terminal APIs"):
            emulation.translate(f"void G() {{ {api}; }}", "impure.mqh")
    with pytest.raises(ValueError, match="datetime literals"):
        emulation.translate("datetime x=D'2026.01.01 00:00:00';", "literal.mqh")


def test_suites_and_counts_match_the_reviewed_native_totals(emulation):
    checker_spec = importlib.util.spec_from_file_location("checker", ROOT / "scripts/check_native_math_logs.py")
    checker = importlib.util.module_from_spec(checker_spec)
    checker_spec.loader.exec_module(checker)
    expected = {name: (summary, count) for name, summary, count in checker.EXPECTED_STAGES}
    for suite, harness, summary, count in emulation.SUITES:
        assert expected[suite] == (summary, count)
        assert (ROOT / "tests/mt5" / harness).is_file()
    # The observer harness reads account/terminal constants and stays out of emulation.
    assert {suite for suite, *_ in emulation.SUITES} == set(expected) - {"observer"}
    assert "-ffp-contract=off" in emulation.FLAGS and "-fsanitize=undefined" in emulation.FLAGS


@needs_compiler
def test_pure_native_suites_pass_under_cpp_emulation(tmp_path):
    output = tmp_path / "emulation.json"
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--output", str(output)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=900)
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == 0, result.stdout + json.dumps(evidence["suites"], indent=1)[:4000]
    assert evidence["passed"] is True and evidence["mql5_runtime_verified"] is False
    assert evidence["execution_authorized"] is False and evidence["full_pipeline_verified"] is False
    for suite in evidence["suites"]:
        assert suite["reason"] == "EMULATED_FIXTURES_PASSED"
        assert suite["checks"] == suite["expected_checks"] and suite["failures"] == 0
        assert suite["compiler_warnings"] == 0 and suite["ubsan_report"] is False


@needs_compiler
@pytest.mark.parametrize("old,new,label", (
    ("if(daily_drawdown>=limits.max_daily_drawdown_pct)", "if(daily_drawdown>limits.max_daily_drawdown_pct)",
     "daily_drawdown_at_limit:reject_code"),
    ("      risk_per_lot=(double)(ticks*value_units)/NATIVE_RISK_UNIT_SCALE;",
     "      risk_per_lot=(double)ticks*tick_value;", "open_risk_jpy_metadata:open_risk_pct_after"),
    ("   if(!state.audit_confirmed) return NativeRiskReject(decision,\"INTERNAL_ERROR\",0.0,0.0,0.0);\n", "",
     "audit_not_confirmed:reject_code"),
))
def test_emulation_detects_a_mutated_risk_gate(tmp_path, old, new, label):
    root = _copy_sources(tmp_path)
    gate = root / "src/mt5/Include/Risk/NativeRiskGate.mqh"
    source = gate.read_text()
    assert source.count(old) == 1
    gate.write_text(source.replace(old, new))
    output = tmp_path / "mutated.json"
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--suite", "risk_gate", "--source-root", str(root),
                             "--output", str(output)], capture_output=True, text=True, timeout=900)
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == 1 and evidence["passed"] is False
    assert label in evidence["suites"][0]["assertion_failures"]

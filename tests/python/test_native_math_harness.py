"""Native math wrapper guards and fail-closed log parser; MQL is never run here."""
import ast
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_native_math_logs.py"
RUNNER = ROOT / "scripts/run_native_math_harness.ps1"
MT5_TESTS = ROOT / "tests/mt5"
WRAPPER = MT5_TESTS / "NativeMathHarness.mq5"
INCLUDE_ROOT = ROOT / "src/mt5/Include"
AGENT_LOG = "Tester/Agent-127.0.0.1-3000/logs/20261010.log"
# (wrapper stage, macro infix, harness, generated fixture include)
SUITES = (
    ("observer", "Observer", "ObservationPolicyHarness.mq5", None),
    ("closed_bars", "ClosedBars", "ClosedBarWindowHarness.mq5", "GeneratedClosedBarFixtures.mqh"),
    ("core_indicators", "CoreIndicators", "CoreIndicatorsHarness.mq5", "GeneratedCoreIndicatorFixtures.mqh"),
    ("risk_gate", "RiskGate", "RiskGateHarness.mq5", "GeneratedRiskGateFixtures.mqh"),
)
STAGE_COUNTS = (("observer", "NATIVE_POLICY_HARNESS", 31), ("closed_bars", "NATIVE_CLOSED_BAR_HARNESS", 1103),
                ("core_indicators", "NATIVE_CORE_INDICATORS_HARNESS", 1348), ("risk_gate", "NATIVE_RISK_GATE_HARNESS", 1433))
TOTAL = sum(count for _, _, count in STAGE_COUNTS)
RENAMED = ("OnStart", "Check", "checks", "failures")
FLAGS = "execution_authorized=false full_pipeline_verified=false"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("native_math_log_checker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code(source):
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/', " ", source)


def _tokens(source):
    return set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", _code(source)))


def _formats(source):
    return re.findall(r'\bPrint(?:Format)?\(\s*"((?:\\.|[^"\\])*)"', source)


def _clean_run(reason=1):
    lines = [f"AGI_NATIVE_MATH_BEGIN version=native_math_harness_v2 expected_checks={TOTAL} model_required=3 "
             f"model_verified_in_mql=false {FLAGS}"]
    for name, summary, count in STAGE_COUNTS:
        lines.append(f"{summary} checks={count} failures=0")
        lines.append(f"AGI_NATIVE_MATH_STAGE name={name} checks={count} failures=0 expected_checks={count} "
                     f"accepted=1 {FLAGS}")
    lines.append(f"AGI_NATIVE_MATH_TOTAL checks={TOTAL} failures=0 ticks=0 accepted=1 wrapper_failures=0 stages=4 "
                 f"expected_checks={TOTAL} {FLAGS}")
    lines.append(f"AGI_NATIVE_MATH_COMPLETE checks={TOTAL} failures=0 ticks=0 accepted=1 reason={reason} completed=1 "
                 f"wrapper_failures=0 stages=4 expected_checks={TOTAL} model_verified_in_mql=false {FLAGS}")
    return lines


def _log_bytes(lines, encoding="utf-16-le-bom"):
    # MT5 journal shape: code, flag, time, source, then the program message.
    text = "".join(f"GK\t0\t00:00:00.000\tCore 1\t2026.10.10 00:00:00   {line}\r\n" for line in lines)
    if encoding == "utf-16-le-bom":
        return b"\xff\xfe" + text.encode("utf-16-le")
    if encoding == "utf-16-le":
        return text.encode("utf-16-le")
    return text.encode("utf-8")


def _runner_config():
    match = re.search(r"\$config = @'\r?\n(.*?)\r?\n'@", RUNNER.read_text(), re.S)
    assert match
    return match.group(1)


def _stage(tmp_path, lines=None, config=None, relative=AGENT_LOG, encoding="utf-16-le-bom"):
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "native-math.ini").write_text(_runner_config() if config is None else config, encoding="utf-8")
    if lines is not None:
        path = stage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_log_bytes(lines, encoding))
    return stage


def _write(stage, relative, lines, encoding="utf-16-le-bom"):
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_log_bytes(lines, encoding))


def _replace(index, old, new):
    def mutate(lines):
        assert old in lines[index]
        lines[index] = lines[index].replace(old, new)
        return lines
    return mutate


# Log parser: one exact clean run passes; every other shape fails closed.

@pytest.mark.parametrize("encoding", ("utf-16-le-bom", "utf-16-le", "utf-8"))
def test_exact_clean_run_passes_and_never_authorizes(checker, tmp_path, encoding):
    evidence = checker.evaluate_stage(_stage(tmp_path, _clean_run(reason=1), encoding=encoding))
    assert evidence["passed"] is True and evidence["reason"] == "NATIVE_MATH_FIXTURES_PASSED"
    assert evidence["record_count"] == 11 and evidence["deinit_reason"] == 1
    assert evidence["config"]["valid"] is True and evidence["config"]["model"] == 3
    assert evidence["assertion_failures"] == {"count": 0, "labels": []}
    for flag in ("execution_authorized", "full_pipeline_verified", "promotion_eligible", "model_verified_in_mql"):
        assert evidence[flag] is False
    [source] = evidence["sources"]
    assert source["directory"] == "Tester/Agent-127.0.0.1-3000/logs"
    assert source["files"][0]["sha256"] == sha256((tmp_path / "stage" / AGENT_LOG).read_bytes()).hexdigest()


@pytest.mark.parametrize("reason", (0, 1, 8, 9))
def test_deinitialization_reason_is_recorded_but_never_treated_as_success_proof(checker, tmp_path, reason):
    evidence = checker.evaluate_stage(_stage(tmp_path, _clean_run(reason=reason)))
    assert evidence["passed"] is True and evidence["deinit_reason"] == reason


MUTATIONS = {
    "truncated_completion": (lambda lines: lines[:-1] + [lines[-1][:60]], "MALFORMED_RECORD"),
    "missing_completion": (lambda lines: lines[:-1], "COMPLETION_RECORD_MISSING"),
    "missing_total": (lambda lines: lines[:-2] + lines[-1:], "RECORD_SEQUENCE_MISMATCH"),
    "missing_stage": (lambda lines: lines[:2] + lines[3:], "RECORD_SEQUENCE_MISMATCH"),
    "duplicated_run": (lambda lines: lines + lines, "RECORD_SEQUENCE_MISMATCH"),
    "record_after_completion": (lambda lines: lines + [lines[1]], "RECORD_SEQUENCE_MISMATCH"),
    "swapped_stages": (lambda lines: lines[:3] + lines[5:7] + lines[3:5] + lines[7:], "RECORD_SEQUENCE_MISMATCH"),
    "assertion_failure": (lambda lines: lines[:1] + ["ASSERTION_FAILED: release always blocked"] + lines[1:],
                          "ASSERTION_FAILURES"),
    "unexpected_tick": (lambda lines: lines[:1] + [f"AGI_NATIVE_MATH_REJECT reason=UNEXPECTED_TICK {FLAGS}"] + lines[1:],
                        "WRAPPER_REJECTED"),
    "observer_count": (lambda lines: _replace(2, "checks=31 ", "checks=30 ")(_replace(1, "checks=31", "checks=30")(lines)),
                       "RECORD_SEQUENCE_MISMATCH"),
    "stage_not_accepted": (_replace(4, "accepted=1", "accepted=0"), "RECORD_SEQUENCE_MISMATCH"),
    "summary_failure_without_label": (_replace(5, "failures=0", "failures=1"), "RECORD_SEQUENCE_MISMATCH"),
    "total_not_accepted": (_replace(-2, "accepted=1", "accepted=0"), "RECORD_SEQUENCE_MISMATCH"),
    "not_completed": (_replace(-1, "completed=1", "completed=0"), "RECORD_SEQUENCE_MISMATCH"),
    "tick_delivered": (_replace(-1, "ticks=0", "ticks=1"), "RECORD_SEQUENCE_MISMATCH"),
    "wrapper_failure": (_replace(-2, "wrapper_failures=0", "wrapper_failures=1"), "RECORD_SEQUENCE_MISMATCH"),
    "three_stages": (_replace(-1, "stages=4", "stages=3"), "RECORD_SEQUENCE_MISMATCH"),
    "different_expected_total": (_replace(0, f"expected_checks={TOTAL}", f"expected_checks={TOTAL - 1}"),
                                 "RECORD_SEQUENCE_MISMATCH"),
    "missing_risk_gate_stage": (lambda lines: lines[:7] + lines[9:], "RECORD_SEQUENCE_MISMATCH"),
    "risk_gate_count": (_replace(8, "checks=1433 ", "checks=1432 "), "RECORD_SEQUENCE_MISMATCH"),
    "execution_flag": (_replace(-1, "execution_authorized=false", "execution_authorized=true"), "MALFORMED_RECORD"),
    "pipeline_flag": (_replace(2, "full_pipeline_verified=false", "full_pipeline_verified=true"), "MALFORMED_RECORD"),
    "model_claimed": (_replace(0, "model_verified_in_mql=false", "model_verified_in_mql=true"), "MALFORMED_RECORD"),
    "other_model": (_replace(0, "model_required=3", "model_required=1"), "MALFORMED_RECORD"),
    "previous_version": (_replace(0, "native_math_harness_v2", "native_math_harness_v1"), "MALFORMED_RECORD"),
    "extra_field": (_replace(2, FLAGS, FLAGS + " extra=1"), "MALFORMED_RECORD"),
    "reordered_fields": (_replace(1, "checks=31 failures=0", "failures=0 checks=31"), "MALFORMED_RECORD"),
    "double_space": (_replace(-2, "AGI_NATIVE_MATH_TOTAL ", "AGI_NATIVE_MATH_TOTAL  "), "MALFORMED_RECORD"),
    "leading_zero": (_replace(1, "checks=31", "checks=031"), "MALFORMED_RECORD"),
    "integer_overflow": (_replace(-1, "reason=1 ", "reason=2147483648 "), "MALFORMED_RECORD"),
    "trailing_space": (_replace(3, "failures=0", "failures=0 "), "MALFORMED_RECORD"),
    "unknown_kind": (lambda lines: lines[:1] + ["AGI_NATIVE_MATH_DEBUG value=1"] + lines[1:], "MALFORMED_RECORD"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_incomplete_inconsistent_or_unsafe_log_fails_closed(checker, tmp_path, name):
    mutate, reason = MUTATIONS[name]
    evidence = checker.evaluate_stage(_stage(tmp_path, mutate(_clean_run())))
    assert evidence["passed"] is False and evidence["reason"] == reason
    if reason == "RECORD_SEQUENCE_MISMATCH":
        assert evidence["first_mismatch"]["index"] >= 0


def test_assertion_labels_and_rejections_are_preserved_with_bounds(checker, tmp_path):
    labels = [f"label {index}" for index in range(150)]
    lines = _clean_run()[:1] + [f"ASSERTION_FAILED: {label}" for label in labels] + _clean_run()[1:]
    evidence = checker.evaluate_stage(_stage(tmp_path, lines))
    assert evidence["reason"] == "ASSERTION_FAILURES"
    assert evidence["assertion_failures"]["count"] == 150
    assert evidence["assertion_failures"]["labels"] == labels[:100]
    assert evidence["records_truncated"] is False and evidence["record_count"] == 161
    (tmp_path / "rejected").mkdir()
    rejected = [f"AGI_NATIVE_MATH_REJECT reason=TEST_CONTEXT_REQUIRED {FLAGS}"]
    other = checker.evaluate_stage(_stage(tmp_path / "rejected", rejected))
    assert other["reason"] == "WRAPPER_REJECTED" and other["reject_reasons"] == ["TEST_CONTEXT_REQUIRED"]


def test_tokens_inside_other_words_and_ordinary_journal_lines_are_not_records(checker, tmp_path):
    noise = ["Tester  NativeMathHarness started", "XAGI_NATIVE_MATH_BEGIN version=other",
             "expertNATIVE_POLICY_HARNESS checks=1 failures=1", "math calculations test passed"]
    lines = noise[:2] + _clean_run()[:4] + noise[2:] + _clean_run()[4:]
    assert checker.evaluate_stage(_stage(tmp_path, lines))["passed"] is True


def test_identical_mirrors_and_daily_rotation_are_one_consistent_run(checker, tmp_path):
    stage = _stage(tmp_path, _clean_run())
    _write(stage, "Tester/logs/20261010.log", _clean_run())
    _write(stage, "logs/20261010.log", ["Terminal  started without account"])
    evidence = checker.evaluate_stage(stage)
    assert evidence["passed"] is True and len(evidence["sources"]) == 3
    (tmp_path / "rotated").mkdir()
    rotated = _stage(tmp_path / "rotated", _clean_run()[:4])
    _write(rotated, "Tester/Agent-127.0.0.1-3000/logs/20261011.log", _clean_run()[4:])
    evidence = checker.evaluate_stage(rotated)
    assert evidence["passed"] is True and [len(item["files"]) for item in evidence["sources"]] == [2]


def test_records_from_two_local_agents_are_two_runs_even_if_identical(checker, tmp_path):
    stage = _stage(tmp_path, _clean_run())
    _write(stage, "Tester/Agent-127.0.0.1-3001/logs/20261010.log", _clean_run())
    evidence = checker.evaluate_stage(stage)
    assert evidence["passed"] is False and evidence["reason"] == "DUPLICATE_AGENT_RUN"
    assert evidence["detail"] == "Tester/Agent-127.0.0.1-3000/logs, Tester/Agent-127.0.0.1-3001/logs"


@pytest.mark.parametrize("mirror", ("partial", "different_reason"))
def test_sources_that_disagree_are_not_merged_or_chosen(checker, tmp_path, mirror):
    stage = _stage(tmp_path, _clean_run(reason=1))
    _write(stage, "Tester/logs/20261010.log", _clean_run()[:-1] if mirror == "partial" else _clean_run(reason=0))
    evidence = checker.evaluate_stage(stage)
    assert evidence["passed"] is False and evidence["reason"] == "LOG_SOURCES_INCONSISTENT"


def test_compile_log_and_missing_logs_never_count_as_runtime_evidence(checker, tmp_path):
    stage = _stage(tmp_path, _clean_run(), relative="MQL5/Experts/NativeMathHarness/NativeMathHarness.log")
    evidence = checker.evaluate_stage(stage)
    assert evidence["reason"] == "NATIVE_MATH_RECORDS_MISSING" and evidence["sources"] == []
    _write(stage, AGENT_LOG, ["Tester  agent started", "Tester  stopped"])
    assert checker.evaluate_stage(stage)["reason"] == "NATIVE_MATH_RECORDS_MISSING"


def test_unreadable_oversized_linked_or_excessive_logs_fail_closed(checker, tmp_path, monkeypatch):
    stage = _stage(tmp_path, _clean_run())
    (stage / "Tester/logs").mkdir(parents=True)
    (stage / "Tester/logs/bad.log").write_bytes(b"A\x00B")
    assert checker.evaluate_stage(stage)["reason"] == "LOG_DECODE_ERROR"
    (stage / "Tester/logs/bad.log").write_bytes(b"\xff\xfe" + b"\x00\xd8")
    assert checker.evaluate_stage(stage)["reason"] == "LOG_DECODE_ERROR"
    (stage / "Tester/logs/bad.log").unlink()
    _write(stage, "Tester/logs/20261010.log", _clean_run())
    monkeypatch.setattr(checker, "MAX_LOG_FILES", 1)
    assert checker.evaluate_stage(stage)["reason"] == "TOO_MANY_LOG_FILES"
    monkeypatch.setattr(checker, "MAX_LOG_FILES", 256)
    monkeypatch.setattr(checker, "MAX_LOG_BYTES", 64)
    assert checker.evaluate_stage(stage)["reason"] == "LOG_TOO_LARGE"
    monkeypatch.undo()
    try:
        os.symlink(stage / AGENT_LOG, stage / "Tester/logs/link.log")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    assert checker.evaluate_stage(stage)["reason"] == "LOG_SOURCE_LINK"


def test_unreadable_directories_logs_or_configuration_fail_closed(checker, tmp_path, monkeypatch):
    stage = _stage(tmp_path, _clean_run())
    real_walk = os.walk

    def failing_walk(top, onerror=None, followlinks=False):
        assert onerror is not None and followlinks is False
        onerror(PermissionError("denied"))
        yield from real_walk(top, onerror=onerror, followlinks=followlinks)

    monkeypatch.setattr(checker.os, "walk", failing_walk)
    assert checker.evaluate_stage(stage)["reason"] == "LOG_DIRECTORY_UNREADABLE"
    monkeypatch.setattr(checker.os, "walk", real_walk)
    real_read = Path.read_bytes

    def failing_read(path):
        if path.suffix in {".log", ".ini"}:
            raise PermissionError("locked")
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", failing_read)
    evidence = checker.evaluate_stage(stage)
    assert evidence["reason"] == "LOG_UNREADABLE" and evidence["config"]["reason"] == "CONFIG_UNREADABLE"


def test_linked_log_directory_is_rejected_instead_of_skipped(checker, tmp_path):
    stage = _stage(tmp_path, _clean_run())
    outside = tmp_path / "outside"
    (outside / "logs").mkdir(parents=True)
    (outside / "logs/20261010.log").write_bytes(_log_bytes(["ASSERTION_FAILED: hidden outside the staging"]))
    try:
        os.symlink(outside, stage / "Tester/Agent-127.0.0.1-3001", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    evidence = checker.evaluate_stage(stage)
    assert evidence["passed"] is False and evidence["reason"] == "LOG_SOURCE_LINK"
    assert evidence["detail"] == "Tester/Agent-127.0.0.1-3001"


CONFIG_CHANGES = {
    "model_every_tick": ("Model=3", "Model=0", "CONFIG_TESTER_MODEL_INVALID"),
    "model_missing": ("Model=3\n", "", "CONFIG_TESTER_MODEL_INVALID"),
    "optimization": ("Optimization=0", "Optimization=1", "CONFIG_TESTER_OPTIMIZATION_INVALID"),
    "forward": ("ForwardMode=0", "ForwardMode=1", "CONFIG_TESTER_FORWARDMODE_INVALID"),
    "visual": ("Visual=0", "Visual=1", "CONFIG_TESTER_VISUAL_INVALID"),
    "remote_agents": ("UseRemote=0", "UseRemote=1", "CONFIG_TESTER_USEREMOTE_INVALID"),
    "cloud_agents": ("UseCloud=0", "UseCloud=1", "CONFIG_TESTER_USECLOUD_INVALID"),
    "other_expert": ("Expert=NativeMathHarness.ex5", "Expert=AGI_STYLE_FOREX_BOT_MT5.ex5", "CONFIG_TESTER_EXPERT_INVALID"),
    "live_trading": ("AllowLiveTrading=0", "AllowLiveTrading=1", "CONFIG_EXPERTS_ALLOWLIVETRADING_INVALID"),
    "dll": ("AllowDllImport=0", "AllowDllImport=1", "CONFIG_EXPERTS_ALLOWDLLIMPORT_INVALID"),
    "login": ("[Common]\n", "[Common]\nLogin=1000\n", "CONFIG_ACCOUNT_ENTRY_FORBIDDEN"),
    "password": ("[Tester]\n", "[Tester]\nPassword=x\n", "CONFIG_ACCOUNT_ENTRY_FORBIDDEN"),
    "server": ("[Common]\n", "[Common]\nserver=Demo\n", "CONFIG_ACCOUNT_ENTRY_FORBIDDEN"),
    "duplicate_key": ("Model=3\n", "Model=3\nModel=3\n", "CONFIG_ENTRY_INVALID"),
    "case_variant_key": ("Model=3\n", "Model=3\nmodel=0\n", "CONFIG_ENTRY_INVALID"),
    "duplicate_section": ("[Tester]\n", "[Tester]\n[Tester]\n", "CONFIG_SECTION_INVALID"),
    "case_variant_section": ("[Tester]\n", "[Tester]\n[tester]\n", "CONFIG_SECTION_INVALID"),
    "lowercase_login": ("[Tester]\n", "[Tester]\nlogin=1000\n", "CONFIG_ACCOUNT_ENTRY_FORBIDDEN"),
    "entry_outside_section": ("[Common]\n", "Model=3\n[Common]\n", "CONFIG_ENTRY_INVALID"),
}


@pytest.mark.parametrize("name", sorted(CONFIG_CHANGES))
def test_non_math_or_account_configuration_blocks_even_a_clean_log(checker, tmp_path, name):
    old, new, reason = CONFIG_CHANGES[name]
    config = _runner_config().replace("\r\n", "\n")
    assert old in config
    evidence = checker.evaluate_stage(_stage(tmp_path, _clean_run(), config=config.replace(old, new, 1)))
    assert evidence["passed"] is False and evidence["reason"] == "TESTER_CONFIG_INVALID"
    assert evidence["config"]["reason"] == reason


def test_missing_configuration_or_stage_is_not_verified(checker, tmp_path):
    stage = _stage(tmp_path, _clean_run())
    (stage / "native-math.ini").unlink()
    evidence = checker.evaluate_stage(stage)
    assert evidence["reason"] == "TESTER_CONFIG_INVALID" and evidence["detail"] == "CONFIG_MISSING"
    assert checker.evaluate_stage(tmp_path / "absent")["reason"] == "STAGE_MISSING"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_cli_writes_relative_evidence_once_and_exit_code_matches(checker, tmp_path, capsys):
    stage = _stage(tmp_path, _clean_run())
    output = tmp_path / "evidence.json"
    assert checker.main(["--stage", str(stage), "--output", str(output)]) == 0
    payload = output.read_text(encoding="utf-8")
    document = json.loads(payload)
    assert document["passed"] is True
    # Inspect decoded strings: raw JSON escapes Windows backslashes and non-ASCII.
    for text in _strings(document):
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text
        assert not os.path.isabs(text) and not PureWindowsPath(text).is_absolute()
    assert checker.main(["--stage", str(stage), "--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == payload
    missing = tmp_path / "missing.json"
    assert checker.main(["--stage", str(tmp_path / "absent"), "--output", str(missing)]) == 1
    assert json.loads(missing.read_text(encoding="utf-8"))["reason"] == "STAGE_MISSING"
    capsys.readouterr()


def test_cli_rejects_a_linked_stage_instead_of_following_it(checker, tmp_path):
    stage = _stage(tmp_path, _clean_run())
    link = tmp_path / "linked-stage"
    try:
        os.symlink(stage, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    output = tmp_path / "linked.json"
    assert checker.main(["--stage", str(link), "--output", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["reason"] == "STAGE_MISSING"


def test_parser_imports_only_the_standard_library():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert modules and modules <= set(sys.stdlib_module_names)


def test_parser_runs_isolated_with_stdlib_from_another_directory(tmp_path):
    stage = _stage(tmp_path, _clean_run())
    output = tmp_path / "isolated.json"
    # -S removes site-packages as well, so a third-party import cannot hide here.
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(SCRIPT), "--stage", str(stage), "--output", str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "passed=true reason=NATIVE_MATH_FIXTURES_PASSED" in result.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "native_math_log_evidence_v1"


def test_decoder_reads_a_preserved_metaeditor_utf16_log(checker):
    data = (ROOT / "docs/testing/evidence/native-core-indicators-2026-10-05/CoreIndicatorsHarness.log").read_bytes()
    text, encoding = checker.decode_log(data)
    assert encoding == "utf-16-le-bom"
    assert re.search(r"(?m)^Result: 0 errors, 0 warnings,", text)
    assert not re.search(r"(?m)^Result: 0 errors, 0 warnings,", "Result: 10 errors, 0 warnings, 1 ms elapsed")
    assert checker.parse_records(text) == []


# Wrapper, suites and parser share one record contract.

def test_wrapper_records_match_parser_grammar_exactly(checker):
    formats = [item for item in _formats(WRAPPER.read_text()) if item.startswith("AGI_NATIVE_MATH_")]
    kinds = {item.split(" ", 1)[0] for item in formats}
    assert kinds == {kind for kind in checker.GRAMMAR if kind.startswith("AGI_NATIVE_MATH_")}
    reject_reasons = set()
    for item in formats:
        assert item.endswith(FLAGS)
        kind, *pairs = item.split(" ")
        grammar = checker.GRAMMAR[kind]
        assert [pair.split("=", 1)[0] for pair in pairs] == [key for key, _ in grammar]
        for pair, (key, expected) in zip(pairs, grammar):
            value = pair.split("=", 1)[1]
            if value in ("%d", "%s"):
                assert not isinstance(expected, str), key
            elif isinstance(expected, str):
                assert value == expected, key
            else:
                assert kind == "AGI_NATIVE_MATH_REJECT" and expected.fullmatch(value)
                reject_reasons.add(value)
    assert reject_reasons == {"TEST_CONTEXT_REQUIRED", "UNEXPECTED_TICK", "TESTER_LIFECYCLE_INVALID"}


def test_suite_summaries_counts_and_stage_order_match_the_parser(checker):
    wrapper = WRAPPER.read_text()
    constants = dict(re.findall(r"const int NATIVE_MATH_EXPECTED_([A-Z_]+)=(\d+);", wrapper))
    tester = wrapper[wrapper.index("double OnTester(void)"):wrapper.index("void OnDeinit(")]
    positions = []
    assert [name for name, _, _ in checker.EXPECTED_STAGES] == [name for name, _, _, _ in SUITES]
    for (name, summary, expected), (_, infix, harness, generated) in zip(checker.EXPECTED_STAGES, SUITES):
        sources = [(MT5_TESTS / harness).read_text()]
        if generated:
            sources.append((MT5_TESTS / generated).read_text())
        code = _code("\n".join(sources))
        calls = len(re.findall(r"\bCheck\s*\(", code)) - len(re.findall(r"\bvoid\s+Check\s*\(", code))
        assert calls == expected == int(constants[re.sub(r"(?<!^)(?=[A-Z])", "_", infix).upper()])
        assert [f for f in _formats(sources[0]) if not f.startswith("ASSERTION")] == [f"{summary} checks=%d failures=%d"]
        assert [key for key, _ in checker.GRAMMAR[summary]] == ["checks", "failures"]
        positions.append(tester.index(f"NativeMathRun{infix}();"))
        assert f'NativeMathRecordStage("{name}",NativeMath{infix}Checks,' in tester
        assert tester.index(f"NativeMathRun{infix}();") < tester.index(f'NativeMathRecordStage("{name}"')
    assert positions == sorted(positions)
    assert int(constants["TOTAL"]) == checker.EXPECTED_TOTAL == TOTAL == 3915
    assert int(constants["STAGES"]) == len(checker.EXPECTED_STAGES) == 4
    assert [tuple(item) for item in checker.EXPECTED_STAGES] == list(STAGE_COUNTS)
    assert checker.expected_sequence()[0]["fields"]["expected_checks"] == checker.EXPECTED_TOTAL


def test_suite_loops_never_repeat_assertions():
    # Static and runtime counts agree on a clean run: loops only copy bars, and
    # every ArraySize-guarded check follows an explicit output_size assertion.
    for _, _, harness, generated in SUITES:
        for name in filter(None, (harness, generated)):
            for line in _code((MT5_TESTS / name).read_text()).splitlines():
                if re.search(r"\b(for|while|do)\b", line):
                    assert re.fullmatch(r"\s*for\(int i=0;i<\d+;i\+\+\) bars\[i\]=source\[i\+\d+\];\s*", line)


# Wrapper source guards: renaming macros, isolation and capabilities.

def test_macro_blocks_rename_each_suite_and_are_fully_undefined():
    directives = [line.strip() for line in WRAPPER.read_text().splitlines()
                  if line.startswith("#") and not line.startswith("#property")]
    expected = []
    for _, infix, harness, _ in SUITES:
        targets = (f"NativeMathRun{infix}", f"NativeMath{infix}Check", f"NativeMath{infix}Checks",
                   f"NativeMath{infix}Failures")
        expected += [f"#define {name} {target}" for name, target in zip(RENAMED, targets)]
        expected.append(f'#include "{harness}"')
        expected += [f"#undef {name}" for name in reversed(RENAMED)]
    assert directives == expected


def test_wrapper_is_an_expert_without_raw_suite_symbols_or_capabilities():
    wrapper = WRAPPER.read_text()
    body = "\n".join(line for line in wrapper.splitlines() if not line.startswith("#"))
    names = _tokens(body)
    assert not names & set(RENAMED)
    assert {"OnInit", "OnTick", "OnTester", "OnDeinit"} <= names
    forbidden = {"OrderSend", "OrderSendAsync", "CTrade", "MqlTradeRequest", "WebRequest", "SendMail",
                 "SendNotification", "TimeCurrent", "TimeGMT", "TimeLocal", "TimeTradeServer", "Sleep", "import",
                 "EventSetTimer", "ExpertRemove", "TerminalClose", "iMA", "iRSI", "iATR", "iCustom", "FrameAdd"}
    assert not names & forbidden
    assert not any(name.startswith(("Order", "Position", "Symbol", "Account", "Terminal", "File", "Socket",
                                    "Copy", "History", "Chart", "GlobalVariable", "Market")) for name in names)
    allowed = re.sub(r"\s+", "", _code(wrapper))
    for clause in ("MQLInfoInteger(MQL_TESTER)!=0", "MQLInfoInteger(MQL_OPTIMIZATION)==0",
                   "MQLInfoInteger(MQL_VISUAL_MODE)==0", "MQLInfoInteger(MQL_FORWARD)==0",
                   "MQLInfoInteger(MQL_FRAME_MODE)==0"):
        assert clause in allowed
    tester = _code(wrapper[wrapper.index("double OnTester(void)"):wrapper.index("void OnDeinit(")])
    assert sorted(set(re.findall(r"return\s+([^;]+);", tester))) == ["0.0", "NativeMathPassed() ? 1.0 : 0.0"]
    tick = _code(wrapper[wrapper.index("void OnTick(void)"):wrapper.index("double OnTester(void)")])
    assert "NativeMathWrapperFailures++" in tick and "Run" not in tick


def _reachable_headers():
    pending = [MT5_TESTS / harness for _, _, harness, _ in SUITES]
    seen, headers = set(), []
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        if path.is_relative_to(INCLUDE_ROOT):
            headers.append(path)
        for quoted, angled in re.findall(r'^#include\s+(?:"([^"]+)"|<([^>]+)>)', path.read_text(), re.M):
            target = (path.parent / quoted) if quoted else (INCLUDE_ROOT / angled)
            assert target.is_file(), target
            pending.append(target)
    return sorted(headers)


def test_shared_headers_are_guarded_and_untouched_by_renaming_macros():
    headers = _reachable_headers()
    assert {path.relative_to(INCLUDE_ROOT).as_posix() for path in headers} >= {
        "Core/ObservationPolicy.mqh", "Core/ClosedBarWindow.mqh", "Core/CoreIndicators.mqh"}
    for path in headers:
        source = path.read_text(encoding="utf-8-sig")
        guard = re.match(r"\s*(?://[^\n]*\n\s*)*#ifndef (\w+)\s*\n#define (\w+)", source)
        assert guard and guard.group(1) == guard.group(2), path
        assert source.rstrip().endswith("#endif"), path
        assert not _tokens(source) & set(RENAMED), path


def test_suite_definitions_do_not_collide_inside_the_combined_translation_unit():
    definition = re.compile(r"^(?:[A-Za-z_][A-Za-z_0-9]*\s+)+&?([A-Za-z_][A-Za-z_0-9]*)\s*\(", re.M)
    variable = re.compile(r"^(?:const\s+)?(?:int|double|bool|string|long|datetime)\s+([A-Za-z_][A-Za-z_0-9]*)\s*[=;\[]", re.M)
    owned = []
    for _, _, harness, generated in SUITES:
        code = _code("\n".join((MT5_TESTS / name).read_text() for name in filter(None, (harness, generated))))
        assert set(variable.findall(code)) == {"checks", "failures"}
        defined = set(definition.findall(code))
        assert {"OnStart", "Check"} <= defined
        owned.append(defined - set(RENAMED))
    owned.append(set(definition.findall(_code(WRAPPER.read_text()))) - {"OnInit", "OnTick", "OnTester", "OnDeinit"})
    assert "RunGeneratedClosedBarFixtures" in owned[1] and "RunGeneratedCoreIndicatorFixtures" in owned[2]
    assert "RunGeneratedRiskGateFixtures" in owned[3] and "NativeMathPassed" in owned[-1]
    for index, names in enumerate(owned):
        for other in owned[index + 1:]:
            assert not names & other


def test_wrapper_header_hashes_bind_the_reviewed_sources_modulo_line_endings():
    recorded = dict((name, digest) for name, digest in
                    re.findall(r"^// (\S+\.mq[5h]) ([0-9a-f]{64})$", WRAPPER.read_text(), re.M))
    assert set(recorded) == {name for _, _, harness, generated in SUITES for name in (harness, generated) if name}
    for name, digest in recorded.items():
        data = (MT5_TESTS / name).read_bytes().replace(b"\r\n", b"\n")
        # A Windows checkout may have produced CRLF bytes when the comment was written.
        assert digest in {sha256(data).hexdigest(), sha256(data.replace(b"\n", b"\r\n")).hexdigest()}, name


# Runner guards: staging, bound configuration, process ownership and verdict.

def test_runner_stages_exactly_the_wrapper_include_graph():
    runner = RUNNER.read_text()
    listed = re.search(r"\$fixtureNames = @\(([^)]*)\)", runner).group(1)
    names = set(re.findall(r"'([^']+)'", listed))
    quoted = {WRAPPER.name}
    for path in [WRAPPER] + [MT5_TESTS / harness for _, _, harness, _ in SUITES]:
        quoted |= set(re.findall(r'^#include\s+"([^"]+)"', path.read_text(), re.M))
    assert names == quoted
    assert "Join-Path $projectRoot 'src\\mt5\\Include'" in runner
    assert "Expert=NativeMathHarness.ex5" in _runner_config()


def test_runner_configuration_is_math_only_without_account_or_remote_agents(checker, tmp_path):
    config = tmp_path / "native-math.ini"
    config.write_text(_runner_config(), encoding="utf-8")
    result = checker.check_config(config)
    assert result["valid"] is True and result["model"] == 3
    assert not re.search(r"(?im)^\s*(login|password|server|certpassword)\s*=", _runner_config())


def test_runner_requires_powershell_7_before_creating_any_staging():
    runner = RUNNER.read_text()
    assert runner.splitlines()[0] == "#Requires -Version 7.0"
    assert runner.index("GetRelativePath") > runner.index("#Requires -Version 7.0")


def test_runner_requires_fresh_temp_staging_and_owned_processes_only():
    runner = RUNNER.read_text()
    assert "if (-not $stage.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase))" in runner
    assert "if (Test-Path -LiteralPath $stage) { throw 'Staging must not already exist.' }" in runner
    assert "Stop-Process -Id $owned.Id -Force -ErrorAction SilentlyContinue" in runner
    parser_call = runner[runner.index("$parserExit = $null"):runner.index("$manifest.parser_exit_code = $parserExit")]
    assert parser_call.lstrip("$parserExit = $null").count("try {") == 1 and "} catch {" in parser_call
    assert "$_.ExecutablePath -in $ownedExecutablePaths" in runner
    lowered = runner.lower()
    for forbidden in ("stop-process -name", "taskkill", "get-process -name", "netsh", "new-netfirewallrule",
                      "set-netfirewall", "new-service", "sc.exe", "reg add", "set-itemproperty", "schtasks",
                      "register-scheduledtask", "metaquotes", "accounts.dat", "servers.dat", "login=", "password="):
        assert forbidden not in lowered, forbidden
    assert "/portable" in runner and "-WindowStyle Hidden" in runner


def test_runner_verdict_requires_clean_compile_parser_and_bindings():
    runner = RUNNER.read_text()
    assert "-notmatch '(?m)^Result: 0 errors, 0 warnings,'" in runner
    assert "-notmatch '0 errors, 0 warnings'" not in runner
    assert "$parser = Join-Path $PSScriptRoot 'check_native_math_logs.py'" in runner and SCRIPT.is_file()
    assert "& py -3.14 -I -S -B $parser --stage $stage --output $logEvidencePath" in runner
    verdict = re.search(r"\$manifest\.passed = (.*?)\n\$manifest\.status", runner, re.S).group(1)
    for clause in ("$manifest.terminal_started", "$manifest.terminal_exited", "-not $manifest.timed_out",
                   "$manifest.terminal_exit_code -eq 0", "$manifest.cleanup_verified", "$bindingsUnchanged",
                   "$parserExit -eq 0", "$manifest.log_evidence_passed"):
        assert clause in verdict
    assert "$manifest.log_evidence_passed = $null -ne $evidence -and $evidence.passed -eq $true" in runner
    # The first failed gate names the reason; a parser pass reason never labels a failed run.
    reason = re.search(r"\$manifest\.reason = \$\(if (.*?)\n\$manifest\.status", runner, re.S).group(1)
    ordered = ["'TERMINAL_EXIT_CODE_'", "'CLEANUP_NOT_VERIFIED'", "'LAUNCH_BINDINGS_CHANGED'",
               "'PARSER_EVIDENCE_MISSING'", "'PARSER_EXIT_CODE_'", "[string]$evidence.reason"]
    assert [reason.index(item) for item in ordered] == sorted(reason.index(item) for item in ordered)
    assert runner.index("$manifest.passed =") < runner.index("$manifest.reason = $(if ($manifest.reason -in")
    for flag in ("execution_authorized", "full_pipeline_verified", "promotion_eligible", "account_or_profile_copied",
                 "credentials_configured", "network_isolation_verified"):
        assert re.search(rf"\b{flag} = \$false\b", runner), flag


def test_powershell_scripts_never_interpolate_a_drive_qualified_name_by_accident():
    # "$Level: text" parses as a drive-qualified variable and makes the whole
    # script unparseable (scripts/healthcheck.ps1 had this); use "${Level}: text".
    scopes = {"env", "script", "global", "local", "using", "private", "variable", "function"}
    offenders = []
    for path in sorted((ROOT / "scripts").glob("*.ps1")):
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            for literal in re.findall(r'"(?:`.|[^"`])*"', line):
                for name in re.findall(r"(?<![`$])\$([A-Za-z_][A-Za-z0-9_]*):(?![A-Za-z0-9_{:\\/])", literal):
                    if name.lower() not in scopes:
                        offenders.append(f"{path.name}:{number}")
    assert offenders == []

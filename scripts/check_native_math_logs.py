"""Fail-closed verification of NativeMathHarness Tester logs; never a trading test.

Reads only the staging directory created by ``run_native_math_harness.ps1``.
Every ``.log`` file in that staging (except the wrapper compile log) is a
candidate source. Files are grouped by directory, so a daily log rotation
inside one directory remains one logical source. Every source that contains a
native math record must hold the identical record sequence; a partial mirror,
a duplicate run, a rejection, an assertion failure, a count discrepancy or a
missing completion record is never a pass. The evidence written here contains
stage-relative paths only and never authorizes execution or promotion.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

SCHEMA_VERSION = "native_math_log_evidence_v1"
PARSER_VERSION = "native_math_log_parser_v1"
WRAPPER_VERSION = "native_math_harness_v2"
REQUIRED_MODEL = 3
# (wrapper stage name, suite summary record, fixed assertion count)
EXPECTED_STAGES = (
    ("observer", "NATIVE_POLICY_HARNESS", 31),
    ("closed_bars", "NATIVE_CLOSED_BAR_HARNESS", 1103),
    ("core_indicators", "NATIVE_CORE_INDICATORS_HARNESS", 1348),
    ("risk_gate", "NATIVE_RISK_GATE_HARNESS", 1433),
)
EXPECTED_TOTAL = sum(count for _, _, count in EXPECTED_STAGES)
COMPILE_LOG = "MQL5/Experts/NativeMathHarness/NativeMathHarness.log"
AGENT_LOG_DIRECTORY = re.compile(r"Tester/Agent-[^/]+/logs", re.IGNORECASE)
CONFIG_NAME = "native-math.ini"
MAX_LOG_FILES = 256
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_RECORDS = 200
MAX_FAILURE_LABELS = 100
MAX_LABEL_CHARS = 200
PASS_REASON = "NATIVE_MATH_FIXTURES_PASSED"

INT = re.compile(r"-?(?:0|[1-9][0-9]{0,9})")
STAGE_NAME = re.compile(r"[a-z_]{1,32}")
REJECT_REASON = re.compile(r"[A-Z_]{1,64}")
# Exact key order and value grammar of every PrintFormat/Print in the wrapper
# and suite summaries. A literal string value must match byte for byte.
GRAMMAR: dict[str, tuple[tuple[str, re.Pattern[str] | str], ...]] = {
    "AGI_NATIVE_MATH_BEGIN": (
        ("version", WRAPPER_VERSION), ("expected_checks", INT), ("model_required", str(REQUIRED_MODEL)),
        ("model_verified_in_mql", "false"), ("execution_authorized", "false"), ("full_pipeline_verified", "false"),
    ),
    "AGI_NATIVE_MATH_STAGE": (
        ("name", STAGE_NAME), ("checks", INT), ("failures", INT), ("expected_checks", INT), ("accepted", INT),
        ("execution_authorized", "false"), ("full_pipeline_verified", "false"),
    ),
    "AGI_NATIVE_MATH_TOTAL": (
        ("checks", INT), ("failures", INT), ("ticks", INT), ("accepted", INT), ("wrapper_failures", INT),
        ("stages", INT), ("expected_checks", INT), ("execution_authorized", "false"), ("full_pipeline_verified", "false"),
    ),
    "AGI_NATIVE_MATH_COMPLETE": (
        ("checks", INT), ("failures", INT), ("ticks", INT), ("accepted", INT), ("reason", INT), ("completed", INT),
        ("wrapper_failures", INT), ("stages", INT), ("expected_checks", INT), ("model_verified_in_mql", "false"),
        ("execution_authorized", "false"), ("full_pipeline_verified", "false"),
    ),
    "AGI_NATIVE_MATH_REJECT": (
        ("reason", REJECT_REASON), ("execution_authorized", "false"), ("full_pipeline_verified", "false"),
    ),
    "NATIVE_POLICY_HARNESS": (("checks", INT), ("failures", INT)),
    "NATIVE_CLOSED_BAR_HARNESS": (("checks", INT), ("failures", INT)),
    "NATIVE_CORE_INDICATORS_HARNESS": (("checks", INT), ("failures", INT)),
    "NATIVE_RISK_GATE_HARNESS": (("checks", INT), ("failures", INT)),
}
ASSERTION_TOKEN = "ASSERTION_FAILED:"
# A record starts at the beginning of a line or after whitespace, never inside
# another word. Unknown AGI_NATIVE_MATH_* kinds are captured and rejected.
TOKEN = re.compile(
    r"(?:(?<=\s)|^)(AGI_NATIVE_MATH_[A-Z_]*|NATIVE_POLICY_HARNESS|NATIVE_CLOSED_BAR_HARNESS"
    r"|NATIVE_CORE_INDICATORS_HARNESS|NATIVE_RISK_GATE_HARNESS|ASSERTION_FAILED:)"
)
ANY = object()  # expected value wildcard (deinitialization reason only)

REQUIRED_CONFIG = {
    "Experts": {"Enabled": "0", "AllowLiveTrading": "0", "AllowDllImport": "0"},
    "Tester": {
        "Expert": "NativeMathHarness.ex5", "Model": str(REQUIRED_MODEL), "Optimization": "0", "ForwardMode": "0",
        "Visual": "0", "UseLocal": "1", "UseRemote": "0", "UseCloud": "0", "ShutdownTerminal": "1",
    },
}
FORBIDDEN_CONFIG_KEYS = frozenset({"login", "password", "server", "certpassword"})

LIMITS = (
    "Synthetic fixtures only; no broker data, account, quote or real clock is verified.",
    "Model=3 is checked in the bound configuration; the wrapper cannot read it in MQL.",
    "A pass does not verify allocation failure, financial performance or execution.",
    "Strategy Promotion Gate and broker execution remain blocked.",
)


class EvidenceError(Exception):
    """A condition that prevents any trustworthy log conclusion."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def parse_record_line(line: str) -> dict | None:
    """Return the record on ``line``, ``None`` when it has none; raise if malformed."""

    match = TOKEN.search(line)
    if match is None:
        return None
    kind = match.group(1)
    rest = line[match.end():]
    if kind == ASSERTION_TOKEN:
        label = rest[1:] if rest.startswith(" ") else rest
        return {"kind": "ASSERTION_FAILED", "label": label[:MAX_LABEL_CHARS]}
    grammar = GRAMMAR.get(kind)
    if grammar is None:
        raise EvidenceError("MALFORMED_RECORD", "unknown record kind " + kind[:64])
    if not rest.startswith(" "):
        raise EvidenceError("MALFORMED_RECORD", kind + " has no fields")
    tokens = rest[1:].split(" ")
    if len(tokens) != len(grammar):
        raise EvidenceError("MALFORMED_RECORD", kind + " field count differs")
    fields: dict[str, int | str] = {}
    for token, (key, expected) in zip(tokens, grammar):
        name, separator, value = token.partition("=")
        if not separator or name != key:
            raise EvidenceError("MALFORMED_RECORD", kind + " field order differs at " + key)
        if isinstance(expected, str):
            if value != expected:
                raise EvidenceError("MALFORMED_RECORD", kind + " literal differs at " + key)
            fields[key] = value
        elif expected.fullmatch(value) is None:
            raise EvidenceError("MALFORMED_RECORD", kind + " invalid value at " + key)
        elif expected is INT:
            number = int(value)
            if not -(2**31) <= number < 2**31:
                raise EvidenceError("MALFORMED_RECORD", kind + " integer out of range at " + key)
            fields[key] = number
        else:
            fields[key] = value
    return {"kind": kind, "fields": fields}


def parse_records(text: str) -> list[dict]:
    records = []
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw[:-1] if raw.endswith("\r") else raw
        try:
            record = parse_record_line(line)
        except EvidenceError as error:
            raise EvidenceError(error.reason, f"line {number}: {error.detail}") from None
        if record is not None:
            records.append(record)
    return records


def decode_log(data: bytes) -> tuple[str, str]:
    """Strictly decode an MT5 log; UTF-16LE with BOM is the documented terminal form."""

    try:
        if data.startswith(b"\xff\xfe"):
            return data[2:].decode("utf-16-le"), "utf-16-le-bom"
        if data.startswith(b"\xfe\xff"):
            return data[2:].decode("utf-16-be"), "utf-16-be-bom"
        if data.startswith(b"\xef\xbb\xbf"):
            return data[3:].decode("utf-8"), "utf-8-bom"
        if b"\x00" in data:
            if len(data) % 2:
                raise EvidenceError("LOG_DECODE_ERROR", "odd byte count for UTF-16")
            return data.decode("utf-16-le"), "utf-16-le"
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        raise EvidenceError("LOG_DECODE_ERROR", "strict decoding failed") from None


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or (isjunction is not None and isjunction(path))


def _walk_error(error: OSError) -> None:
    # os.walk skips unreadable directories silently; a hidden source is not absent.
    raise EvidenceError("LOG_DIRECTORY_UNREADABLE", type(error).__name__)


def discover_log_files(stage: Path) -> list[Path]:
    found = []
    for root, directories, names in os.walk(stage, onerror=_walk_error, followlinks=False):
        directories.sort()
        for name in directories:
            if _is_link(Path(root, name)):
                raise EvidenceError("LOG_SOURCE_LINK", Path(root, name).relative_to(stage).as_posix())
        for name in sorted(names):
            if not name.lower().endswith(".log"):
                continue
            path = Path(root, name)
            relative = path.relative_to(stage).as_posix()
            if relative.casefold() == COMPILE_LOG.casefold():
                continue
            if _is_link(path) or not path.is_file():
                raise EvidenceError("LOG_SOURCE_LINK", relative)
            found.append(path)
            if len(found) > MAX_LOG_FILES:
                raise EvidenceError("TOO_MANY_LOG_FILES", str(MAX_LOG_FILES))
    return found


def read_sources(stage: Path) -> list[dict]:
    """Group candidate logs by directory; return sources with their records."""

    groups: dict[str, list[Path]] = {}
    for path in discover_log_files(stage):
        groups.setdefault(path.parent.relative_to(stage).as_posix(), []).append(path)
    sources = []
    for directory in sorted(groups):
        files, records = [], []
        for path in sorted(groups[directory], key=lambda item: item.name):
            relative = path.relative_to(stage).as_posix()
            try:
                if path.stat().st_size > MAX_LOG_BYTES:
                    raise EvidenceError("LOG_TOO_LARGE", relative)
                data = path.read_bytes()
            except OSError as error:
                raise EvidenceError("LOG_UNREADABLE", f"{relative}: {type(error).__name__}") from None
            if len(data) > MAX_LOG_BYTES:
                raise EvidenceError("LOG_TOO_LARGE", relative)
            try:
                text, encoding = decode_log(data)
                file_records = parse_records(text)
            except EvidenceError as error:
                raise EvidenceError(error.reason, f"{relative}: {error.detail}") from None
            files.append({"path": relative, "bytes": len(data), "sha256": sha256(data).hexdigest(),
                          "encoding": encoding, "record_count": len(file_records)})
            records.extend(file_records)
        sources.append({"directory": directory, "files": files, "records": records})
    return sources


def check_config(path: Path) -> dict:
    """Verify the bound Tester configuration is math-only and carries no account."""

    result = {"path": CONFIG_NAME, "present": path.is_file(), "sha256": None, "valid": False, "reason": None,
              "model": None}
    if not result["present"] or _is_link(path):
        result["reason"] = "CONFIG_MISSING"
        return result
    try:
        data = path.read_bytes()
    except OSError:
        result["reason"] = "CONFIG_UNREADABLE"
        return result
    result["sha256"] = sha256(data).hexdigest()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        result["reason"] = "CONFIG_DECODE_ERROR"
        return result
    # Sections and keys are compared case-insensitively, so a differently cased
    # duplicate cannot shadow a required value for a case-insensitive reader.
    sections: dict[str, dict[str, str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().casefold()
            if not current or current in sections:
                result["reason"] = "CONFIG_SECTION_INVALID"
                return result
            sections[current] = {}
            continue
        key, separator, value = line.partition("=")
        key = key.strip().casefold()
        if current is None or not separator or not key or key in sections[current]:
            result["reason"] = "CONFIG_ENTRY_INVALID"
            return result
        if key in FORBIDDEN_CONFIG_KEYS:
            result["reason"] = "CONFIG_ACCOUNT_ENTRY_FORBIDDEN"
            return result
        sections[current][key] = value.strip()
    model = sections.get("tester", {}).get("model")
    result["model"] = int(model) if model is not None and INT.fullmatch(model) else None
    for section, required in REQUIRED_CONFIG.items():
        for key, value in required.items():
            if sections.get(section.casefold(), {}).get(key.casefold()) != value:
                result["reason"] = f"CONFIG_{section.upper()}_{key.upper()}_INVALID"
                return result
    result["valid"] = True
    result["reason"] = "CONFIG_MATH_ONLY"
    return result


def expected_sequence() -> list[dict]:
    flags = {"execution_authorized": "false", "full_pipeline_verified": "false"}
    sequence = [{"kind": "AGI_NATIVE_MATH_BEGIN", "fields": {
        "version": WRAPPER_VERSION, "expected_checks": EXPECTED_TOTAL, "model_required": str(REQUIRED_MODEL),
        "model_verified_in_mql": "false", **flags}}]
    for name, summary, count in EXPECTED_STAGES:
        sequence.append({"kind": summary, "fields": {"checks": count, "failures": 0}})
        sequence.append({"kind": "AGI_NATIVE_MATH_STAGE", "fields": {
            "name": name, "checks": count, "failures": 0, "expected_checks": count, "accepted": 1, **flags}})
    totals = {"checks": EXPECTED_TOTAL, "failures": 0, "ticks": 0, "accepted": 1}
    sequence.append({"kind": "AGI_NATIVE_MATH_TOTAL", "fields": {
        **totals, "wrapper_failures": 0, "stages": len(EXPECTED_STAGES), "expected_checks": EXPECTED_TOTAL, **flags}})
    sequence.append({"kind": "AGI_NATIVE_MATH_COMPLETE", "fields": {
        **totals, "reason": ANY, "completed": 1, "wrapper_failures": 0, "stages": len(EXPECTED_STAGES),
        "expected_checks": EXPECTED_TOTAL, "model_verified_in_mql": "false", **flags}})
    return sequence


def _matches(expected: dict, observed: dict) -> bool:
    if expected["kind"] != observed["kind"] or "fields" not in observed:
        return False
    fields = observed["fields"]
    if set(fields) != set(expected["fields"]):
        return False
    return all(value is ANY or fields[key] == value for key, value in expected["fields"].items())


def _printable(record: dict | None) -> dict | None:
    if record is None or "fields" not in record:
        return record
    return {"kind": record["kind"],
            "fields": {key: ("ANY_INTEGER" if value is ANY else value) for key, value in record["fields"].items()}}


def base_evidence() -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "parser_version": PARSER_VERSION,
        "scope": "SYNTHETIC_NATIVE_FIXTURES_ONLY", "passed": False, "reason": "NOT_EVALUATED", "detail": "",
        "expected": {"wrapper_version": WRAPPER_VERSION, "model": REQUIRED_MODEL, "total_checks": EXPECTED_TOTAL,
                     "stages": [{"name": name, "summary": summary, "checks": count}
                                for name, summary, count in EXPECTED_STAGES]},
        "config": None, "sources": [], "record_count": 0, "records": [], "records_truncated": False,
        "assertion_failures": {"count": 0, "labels": []}, "reject_reasons": [], "first_mismatch": None,
        "deinit_reason": None, "model_verified_in_mql": False,
        "execution_authorized": False, "full_pipeline_verified": False, "promotion_eligible": False,
        "limits": list(LIMITS),
    }


def evaluate_stage(stage: Path) -> dict:
    """Return the evidence document; ``passed`` is true only for one exact clean run."""

    evidence = base_evidence()
    if not stage.is_dir() or _is_link(stage):
        evidence["reason"] = "STAGE_MISSING"
        return evidence
    config = check_config(stage / CONFIG_NAME)
    evidence["config"] = config
    try:
        sources = read_sources(stage)
    except EvidenceError as error:
        evidence["reason"], evidence["detail"] = error.reason, error.detail
        return evidence
    with_records = [source for source in sources if source["records"]]
    evidence["sources"] = [{"directory": source["directory"], "files": source["files"],
                            "record_count": len(source["records"])} for source in sources]
    if not config["valid"]:
        evidence["reason"] = "TESTER_CONFIG_INVALID"
        evidence["detail"] = config["reason"]
        return evidence
    if not with_records:
        evidence["reason"] = "NATIVE_MATH_RECORDS_MISSING"
        return evidence
    records = with_records[0]["records"]
    evidence["record_count"] = len(records)
    evidence["records"] = [_printable(record) for record in records[:MAX_EVIDENCE_RECORDS]]
    evidence["records_truncated"] = len(records) > MAX_EVIDENCE_RECORDS
    failures = [record["label"] for record in records if record["kind"] == "ASSERTION_FAILED"]
    evidence["assertion_failures"] = {"count": len(failures), "labels": failures[:MAX_FAILURE_LABELS]}
    evidence["reject_reasons"] = [record["fields"]["reason"] for record in records
                                  if record["kind"] == "AGI_NATIVE_MATH_REJECT"]
    completes = [record for record in records if record["kind"] == "AGI_NATIVE_MATH_COMPLETE"]
    if len(completes) == 1:
        evidence["deinit_reason"] = completes[0]["fields"]["reason"]
    agents = [source["directory"] for source in with_records if AGENT_LOG_DIRECTORY.fullmatch(source["directory"])]
    if len(agents) > 1:
        # Local agents never mirror one another: records from two agents are two runs.
        evidence["reason"] = "DUPLICATE_AGENT_RUN"
        evidence["detail"] = ", ".join(agents)
        return evidence
    for source in with_records[1:]:
        if source["records"] != records:
            evidence["reason"] = "LOG_SOURCES_INCONSISTENT"
            evidence["detail"] = with_records[0]["directory"] + " != " + source["directory"]
            return evidence
    if evidence["reject_reasons"]:
        evidence["reason"] = "WRAPPER_REJECTED"
        return evidence
    if failures:
        evidence["reason"] = "ASSERTION_FAILURES"
        return evidence
    if not completes:
        evidence["reason"] = "COMPLETION_RECORD_MISSING"
        return evidence
    expected = expected_sequence()
    for index in range(max(len(expected), len(records))):
        wanted = expected[index] if index < len(expected) else None
        seen = records[index] if index < len(records) else None
        if wanted is None or seen is None or not _matches(wanted, seen):
            evidence["reason"] = "RECORD_SEQUENCE_MISMATCH"
            evidence["first_mismatch"] = {"index": index, "expected": _printable(wanted), "observed": _printable(seen)}
            return evidence
    evidence["passed"] = True
    evidence["reason"] = PASS_REASON
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    # absolute(), not resolve(): a linked stage must reach the link check.
    evidence = evaluate_stage(args.stage.absolute())
    payload = json.dumps(evidence, indent=2, ensure_ascii=True) + "\n"
    try:
        # Never overwrite earlier evidence; the runner always supplies a new path.
        with open(args.output, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except OSError as error:
        print(f"native math evidence not written: {type(error).__name__}", file=sys.stderr)
        return 2
    print(f"native math log evidence: passed={str(evidence['passed']).lower()} reason={evidence['reason']}")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

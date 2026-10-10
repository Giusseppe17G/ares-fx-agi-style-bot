"""Fail-closed lint of the tracked Markdown documentation; never a trading test.

Checks every Markdown file in the git index of ``--root``: it must decode
(UTF-8, or UTF-16 with a BOM), keep its code fences balanced, point relative
links and backticked repository paths at tracked files or directories, and
carry no local home directories or secret-like values (AGENTS.md rule 10).
Fenced code is excluded from link and path checks, never from secret checks.
Findings are printed as JSON with repository-relative paths only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote

LINT_VERSION = "docs_lint_v1"
MAX_DOC_BYTES = 8 * 1024 * 1024
MAX_FINDINGS = 200

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"\n]*\")?\s*\)")
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
URI_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
# Placeholders, globs and shell variables are prose, not repository paths.
NOT_A_PATH = re.compile(r"[*?\[\]<>{}$%|]|\.\.\.")
LINE_SUFFIX = re.compile(r"(?::\d+)+$")
# Runtime state root: docs name its gitignored outputs (logs, reports, sqlite),
# and package-relative module names such as data/indicators.py collide with it.
RUNTIME_ROOTS = frozenset({"data"})
GENERIC_USERS = frozenset({"user", "administrator", "runner", "username"})
PLACEHOLDER_USER = re.compile(r"<[^<>]+>")
LOCAL_PATHS = (
    re.compile(r"(?<![\w./-])/(?:home|Users)/([^/\s`'\"()]+)"),
    re.compile(r"(?i)(?<![\w])[A-Z]:\\Users\\([^\\\s`'\"()]+)"),
)
FIXED_LOCAL_PATHS = re.compile(r"(?<![\w./-])(?:/root/|/tmp/claude)")
SECRETS = (
    ("telegram_bot_token", re.compile(r"\b\d{6,12}:AA[A-Za-z0-9_-]{30,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("anthropic_or_openai_key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}")),
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
ALLOWED_EMAIL_DOMAINS = frozenset({"example.com", "example.org", "example.net"})


class LintError(Exception):
    """The lint could not inspect the repository; never a pass."""


def _git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LintError("GIT_UNAVAILABLE") from exc
    if result.returncode != 0:
        raise LintError("GIT_COMMAND_FAILED")
    return result.stdout


def tracked_files(root: Path) -> list[str]:
    toplevel = _git(root, "rev-parse", "--show-toplevel").decode("utf-8", "surrogateescape").strip()
    if Path(toplevel).resolve() != root.resolve():
        raise LintError("NOT_REPOSITORY_ROOT")
    listing = _git(root, "ls-files", "-z", "--cached")
    names = [item.decode("utf-8", "surrogateescape") for item in listing.split(b"\0") if item]
    if not names:
        raise LintError("NO_TRACKED_FILES")
    return names


def decode(raw: bytes) -> str | None:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def split_fences(text: str) -> tuple[list[tuple[int, str, bool]], bool]:
    """Return (line number, line, inside fenced code) and whether fences balance."""

    lines: list[tuple[int, str, bool]] = []
    opener: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        match = FENCE.match(line)
        if opener is None and match:
            opener = match.group(1)
            lines.append((number, line, True))
        elif opener is not None:
            lines.append((number, line, True))
            if match and match.group(1)[0] == opener[0] and len(match.group(1)) >= len(opener) \
                    and not line.strip()[len(match.group(1)):].strip():
                opener = None
        else:
            lines.append((number, line, False))
    return lines, opener is None


class Repository:
    def __init__(self, files: list[str]) -> None:
        self.files = frozenset(files)
        self.directories = frozenset(str(parent) for name in files for parent in PurePosixPath(name).parents)
        self.top_level = frozenset(name.split("/", 1)[0] for name in files if "/" in name)

    def exists(self, path: str) -> bool:
        path = path.rstrip("/")
        return path in self.files or path in self.directories


def _resolve(document: str, target: str) -> str | None:
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    if target.startswith("/"):
        joined = target.lstrip("/")
    else:
        joined = posixpath.join(posixpath.dirname(document), target)
    normalized = posixpath.normpath(joined)
    return "<outside>" if normalized == ".." or normalized.startswith("../") else normalized


def lint_document(name: str, text: str, repository: Repository) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []

    def report(code: str, line: int, detail: str) -> None:
        findings.append({"code": code, "path": name, "line": line, "detail": detail[:200]})

    lines, balanced = split_fences(text)
    if not balanced:
        report("DOC_UNBALANCED_FENCE", len(lines), "code fence opened but never closed")
    for number, line, fenced in lines:
        for pattern in LOCAL_PATHS:
            for match in pattern.finditer(line):
                user = match.group(1)
                if user.lower() not in GENERIC_USERS and not PLACEHOLDER_USER.fullmatch(user):
                    report("DOC_LOCAL_PATH", number, match.group(0))
        for match in FIXED_LOCAL_PATHS.finditer(line):
            report("DOC_LOCAL_PATH", number, match.group(0))
        for label, pattern in SECRETS:
            if pattern.search(line):
                report("DOC_SECRET_LIKE", number, label)
        for match in EMAIL.finditer(line):
            if match.group(1).lower() not in ALLOWED_EMAIL_DOMAINS:
                report("DOC_EMAIL", number, "email address")
        if fenced:
            continue
        prose = CODE_SPAN.sub(lambda span: " " * len(span.group(0)), line)
        targets = [match.group(1) for match in INLINE_LINK.finditer(prose)]
        reference = REFERENCE_LINK.match(prose)
        if reference:
            targets.append(reference.group(1))
        for target in targets:
            if URI_SCHEME.match(target) or target.startswith(("#", "//")):
                continue
            resolved = _resolve(name, target)
            if resolved is not None and not repository.exists(resolved):
                report("DOC_BROKEN_LINK", number, target)
        for match in CODE_SPAN.finditer(line):
            candidate = LINE_SUFFIX.sub("", match.group(1).strip().rstrip(".,;:"))
            if "/" not in candidate or " " in candidate or NOT_A_PATH.search(candidate):
                continue
            root_name = candidate.split("/", 1)[0]
            if root_name not in repository.top_level or root_name in RUNTIME_ROOTS:
                continue
            if not repository.exists(posixpath.normpath(candidate)):
                report("DOC_MISSING_PATH", number, candidate)
    return findings


def lint_repository(root: Path) -> dict[str, object]:
    files = tracked_files(root)
    repository = Repository(files)
    documents = sorted(name for name in files if name.lower().endswith(".md"))
    findings: list[dict[str, object]] = []
    for name in documents:
        path = root / name
        try:
            if path.is_symlink() or not path.is_file():
                findings.append({"code": "DOC_NOT_REGULAR_FILE", "path": name, "line": 0, "detail": ""})
                continue
            raw = path.read_bytes()
        except OSError:
            findings.append({"code": "DOC_UNREADABLE", "path": name, "line": 0, "detail": ""})
            continue
        if len(raw) > MAX_DOC_BYTES:
            findings.append({"code": "DOC_TOO_LARGE", "path": name, "line": 0, "detail": str(len(raw))})
            continue
        text = decode(raw)
        if text is None:
            findings.append({"code": "DOC_NOT_DECODABLE", "path": name, "line": 0, "detail": ""})
            continue
        findings.extend(lint_document(name, text, repository))
    return {
        "lint_version": LINT_VERSION,
        "status": "PASSED" if not findings else "FAILED",
        "documents": len(documents),
        "finding_count": len(findings),
        "findings": findings[:MAX_FINDINGS],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        report = lint_repository(args.root.resolve())
    except LintError as exc:
        print(json.dumps({"lint_version": LINT_VERSION, "status": "ERROR", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())

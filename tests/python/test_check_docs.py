"""Documentation lint on synthetic git repositories; never a trading test."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_docs.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required to list tracked files")


def _run(root: Path) -> tuple[int, dict]:
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(SCRIPT), "--root", str(root)],
                            capture_output=True, text=True, timeout=120)
    assert str(root) not in result.stdout
    return result.returncode, json.loads(result.stdout)


def _repo(tmp_path: Path, files: dict[str, str | bytes], untracked: dict[str, str] | None = None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    for name, content in (untracked or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(content, encoding="utf-8")
    return root


def _codes(report: dict) -> list[tuple[str, str]]:
    return [(item["code"], item["detail"]) for item in report["findings"]]


def test_repository_documentation_passes():
    code, report = _run(ROOT)
    assert code == 0 and report["status"] == "PASSED", report["findings"][:10]
    assert report["documents"] > 100


def test_clean_synthetic_repository_passes(tmp_path):
    root = _repo(tmp_path, {
        "scripts/run.py": "", "docs/guide.md": "# Guide\n",
        "README.md": "\n".join([
            "See [guide](docs/guide.md), [section](docs/guide.md#guide), [docs](docs/) and [top](#readme).",
            "External [site](https://example.org/x) and mail [me](mailto:ops@example.com).",
            "Run `scripts/run.py:12`, `scripts/run.py`, `docs/` and `data/reports/out.json`.",
            "Placeholders `docs/<name>.md`, `docs/decisions/*.md` and `scripts/run.py --flag` are prose.",
            "Windows home `C:\\Users\\Administrator\\MT5`, `/home/runner/work` and `/home/<user>/repo` are generic.",
            "```bash", "[ignored](missing.md) `scripts/missing.py`", "```",
            "Code span `[not a link](missing.md)` is not a link.",
            "[ref]: docs/guide.md",
        ]) + "\n",
    })
    code, report = _run(root)
    assert code == 0 and report == {"documents": 2, "finding_count": 0, "findings": [],
                                    "lint_version": "docs_lint_v1", "status": "PASSED"}


def test_broken_links_and_paths_fail_with_line_numbers(tmp_path):
    root = _repo(tmp_path, {
        "scripts/run.py": "",
        "docs/a.md": "ok\n[gone](missing.md)\n[up](../../outside.md)\n![img](img/x.png)\n"
                     "`scripts/missing.py` and `scripts/draft.py`\n[ref]: nowhere.md\n",
    }, untracked={"scripts/draft.py": ""})
    code, report = _run(root)
    assert code == 1 and report["status"] == "FAILED"
    found = {(item["code"], item["detail"], item["line"]) for item in report["findings"]}
    assert found == {
        ("DOC_BROKEN_LINK", "missing.md", 2), ("DOC_BROKEN_LINK", "../../outside.md", 3),
        ("DOC_BROKEN_LINK", "img/x.png", 4), ("DOC_MISSING_PATH", "scripts/missing.py", 5),
        ("DOC_MISSING_PATH", "scripts/draft.py", 5), ("DOC_BROKEN_LINK", "nowhere.md", 6),
    }
    assert all(item["path"] == "docs/a.md" for item in report["findings"])


def test_unbalanced_fence_fails(tmp_path):
    root = _repo(tmp_path, {"a.md": "text\n````\ncode\n```\nstill code\n"})
    code, report = _run(root)
    assert code == 1 and _codes(report) == [("DOC_UNBALANCED_FENCE", "code fence opened but never closed")]


def test_local_paths_are_rejected_even_inside_code(tmp_path):
    root = _repo(tmp_path, {"a.md": "\n".join([
        "`/home/alice/repo`", "```", "C:\\Users\\alice\\AppData", "cd /root/.config", "```",
        "scratch /tmp/claude-0/x", "/Users/bob/Library", "ok /tmp/report.json",
    ]) + "\n"})
    code, report = _run(root)
    assert code == 1
    assert [(item["code"], item["line"]) for item in report["findings"]] == [
        ("DOC_LOCAL_PATH", 1), ("DOC_LOCAL_PATH", 3), ("DOC_LOCAL_PATH", 4), ("DOC_LOCAL_PATH", 6),
        ("DOC_LOCAL_PATH", 7)]


def test_secret_like_values_and_emails_are_rejected_without_echo(tmp_path):
    # Built at runtime so this test file never contains a token-shaped literal.
    telegram = "123456789:" + "AA" + "b" * 33
    github = "ghp" + "_" + "c" * 36
    aws = "AKIA" + "D" * 16
    key = "-----BEGIN " + "RSA PRIVATE KEY-----"
    root = _repo(tmp_path, {"a.md": "\n".join([
        f"token {telegram}", "```", github, "```", aws, key, "contact ops@corp.io", "fine ops@example.com",
    ]) + "\n"})
    code, report = _run(root)
    assert code == 1
    assert _codes(report) == [("DOC_SECRET_LIKE", "telegram_bot_token"), ("DOC_SECRET_LIKE", "github_token"),
                              ("DOC_SECRET_LIKE", "aws_access_key"), ("DOC_SECRET_LIKE", "private_key"),
                              ("DOC_EMAIL", "email address")]
    rendered = json.dumps(report)
    for secret in (telegram, github, aws, "ops@corp.io"):
        assert secret not in rendered


def test_encodings_and_irregular_files(tmp_path):
    root = _repo(tmp_path, {
        "docs/target.md": "x\n",
        "utf16.md": b"\xff\xfe" + "[t](docs/target.md) [x](docs/none.md)\n".encode("utf-16-le"),
        "bad.md": b"caf\xe9\n",
    })
    (root / "link.md").symlink_to(root / "docs/target.md")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    code, report = _run(root)
    assert code == 1
    assert {(item["code"], item["path"]) for item in report["findings"]} == {
        ("DOC_NOT_DECODABLE", "bad.md"), ("DOC_NOT_REGULAR_FILE", "link.md"), ("DOC_BROKEN_LINK", "utf16.md")}


def test_not_a_repository_root_is_an_error(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    code, report = _run(plain)
    assert code == 2 and report["status"] == "ERROR" and report["reason"] == "GIT_COMMAND_FAILED"
    root = _repo(tmp_path, {"docs/a.md": "x\n"})
    code, report = _run(root / "docs")
    assert code == 2 and report["reason"] == "NOT_REPOSITORY_ROOT"
    empty = tmp_path / "empty"
    subprocess.run(["git", "init", "-q", str(empty)], check=True)
    code, report = _run(empty)
    assert code == 2 and report["reason"] == "NO_TRACKED_FILES"

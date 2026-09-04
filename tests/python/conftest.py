"""Test-session isolation.

The suite used to run with the repository root as the working directory, which
let every relative ``data/...`` default write into the real evidence tree (it
overwrote ``data/backups/backup_report.json`` and rotated real backups away).
It also hid CWD coupling: seven tests only passed because of where pytest was
launched from.

This conftest removes both problems at once. The session runs from a temporary
directory with ``AGI_FX_DATA_ROOT`` pointing inside it, so unmigrated relative
defaults land in the sandbox, and any test that still depends on the repository
being the CWD fails loudly instead of silently passing.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from agi_style_forex_bot_mt5.core import DATA_ROOT_ENV, PROJECT_ROOT_ENV, workspace_paths

PROJECT_ROOT = workspace_paths().project_root
_PRODUCTION_DATA_ROOT = PROJECT_ROOT / "data"
_baseline_fingerprint: str = ""


def production_data_fingerprint() -> str:
    """Content fingerprint of the repository's real data tree."""

    digest = hashlib.sha256()
    if not _PRODUCTION_DATA_ROOT.exists():
        return digest.hexdigest()
    for path in sorted(_PRODUCTION_DATA_ROOT.rglob("*")):
        if path.is_dir():
            continue
        digest.update(str(path.relative_to(_PRODUCTION_DATA_ROOT)).encode("utf-8"))
        try:
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8"))
        except OSError:
            digest.update(b"UNREADABLE")
    return digest.hexdigest()


def baseline_production_fingerprint() -> str:
    """The fingerprint captured before any test ran."""

    return _baseline_fingerprint


@pytest.fixture(scope="session", autouse=True)
def isolated_workspace(tmp_path_factory: pytest.TempPathFactory):
    """Run the whole session outside the repository, with a sandboxed data root."""

    global _baseline_fingerprint
    _baseline_fingerprint = production_data_fingerprint()

    sandbox = tmp_path_factory.mktemp("workspace_sandbox")
    data_root = sandbox / "data"
    data_root.mkdir(parents=True, exist_ok=True)

    previous_cwd = Path.cwd()
    previous_data_root = os.environ.get(DATA_ROOT_ENV)
    previous_project_root = os.environ.get(PROJECT_ROOT_ENV)

    os.environ[DATA_ROOT_ENV] = str(data_root)
    os.environ.pop(PROJECT_ROOT_ENV, None)
    os.chdir(sandbox)
    try:
        yield workspace_paths()
    finally:
        os.chdir(previous_cwd)
        if previous_data_root is None:
            os.environ.pop(DATA_ROOT_ENV, None)
        else:
            os.environ[DATA_ROOT_ENV] = previous_data_root
        if previous_project_root is not None:
            os.environ[PROJECT_ROOT_ENV] = previous_project_root

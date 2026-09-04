"""Explicit workspace roots so nothing depends on the process working directory.

Two roots, deliberately separate:

* ``project_root`` -- immutable repository content (scripts, docs, config,
  tests). Discovered from this file upwards, never from the CWD, so a gate that
  checks for ``scripts/run_forward_shadow.ps1`` returns the same verdict no
  matter where Python was launched from.
* ``data_root`` -- writable evidence (sqlite, logs, reports, runtime, backups).
  Overridable via ``AGI_FX_DATA_ROOT`` so tests and sandboxes never touch
  production evidence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT_ENV = "AGI_FX_PROJECT_ROOT"
DATA_ROOT_ENV = "AGI_FX_DATA_ROOT"
_PROJECT_MARKERS = ("pyproject.toml", ".git")


@dataclass(frozen=True)
class WorkspacePaths:
    """Resolved workspace roots and the standard directories beneath them."""

    project_root: Path
    data_root: Path

    @classmethod
    def resolve(cls, *, project_root: str | Path | None = None, data_root: str | Path | None = None) -> "WorkspacePaths":
        """Resolve both roots. Explicit argument wins, then environment, then discovery."""

        project = Path(project_root) if project_root is not None else _project_root_from_env_or_discovery()
        project = project.resolve()
        if data_root is not None:
            data = Path(data_root)
        else:
            env_data = os.environ.get(DATA_ROOT_ENV, "").strip()
            data = Path(env_data) if env_data else project / "data"
        return cls(project_root=project, data_root=data.resolve())

    # -- immutable project content -------------------------------------------------
    @property
    def scripts_dir(self) -> Path:
        return self.project_root / "scripts"

    @property
    def docs_dir(self) -> Path:
        return self.project_root / "docs"

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"

    @property
    def tests_dir(self) -> Path:
        return self.project_root / "tests"

    # -- writable evidence ---------------------------------------------------------
    @property
    def sqlite_dir(self) -> Path:
        return self.data_root / "sqlite"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.data_root / "reports"

    @property
    def runtime_dir(self) -> Path:
        return self.data_root / "runtime"

    @property
    def backups_dir(self) -> Path:
        return self.data_root / "backups"

    @property
    def backtests_dir(self) -> Path:
        return self.data_root / "backtests"

    @property
    def raw_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def outputs_dir(self) -> Path:
        return self.data_root / "outputs"

    def project_path(self, *parts: str | Path) -> Path:
        return self.project_root.joinpath(*[str(part) for part in parts])

    def data_path(self, *parts: str | Path) -> Path:
        return self.data_root.joinpath(*[str(part) for part in parts])

    def resolve_path(self, value: str | Path) -> Path:
        """Resolve a possibly-relative path without consulting the CWD.

        An absolute path is returned unchanged. A path starting with ``data/``
        is rebased onto :attr:`data_root`; anything else is rebased onto
        :attr:`project_root`. This is what lets the hundreds of legacy
        ``"data/reports/..."`` defaults be redirected without rewriting them.
        """

        path = Path(value)
        if path.is_absolute():
            return path
        parts = path.parts
        if parts and parts[0] == "data":
            return self.data_root.joinpath(*parts[1:]) if len(parts) > 1 else self.data_root
        return self.project_root.joinpath(*parts)

    def ensure_data_dirs(self) -> "WorkspacePaths":
        for directory in (self.sqlite_dir, self.logs_dir, self.reports_dir, self.runtime_dir, self.backups_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def as_dict(self) -> dict[str, str]:
        return {"project_root": str(self.project_root), "data_root": str(self.data_root)}


def _project_root_from_env_or_discovery() -> Path:
    env_root = os.environ.get(PROJECT_ROOT_ENV, "").strip()
    if env_root:
        return Path(env_root)
    return _discover_project_root(Path(__file__).resolve())


def _discover_project_root(start: Path) -> Path:
    for candidate in start.parents:
        if any((candidate / marker).exists() for marker in _PROJECT_MARKERS):
            return candidate
    return start.parents[-1]


def workspace_paths(*, project_root: str | Path | None = None, data_root: str | Path | None = None) -> WorkspacePaths:
    """Resolve the workspace on every call so tests can rebind the environment."""

    return WorkspacePaths.resolve(project_root=project_root, data_root=data_root)

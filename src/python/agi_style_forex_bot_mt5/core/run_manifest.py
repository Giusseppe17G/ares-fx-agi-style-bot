"""Reproducible provenance record for any run that produces evidence.

`run_id` is derived from the run's own inputs rather than from wall-clock time,
so two runs with the same mode, config, dataset, reference time and seed produce
the same identifier and the same manifest. Secrets are never hashed or stored:
they are dropped before the config digest is computed.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .clock import Clock, resolve_clock
from .safety import SafetyEnvelope
from .workspace import WorkspacePaths, workspace_paths


MANIFEST_VERSION = "1.0"
TRACKED_PACKAGES = ("numpy", "pandas", "scikit-learn", "MetaTrader5")
SECRET_KEY_TOKENS = ("token", "secret", "password", "passwd", "api_key", "apikey", "credential", "chat_id", "login", "private")


@dataclass(frozen=True)
class RunManifest:
    """Everything needed to identify and reproduce one run."""

    mode: str
    run_id: str
    manifest_version: str = MANIFEST_VERSION
    git_commit_sha: str = ""
    git_dirty: bool = False
    project_root: str = ""
    data_root: str = ""
    config_hash: str = ""
    dataset_hash: str = ""
    reference_time_utc: str = ""
    python_version: str = ""
    package_versions: Mapping[str, str] = field(default_factory=dict)
    symbols: Sequence[str] = field(default_factory=tuple)
    timeframe: str = ""
    seed: int | None = None
    safety: Mapping[str, bool] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        mode: str,
        clock: Clock | None = None,
        workspace: WorkspacePaths | None = None,
        config: Mapping[str, Any] | Any | None = None,
        dataset_paths: Iterable[str | Path] | None = None,
        dataset_hash: str = "",
        symbols: Iterable[str] | None = None,
        timeframe: str = "",
        seed: int | None = None,
        envelope: SafetyEnvelope | None = None,
    ) -> "RunManifest":
        paths = workspace or workspace_paths()
        reference_time = resolve_clock(clock).now_utc().isoformat()
        config_hash = hash_config(config) if config is not None else ""
        resolved_dataset_hash = dataset_hash or (hash_paths(dataset_paths) if dataset_paths else "")
        symbol_tuple = tuple(sorted(str(symbol) for symbol in (symbols or ())))
        sha, dirty = _git_state(paths.project_root)
        run_id = _derive_run_id(
            mode=mode,
            config_hash=config_hash,
            dataset_hash=resolved_dataset_hash,
            reference_time=reference_time,
            symbols=symbol_tuple,
            timeframe=timeframe,
            seed=seed,
        )
        return cls(
            mode=mode,
            run_id=run_id,
            git_commit_sha=sha,
            git_dirty=dirty,
            project_root=str(paths.project_root),
            data_root=str(paths.data_root),
            config_hash=config_hash,
            dataset_hash=resolved_dataset_hash,
            reference_time_utc=reference_time,
            python_version=platform.python_version(),
            package_versions=_package_versions(),
            symbols=symbol_tuple,
            timeframe=str(timeframe or ""),
            seed=seed,
            safety=(envelope or SafetyEnvelope()).as_dict(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "mode": self.mode,
            "run_id": self.run_id,
            "git_commit_sha": self.git_commit_sha,
            "git_dirty": self.git_dirty,
            "project_root": self.project_root,
            "data_root": self.data_root,
            "config_hash": self.config_hash,
            "dataset_hash": self.dataset_hash,
            "reference_time_utc": self.reference_time_utc,
            "python_version": self.python_version,
            "package_versions": dict(self.package_versions),
            "symbols": list(self.symbols),
            "timeframe": self.timeframe,
            "seed": self.seed,
            "safety": dict(self.safety),
        }

    def attach(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return the payload with the manifest and sealed safety flags attached."""

        sealed = SafetyEnvelope.from_mapping(self.safety).seal(payload)
        sealed["run_manifest"] = self.as_dict()
        return sealed


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop anything whose key looks like a credential, recursively."""

    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if any(token in key_text.lower() for token in SECRET_KEY_TOKENS):
            continue
        if isinstance(value, Mapping):
            redacted[key_text] = redact_mapping(value)
        elif isinstance(value, (list, tuple)):
            redacted[key_text] = [redact_mapping(item) if isinstance(item, Mapping) else _jsonable(item) for item in value]
        else:
            redacted[key_text] = _jsonable(value)
    return redacted


def hash_config(config: Mapping[str, Any] | Any) -> str:
    """Hash a config after redacting secrets. Never stores the values themselves."""

    if not isinstance(config, Mapping):
        config = {key: value for key, value in vars(config).items() if not key.startswith("_")} if hasattr(config, "__dict__") else {"value": str(config)}
    payload = json.dumps(redact_mapping(config), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_paths(paths: Iterable[str | Path]) -> str:
    """Content hash over a set of dataset files. Missing files are recorded as such."""

    digest = hashlib.sha256()
    for item in sorted(str(path) for path in paths):
        path = Path(item)
        digest.update(path.name.encode("utf-8"))
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8"))
        else:
            digest.update(b"MISSING")
    return digest.hexdigest()


def _derive_run_id(*, mode: str, config_hash: str, dataset_hash: str, reference_time: str, symbols: Sequence[str], timeframe: str, seed: int | None) -> str:
    payload = json.dumps(
        {
            "mode": mode,
            "config_hash": config_hash,
            "dataset_hash": dataset_hash,
            "reference_time_utc": reference_time,
            "symbols": list(symbols),
            "timeframe": timeframe,
            "seed": seed,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _git_state(project_root: Path) -> tuple[str, bool]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root, capture_output=True, text=True, timeout=10, check=False
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=project_root, capture_output=True, text=True, timeout=10, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "", False
    return sha, bool(status)


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

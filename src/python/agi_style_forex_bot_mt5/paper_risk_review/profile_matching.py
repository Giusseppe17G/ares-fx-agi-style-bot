"""Profile name normalization and config matching for paper risk clearance."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PROFILE_KEYS = ("SIGNAL_PROFILE", "PROFILE", "PAPER_RISK_PROFILE", "RISK_PROFILE", "RISK_PROFILE_USED")


def normalize_profile_name(value: Any) -> str:
    """Return the canonical uppercase profile name used for comparisons."""

    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_").upper()


def read_profile_config_profile(profile_config: str | Path | None) -> dict[str, Any]:
    """Read the profile identity from a paper profile INI with safe fallback inference."""

    path = Path(profile_config) if profile_config else None
    values = _read_simple_ini(path) if path else {}
    raw_profile = ""
    source_key = ""
    for key in PROFILE_KEYS:
        if values.get(key):
            raw_profile = values[key]
            source_key = key
            break
    warnings: list[str] = []
    inferred = False
    if not raw_profile and path and "balanced_stable_micro" in path.name.lower():
        raw_profile = "BALANCED_STABLE_MICRO"
        source_key = "CONFIG_PATH"
        inferred = True
        warnings.append("PROFILE_INFERRED_FROM_CONFIG_PATH")
    canonical = normalize_profile_name(raw_profile)
    return {
        "profile": raw_profile,
        "canonical_profile": canonical,
        "source_key": source_key,
        "profile_config": str(path) if path else "",
        "profile_inferred": inferred,
        "warnings": warnings,
        "paper_only": _bool(values.get("PAPER_ONLY"), False),
        "not_for_demo_live": _bool(values.get("NOT_FOR_DEMO_LIVE"), False),
        "values": values,
    }


def effective_requested_profile(profile: Any = "", profile_config: str | Path | None = None) -> dict[str, Any]:
    """Resolve the requested profile, allowing micro INI inference when no explicit profile was supplied."""

    config_profile = read_profile_config_profile(profile_config)
    explicit = normalize_profile_name(profile)
    if explicit:
        canonical = explicit
        raw = str(profile)
        source = "explicit"
    else:
        canonical = str(config_profile.get("canonical_profile", ""))
        raw = str(config_profile.get("profile", ""))
        source = "profile_config"
    return {
        "requested_profile": raw,
        "requested_profile_canonical": canonical,
        "profile_source": source,
        "profile_config_profile": config_profile.get("profile", ""),
        "profile_config_profile_canonical": config_profile.get("canonical_profile", ""),
        "profile_warnings": list(config_profile.get("warnings", [])),
        "paper_only": config_profile.get("paper_only", False),
        "not_for_demo_live": config_profile.get("not_for_demo_live", False),
    }


def _read_simple_ini(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"true", "1", "yes", "on"}

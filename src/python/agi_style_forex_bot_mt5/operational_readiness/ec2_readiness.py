"""Offline Windows EC2 readiness audit."""

from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


REQUIRED_STABLE_SCRIPTS = (
    "run_forward_shadow_balanced_stable.ps1",
    "watchdog_forward_shadow_balanced_stable.ps1",
    "status_forward_shadow_stable.ps1",
    "daily_summary_stable.ps1",
)

SECRET_PATTERNS = (
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(telegram_bot_token|bot_token|api_key|secret|password)\s*=\s*(?!\"?\$env:)(?!\"?changeme)(?!\"?placeholder)(?!\"?redacted)([^\s#;\"']{8,})"),
)


def run_ec2_readiness_audit(
    *,
    reports_root: str | Path,
    output_dir: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Audit repo artifacts required for a safe Windows EC2 dry run."""

    root = Path(project_root) if project_root is not None else Path.cwd()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = Path(reports_root)
    checks: list[dict[str, Any]] = []

    for script in REQUIRED_STABLE_SCRIPTS:
        path = root / "scripts" / script
        _check(checks, f"script_{script}", "PASS" if path.exists() else "FAIL", "EC2_NEEDS_SCRIPT_REPAIR" if not path.exists() else "", str(path))
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore")
            _check(checks, f"script_{script}_safe_flags", "PASS" if _has_safe_script_flags(text) else "WARNING", "EC2_NEEDS_RUNBOOK_UPDATE" if not _has_safe_script_flags(text) else "", "checks BALANCED_STABLE/PYTHONPATH/safe flags")

    gitignore = root / ".gitignore"
    gitignore_text = gitignore.read_text(encoding="utf-8", errors="ignore") if gitignore.exists() else ""
    ignored_ok = all(item in gitignore_text for item in ("data/logs/", "data/sqlite/", "data/reports/", "*.sqlite3"))
    _check(checks, "gitignore_runtime_data", "PASS" if ignored_ok else "FAIL", "" if ignored_ok else "EC2_NEEDS_SECRET_REVIEW", ".gitignore protects runtime logs/sqlite/reports")

    docs_ok = _docs_have_ec2_runbook(root)
    _check(checks, "ec2_runbook_documented", "PASS" if docs_ok else "WARNING", "" if docs_ok else "EC2_NEEDS_RUNBOOK_UPDATE", "README/docs mention EC2 and PYTHONPATH")

    secret_findings = _scan_for_secrets(root)
    _check(
        checks,
        "secret_scan",
        "PASS" if not secret_findings else "FAIL",
        "" if not secret_findings else "EC2_NEEDS_SECRET_REVIEW",
        f"findings={len(secret_findings)}",
        metadata={"findings": secret_findings[:10]},
    )

    _check(checks, "reports_root_exists", "PASS" if reports.exists() else "WARNING", "" if reports.exists() else "EC2_NEEDS_RUNBOOK_UPDATE", str(reports))
    classification = _classify(checks)
    summary = {
        "mode": "ec2-readiness-audit",
        "ec2_readiness_status": classification,
        "classification": classification,
        "checks_passed": sum(1 for item in checks if item["status"] == "PASS"),
        "checks_warning": sum(1 for item in checks if item["status"] == "WARNING"),
        "checks_failed": sum(1 for item in checks if item["status"] == "FAIL"),
        "secret_findings_count": len(secret_findings),
        "recommended_action": _recommendation(classification),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "checks": checks,
    }
    summary_path = output / "ec2_readiness_summary.json"
    checks_path = output / "ec2_checks.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(checks_path, checks)
    html_path.write_text(_html(summary), encoding="utf-8")
    summary["reports_created"] = [str(summary_path), str(checks_path), str(html_path)]
    return summary


def _has_safe_script_flags(text: str) -> bool:
    lowered = text.lower()
    unsafe = "demo_only=false" in lowered or "live_trading_approved=true" in lowered
    has_pythonpath_or_delegates = "pythonpath" in lowered or "run_forward_shadow_balanced_stable.ps1" in lowered
    return has_pythonpath_or_delegates and ("balanced_stable" in lowered or "stable" in lowered) and not unsafe


def _docs_have_ec2_runbook(root: Path) -> bool:
    candidates = [root / "README.md", root / "docs" / "DEPLOY_WINDOWS_EC2.md", root / "docs" / "OPERATIONAL_RUNBOOK.md"]
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") if path.exists() else "" for path in candidates)
    if not combined.strip():
        try:
            combined = (root / "README.md").read_text(encoding="utf-16", errors="ignore")
        except Exception:
            combined = ""
    lowered = combined.lower()
    return "ec2" in lowered and "pythonpath" in lowered and "demo_only=true" in lowered and "live_trading_approved=false" in lowered


def _scan_for_secrets(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    allowed_suffixes = {".ini", ".ps1", ".md", ".py", ".txt", ".json", ".toml"}
    excluded_parts = {".git", "__pycache__", ".pytest_cache", "data", "tests"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not text and path.name.lower() == "readme.md":
            text = path.read_text(encoding="utf-16", errors="ignore")
        for index, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(marker in lowered for marker in ("redacted", "placeholder", "example", "replace_locally", "changeme", "os.getenv")):
                continue
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                findings.append({"path": str(path), "line": str(index), "snippet": line.strip()[:160]})
                if len(findings) >= 25:
                    return findings
    return findings


def _check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    classification: str,
    detail: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "check_name": name,
            "status": status,
            "classification": classification,
            "detail": detail,
            "metadata": dict(metadata or {}),
            "execution_attempted": False,
        }
    )


def _classify(checks: Iterable[Mapping[str, Any]]) -> str:
    failed = [item for item in checks if item.get("status") == "FAIL"]
    if any(item.get("classification") == "EC2_NEEDS_SECRET_REVIEW" for item in failed):
        return "EC2_NEEDS_SECRET_REVIEW"
    if any(item.get("classification") == "EC2_NEEDS_SCRIPT_REPAIR" for item in failed):
        return "EC2_NEEDS_SCRIPT_REPAIR"
    if any(item.get("classification") == "EC2_NEEDS_RUNBOOK_UPDATE" for item in checks if item.get("status") in {"FAIL", "WARNING"}):
        return "EC2_NEEDS_RUNBOOK_UPDATE"
    return "EC2_READY_FOR_DRY_RUN"


def _recommendation(classification: str) -> str:
    if classification == "EC2_READY_FOR_DRY_RUN":
        return "Prepare an EC2 dry run only; keep MT5 paper/shadow and do not enable demo/live execution."
    if classification == "EC2_NEEDS_SECRET_REVIEW":
        return "Remove or redact secrets before moving the repo to EC2."
    if classification == "EC2_NEEDS_SCRIPT_REPAIR":
        return "Repair missing Windows stable shadow scripts before EC2 dry run."
    return "Update README/runbook with EC2, PYTHONPATH and safety instructions."


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("check_name", "status", "classification", "detail", "execution_attempted"))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames or ()})


def _html(summary: Mapping[str, Any]) -> str:
    rows = "\n".join(
        f"<tr><td>{html.escape(str(item.get('check_name')))}</td><td>{html.escape(str(item.get('status')))}</td><td>{html.escape(str(item.get('classification')))}</td><td>{html.escape(str(item.get('detail')))}</td></tr>"
        for item in summary.get("checks", [])
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>EC2 Readiness</title></head>
<body>
<h1>EC2 Readiness Audit</h1>
<p>Classification: <strong>{html.escape(str(summary.get('classification')))}</strong></p>
<p>execution_attempted=false; order_send_called=false; order_check_called=false</p>
<table border="1" cellspacing="0" cellpadding="4"><thead><tr><th>Check</th><th>Status</th><th>Classification</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>
"""

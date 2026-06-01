"""PnL readiness and scaling consistency audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_pnl_readiness(lifecycle: Mapping[str, Any], profile_values: Mapping[str, str]) -> dict[str, Any]:
    rows = list(lifecycle.get("open_trades", []))
    issues: list[dict[str, Any]] = []
    scaled_total = 0.0
    raw_total = 0.0
    latent_total = 0.0
    for row in rows:
        raw = _float(row.get("raw_paper_pnl"))
        scaled = _float(row.get("scaled_paper_pnl"))
        latent = _float(row.get("latent_paper_pnl"))
        raw_total += raw
        scaled_total += scaled
        latent_total += latent
        scaling_status = str(row.get("pnl_scaling_status") or "").upper()
        if "ISSUE" in scaling_status or row.get("pnl_scaling_inconsistent"):
            issues.append({"trade_id": row.get("trade_id"), "issue": "PNL_SCALING_STATUS_ISSUE"})
        if row.get("missing_current_price"):
            continue
        multiplier = _profile_multiplier(profile_values)
        if multiplier is not None and abs(raw) > 1e-9 and abs(scaled - (raw * multiplier)) > max(abs(raw) * 0.05, 1e-6):
            issues.append({"trade_id": row.get("trade_id"), "issue": "PNL_SCALED_VALUE_INCONSISTENT"})
    status = "PNL_READINESS_ISSUE" if issues else "PNL_READINESS_OK"
    return {
        "pnl_readiness_status": status,
        "pnl_issues": len(issues),
        "pnl_issue_rows": issues,
        "open_latent_pnl_total": round(latent_total, 6),
        "scaled_latent_pnl_total": round(scaled_total, 6),
        "raw_latent_pnl_total": round(raw_total, 6),
        "risk_multiplier_applied": _profile_multiplier(profile_values) is not None,
        "pnl_scaling_correct": not issues,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _profile_multiplier(values: Mapping[str, str]) -> float | None:
    for key in ("PAPER_RISK_MULTIPLIER", "RISK_MULTIPLIER"):
        if key in values:
            return _float(values[key], default=1.0)
    return None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default

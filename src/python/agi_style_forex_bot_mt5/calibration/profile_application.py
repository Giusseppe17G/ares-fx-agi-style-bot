"""Safe application of calibrated signal profiles for research runs."""

from __future__ import annotations

import json
from configparser import ConfigParser
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..config import BotConfig
from .calibration_report import write_config_suggestions
from .effective_profile_config import effective_profile_config
from .signal_profile import PROFILES, SignalProfileSettings, get_signal_profile


PROFILE_KEYS = (
    "SIGNAL_PROFILE",
    "MIN_SETUP_SCORE",
    "MIN_COMPONENT_SCORE",
    "COST_FIT_MIN",
    "STRUCTURE_FIT_MIN",
    "VOLATILITY_FIT_MIN",
    "SESSION_FIT_MIN",
    "ENSEMBLE_MIN_SCORE",
)


def profile_to_config(profile: SignalProfileSettings) -> dict[str, Any]:
    """Return the INI-shaped threshold overlay for one signal profile."""

    return {
        "SIGNAL_PROFILE": profile.name,
        "MIN_SETUP_SCORE": profile.min_setup_score,
        "MIN_COMPONENT_SCORE": profile.min_component_score,
        "COST_FIT_MIN": profile.cost_fit_min,
        "STRUCTURE_FIT_MIN": profile.structure_fit_min,
        "VOLATILITY_FIT_MIN": profile.volatility_fit_min,
        "SESSION_FIT_MIN": profile.session_fit_min,
        "ENSEMBLE_MIN_SCORE": profile.ensemble_min_score,
    }


def profile_hash(profile: SignalProfileSettings | Mapping[str, Any]) -> str:
    """Return a stable hash for profile thresholds and safety flags."""

    if isinstance(profile, SignalProfileSettings):
        return effective_profile_config(profile.name).profile_hash
    payload = dict(profile)
    return sha256(json.dumps(_jsonable(payload), sort_keys=True).encode("utf-8")).hexdigest()


def bot_config_with_signal_profile(config: BotConfig, profile_name: str, profile_config: str = "") -> BotConfig:
    """Return a safe config copy with only the signal profile changed."""

    profile = get_signal_profile(profile_name)
    extra: dict[str, Any] = {}
    if profile_config:
        extra["profile_config"] = profile_config
    if profile.name in {"BALANCED_STABLE", "BALANCED_STABLE_MICRO"} and profile_config:
        stable_values = _read_profile_ini(Path(profile_config))
        extra.update(
            {
                "stability_filters_applied": str(stable_values.get("APPLY_STABILITY_FILTERS", stable_values.get("STABILITY_FILTERS_APPLIED", "false"))).strip().lower() == "true",
                "profile_type": str(stable_values.get("PROFILE_TYPE", "RESEARCH_BACKTEST_ONLY")),
                "requires_robustness_rerun": str(stable_values.get("REQUIRES_ROBUSTNESS_RERUN", "true")).strip().lower() == "true",
            }
        )
        if profile.name == "BALANCED_STABLE_MICRO":
            extra.update(
                {
                    "paper_only": str(stable_values.get("PAPER_ONLY", "true")).strip().lower() == "true",
                    "max_open_paper_trades": int(stable_values.get("MAX_OPEN_PAPER_TRADES", 1) or 1),
                    "max_paper_trades_per_day": int(stable_values.get("MAX_PAPER_TRADES_PER_DAY", 2) or 2),
                    "cooldown_after_loss_minutes": int(stable_values.get("COOLDOWN_AFTER_LOSS_MINUTES", 120) or 120),
                    "cooldown_after_drawdown_halt_minutes": int(stable_values.get("COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", 1440) or 1440),
                    "block_new_entries_after_daily_halt": str(stable_values.get("BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", "true")).strip().lower() == "true",
                    "manual_resume_required": str(stable_values.get("MANUAL_RESUME_REQUIRED", "true")).strip().lower() == "true",
                    "paper_risk_multiplier": float(stable_values.get("PAPER_RISK_MULTIPLIER", 0.10) or 0.10),
                    "risk_profile_used": "BALANCED_STABLE_MICRO",
                }
            )
    updated = replace(config, signal_profile=profile.name, **extra)
    updated.validate_safety()
    return updated


def apply_signal_profile(
    *,
    profile_name: str,
    runs_root: str | Path = "data/runs",
    output_dir: str | Path = "data/reports/applied_profiles",
    source_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Apply a profile as an auditable research overlay without mutating defaults."""

    profile = get_signal_profile(profile_name)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source_config = _find_source_config(profile, Path(runs_root), Path(source_dir) if source_dir else None)
    thresholds = _read_profile_ini(source_config) if source_config else profile_to_config(profile)
    thresholds["SIGNAL_PROFILE"] = profile.name
    applied_json = output / "applied_profile.json"
    applied_ini = output / "applied_profile.ini"
    diff_json = output / "profile_diff.json"

    applied_payload = {
        "mode": "apply-signal-profile",
        "profile_name": profile.name,
        "source_config": str(source_config) if source_config else "",
        "thresholds": thresholds,
        "profile_hash": profile_hash(profile),
        "not_for_demo_live": bool(profile.not_for_demo_live),
        "profile_allowed_for_shadow": profile_allowed_for_shadow(profile.name),
        "research_only": bool(profile.research_only),
        "execution_attempted": False,
    }
    diff = profile_diff(profile)
    applied_json.write_text(json.dumps(_jsonable(applied_payload), indent=2, sort_keys=True), encoding="utf-8")
    applied_ini.write_text(_ini_text(profile, thresholds), encoding="utf-8")
    diff_json.write_text(json.dumps(_jsonable(diff), indent=2, sort_keys=True), encoding="utf-8")
    comparison_paths = write_profile_comparison(output.parent / "profile_runs")
    return {
        **applied_payload,
        "reports_created": [str(applied_json), str(applied_ini), str(diff_json), *comparison_paths],
    }


def write_profile_comparison(output_dir: str | Path, metrics_by_profile: Mapping[str, Mapping[str, Any]] | None = None) -> list[str]:
    """Write a compact profile comparison skeleton for research orchestration."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    metrics = {key.upper(): dict(value) for key, value in dict(metrics_by_profile or {}).items()}
    for name, profile in PROFILES.items():
        observed = metrics.get(name, {})
        effective = effective_profile_config(profile.name)
        thresholds = effective.thresholds
        rows.append(
            {
                "profile": name,
                "thresholds_used": thresholds,
                "profile_hash": effective.profile_hash,
                "ensemble_min_score": profile.ensemble_min_score,
                "min_component_score": profile.min_component_score,
                "min_setup_score": profile.min_setup_score,
                "cost_fit_min": profile.cost_fit_min,
                "session_fit_min": profile.session_fit_min,
                "structure_fit_min": profile.structure_fit_min,
                "volatility_fit_min": profile.volatility_fit_min,
                "effective_profile_source": effective.source,
                "signals_generated": int(observed.get("signals_generated", 0) or 0),
                "trades_generated": int(observed.get("trades_generated", 0) or 0),
                "blocked_by_threshold": int(observed.get("blocked_by_threshold", 0) or 0),
                "passed_by_threshold": int(observed.get("passed_by_threshold", observed.get("trades_generated", 0)) or 0),
                "avg_setup_score": float(observed.get("avg_setup_score", 0.0) or 0.0),
                "avg_ensemble_score": float(observed.get("avg_ensemble_score", 0.0) or 0.0),
                "winrate": float(observed.get("winrate", 0.0) or 0.0),
                "profit_factor": observed.get("profit_factor", 0.0),
                "expectancy_r": float(observed.get("expectancy_r", 0.0) or 0.0),
                "max_drawdown_pct": float(observed.get("max_drawdown_pct", 0.0) or 0.0),
                "sample_status": observed.get("sample_status", profile_trade_frequency_status(signals_generated=int(observed.get("signals_generated", 0) or 0), trades_generated=int(observed.get("trades_generated", 0) or 0))),
                "metrics_status": observed.get("metrics_status", "FULL_EDGE_METRICS" if int(observed.get("trades_generated", 0) or 0) > 0 else "NO_TRADES"),
                "benchmark_classification": observed.get("benchmark_classification", ""),
                "validation_decision": observed.get("validation_decision", ""),
                "not_for_demo_live": bool(profile.not_for_demo_live),
                "allowed_for_shadow": profile_allowed_for_shadow(name),
                "profile_allowed_for_shadow": profile_allowed_for_shadow(name),
                "recommendation": observed.get("recommendation", _profile_recommendation(name, profile)),
                "execution_attempted": False,
            }
        )
    json_path = output / "profile_comparison.json"
    csv_path = output / "profile_comparison.csv"
    payload = {
        "mode": "profile-comparison",
        "profiles": rows,
        "execution_attempted": False,
        "reports_created": [str(json_path), str(csv_path)],
    }
    json_path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return [str(json_path), str(csv_path)]


def run_profile_comparison(
    *,
    profiles_value: str,
    data_dir: str | Path,
    symbols: Any,
    output_dir: str | Path,
    base_config: BotConfig | None = None,
) -> dict[str, Any]:
    """Run a quick backtest comparison across calibrated signal profiles."""

    from ..backtesting import run_backtest_for_symbols
    from .signal_profile import parse_profiles

    metrics: dict[str, Mapping[str, Any]] = {}
    reports_created: list[str] = []
    for profile in parse_profiles(profiles_value):
        cfg = bot_config_with_signal_profile(base_config or BotConfig(), profile.name)
        profile_dir = Path(output_dir) / profile.name.lower()
        try:
            result = run_backtest_for_symbols(data_dir=data_dir, symbols=_coerce_symbols(symbols), report_dir=profile_dir, config=cfg)
            summary = result.summary
            reports_created.extend(summary.get("reports_created", []))
            metrics[profile.name] = {
                "signals_generated": summary.get("signals_generated", 0),
                "trades_generated": summary.get("trades_generated", summary.get("total_trades", 0)),
                "blocked_by_threshold": summary.get("blocked_by_threshold", 0),
                "passed_by_threshold": summary.get("passed_by_threshold", summary.get("trades_generated", summary.get("total_trades", 0))),
                "avg_setup_score": summary.get("avg_setup_score", 0.0),
                "avg_ensemble_score": summary.get("avg_ensemble_score", 0.0),
                "profile_hash": summary.get("profile_hash", effective_profile_config(profile.name).profile_hash),
                "thresholds_used": summary.get("thresholds_used", effective_profile_config(profile.name).thresholds),
                "winrate": summary.get("winrate", 0.0),
                "profit_factor": summary.get("profit_factor", 0.0),
                "expectancy_r": summary.get("expectancy_r", 0.0),
                "max_drawdown_pct": summary.get("max_drawdown_pct", 0.0),
                "sample_status": summary.get("sample_status", profile_trade_frequency_status(signals_generated=int(summary.get("signals_generated", 0) or 0), trades_generated=int(summary.get("trades_generated", summary.get("total_trades", 0)) or 0))),
                "metrics_status": summary.get("metrics_status", "FULL_EDGE_METRICS"),
                "benchmark_classification": "",
                "validation_decision": summary.get("classification", ""),
                "average_setup_score": 0.0,
                "top_blockers": summary.get("top_blocking_reasons", []),
                "recommendation": _profile_recommendation(profile.name, profile),
            }
        except Exception as exc:
            metrics[profile.name] = {
                "signals_generated": 0,
                "trades_generated": 0,
                "blocked_by_threshold": 0,
                "passed_by_threshold": 0,
                "avg_setup_score": 0.0,
                "avg_ensemble_score": 0.0,
                "profile_hash": effective_profile_config(profile.name).profile_hash,
                "thresholds_used": effective_profile_config(profile.name).thresholds,
                "sample_status": "NO_TRADES",
                "metrics_status": "NO_TRADES",
                "validation_decision": "NEEDS_MORE_DATA",
                "top_blockers": [{"blocking_reason": str(exc), "count": 1}],
                "recommendation": _profile_recommendation(profile.name, profile),
            }
    comparison_paths = write_profile_comparison(output_dir, metrics)
    reports_created.extend(comparison_paths)
    best = _best_profile(metrics)
    return {
        "mode": "profile-comparison-run",
        "profiles_compared": list(metrics),
        "best_profile": best,
        "reports_created": reports_created,
        "execution_attempted": False,
    }


def profile_diff(profile: SignalProfileSettings) -> dict[str, Any]:
    """Compare a profile against CONSERVATIVE for a clear audit diff."""

    baseline = profile_to_config(get_signal_profile("CONSERVATIVE"))
    current = profile_to_config(profile)
    return {
        "profile_name": profile.name,
        "baseline_profile": "CONSERVATIVE",
        "changes": {
            key: {"from": baseline.get(key), "to": current.get(key)}
            for key in PROFILE_KEYS
            if baseline.get(key) != current.get(key)
        },
        "not_for_demo_live": bool(profile.not_for_demo_live),
        "execution_attempted": False,
    }


def profile_allowed_for_shadow(profile_name: str) -> bool:
    """Return True only for profiles allowed to create forward-shadow paper trades."""

    profile = get_signal_profile(profile_name)
    return profile.name in {"CONSERVATIVE", "BALANCED", "BALANCED_FILTERED"} and not profile.not_for_demo_live


def profile_trade_frequency_status(*, signals_generated: int, trades_generated: int) -> str:
    """Classify signal/trade frequency for compact summaries."""

    if signals_generated <= 0:
        return "NO_SIGNALS"
    if trades_generated <= 0:
        return "SIGNALS_NO_TRADES"
    if trades_generated < 30:
        return "LOW_SAMPLE"
    if trades_generated < 100:
        return "SMALL_SAMPLE"
    if trades_generated < 300:
        return "USABLE_SAMPLE"
    return "PROMOTION_SAMPLE_SIZE"


def _find_source_config(profile: SignalProfileSettings, runs_root: Path, source_dir: Path | None) -> Path | None:
    filename = f"{profile.name.lower()}.ini"
    candidates: list[Path] = []
    if source_dir is not None:
        candidates.append(source_dir / filename)
    latest = _latest_run(runs_root)
    if latest is not None:
        candidates.append(latest / "reports" / "calibration" / "config_suggestions" / filename)
    candidates.append(Path("data/reports/calibration/config_suggestions") / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    generated = Path("data/reports/calibration/config_suggestions")
    write_config_suggestions(generated)
    candidate = generated / filename
    return candidate if candidate.exists() else None


def _latest_run(runs_root: Path) -> Path | None:
    if not runs_root.exists():
        return None
    candidates = [path for path in runs_root.iterdir() if path.is_dir()]
    return sorted(candidates)[-1] if candidates else None


def _read_profile_ini(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8-sig")
    parser = ConfigParser(strict=False)
    parser.read_string("[DEFAULT]\n" + raw)
    values: dict[str, Any] = {}
    for key, value in parser["DEFAULT"].items():
        values[key.upper()] = _coerce(value)
    return values


def _ini_text(profile: SignalProfileSettings, thresholds: Mapping[str, Any]) -> str:
    lines: list[str] = []
    if profile.not_for_demo_live:
        lines.append("; NOT FOR DEMO/LIVE EXECUTION")
    lines.extend(f"{key}={thresholds[key]}" for key in PROFILE_KEYS if key in thresholds)
    return "\n".join(lines) + "\n"


def _coerce(value: str) -> Any:
    stripped = value.strip()
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def _coerce_symbols(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip().upper() for item in value.split(",") if item.strip())
    return tuple(str(item).strip().upper() for item in value if str(item).strip())


def _best_profile(metrics: Mapping[str, Mapping[str, Any]]) -> str:
    if not metrics:
        return ""
    return max(
        metrics,
        key=lambda name: (
            int(metrics[name].get("trades_generated", 0) or 0),
            int(metrics[name].get("signals_generated", 0) or 0),
        ),
    )


def _profile_recommendation(name: str, profile: SignalProfileSettings) -> str:
    if profile.name == "ACTIVE":
        return "research-only frequency experiment; not for demo/live or promotion"
    if profile.name == "BALANCED_FILTERED":
        return "use only when edge-filtering produced APPLY_FILTERS=true"
    if profile.name == "BALANCED_STABLE":
        return "research/backtest-only stability repair profile; requires profile-config and robustness rerun"
    if profile.name == "BALANCED_STABLE_MICRO":
        return "paper-only safer shadow profile; requires stable gate and explicit profile-config"
    if profile.name == "BALANCED":
        return "baseline calibrated research profile"
    return "conservative baseline"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value

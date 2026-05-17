"""Artifact loading helpers for fast robustness validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


TRADE_COLUMNS = ["signal_id", "symbol", "strategy_name", "session", "regime", "entry_time", "exit_time", "profit", "r_multiple"]


def load_balanced_trades(
    *,
    runs_root: str | Path = "data/runs",
    profile_runs_dir: str | Path = "data/reports/profile_runs",
    profile: str = "BALANCED",
) -> tuple[pd.DataFrame, str, str]:
    """Load trade-level evidence for a profile, preferring latest run artifacts."""

    paths = candidate_trade_paths(runs_root=Path(runs_root), profile_runs_dir=Path(profile_runs_dir), profile=profile)
    for path in paths:
        frame = _read_trades(path)
        if not frame.empty:
            return frame, str(path), "trades_csv"
    return pd.DataFrame(columns=TRADE_COLUMNS), "", "missing_trades"


def candidate_trade_paths(*, runs_root: Path, profile_runs_dir: Path, profile: str) -> list[Path]:
    profile_key = profile.strip().lower()
    paths: list[Path] = []
    latest = latest_run_dir(runs_root, profile=profile)
    if latest is not None:
        reports = latest / "reports"
        paths.append(reports / "backtests" / "trades.csv")
        if (reports / "backtests").exists():
            paths.extend(sorted((reports / "backtests").glob("**/trades.csv")))
    paths.append(profile_runs_dir / profile_key / "trades.csv")
    paths.append(profile_runs_dir / profile.strip().upper() / "trades.csv")
    if profile_runs_dir.exists():
        paths.extend(sorted(profile_runs_dir.glob(f"**/{profile_key}/trades.csv")))
        paths.extend(sorted(profile_runs_dir.glob("**/trades.csv")))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def latest_run_dir(runs_root: Path, profile: str | None = None) -> Path | None:
    if not runs_root.exists():
        return None
    candidates = [path for path in runs_root.iterdir() if path.is_dir() and ((path / "final_summary_compact.json").exists() or (path / "reports").exists())]
    if profile:
        profile_key = profile.strip().upper()
        matching = [path for path in candidates if _run_profile(path) == profile_key]
        if matching:
            candidates = matching
    return sorted(candidates, key=lambda path: (_mtime(path), path.name))[-1] if candidates else None


def load_profile_summary(profile_runs_dir: str | Path, profile: str) -> dict[str, Any]:
    """Load aggregate profile metrics when trade-level data is unavailable."""

    profile_key = profile.strip().upper()
    for path in (Path(profile_runs_dir) / "profile_comparison.json", Path(profile_runs_dir) / "summary.json"):
        payload = _read_json(path)
        rows = payload.get("profiles") if isinstance(payload.get("profiles"), list) else []
        for row in rows:
            if str(row.get("profile", "")).upper() == profile_key:
                return dict(row)
    csv_path = Path(profile_runs_dir) / "profile_comparison.csv"
    if csv_path.exists():
        try:
            frame = pd.read_csv(csv_path)
        except (OSError, pd.errors.EmptyDataError):
            return {}
        if "profile" in frame.columns:
            rows = frame.loc[frame["profile"].astype(str).str.upper() == profile_key]
            if not rows.empty:
                return rows.iloc[0].to_dict()
    return {}


def load_latest_profile_run_summary(runs_root: str | Path, profile: str) -> dict[str, Any]:
    """Load final_summary_compact/final_summary for the newest run matching a profile."""

    latest = latest_run_dir(Path(runs_root), profile=profile)
    if latest is None:
        return {}
    compact = _read_json(latest / "final_summary_compact.json")
    full = _read_json(latest / "final_summary.json")
    payload = {**full, **compact}
    if payload:
        payload.setdefault("run_id", latest.name)
    return payload


def normalize_trade_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a numeric, audit-friendly trade frame."""

    if frame.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    copy = frame.copy()
    if "profit" not in copy.columns and "r_multiple" in copy.columns:
        copy["profit"] = pd.to_numeric(copy["r_multiple"], errors="coerce").fillna(0.0)
    if "r_multiple" not in copy.columns and "profit" in copy.columns:
        copy["r_multiple"] = pd.to_numeric(copy["profit"], errors="coerce").fillna(0.0)
    for column in ("profit", "r_multiple", "spread_points", "slippage_points", "commission"):
        if column in copy.columns:
            copy[column] = pd.to_numeric(copy[column], errors="coerce").fillna(0.0)
    for column in ("symbol", "strategy_name", "session", "regime"):
        if column not in copy.columns:
            copy[column] = "UNKNOWN"
        copy[column] = copy[column].fillna("UNKNOWN").replace("", "UNKNOWN")
    return copy


def trade_values(frame: pd.DataFrame) -> pd.Series:
    """Return the primary robustness value sequence, preferring R multiples."""

    normalized = normalize_trade_frame(frame)
    if "r_multiple" in normalized.columns and pd.to_numeric(normalized["r_multiple"], errors="coerce").abs().sum() > 0:
        return pd.to_numeric(normalized["r_multiple"], errors="coerce").fillna(0.0)
    if "profit" in normalized.columns:
        return pd.to_numeric(normalized["profit"], errors="coerce").fillna(0.0)
    return pd.Series(dtype=float)


def metrics_from_values(values: Iterable[float]) -> dict[str, Any]:
    series = pd.Series(list(values), dtype=float)
    total = int(len(series))
    wins = series[series > 0]
    losses = series[series < 0]
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    profit_factor = float("inf") if gross_profit > 0 and gross_loss == 0 else (gross_profit / gross_loss if gross_loss > 0 else 0.0)
    expectancy = float(series.mean()) if total else 0.0
    winrate = float(len(wins) / total * 100.0) if total else 0.0
    equity = series.cumsum()
    running_max = equity.cummax()
    drawdown = equity - running_max
    return {
        "total_trades": total,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy,
        "winrate": winrate,
        "net_value": float(series.sum()) if total else 0.0,
        "max_drawdown_value": float(drawdown.min()) if total else 0.0,
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and value in {float("inf"), float("-inf")}:
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _read_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=TRADE_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=TRADE_COLUMNS)
    return normalize_trade_frame(frame)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _run_profile(path: Path) -> str:
    for candidate in (path / "final_summary_compact.json", path / "final_summary.json"):
        payload = _read_json(candidate)
        profile = str(payload.get("signal_profile_used") or payload.get("signal_profile") or "").strip().upper()
        if profile:
            return profile
    return ""


def _mtime(path: Path) -> float:
    probes = [path / "final_summary_compact.json", path / "final_summary.json", path / "reports" / "backtests" / "trades.csv"]
    times = [probe.stat().st_mtime for probe in probes if probe.exists()]
    return max(times) if times else path.stat().st_mtime

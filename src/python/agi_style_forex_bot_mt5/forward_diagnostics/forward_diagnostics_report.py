"""Forward signal scarcity report runner."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.calibration import effective_profile_config
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.execution import MT5Connector
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

from .forward_near_miss_report import summarize_near_misses
from .live_feature_probe import probe_live_features
from .live_strategy_probe import probe_live_strategies
from .runtime_data_quality import probe_runtime_data_quality
from .signal_scarcity_analyzer import analyze_signal_scarcity


def run_forward_signal_diagnose(
    *,
    config: BotConfig,
    symbols: Iterable[str],
    database: TelemetryDatabase,
    log_dir: str | Path,
    reports_root: str | Path,
    output_dir: str | Path,
    mt5_client: Any | None = None,
    bars: int = 260,
) -> dict[str, Any]:
    """Run read-only live signal scarcity diagnostics."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    audit_logger = JsonlAuditLogger(log_dir, max_file_mb=config.max_jsonl_file_mb)
    connector = MT5Connector(config=config, mt5_client=mt5_client)
    initialize = getattr(connector.mt5, "initialize", None)
    mt5_connected = (not callable(initialize)) or initialize() is True
    selected_symbols = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
    if not mt5_connected:
        data_rows = [_not_connected(symbol) for symbol in selected_symbols]
        feature_rows: list[dict[str, Any]] = []
        strategy_rows: list[dict[str, Any]] = []
        near_rows: list[dict[str, Any]] = []
    else:
        data_rows, runtime_payloads = probe_runtime_data_quality(config=config, connector=connector, symbols=selected_symbols, bars=bars)
        feature_rows, features_by_symbol = probe_live_features(config=config, runtime_payloads=runtime_payloads)
        strategy_rows, near_rows = probe_live_strategies(config=config, runtime_payloads=runtime_payloads, features_by_symbol=features_by_symbol)
        _audit_candidates(database=database, audit_logger=audit_logger, rows=strategy_rows)
    stable_filter = audit_stable_filter(config=config, symbols=selected_symbols, strategy_rows=strategy_rows)
    near_summary = summarize_near_misses(near_rows)
    scarcity = analyze_signal_scarcity(
        data_rows=data_rows,
        feature_rows=feature_rows,
        strategy_rows=strategy_rows,
        near_miss_count=int(near_summary.get("near_miss_count", 0) or 0),
        stable_filter=stable_filter,
    )
    context = compare_forward_vs_backtest_context(
        reports_root=reports_root,
        strategy_rows=strategy_rows,
        data_rows=data_rows,
    )
    paths = _write_reports(output, data_rows, feature_rows, strategy_rows, near_rows, stable_filter, context, scarcity, features_by_symbol if mt5_connected else {})
    feature_ready_symbols = [row["symbol"] for row in feature_rows if row.get("features_generated")]
    candidate_count = len(strategy_rows)
    summary = {
        "mode": "forward-signal-diagnose",
        "mt5_connected": mt5_connected,
        "symbols_checked": len(selected_symbols),
        "live_data_ready_symbols": [row["symbol"] for row in data_rows if row.get("status") == "READY"],
        "feature_ready_symbols": feature_ready_symbols,
        "candidate_count": candidate_count,
        "near_miss_count": int(near_summary.get("near_miss_count", 0) or 0),
        "top_blockers": scarcity.get("top_blockers", []),
        "classification": scarcity.get("classification"),
        "recommended_action": scarcity.get("recommended_action"),
        "reports_created": [str(output / "signal_scarcity_summary.json"), *paths],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    (output / "signal_scarcity_summary.json").write_text(json.dumps(_jsonable({**summary, "near_miss_summary": near_summary}), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def audit_stable_filter(*, config: BotConfig, symbols: Iterable[str], strategy_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    effective = effective_profile_config(config.signal_profile, source="forward-signal-diagnose", profile_config=config.profile_config or None)
    filters = dict(effective.filters)
    disabled_symbols = list(filters.get("disabled_symbols") or [])
    disabled_strategies = list(filters.get("disabled_strategies") or [])
    blocked_sessions = list(filters.get("blocked_sessions") or [])
    blocked_regimes = list(filters.get("blocked_regimes") or [])
    rows = [dict(row) for row in strategy_rows]
    all_symbols_disabled = bool(symbols) and all(str(symbol).upper() in set(disabled_symbols) for symbol in symbols)
    all_rows_blocked = bool(rows) and all(any(str(reason).startswith("STABLE_") for reason in _as_tuple(row.get("threshold_failures"))) for row in rows)
    classification = "STABLE_FILTER_TOO_RESTRICTIVE" if all_symbols_disabled or all_rows_blocked else "STABLE_FILTER_OK"
    return {
        "profile": effective.profile_name,
        "profile_hash": effective.profile_hash,
        "disabled_symbols": disabled_symbols,
        "disabled_strategies": disabled_strategies,
        "blocked_sessions": blocked_sessions,
        "blocked_regimes": blocked_regimes,
        "allowed_symbols": [symbol for symbol in symbols if str(symbol).upper() not in set(disabled_symbols)],
        "allowed_strategies": "ALL_EXCEPT_DISABLED",
        "current_session": sorted({str(row.get("session", "")) for row in rows if row.get("session")}),
        "current_regime": sorted({str(row.get("regime", "")) for row in rows if row.get("regime")}),
        "classification": classification,
        "recommended_action": "Run stability repair with less restrictive filters in research only." if classification == "STABLE_FILTER_TOO_RESTRICTIVE" else "Keep stable filters.",
        "execution_attempted": False,
    }


def compare_forward_vs_backtest_context(*, reports_root: str | Path, strategy_rows: Iterable[Mapping[str, Any]], data_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    root = Path(reports_root)
    backtest_summary = _load_json(root / "profile_runs" / "balanced_stable" / "summary.json") or _load_json(root / "backtests" / "summary.json")
    rows = [dict(row) for row in strategy_rows]
    data = [dict(row) for row in data_rows]
    spread_blockers = sum(1 for row in data if "LIVE_SPREAD_TOO_HIGH" in _as_tuple(row.get("blockers")))
    if spread_blockers:
        classification = "SPREAD_ENVIRONMENT_DIFFERENT"
    elif rows and all(str(row.get("action")) == "NONE" for row in rows):
        classification = "FORWARD_PIPELINE_OK_WAIT_FOR_SETUP"
    elif not rows:
        classification = "FEATURE_PIPELINE_NOT_READY"
    else:
        classification = "NEEDS_MORE_FORWARD_TIME"
    return {
        "classification": classification,
        "backtest_total_trades": backtest_summary.get("total_trades", backtest_summary.get("trades_generated")),
        "backtest_trades_by_symbol": backtest_summary.get("trades_by_symbol", {}),
        "backtest_trades_by_strategy": backtest_summary.get("trades_by_strategy", {}),
        "forward_sessions": sorted({str(row.get("session", "")) for row in rows if row.get("session")}),
        "forward_regimes": sorted({str(row.get("regime", "")) for row in rows if row.get("regime")}),
        "forward_spread_points": [row.get("spread_points") for row in data if row.get("spread_points") is not None],
        "execution_attempted": False,
    }


def _audit_candidates(*, database: TelemetryDatabase, audit_logger: JsonlAuditLogger, rows: Iterable[Mapping[str, Any]]) -> None:
    from .forward_candidate_audit import audit_forward_candidate

    for row in rows:
        symbol = str(row.get("symbol") or "")
        audit_forward_candidate(database=database, audit_logger=audit_logger, run_id="forward_signal_diagnose", event_type="FORWARD_CANDIDATE_EVALUATED", payload=row, symbol=symbol)
        if str(row.get("action")) == "NONE" or not bool(row.get("passed_thresholds")):
            audit_forward_candidate(database=database, audit_logger=audit_logger, run_id="forward_signal_diagnose", event_type="FORWARD_CANDIDATE_BLOCKED", payload=row, symbol=symbol)
        if row.get("near_miss"):
            audit_forward_candidate(database=database, audit_logger=audit_logger, run_id="forward_signal_diagnose", event_type="FORWARD_NEAR_MISS", payload=row, symbol=symbol)
    if not list(rows):
        audit_forward_candidate(database=database, audit_logger=audit_logger, run_id="forward_signal_diagnose", event_type="FORWARD_NO_SIGNAL_DIAGNOSTIC", payload={"no_signal_reason": "NO_RUNTIME_CANDIDATES", "execution_attempted": False})


def _write_reports(
    output: Path,
    data_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    strategy_rows: list[dict[str, Any]],
    near_rows: list[dict[str, Any]],
    stable_filter: Mapping[str, Any],
    context: Mapping[str, Any],
    scarcity: Mapping[str, Any],
    features_by_symbol: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    paths = {
        "live_data_quality": output / "live_data_quality.csv",
        "live_feature_probe": output / "live_feature_probe.csv",
        "live_feature_contract_summary": output / "live_feature_contract_summary.json",
        "live_feature_contract_by_symbol": output / "live_feature_contract_by_symbol.csv",
        "feature_build_errors": output / "feature_build_errors.csv",
        "live_strategy_probe": output / "live_strategy_probe.csv",
        "near_misses": output / "near_misses.csv",
        "stable_filter": output / "stable_filter_audit.json",
        "context": output / "forward_vs_backtest_context.json",
        "html": output / "report.html",
    }
    _frame(data_rows).to_csv(paths["live_data_quality"], index=False)
    _frame(feature_rows).to_csv(paths["live_feature_probe"], index=False)
    feature_errors = [row for row in feature_rows if not row.get("features_generated")]
    contract_summary = {
        "mode": "live-feature-contract",
        "symbols_checked": len(feature_rows),
        "feature_ready_symbols": [row.get("symbol") for row in feature_rows if row.get("features_generated")],
        "schema_ok": bool(feature_rows) and not feature_errors,
        "features_ok": bool(feature_rows) and not feature_errors,
        "top_blockers": _top_blockers(feature_rows),
        "execution_attempted": False,
    }
    paths["live_feature_contract_summary"].write_text(json.dumps(_jsonable(contract_summary), indent=2, sort_keys=True), encoding="utf-8")
    _frame(_contract_rows(feature_rows)).to_csv(paths["live_feature_contract_by_symbol"], index=False)
    _frame(feature_errors).to_csv(paths["feature_build_errors"], index=False)
    for symbol, features in features_by_symbol.items():
        sample_path = output / f"feature_sample_{str(symbol).upper()}.csv"
        _frame([{key: value for key, value in features.items() if isinstance(value, (str, int, float, bool)) or value is None}]).to_csv(sample_path, index=False)
        paths[f"feature_sample_{str(symbol).upper()}"] = sample_path
    _frame(strategy_rows).to_csv(paths["live_strategy_probe"], index=False)
    _frame(near_rows).to_csv(paths["near_misses"], index=False)
    paths["stable_filter"].write_text(json.dumps(_jsonable(stable_filter), indent=2, sort_keys=True), encoding="utf-8")
    paths["context"].write_text(json.dumps(_jsonable(context), indent=2, sort_keys=True), encoding="utf-8")
    paths["html"].write_text(f"<html><body><h1>Forward Signal Diagnostics</h1><pre>{json.dumps(_jsonable({'scarcity': scarcity, 'stable_filter': stable_filter, 'context': context}), indent=2, sort_keys=True)}</pre></body></html>", encoding="utf-8")
    return [str(path) for path in paths.values()]


def _contract_rows(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in feature_rows:
        blockers = _as_tuple(row.get("blockers"))
        rows.append(
            {
                "symbol": row.get("symbol"),
                "timeframe": "M5",
                "schema_ok": bool(row.get("features_generated")),
                "timestamps_ok": row.get("timestamp_status") == "OK",
                "numeric_ok": row.get("feature_build_error_type") != "LIVE_NUMERIC_CAST_FAILED",
                "row_counts_ok": row.get("feature_build_error_type") != "LIVE_INSUFFICIENT_ROWS_FOR_FEATURES",
                "features_ok": bool(row.get("features_generated")),
                "rows": (row.get("row_count_by_timeframe") or {}).get("M5", 0) if isinstance(row.get("row_count_by_timeframe"), Mapping) else 0,
                "columns_before": "|".join(str(item) for item in _as_tuple(row.get("schema_before"))),
                "columns_after": "|".join(str(item) for item in _as_tuple(row.get("schema_after"))),
                "blockers": "|".join(str(item) for item in blockers),
                "execution_attempted": False,
            }
        )
    return rows


def _top_blockers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        for blocker in _as_tuple(row.get("blockers")):
            counter[str(blocker)] += 1
    return [{"blocking_reason": key, "count": value} for key, value in counter.most_common(10)]


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _not_connected(symbol: str) -> dict[str, Any]:
    return {"symbol": symbol, "status": "NOT_READY", "blockers": ("MT5_CONNECTION_FAILED",), "execution_attempted": False}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

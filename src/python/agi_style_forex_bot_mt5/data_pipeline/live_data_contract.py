"""Canonical OHLCV contract for live MT5 runtime rates."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.execution import MT5Connector

REQUIRED_LIVE_CONTRACT_COLUMNS = (
    "timestamp_utc",
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
OHLC = ("open", "high", "low", "close")
DIAGNOSTIC_MIN_BARS = {"M5": 200, "M15": 200, "H1": 100}


@dataclass(frozen=True)
class LiveContractResult:
    frame: pd.DataFrame
    diagnostics: dict[str, Any]


def normalize_ohlcv_contract(
    data: Any,
    *,
    source: str,
    symbol: str,
    timeframe: str,
    min_rows: int | None = None,
) -> LiveContractResult:
    """Normalize historical or live MT5 rates to one canonical schema."""

    columns_before: tuple[str, ...] = ()
    try:
        raw = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    except Exception as exc:
        return LiveContractResult(_empty(), _diag("LIVE_SCHEMA_MISMATCH", source, symbol, timeframe, error=str(exc)))
    columns_before = tuple(str(column) for column in raw.columns)
    if raw.empty:
        return LiveContractResult(_empty(), _diag("LIVE_RATES_EMPTY", source, symbol, timeframe, columns_before=columns_before))
    frame = raw.copy()
    frame.columns = [str(column).strip().strip("\ufeff").lower() for column in frame.columns]
    schema_after_initial = tuple(frame.columns)
    aliases = {
        "datetime": "timestamp_utc",
        "timestamp": "timestamp_utc",
        "date_time": "timestamp_utc",
        "volume": "tick_volume",
        "vol": "tick_volume",
    }
    for source_column, target_column in aliases.items():
        if source_column in frame.columns and target_column not in frame.columns:
            frame[target_column] = frame[source_column]
    if "timestamp_utc" not in frame.columns and "time" in frame.columns:
        frame["timestamp_utc"] = frame["time"]
    missing = [column for column in ("timestamp_utc", *OHLC) if column not in frame.columns]
    if "tick_volume" not in frame.columns:
        missing.append("tick_volume")
    if missing:
        return LiveContractResult(frame, _diag("LIVE_MISSING_REQUIRED_COLUMNS", source, symbol, timeframe, columns_before=columns_before, columns_after=tuple(frame.columns), missing_columns=missing))
    timestamp, timestamp_status = _parse_timestamp(frame["timestamp_utc"])
    if timestamp_status != "OK":
        return LiveContractResult(frame, _diag(timestamp_status, source, symbol, timeframe, columns_before=columns_before, columns_after=tuple(frame.columns)))
    frame["timestamp_utc"] = timestamp
    frame["time"] = frame["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    contract_warnings: list[str] = []
    if "spread" not in frame.columns:
        frame["spread"] = 0
        contract_warnings.append("CSV_SPREAD_MISSING_ASSUMED_ZERO" if source == "historical" else "CSV_SPREAD_MISSING_ASSUMED_ZERO")
    if "real_volume" not in frame.columns:
        frame["real_volume"] = 0
    numeric_columns = ["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    numeric_error = _coerce_numeric(frame, numeric_columns)
    if numeric_error:
        return LiveContractResult(frame, _diag("LIVE_NUMERIC_CAST_FAILED", source, symbol, timeframe, columns_before=columns_before, columns_after=tuple(frame.columns), error=numeric_error))
    null_counts = {column: int(frame[column].isna().sum()) for column in ("timestamp_utc", *numeric_columns) if column in frame.columns}
    if any(null_counts.get(column, 0) for column in ("timestamp_utc", *OHLC, "tick_volume")):
        return LiveContractResult(frame, _diag("LIVE_NUMERIC_CAST_FAILED", source, symbol, timeframe, columns_before=columns_before, columns_after=tuple(frame.columns), null_counts=null_counts, error="critical nulls after normalization"))
    duplicates = int(frame["timestamp_utc"].duplicated().sum())
    frame = frame.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last").reset_index(drop=True)
    required_rows = int(min_rows if min_rows is not None else DIAGNOSTIC_MIN_BARS.get(timeframe.upper(), 200))
    status = "OK"
    blockers: list[str] = []
    blockers.extend(contract_warnings)
    if duplicates:
        blockers.append("LIVE_DUPLICATE_TIMESTAMPS")
    if len(frame) < required_rows:
        status = "LIVE_INSUFFICIENT_ROWS_FOR_FEATURES"
        blockers.append(status)
    for column in REQUIRED_LIVE_CONTRACT_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0 if column in {"spread", "real_volume"} else ""
    if source == "historical":
        frame = frame.drop(columns=["volume", "spread_points"], errors="ignore")
        ordered = list(REQUIRED_LIVE_CONTRACT_COLUMNS)
    else:
        frame["volume"] = frame["tick_volume"]
        frame["spread_points"] = frame["spread"]
        frame["symbol"] = symbol
        frame["timeframe"] = timeframe
        ordered = list(REQUIRED_LIVE_CONTRACT_COLUMNS) + ["volume", "spread_points", "symbol", "timeframe"]
    frame = frame.loc[:, ordered + [column for column in frame.columns if column not in ordered]]
    diagnostics = _diag(
        status,
        source,
        symbol,
        timeframe,
        columns_before=columns_before,
        columns_after=tuple(frame.columns),
        schema_before=schema_after_initial,
        rows_before=int(len(raw)),
        rows_after=int(len(frame)),
        null_counts=null_counts,
        duplicate_timestamps=duplicates,
        blockers=blockers,
        first_timestamp_utc=frame["timestamp_utc"].iloc[0].isoformat() if not frame.empty else "",
        last_timestamp_utc=frame["timestamp_utc"].iloc[-1].isoformat() if not frame.empty else "",
        last_closed_candle_utc=_last_closed(frame),
        last_candle_incomplete=True,
    )
    return LiveContractResult(frame, diagnostics)


def build_live_feature_contract_report(
    *,
    config: BotConfig,
    symbols: Iterable[str],
    output_dir: str | Path,
    mt5_client: Any | None = None,
) -> dict[str, Any]:
    """Audit live MT5 rate schemas without producing strategy signals."""

    connector = MT5Connector(config=config, mt5_client=mt5_client)
    initialize = getattr(connector.mt5, "initialize", None)
    mt5_connected = (not callable(initialize)) or initialize() is True
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    selected_symbols = [str(item).strip().upper() for item in symbols if str(item).strip()]
    if mt5_connected:
        for symbol in selected_symbols:
            resolution_check, resolution = connector.resolve_symbol(symbol)
            if not resolution_check.accepted or resolution is None:
                rows.append({"symbol": symbol, "timeframe": "", "schema_ok": False, "blockers": "LIVE_SYMBOL_NOT_READY", "execution_attempted": False})
                continue
            for timeframe in ("M5", "M15", "H1"):
                count = _bars_for(config, timeframe)
                mt5_tf = getattr(connector.mt5, f"TIMEFRAME_{timeframe}", timeframe)
                raw = connector.mt5.copy_rates_from_pos(resolution.broker_symbol, mt5_tf, 0, count)
                result = normalize_ohlcv_contract(raw, source="live_mt5", symbol=symbol, timeframe=timeframe, min_rows=DIAGNOSTIC_MIN_BARS[timeframe])
                diag = result.diagnostics
                rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "schema_ok": diag["status"] == "OK",
                        "timestamps_ok": diag["timestamp_status"] == "OK",
                        "numeric_ok": diag["status"] not in {"LIVE_NUMERIC_CAST_FAILED"},
                        "row_counts_ok": int(diag.get("rows_after", 0) or 0) >= DIAGNOSTIC_MIN_BARS[timeframe],
                        "features_ok": diag["status"] == "OK",
                        "rows": diag.get("rows_after", 0),
                        "columns_before": "|".join(diag.get("columns_before", [])),
                        "columns_after": "|".join(diag.get("columns_after", [])),
                        "blockers": "|".join(diag.get("blockers", [])) or ("" if diag["status"] == "OK" else diag["status"]),
                        "execution_attempted": False,
                    }
                )
    summary = {
        "mode": "live-feature-contract",
        "mt5_connected": mt5_connected,
        "symbols_checked": len(selected_symbols),
        "schema_ok": bool(rows) and all(row["schema_ok"] for row in rows),
        "features_ok": bool(rows) and all(row["features_ok"] for row in rows),
        "reports_created": [str(output / "live_feature_contract_summary.json"), str(output / "live_feature_contract_by_symbol.csv")],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    (output / "live_feature_contract_summary.json").write_text(json.dumps(_jsonable({**summary, "rows": rows}), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(output / "live_feature_contract_by_symbol.csv", rows)
    return summary


def _bars_for(config: BotConfig, timeframe: str) -> int:
    return int(getattr(config, f"live_{timeframe.lower()}_bars", DIAGNOSTIC_MIN_BARS.get(timeframe, 200)))


def _parse_timestamp(series: pd.Series) -> tuple[pd.Series, str]:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        unit = "ms" if float(numeric.dropna().median()) > 10_000_000_000 else "s"
        parsed = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        parsed = pd.to_datetime(series, utc=True, errors="coerce")
    if parsed.isna().any():
        return parsed, "LIVE_TIMESTAMP_NOT_DATETIME"
    if not pd.api.types.is_datetime64_any_dtype(parsed):
        return parsed, "LIVE_TIMESTAMP_NOT_DATETIME"
    return parsed, "OK"


def _coerce_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> str:
    for column in columns:
        if column not in frame.columns:
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.isna().any():
            return f"{column} contains non-numeric values"
        frame[column] = converted.astype(float)
    return ""


def _last_closed(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    if len(frame) == 1:
        return frame["timestamp_utc"].iloc[0].isoformat()
    return frame["timestamp_utc"].iloc[-2].isoformat()


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_LIVE_CONTRACT_COLUMNS)


def _diag(
    status: str,
    source: str,
    symbol: str,
    timeframe: str,
    **extra: Any,
) -> dict[str, Any]:
    blockers = list(extra.pop("blockers", []))
    if status != "OK" and status not in blockers:
        blockers.append(status)
    return {
        "status": status,
        "feature_build_error_type": status if status != "OK" else "",
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp_status": "OK" if status not in {"LIVE_TIMESTAMP_NOT_DATETIME", "LIVE_TIMESTAMP_NOT_UTC"} else status,
        "blockers": tuple(blockers),
        "missing_columns": tuple(extra.pop("missing_columns", ())),
        "invalid_dtypes": tuple(),
        "schema_before": tuple(extra.pop("schema_before", ())),
        "schema_after": tuple(extra.get("columns_after", ())),
        "execution_attempted": False,
        **extra,
    }


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["symbol", "timeframe", "blockers"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

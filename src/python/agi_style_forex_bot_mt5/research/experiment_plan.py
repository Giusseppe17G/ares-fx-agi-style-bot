"""Immutable, strict and development-only protocol for a predeclared comparison."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping

import pandas as pd

from ..backtesting.backtester import CostModel
from ..core.instruments import InstrumentSpec
from ..data.market_data import validate_ohlcv_frame
from ..data.strategy_features import FEATURE_VERSION
from ..strategy.strategy_trend_pullback import STRATEGY_NAME, STRATEGY_VERSION, TrendPullbackResearchParams

EVALUATOR_VERSION = "trend_pullback_research_v1"
SCHEMA_VERSION = "predeclared_research_plan_v1"
BAR_DURATION = pd.Timedelta(minutes=5)
SPLIT_NAMES = ("train", "validation", "development_test")
ROLES = {"DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED", "SYNTHETIC_FIXTURE"}
BAR_COLUMNS = ("timestamp_utc", "open", "high", "low", "close", "volume", "spread_points", "symbol", "timeframe")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return float(value)


def _keys(value: Any, names: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != names:
        raise ValueError(f"invalid {label} fields; expected {sorted(names)}")


def _hash(value: Any, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(f"{label} must be a SHA256 hex digest")


def _text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be nonempty text")


def _utc(value: Any) -> pd.Timestamp:
    if not isinstance(value, (str, pd.Timestamp)):
        raise ValueError("timestamp must be explicit timezone-aware text or Timestamp")
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("timestamp must be valid and timezone-aware")
    return result.tz_convert("UTC")


@dataclass(frozen=True)
class ResearchManagement:
    max_holding_bars: int = 96
    break_even_trigger_r: float | None = .6
    break_even_lock_points: float = 0
    trailing_start_r: float | None = .8
    trailing_distance_points: float = 80

    def __post_init__(self) -> None:
        if type(self.max_holding_bars) is not int or self.max_holding_bars <= 0:
            raise ValueError("max_holding_bars must be a positive integer")
        for name in ("break_even_trigger_r", "trailing_start_r", "break_even_lock_points", "trailing_distance_points"):
            value = getattr(self, name)
            if value is None and name in {"break_even_trigger_r", "trailing_start_r"}:
                continue
            object.__setattr__(self, name, _number(value, name))


@dataclass(frozen=True)
class ResearchHypothesis:
    hypothesis_id: str
    params: TrendPullbackResearchParams


@dataclass(frozen=True)
class ResearchSplit:
    name: str
    start_utc: str
    end_utc: str


def _hypotheses() -> list[dict[str, Any]]:
    rows = []
    for threshold in (62, 70, 78):
        params = TrendPullbackResearchParams(min_score=threshold).to_dict()
        identity = {"strategy_name": STRATEGY_NAME, "strategy_version": STRATEGY_VERSION, "params": params}
        rows.append({"hypothesis_id": _digest(identity), "params": params})
    return rows


def _splits(start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, str]]:
    if start >= end:
        raise ValueError("datasets have no common temporal interval")
    # Integer nanoseconds make the 60/20/20 calculation independent of float rounding.
    duration = end.value - start.value
    cuts = (start, start + pd.Timedelta(duration * 3 // 5, unit="ns"), start + pd.Timedelta(duration * 4 // 5, unit="ns"), end)
    return [{"name": name, "start_utc": cuts[i].isoformat(), "end_utc": cuts[i+1].isoformat()} for i, name in enumerate(SPLIT_NAMES)]


def normalize_research_bars(candles: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    """Normalize aliases, never sort, drop duplicates, impute prices or infer timezone."""
    if not isinstance(candles, pd.DataFrame) or candles.empty or candles.columns.duplicated().any():
        raise ValueError("research bars must be a nonempty DataFrame with unique columns")
    bars = candles.copy()
    for alias, target in (("timestamp", "timestamp_utc"), ("tick_volume", "volume")):
        if alias in bars and target in bars:
            raise ValueError(f"ambiguous {alias}/{target} columns")
        if alias in bars:
            bars = bars.rename(columns={alias: target})
    required = set(BAR_COLUMNS) - {"symbol", "timeframe"}
    if required - set(bars):
        raise ValueError(f"missing research bar columns: {sorted(required-set(bars))}")
    times = [_utc(value) for value in bars["timestamp_utc"]]
    bars["timestamp_utc"] = pd.DatetimeIndex(times)
    if bars["timestamp_utc"].duplicated().any() or not bars["timestamp_utc"].is_monotonic_increasing:
        raise ValueError("research timestamps must be unique and chronological")
    if (bars["timestamp_utc"].diff().dropna() < BAR_DURATION).any():
        raise ValueError("overlapping M5 bars")
    for name, expected in (("symbol", symbol), ("timeframe", "M5")):
        if name in bars and not bars[name].eq(expected).all():
            raise ValueError(f"research {name} mismatch")
        bars[name] = expected
    for name in ("open", "high", "low", "close", "volume", "spread_points"):
        if any(isinstance(value, bool) for value in bars[name]):
            raise ValueError("boolean bar values are not numbers")
        bars[name] = pd.to_numeric(bars[name], errors="raise").astype(float)
    validate_ohlcv_frame(bars, require_spread=True)
    return bars.loc[:, BAR_COLUMNS].reset_index(drop=True)


def _frame_hash(bars: pd.DataFrame) -> str:
    rows = bars.copy()
    rows["timestamp_utc"] = rows["timestamp_utc"].map(lambda value: value.isoformat())
    return _digest({"columns": list(BAR_COLUMNS), "rows": rows.loc[:, BAR_COLUMNS].values.tolist()})


def dataframe_sha256(candles: pd.DataFrame, *, symbol: str) -> str:
    return _frame_hash(normalize_research_bars(candles, symbol=symbol))


def _split_bars(bars: pd.DataFrame, split: Mapping[str, str]) -> pd.DataFrame:
    # Both the source bar and its complete interval belong to this partition.
    times = bars["timestamp_utc"]
    return bars.loc[(times >= _utc(split["start_utc"])) & (times + BAR_DURATION <= _utc(split["end_utc"]))]


def _binding(bars: pd.DataFrame, splits: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "data_sha256": _frame_hash(bars), "rows": len(bars),
        "first_timestamp_utc": bars.iloc[0]["timestamp_utc"].isoformat(),
        "last_timestamp_utc": bars.iloc[-1]["timestamp_utc"].isoformat(),
        "split_bindings": {s["name"]: {"rows": len(_split_bars(bars, s)), "data_sha256": _frame_hash(_split_bars(bars, s))} for s in splits},
    }


def _validate_instrument_cost(spec: InstrumentSpec, cost: CostModel, lot: float) -> None:
    spec.validate()
    if not 0 <= spec.digits <= 323:
        raise ValueError("instrument digits must be in [0, 323]")
    with localcontext() as context:
        context.prec = 700
        point, tick = Decimal(str(spec.point)), Decimal(str(spec.tick_size))
        if point != Decimal(10) ** -spec.digits or tick % point != 0:
            raise ValueError("instrument point/digits/tick grid geometry is inconsistent")
    cost.validate()
    for name, value in asdict(cost).items():
        _number(value, name, positive=name in {"point", "tick_size", "tick_value", "max_spread_points"})
    for name in ("point", "tick_size", "tick_value"):
        if getattr(cost, name) != getattr(spec, name):
            raise ValueError(f"cost model {name} differs from instrument")
    with localcontext() as context:
        context.prec = 700
        raw, minimum, maximum, step = map(lambda x: Decimal(str(x)), (lot, spec.min_volume, spec.max_volume, spec.volume_step))
        if not minimum <= raw <= maximum or (raw-minimum) % step != 0:
            raise ValueError("lot is outside instrument volume limits or grid")


def _validate_payload(value: Mapping[str, Any]) -> None:
    fields = {"schema_version", "strategy_name", "strategy_version", "evaluator_version", "feature_version", "selection_policy", "data_role", "final_holdout", "timeframe", "warmup_bars", "lot", "initial_balance", "management", "random_seed", "code_commit", "source_sha256", "hypotheses", "splits", "datasets", "denomination_currency"}
    _keys(value, fields, "plan")
    fixed = {"schema_version": SCHEMA_VERSION, "strategy_name": STRATEGY_NAME, "strategy_version": STRATEGY_VERSION, "evaluator_version": EVALUATOR_VERSION, "feature_version": FEATURE_VERSION, "selection_policy": "NONE_COMPARE_ALL", "final_holdout": "NOT_AVAILABLE", "timeframe": "M5", "warmup_bars": 250}
    if any(value[k] != v or type(value[k]) is not type(v) for k, v in fixed.items()):
        raise ValueError("unsupported plan protocol or version")
    if value["data_role"] not in ROLES:
        raise ValueError("unsupported research data role")
    lot = _number(value["lot"], "lot", positive=True)
    _number(value["initial_balance"], "initial_balance", positive=True)
    if not isinstance(value["denomination_currency"], str) or not re.fullmatch("[A-Z]{3}", value["denomination_currency"]):
        raise ValueError("denomination_currency must be three uppercase ASCII letters")
    _keys(value["management"], set(ResearchManagement.__dataclass_fields__), "management")
    ResearchManagement(**value["management"])
    if type(value["random_seed"]) is not int or not 0 <= value["random_seed"] < 2**32:
        raise ValueError("random_seed must be an integer in [0, 2**32)")
    if not isinstance(value["code_commit"], str) or not re.fullmatch("[a-f0-9]{40}", value["code_commit"]):
        raise ValueError("code_commit must be the full Git commit")
    _hash(value["source_sha256"], "source_sha256")
    # Exact identity AND value/type validation, not Python's bool == 1 equality.
    if not isinstance(value["hypotheses"], list) or len(value["hypotheses"]) != 3:
        raise ValueError("exactly three predeclared hypotheses required")
    for item in value["hypotheses"]:
        _keys(item, {"hypothesis_id", "params"}, "hypothesis")
        _keys(item["params"], set(TrendPullbackResearchParams.__dataclass_fields__), "params")
        TrendPullbackResearchParams.from_dict(item["params"])
    if value["hypotheses"] != _hypotheses():
        raise ValueError("hypotheses differ from predeclared comparison")
    datasets = value["datasets"]
    if not isinstance(datasets, dict) or not datasets:
        raise ValueError("plan datasets required")
    for symbol, entry in datasets.items():
        if symbol not in {"EURUSD", "GBPUSD", "USDJPY"}:
            raise ValueError("unsupported initial universe symbol")
        _keys(entry, {"data_sha256", "rows", "first_timestamp_utc", "last_timestamp_utc", "split_bindings", "instrument", "cost_model", "data_provenance", "cost_provenance"}, "dataset")
        _hash(entry["data_sha256"], "dataset hash")
        if type(entry["rows"]) is not int or entry["rows"] < 1:
            raise ValueError("dataset row count must be positive")
        if _utc(entry["first_timestamp_utc"]) > _utc(entry["last_timestamp_utc"]):
            raise ValueError("invalid dataset interval")
        _keys(entry["instrument"], set(InstrumentSpec.__dataclass_fields__), "instrument")
        _keys(entry["cost_model"], set(CostModel.__dataclass_fields__), "cost model")
        spec, cost = InstrumentSpec(**entry["instrument"]), CostModel(**entry["cost_model"])
        if spec.symbol != symbol or spec.canonical_symbol != symbol:
            raise ValueError("instrument symbol mismatch")
        _validate_instrument_cost(spec, cost, lot)
        data_prov, cost_prov = entry["data_provenance"], entry["cost_provenance"]
        _keys(data_prov, {"source_sha256", "provider", "quality_report", "tick_value_currency", "tick_value_status"}, "data provenance")
        _hash(data_prov["source_sha256"], "source data hash")
        _text(data_prov["provider"], "provider")
        if not isinstance(data_prov["quality_report"], dict):
            raise ValueError("quality_report must be an explicit JSON object")
        _keys(cost_prov, {"source", "assumptions", "commission_currency", "swap_mode", "status"}, "cost provenance")
        if data_prov["tick_value_currency"] != value["denomination_currency"] or cost_prov["commission_currency"] != value["denomination_currency"]:
            raise ValueError("tick value and commission currencies must equal denomination_currency; no implicit conversion")
        if data_prov["tick_value_status"] not in {"ASSUMED", "OBSERVED"} or cost_prov["status"] not in {"ASSUMED", "OBSERVED"}:
            raise ValueError("monetary provenance status must be ASSUMED or OBSERVED")
        for name in ("source", "commission_currency", "swap_mode"):
            _text(cost_prov[name], name)
        if cost_prov["swap_mode"] != "NOT_MODELED":
            raise ValueError("swap_mode must be NOT_MODELED; this engine has no swap model")
        if not isinstance(cost_prov["assumptions"], list) or not all(isinstance(x, str) and x.strip() for x in cost_prov["assumptions"]):
            raise ValueError("cost assumptions must be a list of explicit strings")
        _keys(entry["split_bindings"], set(SPLIT_NAMES), "split bindings")
        for binding in entry["split_bindings"].values():
            _keys(binding, {"rows", "data_sha256"}, "split binding")
            if type(binding["rows"]) is not int or not 0 <= binding["rows"] <= entry["rows"]:
                raise ValueError("invalid split row count")
            _hash(binding["data_sha256"], "split data hash")
    start = max(_utc(x["first_timestamp_utc"]) for x in datasets.values())
    end = min(_utc(x["last_timestamp_utc"]) + BAR_DURATION for x in datasets.values())
    if value["splits"] != _splits(start, end):
        raise ValueError("splits must be common UTC 60/20/20 intervals")
    canonical_json(value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


@dataclass(frozen=True)
class ExperimentPlan:
    """Only immutable canonical bytes are stored; all exposed containers are copies."""
    canonical_json: str

    def __post_init__(self) -> None:
        payload = json.loads(self.canonical_json, object_pairs_hook=_unique_object,
                             parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        _validate_payload(payload)
        object.__setattr__(self, "canonical_json", canonical_json(payload))

    @classmethod
    def from_json(cls, text: str) -> "ExperimentPlan":
        return cls(text)

    @property
    def plan_id(self) -> str:
        return sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.to_dict()["datasets"]))

    @property
    def hypotheses(self) -> tuple[ResearchHypothesis, ...]:
        return tuple(ResearchHypothesis(x["hypothesis_id"], TrendPullbackResearchParams.from_dict(x["params"])) for x in self.to_dict()["hypotheses"])

    @property
    def splits(self) -> tuple[ResearchSplit, ...]:
        return tuple(ResearchSplit(**x) for x in self.to_dict()["splits"])


def build_experiment_plan(datasets: Mapping[str, pd.DataFrame], *, instruments: Mapping[str, InstrumentSpec], cost_models: Mapping[str, CostModel], data_provenance: Mapping[str, Mapping[str, Any]], cost_provenance: Mapping[str, Mapping[str, Any]], code_commit: str, source_sha256: str, data_role: str, lot: float, denomination_currency: str, initial_balance: float = 10000., management: ResearchManagement = ResearchManagement(), random_seed: int = 1729) -> ExperimentPlan:
    if not datasets or any(set(mapping) != set(datasets) for mapping in (instruments, cost_models, data_provenance, cost_provenance)):
        raise ValueError("dataset, instrument, cost and provenance symbol sets must match")
    if not isinstance(management, ResearchManagement):
        raise ValueError("management must be ResearchManagement")
    frames = {symbol: normalize_research_bars(frame, symbol=symbol) for symbol, frame in datasets.items()}
    splits = _splits(max(x.iloc[0]["timestamp_utc"] for x in frames.values()), min(x.iloc[-1]["timestamp_utc"] + BAR_DURATION for x in frames.values()))
    entries = {symbol: {**_binding(frame, splits), "instrument": instruments[symbol].as_dict(), "cost_model": asdict(cost_models[symbol]), "data_provenance": dict(data_provenance[symbol]), "cost_provenance": dict(cost_provenance[symbol])} for symbol, frame in frames.items()}
    payload = {"schema_version": SCHEMA_VERSION, "strategy_name": STRATEGY_NAME, "strategy_version": STRATEGY_VERSION, "evaluator_version": EVALUATOR_VERSION, "feature_version": FEATURE_VERSION, "selection_policy": "NONE_COMPARE_ALL", "data_role": data_role, "final_holdout": "NOT_AVAILABLE", "timeframe": "M5", "warmup_bars": 250, "lot": lot, "initial_balance": initial_balance, "management": asdict(management), "random_seed": random_seed, "code_commit": code_commit, "source_sha256": source_sha256, "hypotheses": _hypotheses(), "splits": splits, "datasets": entries, "denomination_currency": denomination_currency}
    return ExperimentPlan(canonical_json(payload))


def validate_plan_datasets(plan: ExperimentPlan, datasets: Mapping[str, pd.DataFrame]) -> None:
    payload = plan.to_dict()
    if set(datasets) != set(plan.symbols):
        raise ValueError("dataset symbols differ from plan")
    for symbol, frame in datasets.items():
        bindings = _binding(normalize_research_bars(frame, symbol=symbol), payload["splits"])
        if any(payload["datasets"][symbol][key] != value for key, value in bindings.items()):
            raise ValueError(f"dataset hash/rows/splits differ from plan: {symbol}")

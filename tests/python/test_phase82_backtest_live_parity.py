"""FASE 82 - backtest/live parity, instrument registry, shared execution, baselines."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agi_style_forex_bot_mt5.backtesting.backtester import (
    _apply_entry_cost,
    _apply_exit_cost,
    _snapshot_from_row,
    run_backtest_for_symbols,
)
from agi_style_forex_bot_mt5.config import BotConfig, load_config
from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.core import FrozenClock, assert_safety_flags, workspace_paths
from agi_style_forex_bot_mt5.core.execution import SharedFillModel
from agi_style_forex_bot_mt5.core.instruments import (
    ASSUMED_SOURCE,
    InstrumentRegistry,
    InstrumentSpec,
    assumed_fx_spec,
    is_assumed,
    resolve_registry,
    spec_from_mapping,
    spec_from_symbol_info,
)
from agi_style_forex_bot_mt5.core.operational_state.errors import ExecutionSimulationError, InstrumentError
from agi_style_forex_bot_mt5.core.parity import BACKTEST_ONLY, FORWARD_ONLY, SHARED, build_fixture, compare_pipelines, pipeline_stages
from agi_style_forex_bot_mt5.core.validation import buy_and_hold, compare_to_baselines, permuted_signal, random_entry
from agi_style_forex_bot_mt5.parity_report import run_backtest_live_parity_report

NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
CLOCK = FrozenClock(NOW)

EURUSD_VALUES = {
    "digits": 5,
    "point": 0.00001,
    "tick_size": 0.00001,
    "tick_value": 1.0,
    "contract_size": 100000.0,
    "min_volume": 0.01,
    "max_volume": 100.0,
    "volume_step": 0.01,
    "stops_level_points": 0,
    "freeze_level_points": 0,
    "currency_base": "EUR",
    "currency_quote": "USD",
}


# --------------------------------------------------------------------------- InstrumentRegistry


def test_spec_exposes_every_required_field() -> None:
    spec = spec_from_mapping("EURUSD", EURUSD_VALUES)
    for field in ("symbol", "canonical_symbol", "broker_symbol", "digits", "point", "tick_size", "tick_value", "contract_size", "min_volume", "max_volume", "volume_step", "stops_level_points", "freeze_level_points", "currency_base", "currency_quote"):
        assert hasattr(spec, field)
    assert spec.canonical_symbol == "EURUSD"


def test_registry_lookup_is_case_insensitive_and_discoverable() -> None:
    registry = InstrumentRegistry.from_specs([spec_from_mapping("EURUSD", EURUSD_VALUES)])
    assert registry.has("eurusd") is True
    assert registry.has("GBPUSD") is False
    assert registry.get("EurUsd").digits == 5
    assert registry.symbols() == ["EURUSD"]


def test_missing_instrument_fails_closed() -> None:
    registry = InstrumentRegistry.from_specs([spec_from_mapping("EURUSD", EURUSD_VALUES)])
    with pytest.raises(InstrumentError) as excinfo:
        registry.get("GBPUSD")
    assert "refusing to guess" in str(excinfo.value)


@pytest.mark.parametrize("missing", ["digits", "tick_value", "contract_size", "min_volume", "currency_base"])
def test_incomplete_metadata_fails_closed(missing: str) -> None:
    values = {key: value for key, value in EURUSD_VALUES.items() if key != missing}
    with pytest.raises(InstrumentError) as excinfo:
        spec_from_mapping("EURUSD", values)
    assert missing in str(excinfo.value)


@pytest.mark.parametrize("field,value", [("point", 0.0), ("tick_value", -1.0), ("min_volume", 0.0), ("volume_step", 0.0)])
def test_invalid_instrument_values_are_rejected(field: str, value: float) -> None:
    with pytest.raises(InstrumentError):
        spec_from_mapping("EURUSD", {**EURUSD_VALUES, field: value})


def test_min_volume_above_max_volume_is_rejected() -> None:
    with pytest.raises(InstrumentError):
        spec_from_mapping("EURUSD", {**EURUSD_VALUES, "min_volume": 10.0, "max_volume": 1.0})


def test_spec_from_mt5_symbol_info_uses_broker_metadata() -> None:
    info = {
        "name": "EURUSD.raw",
        "digits": 5,
        "point": 0.00001,
        "trade_tick_size": 0.00001,
        "trade_tick_value": 0.98,
        "trade_contract_size": 100000.0,
        "volume_min": 0.01,
        "volume_max": 200.0,
        "volume_step": 0.01,
        "trade_stops_level": 3,
        "trade_freeze_level": 2,
        "currency_base": "EUR",
        "currency_profit": "USD",
    }
    spec = spec_from_symbol_info("EURUSD", info)
    assert (spec.digits, spec.tick_value, spec.max_volume, spec.stops_level_points) == (5, 0.98, 200.0, 3)
    assert spec.source == "mt5:symbol_info"
    assert is_assumed(spec) is False


def test_missing_mt5_attribute_fails_closed() -> None:
    with pytest.raises(InstrumentError):
        spec_from_symbol_info("EURUSD", {"digits": 5})


def test_dataset_sidecar_is_required_and_loaded(tmp_path: Path) -> None:
    with pytest.raises(InstrumentError):
        InstrumentRegistry.from_dataset(tmp_path)
    (tmp_path / "instruments.json").write_text(json.dumps({"instruments": {"EURUSD": EURUSD_VALUES}}), encoding="utf-8")
    registry = InstrumentRegistry.from_dataset(tmp_path)
    assert registry.get("EURUSD").source.startswith("dataset:")


def test_rounding_uses_instrument_metadata() -> None:
    usdjpy = spec_from_mapping("USDJPY", {**EURUSD_VALUES, "digits": 3, "point": 0.001, "tick_size": 0.001, "currency_base": "USD", "currency_quote": "JPY"})
    assert usdjpy.round_price(150.123456) == 150.123
    assert spec_from_mapping("EURUSD", EURUSD_VALUES).round_price(1.1234567) == 1.12346
    assert usdjpy.round_volume(0.0137) == 0.01
    assert usdjpy.round_volume(500.0) == 100.0


def test_resolution_order_and_strict_mode(tmp_path: Path) -> None:
    explicit = InstrumentRegistry.from_specs([spec_from_mapping("EURUSD", EURUSD_VALUES)])
    registry, source = resolve_registry(registry=explicit, data_dir=tmp_path, symbols=["EURUSD"])
    assert source == "explicit" and registry.get("EURUSD").digits == 5

    (tmp_path / "instruments.json").write_text(json.dumps({"EURUSD": EURUSD_VALUES}), encoding="utf-8")
    _, source = resolve_registry(data_dir=tmp_path, symbols=["EURUSD"])
    assert source.startswith("dataset:")

    _, source = resolve_registry(symbols=["EURUSD"])
    assert source == ASSUMED_SOURCE
    with pytest.raises(InstrumentError):
        resolve_registry(symbols=["EURUSD"], allow_assumptions=False)


def test_assumed_specs_are_labelled_so_reports_can_refuse_them() -> None:
    assert is_assumed(assumed_fx_spec("EURUSD")) is True
    assert assumed_fx_spec("USDJPY").digits == 3
    assert assumed_fx_spec("EURUSD").digits == 5


def test_backtest_snapshot_no_longer_guesses_instrument_metadata() -> None:
    import pandas as pd

    row = pd.Series({"close": 150.000, "spread_points": 10.0, "timestamp_utc": NOW})
    spec = spec_from_mapping("USDJPY", {**EURUSD_VALUES, "digits": 3, "point": 0.001, "tick_size": 0.001, "tick_value": 0.68, "max_volume": 50.0, "stops_level_points": 7, "freeze_level_points": 4, "currency_base": "USD", "currency_quote": "JPY"})
    snapshot = _snapshot_from_row(row, symbol="USDJPY", timeframe="M5", point=spec.point, config=BotConfig(), instrument=spec)

    # Every field now comes from the registry, not from a JPY substring test.
    assert snapshot.digits == 3
    assert snapshot.tick_value == 0.68
    assert snapshot.volume_max == 50.0
    assert snapshot.stops_level_points == 7
    assert snapshot.freeze_level_points == 4
    snapshot.validate()


def test_backtest_summary_declares_where_instrument_metadata_came_from(tmp_path: Path) -> None:
    import pandas as pd

    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    timestamps = pd.date_range("2026-01-01", periods=120, freq="5min", tz="UTC")
    price = 1.10
    rows = []
    for index, timestamp in enumerate(timestamps):
        price += 0.00005
        rows.append({"time": timestamp.isoformat(), "open": price, "high": price + 0.0001, "low": price - 0.0001, "close": price + 0.00003, "tick_volume": 1000 + index, "spread": 10})
    pd.DataFrame(rows).to_csv(data_dir / "EURUSD_M5.csv", index=False)

    assumed = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",), report_dir=tmp_path / "r1")
    assert assumed.summary["instrument_metadata_source"] == ASSUMED_SOURCE
    assert assumed.summary["instrument_metadata_assumed"] is True

    (data_dir / "instruments.json").write_text(json.dumps({"EURUSD": EURUSD_VALUES}), encoding="utf-8")
    declared = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",), report_dir=tmp_path / "r2")
    assert declared.summary["instrument_metadata_source"].startswith("dataset:")
    assert declared.summary["instrument_metadata_assumed"] is False
    assert declared.summary["execution_attempted"] is False


# --------------------------------------------------------------------------- shared execution model


def _snapshot(close: float, spread_points: float, spec: InstrumentSpec) -> MarketSnapshot:
    half = spread_points * spec.point / 2.0
    return MarketSnapshot(
        symbol=spec.canonical_symbol, timeframe="M5", timestamp_utc=NOW,
        bid=close - half, ask=close + half, spread_points=spread_points,
        digits=spec.digits, point=spec.point, tick_value=spec.tick_value, tick_size=spec.tick_size,
        volume_min=spec.min_volume, volume_max=spec.max_volume, volume_step=spec.volume_step,
        stops_level_points=spec.stops_level_points, freeze_level_points=spec.freeze_level_points,
    )


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
@pytest.mark.parametrize("spread_points", [0.0, 4.0, 10.0, 20.0])
def test_backtest_and_paper_price_the_same_fill(direction: str, spread_points: float) -> None:
    """The backtester and paper trading must not price the same bar differently."""

    from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel

    spec = spec_from_mapping("EURUSD", EURUSD_VALUES)
    snapshot = _snapshot(1.10000, spread_points, spec)
    paper = PaperFillModel(max_spread_points=25.0, slippage_points=1.0)
    paper_entry = paper.entry_result(direction=direction, snapshot=snapshot)
    backtest_entry = _apply_entry_cost(1.10000, direction=direction, spread_points=spread_points, slippage_points=1.0, point=spec.point)

    if paper_entry.accepted:
        assert round(backtest_entry, spec.digits) == paper_entry.fill_price

    backtest_exit = _apply_exit_cost(1.10000, direction=direction, spread_points=spread_points, slippage_points=1.0, point=spec.point)
    paper_exit = paper.exit_result(direction=direction, snapshot=snapshot)
    if paper_exit.accepted:
        assert round(backtest_exit, spec.digits) == paper_exit.fill_price


def test_shared_fill_model_rejects_and_reports_structured_errors() -> None:
    spec = spec_from_mapping("EURUSD", EURUSD_VALUES)
    model = SharedFillModel(max_spread_points=5.0, slippage_points=1.0)
    with pytest.raises(ExecutionSimulationError):
        model.entry_price(direction="BUY", snapshot=_snapshot(1.1, 50.0, spec), replay=True)


def test_replayed_bars_are_not_treated_as_stale_ticks() -> None:
    """A stored bar is old by definition; the replay context is what makes it usable."""

    spec = spec_from_mapping("EURUSD", EURUSD_VALUES)
    snapshot = _snapshot(1.10000, 8.0, spec)
    model = SharedFillModel(slippage_points=1.0)
    assert model.entry(direction="BUY", snapshot=snapshot, replay=True, context={"forward_spreads": (8.0,)}).accepted is True
    assert model.entry(direction="BUY", snapshot=snapshot, replay=False).accepted is False


def test_cost_model_takes_geometry_from_the_instrument() -> None:
    from agi_style_forex_bot_mt5.backtesting.backtester import CostModel

    usdjpy = spec_from_mapping("USDJPY", {**EURUSD_VALUES, "digits": 3, "point": 0.001, "tick_size": 0.001, "tick_value": 0.68, "currency_base": "USD", "currency_quote": "JPY"})
    model = CostModel(spread_points=8.0, slippage_points=1.0).with_instrument(usdjpy)
    assert (model.point, model.tick_size, model.tick_value) == (0.001, 0.001, 0.68)
    assert model.spread_points == 8.0
    model.validate()


# --------------------------------------------------------------------------- pipeline parity


def test_stage_map_covers_both_pipelines_and_names_every_gap() -> None:
    stages = pipeline_stages()
    scopes = {stage.stage_id: stage.scope for stage in stages}
    assert scopes["strategy"] == SHARED
    assert scopes["instrument_metadata"] == SHARED
    assert scopes["execution_simulation"] == SHARED
    for forward_only in ("risk_engine", "ml_filter", "signal_ranker", "portfolio_guard", "dynamic_risk", "paper_limits"):
        assert scopes[forward_only] == FORWARD_ONLY
    for backtest_only in ("profile_thresholds", "stable_filters"):
        assert scopes[backtest_only] == SHARED
    # No gap is left without a stated reason.
    for stage in stages:
        if stage.scope != SHARED:
            assert stage.note


def test_shared_stage_decisions_are_equivalent_on_a_deterministic_fixture() -> None:
    report = compare_pipelines(build_fixture(clock=CLOCK))
    assert report["decision_count"] > 0
    assert report["decision_parity_pct"] >= 95.0
    assert report["decision_parity_status"] == "PARITY_OK"
    assert report["parity_status"] == "PARITY_INCOMPLETE"
    assert report["full_pipeline_verified"] is False
    assert report["evidence_scope"] == "SHARED_COMPONENT_SMOKE_TEST"
    assert report["differences"] == []
    assert_safety_flags(report, context="parity report")


def test_parity_run_is_reproducible() -> None:
    first = compare_pipelines(build_fixture(clock=FrozenClock(NOW)))
    second = compare_pipelines(build_fixture(clock=FrozenClock(NOW)))
    assert first == second


def test_parity_report_declares_the_stage_gap_honestly() -> None:
    report = compare_pipelines(build_fixture(clock=CLOCK))
    assert report["parity_gap_stage_count"] == 9
    assert report["stage_parity_pct"] == 43.75
    assert report["shared_stage_count"] + report["parity_gap_stage_count"] == report["stage_count"]
    assert "risk_engine" in report["parity_gap_stage_ids"]


def test_parity_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from agi_style_forex_bot_mt5.cli import main

    assert main(["--mode", "backtest-live-parity", "--output-dir", str(tmp_path / "out")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parity_status"] == "PARITY_INCOMPLETE"
    assert payload["decision_parity_status"] == "PARITY_OK"
    assert payload["decision_parity_pct"] >= 95.0
    assert payload["run_manifest"]["run_id"]
    assert_safety_flags(payload, context="parity CLI")
    assert (tmp_path / "out" / "pipeline_parity.json").exists()


def test_parity_report_writes_nothing_into_production_evidence(tmp_path: Path) -> None:
    production = workspace_paths().project_root / "data"
    before = sorted(str(path) for path in production.rglob("*")) if production.exists() else []
    run_backtest_live_parity_report(output_dir=tmp_path / "out")
    after = sorted(str(path) for path in production.rglob("*")) if production.exists() else []
    assert before == after


# --------------------------------------------------------------------------- baselines


def test_buy_and_hold_baseline() -> None:
    assert buy_and_hold([1.10, 1.12]).net_return == pytest.approx(0.02)
    assert buy_and_hold([1.10]).trades == 0


def test_random_and_permuted_baselines_are_seeded_and_reproducible() -> None:
    closes = [1.10 + 0.0001 * index for index in range(200)]
    assert random_entry(closes, trades=10, seed=7) == random_entry(closes, trades=10, seed=7)
    assert permuted_signal(closes, [5, 20, 50], seed=7) == permuted_signal(closes, [5, 20, 50], seed=7)
    assert random_entry(closes, trades=10, seed=7) != random_entry(closes, trades=10, seed=8)


def test_candidate_must_beat_every_baseline() -> None:
    closes = [1.10 + 0.0001 * index for index in range(200)]
    weak = compare_to_baselines(candidate_net_return=0.001, candidate_trades=10, candidate_win_rate=0.9, closes=closes, signal_bars=[5, 20, 50])
    assert weak["baseline_verdict"] == "CANDIDATE_NOT_DISTINGUISHABLE_FROM_BASELINE"
    assert weak["beats_all_baselines"] is False

    strong = compare_to_baselines(candidate_net_return=1.0, candidate_trades=10, candidate_win_rate=0.55, closes=closes, signal_bars=[5, 20, 50])
    assert strong["baseline_verdict"] == "CANDIDATE_BEATS_ALL_BASELINES"
    assert_safety_flags(strong, context="baseline comparison")


def test_a_high_win_rate_alone_does_not_beat_the_baselines() -> None:
    """The rule this module exists to enforce."""

    closes = [1.10 + 0.0001 * index for index in range(200)]
    result = compare_to_baselines(candidate_net_return=0.0005, candidate_trades=50, candidate_win_rate=0.99, closes=closes, signal_bars=[1, 2, 3])
    assert result["candidate"]["win_rate"] == 0.99
    assert result["beats_all_baselines"] is False


# --------------------------------------------------------------------------- safety


def test_global_safety_defaults_intact() -> None:
    config = load_config(None)
    assert config.demo_only is True
    assert config.live_trading_approved is False

"""Forward paper tracking of the frozen v2 book, on synthetic broker exports only (no market data)."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.broker_swap_snapshot import build_swap_snapshot
from agi_style_forex_bot_mt5.research.daily_fx import forward_runner
from agi_style_forex_bot_mt5.research.daily_fx.data import MT5_USD_PAIRS, ORIENTATION_ANCHORS
from agi_style_forex_bot_mt5.research.daily_fx import forward
from agi_style_forex_bot_mt5.research.daily_fx.forward import (CHECKPOINT, DecisionRule, ForwardRefused,
    _decision_rows, _swap_rates, assemble_inflation, broker_swap_returns, fetch_world_bank_inflation,
    forward_engine_sha256, load_broker_daily, parse_world_bank_inflation, read_inflation_supplement, rule_status,
    run_forward)
from agi_style_forex_bot_mt5.research.daily_fx.plans import REAL_VALUE_V2_PLAN_HASH, value_forward_v1
from agi_style_forex_bot_mt5.research.daily_fx.portfolio import CostModel
from agi_style_forex_bot_mt5.research.trial_registry import TrialLedger

PLAN = value_forward_v1()
CURRENCIES = PLAN.currencies
ROOT = Path(__file__).resolve().parents[2]


def _export(folder, end="2027-03-31", seed=0, shock=None):
    """MT5 D1 exports of the nine USD pairs, bars opening at 00:00 UTC, plus one forming bar."""

    folder.mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range("2017-06-01", end, tz="UTC")
    anchor_row = days.get_loc(pd.Timestamp("2020-01-02", tz="UTC"))
    for number, code in enumerate(CURRENCIES):
        # One stream per currency: a longer export extends exactly the same history.
        steps = np.random.default_rng([seed, number]).normal(0.0, 0.006, size=len(days))
        level = np.cumsum(steps)
        usd_price = ORIENTATION_ANCHORS[code] * np.exp(level - level[anchor_row])
        if shock is not None and shock[0] == code:
            usd_price[days.get_loc(pd.Timestamp(shock[1], tz="UTC"))] *= 1.01
        symbol, usd_base = MT5_USD_PAIRS[code]
        close = 1.0 / usd_price if usd_base else usd_price
        stamps = list(days.strftime("%Y-%m-%dT00:00:00Z")) + [(days[-1] + pd.offsets.BDay(1)).strftime(
            "%Y-%m-%dT00:00:00Z")]
        closes = list(close) + [close[-1] * 1.5]  # the forming bar: must be dropped
        pd.DataFrame({"time": stamps, "close": closes, "timestamp_utc": stamps}).to_csv(
            folder / f"{symbol}_D1.csv", index=False)
    return folder


def _base_inflation(last=2024):
    years = range(1990, last + 1)
    rng = np.random.default_rng(3)
    return pd.DataFrame({code: rng.uniform(0.0, 4.0, len(years)) for code in ("USD", *CURRENCIES)},
                        index=list(years))


def _supplement(years=(2025,), value=2.5, missing=None):
    rows = []
    for year in years:
        for code in ("USD", *CURRENCIES):
            if missing == (code, year):
                continue
            rows.append({"code": code, "year": year, "value": value})
    wide = pd.DataFrame(rows).pivot(index="year", columns="code", values="value")
    wide = wide.reindex(columns=["USD", *CURRENCIES])
    wide.columns.name = None
    wide.index.name = None
    return wide


def _run(tmp_path, folder, supplement=None, snapshots=(), ledger="ledger.jsonl", plan=PLAN, now=None):
    prices = load_broker_daily(folder, plan.currencies, plan.price_start)
    return run_forward(plan, prices, _base_inflation(), plan.inflation_base_sha256, supplement, list(snapshots),
                       TrialLedger(tmp_path / ledger), now or datetime(2027, 4, 2, tzinfo=timezone.utc))


def _trim(folder, symbol, keep_until=None, drop_first_on=None):
    path = folder / f"{symbol}_D1.csv"
    frame = pd.read_csv(path)
    if keep_until is not None:
        frame = frame[frame["timestamp_utc"] <= keep_until]
    if drop_first_on is not None:
        frame = frame[~frame["timestamp_utc"].str.startswith(drop_first_on)]
    frame.to_csv(path, index=False)


def test_forward_book_is_exactly_the_frozen_v2_book():
    frozen = json.loads((ROOT / "docs/research/daily_fx_real_value_v2/plan.json").read_text(encoding="utf-8"))
    book = frozen["plan"]
    assert PLAN.book_plan_hash == frozen["plan_hash"] == REAL_VALUE_V2_PLAN_HASH
    assert PLAN.config.to_dict() == book["hypotheses"][0]["primary"]
    assert PLAN.limits.to_dict() == book["limits"] and list(PLAN.currencies) == book["currencies"]
    assert dict(sorted(PLAN.costs.one_way_bps.items())) == book["costs"]["one_way_bps"]
    assert PLAN.costs.financing_bps_per_year == book["costs"]["financing_bps_per_year"]
    assert PLAN.inflation_base_sha256 == book["data"]["inflation_sha256"]
    assert PLAN.forward_start == "2026-10-26" and PLAN.price_start == "2018-01-02"
    assert PLAN.engine == forward_engine_sha256() and len(PLAN.plan_hash()) == 64


def test_broker_exports_drop_the_forming_bar_and_need_the_whole_history(tmp_path):
    folder = _export(tmp_path / "prices", end="2026-12-31")
    loaded = load_broker_daily(folder, CURRENCIES, PLAN.price_start)
    panel = loaded.panel
    assert panel.prices.index[0] == pd.Timestamp("2018-01-02", tz="UTC") and len(loaded.files) == 9
    assert panel.prices.index[-1] == pd.Timestamp("2026-12-31", tz="UTC")  # the forming bar is gone
    # A pair one day behind cuts the panel at its last day; never a forward-filled price.
    _trim(folder, "USDDKK", keep_until="2026-12-31T23")  # its new last complete bar is 2026-12-30
    assert load_broker_daily(folder, CURRENCIES, PLAN.price_start).panel.prices.index[-1] == \
        pd.Timestamp("2026-12-30", tz="UTC")
    # A pair whose export failed this week (a stale file) refuses the run.
    _trim(folder, "USDDKK", keep_until="2026-12-24T23")
    with pytest.raises(ForwardRefused, match="PRICES_STALE"):
        load_broker_daily(folder, CURRENCIES, PLAN.price_start)
    short = _export(tmp_path / "short", end="2026-12-31")
    frame = pd.read_csv(short / "USDJPY_D1.csv")
    frame[frame["timestamp_utc"] >= "2019-01-01"].to_csv(short / "USDJPY_D1.csv", index=False)
    with pytest.raises(ForwardRefused, match="PRICES_TOO_SHORT"):
        load_broker_daily(short, CURRENCIES, PLAN.price_start)
    (short / "USDJPY_D1.csv").unlink()
    with pytest.raises(ForwardRefused, match="PRICES_MISSING"):
        load_broker_daily(short, CURRENCIES, PLAN.price_start)


def test_later_inflation_years_are_fixed_the_first_time_all_series_have_them():
    base = _base_inflation()
    table, added, notes = assemble_inflation(base, 2024, {}, _supplement())
    assert int(table.index.max()) == 2025 and list(added) == ["2025"] and table.at[2025, "JPY"] == 2.5
    # A later revision of a fixed year is ignored and reported.
    table, added, notes = assemble_inflation(base, 2024, added, _supplement(value=9.0))
    assert table.at[2025, "JPY"] == 2.5 and added == {} and any("ignored" in note for note in notes)
    # A year that not every series has yet is not used.
    table, added, notes = assemble_inflation(base, 2024, {}, _supplement((2025, 2026), missing=("SEK", 2026)))
    assert int(table.index.max()) == 2025 and list(added) == ["2025"] and any("2026" in note for note in notes)
    table, added, notes = assemble_inflation(base, 2024, {}, None)
    assert int(table.index.max()) == 2024 and added == {}


def _api_payload(values=None, indicator="FP.CPI.TOTL.ZG", pages=1):
    rows = []
    for iso3 in ("USA", "AUS", "CAN", "CHE", "DNK", "GBR", "JPN", "NOR", "NZL", "SWE"):
        for year in (2024, 2025):
            value = (values or {}).get((iso3, year), 2.0 + 0.1 * year % 3)
            rows.append({"indicator": {"id": indicator, "value": "Inflation, consumer prices (annual %)"},
                         "country": {"id": iso3[:2], "value": f"Country {iso3}"}, "countryiso3code": iso3,
                         "date": str(year), "value": value, "unit": "", "obs_status": "", "decimal": 1})
    return [{"page": 1, "pages": pages, "per_page": 1000, "total": len(rows), "sourceid": "2",
             "lastupdated": "2026-07-01"}, rows]


def test_world_bank_download_is_parsed_and_written_once(tmp_path):
    payload = _api_payload({("JPN", 2025): 3.1, ("NZL", 2025): None})
    rows, updated = parse_world_bank_inflation(payload)
    assert updated == "2026-07-01" and len(rows) == 19 and ("Country JPN", "JPN", 2025, 3.1) in rows
    with pytest.raises(ValueError, match="indicator"):
        parse_world_bank_inflation(_api_payload(indicator="NY.GDP.MKTP.CD"))
    with pytest.raises(ValueError, match="page"):
        parse_world_bank_inflation(_api_payload(pages=2))
    seen = {}

    def opener(url, timeout):
        seen["url"] = url
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    output = tmp_path / "inflation.csv"
    meta = fetch_world_bank_inflation(output, 2024, 2025, opener=opener)
    assert "FP.CPI.TOTL.ZG" in seen["url"] and "date=2024:2025" in seen["url"] and meta["rows"] == 19
    table, _ = read_inflation_supplement(output, CURRENCIES)
    assert table.at[2025, "JPY"] == 3.1 and math.isnan(table.at[2025, "NZD"])
    assert json.loads(output.with_suffix(".csv.json").read_text())["lastupdated"] == "2026-07-01"
    with pytest.raises(FileExistsError):
        fetch_world_bank_inflation(output, 2024, 2025, opener=opener)


def _returns(drift, years, vol=0.001, seed=0, start="2026-10-26"):
    days = pd.bdate_range(start, periods=int(261 * years), tz="UTC")
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(drift, vol, len(days)), index=days)


def test_rule_confirms_withholds_abandons_and_waits():
    rule = DecisionRule()
    strong = _returns(0.0004, 3.2)
    status = rule_status(strong, strong, "2026-10-26", strong.index[-1], rule)
    assert status["status"] == "CONFIRMED" and status["looks"][-1]["t"] >= status["looks"][-1]["boundary"]
    # Without broker-swap coverage the same t confirms nothing.
    uncovered = strong.where(strong.index < strong.index[100])
    withheld = rule_status(strong, uncovered, "2026-10-26", strong.index[-1], rule)
    assert withheld["status"] != "CONFIRMED" and "confirmation_withheld" in withheld["looks"][-1]
    losing = _returns(-0.0001, 2.2, seed=1)
    assert rule_status(losing, losing, "2026-10-26", losing.index[-1], rule)["status"] == "ABANDONED_FUTILITY"
    crash = _returns(0.0, 0.5, seed=2)
    crash.iloc[60] = -0.2
    assert rule_status(crash, crash, "2026-10-26", crash.index[-1], rule)["status"] == "ABANDONED_DRAWDOWN"
    young = _returns(0.0004, 0.5)
    early = rule_status(young, young, "2026-10-26", young.index[-1], rule)
    assert early == {"status": "ONGOING", "next_look": "2027-10-26", "looks": []}


def test_broker_swap_replaces_the_assumed_markup():
    days = pd.bdate_range("2026-10-26", periods=30, tz="UTC")
    prices = pd.DataFrame(1.0, index=days, columns=["AUD", "JPY"])
    positions = pd.DataFrame({"AUD": 0.06, "JPY": -0.05}, index=days)
    primary = pd.Series(0.0002, index=days)
    costs = CostModel({"AUD": 1.0, "JPY": 1.0}, financing_bps_per_year=75.0)
    flat = pd.DataFrame(-0.0075, index=days, columns=["AUD", "JPY"])
    # A broker swap equal to the assumed mark-up on both sides leaves the returns unchanged.
    same = broker_swap_returns(primary, positions, prices, costs, flat, flat)
    np.testing.assert_allclose(same.iloc[1:].to_numpy(), primary.iloc[1:].to_numpy(), atol=1e-15)
    gaps = flat.copy()
    gaps.iloc[10:12, 1] = np.nan  # no short JPY terms on two days
    adjusted = broker_swap_returns(primary, positions, prices, costs, flat, gaps)
    assert adjusted.isna().sum() == 2 and adjusted.notna().sum() == 28


def _snapshot(captured, swaps):
    infos = {}
    for code in CURRENCIES:
        symbol, usd_base = MT5_USD_PAIRS[code]
        point, digits = (0.001, 3) if code == "JPY" else (0.00001, 5)
        long_points, short_points = swaps.get(symbol, (-5.0, -5.0))
        infos[symbol + ".r"] = SimpleNamespace(
            name=symbol + ".r", swap_long=long_points, swap_short=short_points, swap_mode=1, swap_rollover3days=3,
            currency_base=symbol[:3], currency_profit=symbol[3:], currency_margin=symbol[:3],
            trade_contract_size=100000.0, point=point, digits=digits, spread=10)

    class Client:
        def symbol_info(self, name):
            return infos[name]

    symbols = {MT5_USD_PAIRS[code][0]: MT5_USD_PAIRS[code][0] + ".r" for code in CURRENCIES}
    return build_swap_snapshot(client=Client(), symbols=symbols, captured_at_utc=captured, mt5_server_time="UTC")


def test_swap_terms_map_to_currency_direction_and_expire():
    days = pd.bdate_range("2026-10-26", periods=60, tz="UTC")
    prices = pd.DataFrame({code: ORIENTATION_ANCHORS[code] for code in CURRENCIES}, index=days)
    snapshot = _snapshot(datetime(2026, 10, 27, 21, 0, tzinfo=timezone.utc), {"USDJPY": (15.0, -32.0),
                                                                              "AUDUSD": (2.0, -9.0)})
    long_rate, short_rate, used, reasons = _swap_rates([snapshot], prices, 35, days)
    assert used == [snapshot["payload_sha256"]] and reasons == {}
    first = pd.Timestamp("2026-10-28", tz="UTC")  # the first day that began after the capture
    assert long_rate.loc[:"2026-10-27"].isna().all().all() and long_rate.loc[first].notna().all()
    jpy_price = 1.0 / ORIENTATION_ANCHORS["JPY"]
    # Long JPY is short USDJPY: it earns USDJPY's short swap.
    # Annual fraction of notional: swap points * point / pair price * 365.
    assert long_rate.at[first, "JPY"] == pytest.approx(-32.0 * 0.001 / jpy_price * 365)
    assert short_rate.at[first, "JPY"] == pytest.approx(15.0 * 0.001 / jpy_price * 365)
    assert long_rate.at[first, "AUD"] == pytest.approx(2.0 * 0.00001 / ORIENTATION_ANCHORS["AUD"] * 365)
    stale = pd.Timestamp("2026-10-27", tz="UTC") + pd.Timedelta(days=37)
    assert long_rate.loc[stale:].isna().all().all()


def test_a_forward_run_seals_decisions_and_refuses_a_changed_past(tmp_path):
    folder = _export(tmp_path / "prices", end="2027-01-29")
    first = _run(tmp_path, folder, _supplement())
    assert first["appended"] is True and first["inflation_fixed"] == {"2025": {c: 2.5 for c in ("USD", *CURRENCIES)}}
    assert first["through_day"] == "2027-01-29" and first["forward_days"] > 60
    assert first["rule"]["status"] == "ONGOING" and first["decisions"] and first["execution_authorized"] is False
    assert len(first["days"]) == len(first["primary"]) == len(first["broker_swap"]) == first["forward_days"]
    assert set(first["closes"]["values"]) == set(CURRENCIES) and first["closes"]["days"][0] == "2018-01-02"
    assert first["closes"]["days"][-1] == first["closes_through"] == first["through_day"]
    assert len(first["inputs"]["price_files_sha256"]) == 9
    assert all(set(item["directions"].values()) <= {-1.0, 0.0, 1.0} for item in first["decisions"])
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    assert [record["kind"] for record in ledger.records()] == [CHECKPOINT]
    # More data later: the past is recomputed identically and the record grows.
    more = _export(tmp_path / "more", end="2027-03-31")
    second = _run(tmp_path, more, _supplement(value=7.0))
    assert second["appended"] is True and second["through_day"] == "2027-03-31"
    assert any("ignored" in note for note in second["inflation"]["notes"])  # 2025 stays as first seen
    assert second["inflation_fixed"] == {}
    sealed = {item["decision_day"] for record in ledger.records() for item in record["payload"]["decisions"]}
    assert len(sealed) == len(first["decisions"]) + len(second["decisions"])
    # A broker that re-quotes a past forward day is refused; nothing is appended.
    revised = _export(tmp_path / "revised", end="2027-04-30", shock=("GBP", "2026-12-15"))
    size = (tmp_path / "ledger.jsonl").stat().st_size
    with pytest.raises(ForwardRefused, match="FORWARD_HISTORY_CHANGED"):
        _run(tmp_path, revised, _supplement())
    assert (tmp_path / "ledger.jsonl").stat().st_size == size


def test_missing_inflation_stops_the_record_before_the_rebalance_that_needs_it(tmp_path):
    folder = _export(tmp_path / "prices", end="2027-01-29")
    # Without 2025 inflation every rebalance from 2026-07-01 lacks inputs: no forward day can be counted.
    summary = _run(tmp_path, folder, None)
    assert summary["appended"] is False and summary["forward_days"] == 0
    assert pd.Timestamp(summary["waiting_for_inputs_on"]) >= pd.Timestamp("2026-07-01")
    assert not (tmp_path / "ledger.jsonl").exists()


def test_a_changed_engine_or_another_plan_is_refused(tmp_path):
    folder = _export(tmp_path / "prices", end="2027-01-29")
    with pytest.raises(ForwardRefused, match="ENGINE_CHANGED"):
        _run(tmp_path, folder, _supplement(), plan=replace(PLAN, engine="0" * 64))
    with pytest.raises(ForwardRefused, match="INFLATION_BASE_CHANGED"):
        prices = load_broker_daily(folder, CURRENCIES, PLAN.price_start)
        run_forward(PLAN, prices, _base_inflation(), "f" * 64, _supplement(), [], TrialLedger(tmp_path / "x.jsonl"))
    _run(tmp_path, folder, _supplement())
    with pytest.raises(ForwardRefused, match="LEDGER_MISMATCH"):
        _run(tmp_path, folder, _supplement(), plan=replace(PLAN, swap_max_age_days=20))


def _base_csv(path):
    rows = ["Country,Country Code,Year,CPI"]
    anchors = {("USA", 1974): 11.05, ("USA", 1980): 13.55, ("USA", 2009): -0.36, ("USA", 2022): 8.0,
               ("JPN", 1974): 23.22}
    for iso3 in ("USA", "AUS", "CAN", "CHE", "DNK", "GBR", "JPN", "NOR", "NZL", "SWE"):
        for year in range(1970, 2025):
            rows.append(f"Name,{iso3},{year},{anchors.get((iso3, year), 2.0)}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_runner_freezes_runs_and_reports_refusals(tmp_path, monkeypatch, capsys):
    base = _base_csv(tmp_path / "cpi.csv")
    import hashlib
    plan = replace(PLAN, inflation_base_sha256=hashlib.sha256(base.read_bytes()).hexdigest())
    monkeypatch.setitem(forward_runner.PLANS, "value_forward_v1", lambda: plan)
    plan_file = tmp_path / "plan.json"
    assert forward_runner.main(["freeze", "--plan-file", str(plan_file)]) == 0
    assert forward_runner.main(["freeze", "--plan-file", str(plan_file)]) == 2  # never overwritten
    folder = _export(tmp_path / "prices", end="2027-01-29")
    supplement = tmp_path / "inflation.csv"
    supplement.write_text("Country,Country Code,Year,CPI\n" + "".join(
        f"N,{iso3},2025,2.5\n" for iso3 in ("USA", "AUS", "CAN", "CHE", "DNK", "GBR", "JPN", "NOR", "NZL", "SWE")))
    args = ["run", "--plan-file", str(plan_file), "--prices-dir", str(folder), "--inflation-base", str(base),
            "--inflation-supplement", str(supplement), "--ledger", str(tmp_path / "ledger.jsonl")]
    capsys.readouterr()
    assert forward_runner.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["appended"] is True and printed["rule"]["status"] == "ONGOING"
    # A plan file that no longer matches the code is refused.
    plan_file.write_text(json.dumps({"plan_hash": "0" * 64, "plan": {}}))
    assert forward_runner.main(args) == 2
    assert "PLAN_MISMATCH" in capsys.readouterr().err

    def offline(*_args, **_kwargs):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(forward_runner, "fetch_world_bank_inflation", offline)
    assert forward_runner.main(["fetch-inflation", "--output", str(tmp_path / "x.csv")]) == 3


def test_a_missing_inflation_year_on_the_last_bar_never_seals_an_incomplete_decision(tmp_path):
    folder = _export(tmp_path / "probe", end="2027-09-30")
    probe = _run(tmp_path, folder, _supplement(), ledger="probe.jsonl")
    waiting = probe["waiting_for_inputs_on"]  # the first rebalance that needs 2026 inflation
    assert waiting is not None and waiting >= "2027-07-01"
    # The export ends exactly on that rebalance day: it must stop the day before, not seal NaN.
    edge = _export(tmp_path / "edge", end=waiting)
    first = _run(tmp_path, edge, _supplement())
    assert first["appended"] is True and first["waiting_for_inputs_on"] == waiting
    assert first["through_day"] < waiting
    assert all(math.isfinite(v) for item in first["decisions"] for v in item["directions"].values())
    again = _run(tmp_path, edge, _supplement())
    assert again["appended"] is False
    later = _run(tmp_path, folder, _supplement((2025, 2026)))
    assert later["appended"] is True and later["waiting_for_inputs_on"] is None
    assert "NaN" not in (tmp_path / "ledger.jsonl").read_text()


def test_the_calendar_does_not_depend_on_a_bar_exactly_on_price_start(tmp_path):
    full = _export(tmp_path / "full", end="2027-01-29")
    holed = _export(tmp_path / "holed", end="2027-01-29")
    _trim(holed, "USDDKK", drop_first_on="2018-01-02")
    inflation = assemble_inflation(_base_inflation(), 2024, {}, _supplement())[0]
    rows_full, _ = _decision_rows(load_broker_daily(full, CURRENCIES, PLAN.price_start).panel.prices,
                                  PLAN.config, inflation)
    rows_holed, _ = _decision_rows(load_broker_daily(holed, CURRENCIES, PLAN.price_start).panel.prices,
                                   PLAN.config, inflation)
    assert rows_full == rows_holed


def test_sealed_broker_swap_values_do_not_change_and_back_dated_snapshots_are_ignored(tmp_path):
    folder = _export(tmp_path / "prices", end="2027-01-29")
    early = _snapshot(datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc), {})
    first = _run(tmp_path, folder, _supplement(), [early], now=datetime(2027, 1, 30, tzinfo=timezone.utc))
    covered = sum(value is not None for value in first["broker_swap"])
    assert covered > 20 and first["swap_snapshots_used"] == [early["payload_sha256"]]
    # The early snapshot is deleted and one claiming 2026-12-01 appears after the fact: the past stays.
    back_dated = _snapshot(datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc), {})
    more = _export(tmp_path / "more", end="2027-02-26")
    second = _run(tmp_path, more, _supplement(), [back_dated], now=datetime(2027, 2, 27, tzinfo=timezone.utc))
    assert back_dated["payload_sha256"] not in second["swap_snapshots_seen"]
    assert all(value is None for value in second["broker_swap"])  # no admissible snapshot for the new days
    sealed = [value for record in TrialLedger(tmp_path / "ledger.jsonl").records()
              for value in record["payload"]["broker_swap"]]
    assert sum(value is not None for value in sealed) == covered


def test_last_bit_noise_passes_and_a_real_change_is_refused(tmp_path, monkeypatch):
    folder = _export(tmp_path / "prices", end="2027-01-29")
    _run(tmp_path, folder, _supplement())
    real_backtest = forward.backtest

    def nudged(amount):
        def run(*args, **kwargs):
            result = real_backtest(*args, **kwargs)
            object.__setattr__(result, "net_returns", result.net_returns + amount)
            return result
        return run

    more = _export(tmp_path / "more", end="2027-02-26")
    monkeypatch.setattr(forward, "backtest", nudged(1e-14))
    assert _run(tmp_path, more, _supplement())["appended"] is True
    monkeypatch.setattr(forward, "backtest", nudged(1e-6))
    with pytest.raises(ForwardRefused, match="FORWARD_HISTORY_CHANGED"):
        _run(tmp_path, _export(tmp_path / "most", end="2027-03-31"), _supplement())


def test_a_final_status_closes_the_record(tmp_path):
    plan = replace(PLAN, rule=DecisionRule(max_drawdown=0.0001))
    folder = _export(tmp_path / "prices", end="2027-01-29")
    first = _run(tmp_path, folder, _supplement(), plan=plan)
    assert first["rule"]["status"] == "ABANDONED_DRAWDOWN" and first["appended"] is True
    closed = _run(tmp_path, _export(tmp_path / "more", end="2027-02-26"), _supplement(), plan=plan)
    assert closed["appended"] is False and "final status" in closed["note"]


def test_the_frozen_forward_plan_file_is_self_consistent_and_tracks_v2():
    frozen = json.loads((ROOT / "docs/research/daily_fx_value_forward_v1/plan.json").read_text(encoding="utf-8"))
    canonical = json.dumps(frozen["plan"], sort_keys=True, separators=(",", ":"))
    assert frozen["plan_hash"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert frozen["plan_hash"] == "0da01b7ad0ff9307c95a8c4414160c53dbbe1a4caceecc1584e79510d4693fe2"
    book = json.loads((ROOT / "docs/research/daily_fx_real_value_v2/plan.json").read_text(encoding="utf-8"))
    assert frozen["plan"]["book_plan_hash"] == book["plan_hash"]
    assert frozen["plan"]["config"] == book["plan"]["hypotheses"][0]["primary"]
    assert frozen["plan"]["forward_start"] == "2026-10-26"


def test_a_revised_close_is_refused_even_when_the_sealed_returns_do_not_move(tmp_path):
    folder = _export(tmp_path / "prices", end="2027-01-29")
    first = _run(tmp_path, folder, _supplement())
    held = [item["weights_after_execution"] for item in first["decisions"] if item["weights_after_execution"]][-1]
    flat = next(code for code, weight in held.items() if weight == 0.0)
    # The broker re-quotes the last sealed close of a currency the book does not hold.
    revised = _export(tmp_path / "revised", end="2027-02-26", shock=(flat, first["through_day"]))
    with pytest.raises(ForwardRefused, match="FORWARD_HISTORY_CHANGED"):
        _run(tmp_path, revised, _supplement())
    # Pre-start history is sealed too: a revision there is refused as well.
    old = _export(tmp_path / "old", end="2027-02-26", shock=(flat, "2019-03-12"))
    with pytest.raises(ForwardRefused, match="FORWARD_HISTORY_CHANGED"):
        _run(tmp_path, old, _supplement())

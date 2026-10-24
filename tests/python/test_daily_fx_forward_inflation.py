"""Inflation supplement with the US year filled from checked BLS CPI-U data (no network)."""
import json
import urllib.error

import pytest

from agi_style_forex_bot_mt5.research.daily_fx import forward_inflation
from agi_style_forex_bot_mt5.research.daily_fx.data import WORLD_BANK_COUNTRIES
from agi_style_forex_bot_mt5.research.daily_fx.forward import WORLD_BANK_INDICATOR, read_inflation_supplement
from agi_style_forex_bot_mt5.research.daily_fx.forward_inflation import fetch_inflation, us_inflation_from_cpi

LEVELS = {year: 230.0 * 1.025 ** (year - 2014) for year in range(2014, 2027)}


def _fred(last_months=9):
    lines = ["observation_date,CPIAUCNS"]
    for year, level in LEVELS.items():
        for month in range(1, 13 if year < 2026 else last_months + 1):
            lines.append(f"{year}-{month:02d}-01,{level:.6f}")
    return "\n".join(lines) + "\n"


def _world_bank(us_through=2024, shift=0.0):
    items = []
    for iso3 in WORLD_BANK_COUNTRIES:
        for year in range(2015, 2026):
            if iso3 == "USA":
                value = (100.0 * (LEVELS[year] / LEVELS[year - 1] - 1.0) + (shift if year == 2020 else 0.0)
                         if year <= us_through else None)
            else:
                value = 2.0 + 0.1 * (year - 2015)
            items.append({"indicator": {"id": WORLD_BANK_INDICATOR}, "countryiso3code": iso3,
                          "country": {"value": iso3}, "date": str(year), "value": value})
    return [{"page": 1, "pages": 1, "lastupdated": "2026-10-08"}, items]


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def _opener(world_bank, fred):
    def open_(request, timeout):
        url = request.full_url
        if "fred.stlouisfed.org" in url:
            return _Response(fred.encode("utf-8"))
        return _Response(json.dumps(world_bank).encode("utf-8"))
    return open_


def test_bls_annual_average_change_uses_complete_years_only():
    values = us_inflation_from_cpi(_fred())
    assert values[2025] == pytest.approx(2.5) and 2026 not in values and 2014 not in values


def test_a_missing_us_year_is_filled_from_checked_bls_data(tmp_path):
    output = tmp_path / "inflation-20261026.csv"
    meta = fetch_inflation(output, 2025, 2026, opener=_opener(_world_bank(), _fred()))
    assert meta["us_years_from_bls"] == [2025] and meta["us_check_years"] == list(range(2015, 2025))
    table, _ = read_inflation_supplement(output, tuple(code for code in WORLD_BANK_COUNTRIES.values()
                                                       if code != "USD"))
    assert list(table.index) == [2025] and not table.loc[2025].isna().any()
    assert table.at[2025, "USD"] == pytest.approx(2.5)
    sidecar = json.loads(output.with_suffix(".csv.json").read_text(encoding="utf-8"))
    assert sidecar["us_years_from_bls"] == [2025] and "CPIAUCNS" in sidecar["source"]


def test_the_world_bank_us_value_is_kept_when_published(tmp_path):
    meta = fetch_inflation(tmp_path / "a.csv", 2025, 2026, opener=_opener(_world_bank(us_through=2025), _fred()))
    assert meta["us_years_from_bls"] == []


def test_a_bls_series_that_disagrees_with_the_world_bank_is_refused(tmp_path):
    output = tmp_path / "a.csv"
    with pytest.raises(ValueError, match="US_CPI_MISMATCH"):
        fetch_inflation(output, 2025, 2026, opener=_opener(_world_bank(shift=0.5), _fred()))
    assert not output.exists()


def test_the_command_reports_download_failures_and_never_overwrites(tmp_path, monkeypatch, capsys):
    output = tmp_path / "a.csv"
    output.write_text("x")
    assert forward_inflation.main(["fetch-inflation", "--output", str(output)]) == 2

    def offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(forward_inflation.urllib.request, "urlopen", offline)
    monkeypatch.setattr(forward_inflation.fetch_inflation, "__defaults__", (offline,))
    assert forward_inflation.main(["fetch-inflation", "--output", str(tmp_path / "b.csv")]) == 3
    assert "download failed" in capsys.readouterr().err

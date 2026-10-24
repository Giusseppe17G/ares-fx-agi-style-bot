"""Inflation supplement of the forward tracking, with the US year filled from BLS data (research only).

    python -m agi_style_forex_bot_mt5.research.daily_fx.forward_inflation fetch-inflation \\
        --output data/historical/worldbank/inflation-20261026.csv

The frozen tracker reads a supplement CSV (``Country,Country Code,Year,CPI``)
and uses a year only once all ten series have it. The World Bank publishes the
US value of indicator FP.CPI.TOTL.ZG months after the other nine. The value
is the annual-average change of the BLS CPI-U, which BLS publishes in January.
This command writes the same file as ``forward_runner fetch-inflation``, with
one difference: a US year the World Bank does not have yet is computed from
FRED series ``CPIAUCNS``, the CPI-U not seasonally adjusted. The value is the
change of the twelve-month average, and only complete years are used.

The US value is used only after it is checked. For every year from 2015 that
the World Bank has, the FRED value must match within ``MATCH_TOLERANCE``
percentage points. Otherwise nothing is written (``US_CPI_MISMATCH``). The
other nine series always come from the World Bank. The sidecar JSON records
which US years came from FRED.

Exit codes: 0 written; 2 refused or invalid (an output that exists, a
mismatch, a series missing); 3 a download failed. Nothing here reads a
terminal or sends an order.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import http.client
import io
import json
from pathlib import Path
import sys
from typing import Any, Callable, Sequence
import urllib.error
import urllib.request

import pandas as pd

from .data import WORLD_BANK_COUNTRIES
from .forward import WORLD_BANK_INDICATOR, WORLD_BANK_URL, parse_world_bank_inflation

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS"
CHECK_FROM = 2015
MATCH_TOLERANCE = 0.02  # percentage points; BLS rounds the index to three decimals


def _get(opener: Callable[..., Any], url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ares-forward-tracking/1.0"})
    with opener(request, timeout=60) as response:
        return response.read()


def us_inflation_from_cpi(csv_text: str) -> dict[int, float]:
    """Annual % change of the twelve-month average CPI-U, complete years only."""

    frame = pd.read_csv(io.StringIO(csv_text))
    if frame.shape[1] != 2:
        raise ValueError("unexpected FRED CSV columns")
    dates = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
    values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    monthly = pd.Series(values.to_numpy(), index=dates).dropna()
    monthly = monthly[monthly.index.notna()]
    counts = monthly.groupby(monthly.index.year).count()
    means = monthly.groupby(monthly.index.year).mean()[counts == 12]
    years = sorted(int(year) for year in means.index)
    return {year: float(100.0 * (means[year] / means[year - 1] - 1.0)) for year in years if year - 1 in means.index}


def fetch_inflation(output: str | Path, first_year: int, last_year: int,
                    opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """Write the supplement CSV and its sidecar JSON (never overwrite); US gaps filled from checked BLS data."""

    target = Path(output)
    sidecar = target.with_suffix(target.suffix + ".json")
    if target.exists() or sidecar.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    world_bank_url = WORLD_BANK_URL.format(countries=";".join(sorted(WORLD_BANK_COUNTRIES)),
                                           first=CHECK_FROM, last=int(last_year))
    rows, last_updated = parse_world_bank_inflation(json.loads(_get(opener, world_bank_url).decode("utf-8")))
    us_world_bank = {year: value for _, iso3, year, value in rows if iso3 == "USA"}
    us_bls = us_inflation_from_cpi(_get(opener, FRED_URL).decode("utf-8"))
    checked = sorted(year for year in us_world_bank if year in us_bls)
    if not checked:
        raise ValueError("US_CPI_MISMATCH: no year to compare the BLS series with the World Bank")
    gaps = {year: round(abs(us_bls[year] - us_world_bank[year]), 4) for year in checked}
    if max(gaps.values()) > MATCH_TOLERANCE:
        raise ValueError(f"US_CPI_MISMATCH: BLS and World Bank differ by more than {MATCH_TOLERANCE} pp: {gaps}")
    kept = [row for row in rows if int(first_year) <= row[2] <= int(last_year)]
    filled = sorted(year for year in us_bls
                    if int(first_year) <= year <= int(last_year) and year not in us_world_bank)
    kept += [("United States", "USA", year, us_bls[year]) for year in filled]
    kept.sort(key=lambda row: (row[1], row[2]))
    if {row[1] for row in kept} != set(WORLD_BANK_COUNTRIES):
        missing = sorted(set(WORLD_BANK_COUNTRIES) - {row[1] for row in kept})
        raise ValueError(f"no value at all for: {', '.join(missing)}")
    lines = ["Country,Country Code,Year,CPI"] + [f"{name.replace(',', ' ')},{iso3},{year},{value!r}"
                                                  for name, iso3, year, value in kept]
    text = "\n".join(lines) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    meta = {"source": f"{world_bank_url} ; US gaps: {FRED_URL}", "indicator": WORLD_BANK_INDICATOR,
            "lastupdated": last_updated,
            "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha256": sha256(text.encode("utf-8")).hexdigest(), "rows": len(kept),
            "years": sorted({row[2] for row in kept}), "us_years_from_bls": filled,
            "us_check_years": checked, "us_check_max_gap_pp": max(gaps.values())}
    with sidecar.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inflation supplement of the forward tracking (research only)")
    parser.add_argument("phase", choices=("fetch-inflation",))
    parser.add_argument("--output", type=Path, required=True, help="new CSV path")
    parser.add_argument("--first-year", type=int, default=2025)
    parser.add_argument("--last-year", type=int, default=datetime.now(timezone.utc).year)
    args = parser.parse_args(argv)
    try:
        meta = fetch_inflation(args.output, args.first_year, args.last_year)
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException,
            json.JSONDecodeError, UnicodeDecodeError) as error:
        print(json.dumps({"phase": args.phase, "error": f"download failed: {type(error).__name__}: {error}"}),
              file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"phase": args.phase, "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 2
    print(json.dumps({"phase": args.phase, "output": str(args.output), **meta}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

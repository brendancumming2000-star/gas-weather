"""NSIDC Sea Ice Index v4 Arctic daily extent; no API key required."""
from datetime import datetime, timezone
from io import StringIO

import pandas as pd

from data_sources.common import get_text

ICE_URL = "https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv"
ICE_PAGE = "https://nsidc.org/data/seaice_index/data-and-image-archive"


def parse_ice(text: str) -> pd.DataFrame:
    # Line two is unit metadata, not an observation. The unused final source-file
    # column contains commas, so select the first five fields explicitly.
    frame = pd.read_csv(StringIO(text), skiprows=[1], usecols=range(5), skipinitialspace=True)
    frame.columns = [c.strip().lower() for c in frame.columns]
    expected = {"year", "month", "day", "extent", "missing"}
    if not expected.issubset(frame.columns):
        raise ValueError("NSIDC Sea Ice Index schema changed")
    for col in frame:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["date"] = pd.to_datetime(frame[["year", "month", "day"]], errors="coerce")
    frame = frame.dropna(subset=["date", "extent", "missing"])
    frame = frame[frame.extent.between(0, 30) & (frame.missing == 0)]
    if frame.empty:
        raise ValueError("NSIDC file has no complete valid Arctic observations")
    frame["year"] = frame.date.dt.year
    frame["extent_million_km2"] = frame.extent
    # Use one leap-year calendar so March–December do not shift when comparing
    # leap and nonleap years. This is a calendar-day axis, not native day-of-year.
    frame["day_of_year"] = pd.to_datetime("2000-" + frame.date.dt.strftime("%m-%d")).dt.dayofyear
    return frame[["date", "year", "day_of_year", "extent_million_km2"]].drop_duplicates("date").sort_values("date")


def summarize_ice(frame: pd.DataFrame) -> dict:
    latest = frame.iloc[-1]
    current = float(latest.extent_million_km2)
    baseline = frame[frame.year.between(1991, 2020)]
    same_day = baseline[baseline.day_of_year == latest.day_of_year].extent_million_km2
    # February 29 has at most eight observations in a 30-year period.
    if len(same_day) < 5:
        raise ValueError("Insufficient NSIDC same-calendar-day baseline")
    normal = float(same_day.mean())
    climatology = baseline.groupby("day_of_year").extent_million_km2.agg(mean="mean", p10=lambda v: v.quantile(.1), p90=lambda v: v.quantile(.9), samples="count").reset_index()
    history = frame.copy()
    history["date"] = history.date.dt.strftime("%Y-%m-%d")
    percentile = float(100 * ((same_day < current).sum() + .5 * (same_day == current).sum()) / len(same_day))
    year = int(latest.year)
    return {"observed_at": latest.date.date().isoformat(), "current_extent_million_km2": current,
            "normal_extent_million_km2": normal, "anomaly_million_km2": current - normal,
            "percentile": percentile, "baseline_samples": len(same_day),
            "baseline": "1991–2020, same calendar date; midpoint empirical percentile (dashboard calculation)",
            "history": history.to_dict("records"),
            "seasonal": history[history.year.isin([year, year - 1, year - 2, 2012])].to_dict("records"),
            "climatology": climatology.to_dict("records"), "source_url": ICE_URL, "source_page": ICE_PAGE,
            "methodology": "NOAA/NSIDC Sea Ice Index v4 total Arctic sea-ice extent in million km², already in source units. Extent is the area of grid cells with at least 15% concentration, not ice area or volume. Exclude missing or negative-sentinel data. Compare identical month/day in 1991–2020; this is our baseline, distinct from NSIDC's published 1981–2010 climatology. The seasonal x-axis maps month/day to leap year 2000 to align calendars. Latest values are provisional; v4 uses AMSR2 for the recent period. No direct gas-demand conversion is assigned.",
            "warnings": []}


def fetch_ice() -> dict:
    result = summarize_ice(parse_ice(get_text(ICE_URL)))
    age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(result["observed_at"]).date()).days
    if age > 5:
        result["warnings"].append(f"NSIDC extent observation is {age} days old: {result['observed_at']}.")
    return result

"""Rutgers Global Snow Lab weekly Eurasian snow extent and seasonal context."""
from datetime import datetime, timezone
from io import StringIO
import re

import numpy as np
import pandas as pd

from data_sources.common import get_text

SNOW_URL = "https://climate.rutgers.edu/snowcover/files/wkcov.eurasia.txt"
SNOW_PAGE = "https://climate.rutgers.edu/snowcover/table_area.php?ui_set=2&ui_sort=0"


def parse_snow(text: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text), sep=r"\s+", names=["year", "week", "extent_km2"], comment="#")
    for col in frame:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna()
    frame = frame[frame.year.between(1960, 2200) & frame.week.between(1, 53) & frame.extent_km2.between(0, 60_000_000)]
    if frame.empty:
        raise ValueError("Rutgers snow file contains no valid observations")
    frame[["year", "week"]] = frame[["year", "week"]].astype(int)
    frame["extent_million_km2"] = frame.extent_km2 / 1_000_000
    return frame[["year", "week", "extent_million_km2"]].drop_duplicates(["year", "week"]).sort_values(["year", "week"])


def summarize_snow(frame: pd.DataFrame, period_start: str | None = None, period_end: str | None = None) -> dict:
    last = frame.iloc[-1]
    year, week = int(last.year), int(last.week)
    current = float(last.extent_million_km2)
    baseline = frame[frame.year.between(1991, 2020)]
    same_week = baseline[baseline.week == week].extent_million_km2
    if len(same_week) < 20:
        raise ValueError("Insufficient Rutgers same-week 1991–2020 baseline")
    normal = float(same_week.mean())
    grouped = baseline.groupby("week").extent_million_km2
    climatology = grouped.agg(mean="mean", p10=lambda v: v.quantile(.1), p90=lambda v: v.quantile(.9), samples="count").reset_index()
    changes = {}
    for lag in (1, 4):
        # Preserve source week numbering. Do not silently substitute last available
        # row for a missing week, or invent a year-boundary calendar convention.
        earlier = frame[(frame.year == year) & (frame.week == week - lag)]
        changes[f"change_{lag}w"] = current - float(earlier.iloc[-1].extent_million_km2) if not earlier.empty else None
    percentile = float(100 * ((same_week < current).sum() + .5 * (same_week == current).sum()) / len(same_week))
    chart = f"https://climate.rutgers.edu/snowcover/chart_vis.php?ui_year={year}&ui_week={week}&ui_set=0"
    return {"observed_at": period_end, "year": year, "week": week,
            "period_start": period_start, "period_end": period_end,
            "current_extent_million_km2": current, "normal_extent_million_km2": normal,
            "anomaly_million_km2": current - normal, "percentile": percentile,
            "baseline": "1991–2020, same Rutgers week; midpoint empirical percentile", "baseline_samples": len(same_week),
            "history": frame.to_dict("records"), "seasonal": frame[frame.year >= year - 5].to_dict("records"),
            "climatology": climatology.to_dict("records"), **changes,
            "source_url": SNOW_URL, "source_page": SNOW_PAGE, "chart_url": chart,
            "methodology": "Rutgers NH snow-cover climate data record, Eurasia only. Source square kilometers are divided by 1,000,000. Baseline and percentiles compare the same source week in 1991–2020; source weeks are not ISO weeks. Period dates come from Rutgers' dated chart. Eurasia is a continental proxy, not a Siberia-only mask. Fall/October accumulation is contextual and does not mechanically predict a U.S. cold outbreak.",
            "warnings": []}


def fetch_snow() -> dict:
    frame = parse_snow(get_text(SNOW_URL))
    last = frame.iloc[-1]
    chart = f"https://climate.rutgers.edu/snowcover/chart_vis.php?ui_year={int(last.year)}&ui_week={int(last.week)}&ui_set=0"
    dates = get_text(chart)
    plain = re.sub(r"<[^>]+>", " ", dates)
    start = re.search(r"Week start:\s*(\d{4}-\d{2}-\d{2})", plain)
    end = re.search(r"Week end:\s*(\d{4}-\d{2}-\d{2})", plain)
    if not start or not end:
        raise ValueError("Rutgers chart no longer exposes weekly observation dates")
    result = summarize_snow(frame, start.group(1), end.group(1))
    age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(end.group(1)).date()).days
    if age > 10:
        result["warnings"].append(f"Latest Rutgers weekly file is {age} days old (week ending {end.group(1)}); publication can lag. This is the latest source observation, not today's snow cover.")
    return result

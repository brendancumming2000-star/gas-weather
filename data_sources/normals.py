"""NOAA NCEI 1991–2020 observed station daily climate normals.

The `access` CSV product reports temperature directly in degrees Fahrenheit and
heating/cooling degree days directly in Fahrenheit degree days (not tenths). Values are
NOAA's smoothed daily climatology, not an extrapolated seasonal sine curve.
"""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import math
from numbers import Real
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NORMALS_BASE = "https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access"
NORMALS_DOCUMENTATION = "https://www.ncei.noaa.gov/data/normals-daily/1991-2020/doc/Normals_DLY_Documentation_1991-2020.pdf"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "normals"
CACHE_SCHEMA_VERSION = 2


def parse_normals_csv(text: str) -> dict[str, dict]:
    """Parse the native access CSV; preserve the product's Fahrenheit units."""
    result = {}
    reader = csv.DictReader(io.StringIO(text))
    has_cooling = "DLY-CLDD-NORMAL" in (reader.fieldnames or [])
    for row in reader:
        date_key = row.get("DATE", "")[-5:]
        if not re.fullmatch(r"\d{2}-\d{2}", date_key):
            continue
        try:
            temp = float(row["DLY-TAVG-NORMAL"])
            hdd = float(row["DLY-HTDD-NORMAL"])
            cdd = float(row["DLY-CLDD-NORMAL"]) if has_cooling else None
        except (KeyError, ValueError, TypeError):
            continue
        if not (-90 <= temp <= 130 and 0 <= hdd <= 160):
            continue
        if has_cooling and not 0 <= cdd <= 160:
            continue
        result[date_key] = {"normal_temp_f": temp, "normal_hdd": hdd}
        # Old callers can still parse a heating-only CSV, but its absent CDDs
        # must never be synthesized from the mean climate temperature.
        if has_cooling:
            result[date_key]["normal_cdd"] = cdd
    if len(result) < 365:
        raise ValueError(f"NOAA daily normals file contains only {len(result)} valid dates")
    return result


def _complete_degree_day_normals(days: dict) -> bool:
    """Reject old heating-only caches and corrupted climatology values."""
    if not isinstance(days, dict) or len(days) < 365:
        return False
    for values in days.values():
        if not isinstance(values, dict):
            return False
        for key, lower, upper in (("normal_temp_f", -90, 130), ("normal_hdd", 0, 160), ("normal_cdd", 0, 160)):
            value = values.get(key)
            if not isinstance(value, Real) or not math.isfinite(value) or not lower <= value <= upper:
                return False
    return True


def fetch_station_normals(station: str) -> dict:
    """Return a persistent cache of this fixed climatological reference period."""
    if not re.fullmatch(r"[A-Z0-9]{11}", station):
        raise ValueError(f"Invalid NOAA normals station ID: {station!r}")
    path = CACHE_DIR / f"{station}.json"
    if path.exists():
        try:
            cached = json.loads(path.read_text())
            if _complete_degree_day_normals(cached.get("days", {})):
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    url = f"{NORMALS_BASE}/{station}.csv"
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        response = session.get(url, timeout=(10, 30))
        response.raise_for_status()
    days = parse_normals_csv(response.text)
    if not _complete_degree_day_normals(days):
        raise ValueError("NOAA daily normals file lacks complete heating and cooling degree-day normals")
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "station": station,
        "period": "1991–2020",
        "days": days,
        "source_url": url,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "NOAA NCEI observed 1991–2020 daily station normals; native Fahrenheit units. DLY-HTDD-NORMAL and DLY-CLDD-NORMAL are average daily base-65°F HDD and CDD, not degree days calculated from the average climate temperature.",
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Multiple browser sessions can populate the same station in one process.
    # Give each write its own file before atomically replacing the shared cache.
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)
    return payload


def fetch_normals(regions: list[dict]) -> dict:
    """Fetch each region independently so one station outage cannot drop GFS."""
    result = {"regions": {}, "warnings": [], "period": "1991–2020", "source_url": NORMALS_BASE}
    stations = {r["name"]: r.get("normal_station") for r in regions}
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = {executor.submit(fetch_station_normals, station): name for name, station in stations.items() if station}
        for task in as_completed(tasks):
            name = tasks[task]
            try:
                result["regions"][name] = task.result()
            except Exception as error:
                result["warnings"].append(f"{name}: normal unavailable ({error})")
    for name, station in stations.items():
        if not station:
            result["warnings"].append(f"{name}: no NOAA normal station configured")
    return result


def attach_degree_day_normals(rows, regions=None, normals=None) -> list[dict]:
    """Enrich copied forecast rows from the fixed NOAA reference, in memory only.

    Existing finite normals are preserved. Missing station/date values remain
    missing, so an unavailable normal cannot become zero demand. Pass one
    fetch_normals() result to reuse it across current and historical snapshots.
    No forecast cache or database snapshot is written by this helper.
    """
    copied = [dict(row) for row in rows]
    keys = ("normal_temp_f", "normal_hdd", "normal_cdd")

    def missing(value):
        return value is None or (isinstance(value, Real) and math.isnan(value))

    if not any(missing(row.get(key)) for row in copied for key in keys):
        return copied
    if normals is None:
        if regions is None:
            from config import REGIONS
            regions = REGIONS
        normals = fetch_normals(regions)
    for row in copied:
        day = str(row.get("date", ""))[5:10]
        normal = normals.get("regions", {}).get(row.get("region"), {}).get("days", {}).get(day, {})
        for key in keys:
            if missing(row.get(key)):
                row[key] = normal.get(key)
    return copied

"""Live deterministic NOAA GFS: 2 m temperatures and 10 hPa vortex indicators.

Downloads only the needed messages from the public NOAA AWS GRIB2 files. Every
message's encoded initialization and valid time is checked. A saved lead is
immutable; archive retrievals retain their true model initialization and their
actual retrieval timestamp, and are never represented as pulls made in the past.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import uuid

import eccodes
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from data_sources.normals import fetch_normals

BASE_URL = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "gfs"
UTC = timezone.utc
_thread_local = threading.local()


@dataclass(frozen=True)
class IndexRecord:
    start: int
    end: int | None
    init: datetime
    variable: str
    level: str


def _session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        session = requests.Session()
        session.headers["User-Agent"] = "GasWeatherDashboard/1.0 (NOAA public-data client)"
        session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=2))
        _thread_local.session = session
    return _thread_local.session


def parse_index(text: str) -> list[IndexRecord]:
    """Resolve byte ranges using the next message offset, never fixed offsets."""
    entries = []
    for line in text.splitlines():
        fields = line.split(":")
        if len(fields) < 6 or not fields[1].isdigit() or not re.fullmatch(r"d=\d{10}", fields[2]):
            continue
        entries.append((int(fields[1]), datetime.strptime(fields[2][2:], "%Y%m%d%H").replace(tzinfo=UTC), fields[3], fields[4]))
    if not entries:
        raise ValueError("GFS index has no valid GRIB records")
    if any(b[0] <= a[0] for a, b in zip(entries, entries[1:])):
        raise ValueError("GFS index byte offsets are not strictly increasing")
    return [IndexRecord(start, entries[i + 1][0] - 1 if i + 1 < len(entries) else None, init, var, level)
            for i, (start, init, var, level) in enumerate(entries)]


def _url(run: datetime, lead: int) -> str:
    return f"{BASE_URL}/gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.1p00.f{lead:03d}"


def _index(run: datetime, lead: int) -> list[IndexRecord]:
    response = _session().get(_url(run, lead) + ".idx", timeout=(8, 25))
    response.raise_for_status()
    records = parse_index(response.text)
    if any(record.init != run for record in records):
        raise ValueError("GFS index initialization differs from requested run")
    return records


def discover_latest_run(now: datetime | None = None) -> datetime:
    """Find an actually published complete f384 run, rather than assuming latency."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Model discovery requires a timezone-aware datetime")
    now = now.astimezone(UTC)
    candidate = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    errors = []
    for offset in range(8):
        run = candidate - timedelta(hours=6 * offset)
        try:
            records = _index(run, 384)
            if not any(r.variable == "TMP" and r.level == "2 m above ground" for r in records):
                raise ValueError("Missing 2 m temperature record")
            return run
        except requests.HTTPError as error:
            errors.append(f"{run:%Y-%m-%d %HZ}: HTTP {error.response.status_code}")
        except (requests.RequestException, ValueError) as error:
            errors.append(f"{run:%Y-%m-%d %HZ}: {error}")
    raise RuntimeError("No complete GFS run could be retrieved in the past 48 hours. " + "; ".join(errors[:3]))


def forecast_calendar(run: datetime, now: datetime | None = None, days: int = 15) -> list[tuple[str, list[int]]]:
    """Four instantaneous samples (00,06,12,18 UTC) for each full future UTC day."""
    now = now or datetime.now(UTC)
    if run.tzinfo is None or now.tzinfo is None:
        raise ValueError("Forecast calendar requires timezone-aware datetimes")
    start = datetime.combine(now.astimezone(UTC).date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    result = []
    for day in range(days):
        date = start + timedelta(days=day)
        leads = [int(((date + timedelta(hours=hour)) - run).total_seconds() / 3600) for hour in (0, 6, 12, 18)]
        if min(leads) < 0 or max(leads) > 384 or any(lead % 6 for lead in leads):
            raise ValueError("Latest available GFS run cannot cover all requested full future UTC days")
        result.append((date.date().isoformat(), leads))
    return result


def archive_calendar(run: datetime, comparison_dates=None) -> list[tuple[str, list[int]]]:
    """Clip requested UTC calendar days to the archived run's actual horizon.

    An unsupported date is excluded in full, never partly sampled or extrapolated.
    With no requested dates, use the 15 full UTC days after initialization day.
    """
    if run.tzinfo is None:
        raise ValueError("Archive calendar requires a timezone-aware model run")
    run = run.astimezone(UTC)
    if comparison_dates is None:
        return forecast_calendar(run, now=run)
    result = []
    for value in sorted({str(date) for date in comparison_dates}):
        try:
            date = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as error:
            raise ValueError(f"Comparison date must be YYYY-MM-DD: {value!r}") from error
        leads = [int(((date + timedelta(hours=hour)) - run).total_seconds() / 3600) for hour in (0, 6, 12, 18)]
        if min(leads) >= 0 and max(leads) <= 384 and all(lead % 6 == 0 for lead in leads):
            result.append((date.date().isoformat(), leads))
    if not result:
        raise ValueError("No complete requested UTC day overlaps this archived GFS run's 0–384 hour horizon")
    return result


def kelvin_to_fahrenheit(value):
    return (np.asarray(value) - 273.15) * 9.0 / 5.0 + 32.0


def _download_range(url: str, start: int, end: int) -> bytes:
    # Check status before materializing content; a server ignoring Range must not
    # accidentally trigger downloads of 60 complete ~45 MB global files.
    with _session().get(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
                        stream=True, timeout=(8, 30)) as response:
        response.raise_for_status()
        if response.status_code != 206:
            raise ValueError(f"GFS server did not honor byte range (HTTP {response.status_code})")
        expected = f"bytes {start}-{end}/"
        if not response.headers.get("Content-Range", "").startswith(expected):
            raise ValueError("GFS server returned a different byte range")
        content = response.content
    if len(content) != end - start + 1:
        raise ValueError("Truncated GFS range response")
    return content


def _validate_message(handle, run: datetime, lead: int) -> None:
    def dt(date_key, time_key):
        return datetime.strptime(f"{eccodes.codes_get(handle, date_key)}{int(eccodes.codes_get(handle, time_key)):04d}", "%Y%m%d%H%M").replace(tzinfo=UTC)
    if dt("dataDate", "dataTime") != run:
        raise ValueError("GRIB encoded initialization differs from requested model run")
    if dt("validityDate", "validityTime") != run + timedelta(hours=lead):
        raise ValueError("GRIB encoded valid time differs from requested forecast hour")


def polar_cap_mean(values, latitudes, minimum_latitude: float = 60.0) -> float:
    values = np.asarray(values, dtype=float)
    latitudes = np.asarray(latitudes, dtype=float)
    valid = (latitudes >= minimum_latitude) & np.isfinite(values) & (np.abs(values) < 1e10)
    if not np.any(valid):
        raise ValueError("No valid polar-cap grid points")
    return float(np.average(values[valid], weights=np.cos(np.deg2rad(latitudes[valid]))))


def zonal_mean_wind(values, latitudes, target_latitude: float = 60.0) -> float:
    values = np.asarray(values, dtype=float)
    latitudes = np.asarray(latitudes, dtype=float)
    valid = np.isclose(latitudes, target_latitude) & np.isfinite(values) & (np.abs(values) < 1e10)
    if not np.any(valid):
        raise ValueError("GFS field does not contain the 60°N latitude circle")
    # Regular 1-degree grid: every longitude has equal weight at fixed latitude.
    return float(np.mean(values[valid]))


def _extract_lead(run: datetime, lead: int, regions: list[dict], with_polar: bool) -> dict:
    region_signature = hashlib.sha256(json.dumps([(r["name"], r["latitude"], r["longitude"]) for r in regions]).encode()).hexdigest()[:12]
    cache = CACHE_DIR / f"{run:%Y%m%d%H}_{lead:03d}_{region_signature}_v1.json"
    if cache.exists():
        try:
            cached = json.loads(cache.read_text())
            if (cached.get("lead") == lead
                    and cached.get("valid_time") == (run + timedelta(hours=lead)).isoformat()
                    and set(cached.get("temps_f", {})) == {r["name"] for r in regions}
                    and (not with_polar or "polar" in cached)):
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    records = _index(run, lead)
    surface = next((r for r in records if r.variable == "TMP" and r.level == "2 m above ground"), None)
    if surface is None or surface.end is None:
        raise ValueError("GFS missing bounded 2 m temperature message")
    content = _download_range(_url(run, lead), surface.start, surface.end)
    handle = eccodes.codes_new_from_message(content)
    try:
        _validate_message(handle, run, lead)
        if eccodes.codes_get(handle, "units") != "K" or eccodes.codes_get(handle, "shortName") != "2t":
            raise ValueError("Expected 2 m temperature in Kelvin")
        temperatures = {}
        grid_points = {}
        for region in regions:
            nearest = eccodes.codes_grib_find_nearest(handle, region["latitude"], region["longitude"] % 360)[0]
            value = float(nearest["value"])
            if not 170 < value < 340:
                raise ValueError(f"Implausible GFS Kelvin temperature for {region['name']}: {value}")
            temperatures[region["name"]] = float(kelvin_to_fahrenheit(value))
            grid_points[region["name"]] = {"latitude": nearest["lat"], "longitude": (nearest["lon"] + 180) % 360 - 180,
                                          "distance_km": nearest["distance"]}
    finally:
        eccodes.codes_release(handle)
    result = {"lead": lead, "valid_time": (run + timedelta(hours=lead)).isoformat(), "temps_f": temperatures, "grid_points": grid_points}
    if with_polar:
        chosen = [r for r in records if r.level == "10 mb" and r.variable in ("UGRD", "TMP", "HGT")]
        if len(chosen) != 3 or any(r.end is None for r in chosen):
            raise ValueError("GFS missing 10 hPa wind, temperature, or geopotential height")
        start = min(r.start for r in chosen)
        end = max(r.end for r in chosen)
        block = _download_range(_url(run, lead), start, end)
        polar = {"date": (run + timedelta(hours=lead)).date().isoformat(), "valid_time": result["valid_time"]}
        for record in chosen:
            message = block[record.start - start:record.end - start + 1]
            handle = eccodes.codes_new_from_message(message)
            try:
                _validate_message(handle, run, lead)
                values = eccodes.codes_get_values(handle)
                latitudes = eccodes.codes_get_array(handle, "latitudes")
                units = eccodes.codes_get(handle, "units")
                if record.variable == "UGRD":
                    if units != "m s**-1":
                        raise ValueError(f"Unexpected GFS zonal-wind units {units}")
                    polar["u10_ms"] = zonal_mean_wind(values, latitudes)
                elif record.variable == "TMP":
                    if units != "K":
                        raise ValueError(f"Unexpected GFS stratospheric temperature units {units}")
                    polar["temp10_k"] = polar_cap_mean(values, latitudes)
                else:
                    if units not in ("gpm", "m"):
                        raise ValueError(f"Unexpected GFS geopotential-height units {units}")
                    polar["height10_m"] = polar_cap_mean(values, latitudes)
            finally:
                eccodes.codes_release(handle)
        result["polar"] = polar
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(result))
    tmp.replace(cache)
    return result


def fetch_gfs(regions: list[dict] | None = None) -> dict:
    """Return a complete 15-day forecast with real station HDD and CDD normals.

    Raises on an incomplete surface horizon so the application can retain its
    timestamped last successful snapshot. Stratospheric failure is isolated.
    """
    if regions is None:
        from config import REGIONS
        regions = REGIONS
    now = datetime.now(UTC)
    run = discover_latest_run(now)
    calendar = forecast_calendar(run, now)
    return _fetch_run(run, calendar, regions, retrieval_mode="live")


def fetch_archived_gfs(model_run: datetime | str, regions: list[dict] | None = None, comparison_dates=None) -> dict:
    """Retrieve a genuine NOAA archived cycle, with honest retrieval provenance.

    When comparison_dates are supplied, only fully supported dates are returned.
    Archive availability is verified through the same GRIB timestamps and fields
    as live retrievals. Missing old cycles raise rather than substituting data.
    """
    if isinstance(model_run, str):
        model_run = datetime.fromisoformat(model_run.replace("Z", "+00:00"))
    if model_run.tzinfo is None:
        raise ValueError("Archived model run must include its UTC timezone")
    run = model_run.astimezone(UTC)
    if run.hour % 6 or run.minute or run.second or run.microsecond:
        raise ValueError("GFS initialization must be exactly 00, 06, 12, or 18 UTC")
    if run > datetime.now(UTC):
        raise ValueError("An archived GFS run cannot have a future initialization")
    if regions is None:
        from config import REGIONS
        regions = REGIONS
    requested = list(comparison_dates) if comparison_dates is not None else None
    calendar = archive_calendar(run, requested)
    payload = _fetch_run(run, calendar, regions, retrieval_mode="archive")
    available_dates = {date for date, _ in calendar}
    payload["requested_dates"] = sorted({str(date) for date in requested}) if requested is not None else sorted(available_dates)
    payload["excluded_dates"] = sorted(set(payload["requested_dates"]) - available_dates)
    return payload


def _fetch_run(run: datetime, calendar: list[tuple[str, list[int]]], regions: list[dict], retrieval_mode: str) -> dict:
    """Decode one verified run/calendar for both current and archive entry points."""
    required_leads = {lead for _, leads in calendar for lead in leads}
    polar_leads = {leads[2] for _, leads in calendar}
    # The analysis shows the initial state; 12 UTC samples show daily evolution.
    all_leads = required_leads | {0}
    data = {}
    polar_errors = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        normals_task = executor.submit(fetch_normals, regions)
        jobs = {executor.submit(_extract_lead, run, lead, regions, lead in polar_leads or lead == 0): lead for lead in all_leads}
        for task in as_completed(jobs):
            lead = jobs[task]
            try:
                data[lead] = task.result()
            except Exception as error:
                if lead in polar_leads or lead == 0:
                    # Retry surface alone when stratospheric fields are unavailable.
                    polar_errors.append(f"f{lead:03d}: {type(error).__name__}: {error}")
                    if lead in required_leads:
                        data[lead] = _extract_lead(run, lead, regions, False)
                else:
                    raise RuntimeError(f"GFS f{lead:03d} failed: {error}") from error
        normals = normals_task.result()
    rows = []
    for date, leads in calendar:
        for region in regions:
            temperature = float(np.mean([data[lead]["temps_f"][region["name"]] for lead in leads]))
            normal = normals["regions"].get(region["name"], {}).get("days", {}).get(date[5:], {})
            rows.append({"date": date, "region": region["name"], "temp_f": temperature,
                         "hdd": max(65.0 - temperature, 0.0), "normal_hdd": normal.get("normal_hdd"),
                         "cdd": max(temperature - 65.0, 0.0), "normal_cdd": normal.get("normal_cdd"),
                         "normal_temp_f": normal.get("normal_temp_f"), "sample_count": len(leads)})
    polar_rows = [data[lead]["polar"] for lead in sorted(data) if "polar" in data[lead]]
    forecast_polar = [r for r in polar_rows if r["valid_time"] != run.isoformat()]
    reversal = any(r["u10_ms"] < 0 for r in forecast_polar)
    # Do not label a summertime easterly as a sudden stratospheric warming.
    winter = run.month in (11, 12, 1, 2, 3)
    initial_wind = data.get(0, {}).get("polar", {}).get("u10_ms")
    winter_reversal = bool(winter and initial_wind is not None and initial_wind > 0
                           and any(r["u10_ms"] < 0 and datetime.fromisoformat(r["valid_time"]).month in (11, 12, 1, 2, 3)
                                   for r in forecast_polar))
    polar_complete = initial_wind is not None and len(forecast_polar) == len(calendar)
    warnings = list(normals["warnings"])
    if polar_errors:
        warnings.append(f"Stratospheric data incomplete: {len(polar_errors)} samples unavailable; see polar-vortex details.")
    return {
        "rows": rows,
        "model_run": run.isoformat(),
        "observed_at": run.isoformat(),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "retrieval_mode": retrieval_mode,
        "forecast_days": len(calendar),
        "source_url": _url(run, 0) + ".idx",
        "methodology": f"Deterministic NOAA GFS 1° grid, nearest grid point to each representative station. Mean daily 2 m temperature approximated from 00/06/12/18 UTC samples; {len(calendar)} complete UTC calendar days within this run’s 384-hour horizon. HDD=max(65°F−mean temperature,0); CDD=max(mean temperature−65°F,0), each calculated regionally before population weighting. Climatology uses NOAA 1991–2020 station daily HDD and CDD normals, whose observation-day convention differs from UTC forecast days. No ensemble probabilities or extrapolated dates. " + ("Genuine NOAA archive retrieved now; model initialization is historical, retrieval time is current." if retrieval_mode == "archive" else "Latest complete operational run; 15 complete future UTC days."),
        "warnings": warnings,
        "grid_points": data[min(required_leads)]["grid_points"],
        "normals": {"period": "1991–2020", "source_url": normals["source_url"],
                    "stations": {name: {key: value for key, value in station.items() if key != "days"} for name, station in normals["regions"].items()}},
        "polar_vortex": {
            "rows": polar_rows,
            "model_run": run.isoformat(),
            "source_url": _url(run, 0) + ".idx",
            "methodology": "10 hPa zonal wind is the equal-longitude zonal mean at exactly 60°N (m/s). Temperature (K) and geopotential height (geopotential metres) are cosine-latitude-weighted 60–90°N polar-cap means. Initial analysis plus one 12 UTC forecast sample per day. Negative zonal wind denotes easterlies; summer easterlies do not imply a sudden stratospheric warming. No historical climatology, displacement metric, or calibrated cold-outbreak probability is supplied.",
            "warnings": polar_errors,
            "wind_reversal_forecast": reversal,
            "winter_westerly_to_easterly_transition": winter_reversal,
            "winter_monitoring_season": winter,
            "historical_context_available": False,
            "complete": polar_complete,
            "forecast_samples": len(forecast_polar),
            "expected_forecast_samples": len(calendar),
            "interpretation": "Stratospheric coverage is incomplete; the available raw fields cannot exclude a wind transition." if not polar_complete else "Winter westerly-to-easterly transition appears in this deterministic run; investigate persistence and tropospheric coupling." if winter_reversal else ("No winter westerly-to-easterly transition identified in this run." if winter else "Outside November–March monitoring season; raw stratospheric indicators shown without an SSW risk classification."),
        },
    }

"""Keyless EIA Henry Hub spot prices and Lower 48 working-gas storage.

The files are the public XLS downloads linked by EIA's own series pages.
No API key, futures substitution, or generated fallback observations are used.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from io import BytesIO
import math
from typing import Any

import pandas as pd

from data_sources.common import get_bytes


PRICE_URL = "https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls"
STORAGE_URL = "https://www.eia.gov/dnav/ng/hist_xls/NW2_EPG0_SWO_R48_BCFw.xls"
PRICE_PAGE = "https://www.eia.gov/dnav/ng/hist/rngwhhdD.htm"
STORAGE_PAGE = "https://www.eia.gov/dnav/ng/hist/nw2_epg0_swo_r48_bcfw.htm"

METHODOLOGY = (
    "Price is the EIA daily Henry Hub physical spot price in USD/MMBtu, not a "
    "futures quote. Missing holidays and unpublished dates are not filled. "
    "Storage is Lower 48 working gas in Bcf, dated at the reporting week's end. "
    "Weekly change is the difference between consecutive observations exactly "
    "seven days apart; it includes stock reclassifications and is not necessarily "
    "EIA's adjusted net injection/withdrawal. For each storage date, the seasonal "
    "comparison selects the observation closest to the same month/day in each "
    "of the five prior completed calendar years, within seven days and in that "
    "calendar year. Earlier dates win equal-distance ties; February 29 maps to "
    "February 28 in non-leap years. Mean, minimum, and maximum require all five "
    "years; otherwise they remain unavailable. This locally computed benchmark "
    "can differ from EIA's published five-year benchmark. Historical values are "
    "the current revised series, not a reconstruction of what was published then. "
    "Publication timestamps have date precision: midnight UTC represents the "
    "workbook's stated release date, not an asserted time of release."
)


def _as_date(value: Any) -> date | None:
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def parse_series_frame(
    frame: pd.DataFrame, *, series_key: str, value_key: str, unit_text: str
) -> list[dict[str, Any]]:
    """Validate the named series and units before reading actual dated rows."""
    if frame.shape[1] < 2:
        raise ValueError("EIA workbook has fewer than two columns")
    headers = frame.iloc[:5].astype(str)
    if series_key not in set(headers.iloc[:, 1]):
        raise ValueError(f"EIA workbook does not identify expected series {series_key}")
    if not any(unit_text.lower() in cell.lower() for cell in headers.iloc[:, 1]):
        raise ValueError(f"EIA workbook does not identify expected units: {unit_text}")

    values: dict[str, float] = {}
    for raw_date, raw_value in frame.iloc[:, :2].itertuples(index=False, name=None):
        day = _as_date(raw_date)
        if day is None or pd.isna(raw_value):
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            # EIA's explicit unavailable/withheld markers are missing observations.
            if str(raw_value).strip().upper() in {"NA", "N/A", "W", "-", "--", ""}:
                continue
            raise ValueError(f"Invalid EIA value for {day}: {raw_value!r}") from None
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite EIA observation for {day}")
        if value_key == "storage_bcf" and value < 0:
            raise ValueError(f"Negative working-gas storage for {day}")
        key = day.isoformat()
        if key in values and values[key] != value:
            raise ValueError(f"Conflicting EIA observations for {key}")
        values[key] = value
    if not values:
        raise ValueError(f"EIA workbook contains no valid {series_key} observations")
    return [{"date": day, value_key: value} for day, value in sorted(values.items())]


def _read_workbook(
    content: bytes, *, series_key: str, value_key: str, unit_text: str
) -> tuple[list[dict[str, Any]], str | None]:
    with pd.ExcelFile(BytesIO(content), engine="xlrd") as workbook:
        rows = parse_series_frame(
            pd.read_excel(workbook, sheet_name="Data 1", header=None),
            series_key=series_key,
            value_key=value_key,
            unit_text=unit_text,
        )
        contents = pd.read_excel(workbook, sheet_name="Contents", header=None)
    release_date = None
    for row in contents.itertuples(index=False, name=None):
        for index, cell in enumerate(row[:-1]):
            if str(cell).strip().lower() == "release date:":
                parsed = pd.to_datetime(row[index + 1], errors="coerce")
                if not pd.isna(parsed):
                    release_date = parsed.date().isoformat()
    return rows, release_date


def storage_context(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add stock changes and an auditable, lookback-only seasonal benchmark."""
    ordered = sorted(rows, key=lambda row: row["date"])
    years: dict[int, list[tuple[date, float]]] = {}
    for row in ordered:
        day = date.fromisoformat(row["date"])
        years.setdefault(day.year, []).append((day, float(row["storage_bcf"])))

    result = []
    previous: dict[str, Any] | None = None
    for row in ordered:
        day = date.fromisoformat(row["date"])
        value = float(row["storage_bcf"])
        change = None
        if previous and (day - date.fromisoformat(previous["date"])).days == 7:
            change = value - float(previous["storage_bcf"])
        comparison_years = list(range(day.year - 5, day.year))
        matches: list[dict[str, Any]] = []
        for year in comparison_years:
            try:
                anniversary = day.replace(year=year)
            except ValueError:  # Leap day has no exact anniversary in this year.
                anniversary = date(year, 2, 28)
            candidates = years.get(year, [])
            if not candidates:
                continue
            matched_date, matched_value = min(
                candidates, key=lambda item: (abs((item[0] - anniversary).days), item[0])
            )
            if abs((matched_date - anniversary).days) <= 7:
                matches.append({"date": matched_date.isoformat(), "storage_bcf": matched_value})
        sample = [match["storage_bcf"] for match in matches]
        average = sum(sample) / 5 if len(sample) == 5 else None
        result.append({
            "date": day.isoformat(),
            "storage_bcf": value,
            "weekly_change_bcf": change,
            "five_year_avg": average,
            "five_year_min": min(sample) if len(sample) == 5 else None,
            "five_year_max": max(sample) if len(sample) == 5 else None,
            "surplus_bcf": value - average if average is not None else None,
            "surplus_pct": (value / average - 1) * 100 if average else None,
            "comparison_years": comparison_years,
            "comparison_sample_count": len(sample),
            "comparison_observations": matches,
        })
        previous = row
    return result


def _date_timestamp(day: str) -> str:
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), timezone.utc).isoformat()


def fetch_eia() -> dict[str, Any]:
    """Fetch both real series, returning a JSON-serializable atomic snapshot.

    If either series cannot be downloaded/validated, raise so the application can
    retain its complete last successful snapshot instead of erasing valid history.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        price_future = executor.submit(get_bytes, PRICE_URL)
        storage_future = executor.submit(get_bytes, STORAGE_URL)
        price_content = price_future.result()
        storage_content = storage_future.result()
    prices, price_release = _read_workbook(
        price_content,
        series_key="RNGWHHD",
        value_key="price_usd_mmbtu",
        unit_text="Dollars per Million Btu",
    )
    storage, storage_release = _read_workbook(
        storage_content,
        series_key="NW2_EPG0_SWO_R48_BCF",
        value_key="storage_bcf",
        unit_text="Billion Cubic Feet",
    )
    storage = storage_context(storage)
    price_date = prices[-1]["date"]
    storage_date = storage[-1]["date"]
    price_observed_at = _date_timestamp(price_release or price_date)
    storage_observed_at = _date_timestamp(storage_release or storage_date)
    return {
        "observed_at": max(price_observed_at, storage_observed_at),
        "timestamp_precision": "date",
        "source_url": "https://www.eia.gov/naturalgas/",
        "price_source_url": PRICE_PAGE,
        "storage_source_url": STORAGE_PAGE,
        "price_download_url": PRICE_URL,
        "storage_download_url": STORAGE_URL,
        "price_label": "Henry Hub daily spot (not futures)",
        "price_observed_at": price_observed_at,
        "storage_observed_at": storage_observed_at,
        "price_release_date": price_release,
        "storage_release_date": storage_release,
        "price_data_date": price_date,
        "storage_data_date": storage_date,
        "latest_price": prices[-1],
        "latest_storage": storage[-1],
        "price_rows": prices,
        "storage_rows": storage,
        "methodology": METHODOLOGY,
        "warnings": [
            f"{name} release date unavailable; timestamp uses latest observation date."
            for name, published in (("Price", price_release), ("Storage", storage_release))
            if published is None
        ],
    }

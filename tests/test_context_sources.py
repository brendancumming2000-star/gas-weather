"""Deterministic unit/schema tests; tiny fixtures are not production data."""
import json
import base64

import pandas as pd
import pytest

from data_sources.cpc import MAX_OUTLOOK_IMAGE_BYTES, category_definition_from_page, encode_outlook_image, parse_nao_forecasts, parse_nao_observations, parse_outlook, parse_state_categories
from data_sources.nsidc import parse_ice, summarize_ice
from data_sources.rutgers_snow import parse_snow, summarize_snow


def test_nao_revision_matches_valid_date_and_keeps_new_tail_missing():
    raw = """lead,member,time,nao_index,valid_time
2,0,2026-01-01,1,2026-01-03
2,1,2026-01-01,3,2026-01-03
1,0,2026-01-02,0,2026-01-03
1,1,2026-01-02,2,2026-01-03
15,0,2026-01-02,-1,2026-01-17
15,1,2026-01-02,-3,2026-01-17
1,4,2026-01-03,-100,2026-01-04
"""
    result = parse_nao_forecasts(raw)
    assert result["forecast_initialized_at"] == "2026-01-02"
    first, tail = result["forecast"]
    assert first["prior_mean"] == 2
    assert first["mean"] == 1
    assert first["change"] == -1
    assert first["member_count"] == 2
    assert first["p10"] <= first["mean"] <= first["p90"]
    assert tail["prior_mean"] is None
    assert result["forecast_mean_days8_15"] == -2
    json.dumps(result, allow_nan=False)


def test_nao_rejects_invalid_dates_and_changed_schema():
    with pytest.raises(ValueError, match="schema"):
        parse_nao_observations("day,temperature\n1,5")
    frame = parse_nao_observations("year,month,day,nao_index_cdas\n2026,2,30,5\n2026,2,28,0.5\n")
    assert len(frame) == 1
    assert frame.iloc[0].date == pd.Timestamp("2026-02-28")


def test_cpc_separates_temperature_and_precipitation_categories():
    table = """<PRE>6-10 DAY OUTLOOK TABLE
STATE TEMP PCPN
NEW YORK    N    B     MAINE       B    A     MINNESOTA   A    N
8-14 DAY OUTLOOK TABLE
NEW YORK    A    B     MAINE       N    A
LEGEND</PRE>"""
    first = parse_state_categories(table, "6–10 day")
    assert first == [
        {"state": "NEW YORK", "temperature_category": "Near normal"},
        {"state": "MAINE", "temperature_category": "Below normal"},
        {"state": "MINNESOTA", "temperature_category": "Above normal"},
    ]
    second = parse_state_categories(table, "8–14 day")
    assert second[0]["temperature_category"] == "Above normal"
    result = parse_outlook("Valid: January 10 to 14, 2026<br>Updated: 04 Jan 2026", "6–10 day", "https://test.invalid", "https://test.invalid/map.gif", table)
    assert result["observed_at"] == "2026-01-04"
    assert result["valid_period"] == "January 10 to 14, 2026"
    with pytest.raises(ValueError, match="issue date"):
        parse_outlook("No date", "6–10 day", "", "")


def test_snow_unit_conversion_same_week_baseline_and_missing_week():
    rows = [f"{year} 35 1000000" for year in range(1991, 2021)]
    rows += [f"{year} 36 10000000" for year in range(1991, 2021)]
    rows += ["2026 31 500000", "2026 35 1500000", "2026 36 -9999"]
    result = summarize_snow(parse_snow("\n".join(rows)), "2026-08-25", "2026-08-31")
    assert result["observed_at"] == "2026-08-31"
    assert result["current_extent_million_km2"] == 1.5
    assert result["normal_extent_million_km2"] == 1
    assert result["anomaly_million_km2"] == .5
    assert result["percentile"] == 100
    assert result["change_1w"] is None
    assert result["change_4w"] == 1
    assert result["baseline_samples"] == 30
    json.dumps(result, allow_nan=False)


def test_ice_keeps_source_units_aligns_leap_calendar_and_drops_sentinels():
    header = "Year, Month, Day, Extent, Missing, Source Data\nYYYY,MM,DD,10^6 sq km,10^6 sq km,source\n"
    rows = [f"{year},3,1,10,0,source" for year in range(1991, 2021)]
    rows += ["2026,3,1,8,0,source", "2026,3,2,-9999,0,source", "2026,3,3,8,1,source"]
    frame = parse_ice(header + "\n".join(rows))
    assert set(frame.day_of_year) == {61}
    result = summarize_ice(frame)
    assert result["observed_at"] == "2026-03-01"
    assert result["current_extent_million_km2"] == 8
    assert result["normal_extent_million_km2"] == 10
    assert result["anomaly_million_km2"] == -2
    assert result["percentile"] == 0
    assert result["baseline_samples"] == 30
    json.dumps(result, allow_nan=False)


def test_cpc_image_snapshot_preserves_bytes_and_rejects_error_pages_or_oversize():
    gif = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
    encoded = encode_outlook_image(gif)
    assert encoded["image_mime_type"] == "image/gif"
    assert base64.b64decode(encoded["image_base64"]) == gif
    with pytest.raises(ValueError, match="signature"):
        encode_outlook_image(b"<html>A temporary NOAA server error page</html>")
    with pytest.raises(ValueError, match="5 MiB"):
        encode_outlook_image(b"GIF89a" + b"x" * MAX_OUTLOOK_IMAGE_BYTES)


def test_cpc_category_definition_uses_actual_temperature_legend_not_fixed_categories():
    three = "The shading on the temperature map depicts the most favored category, either above-normal (A), below-normal (B), or near-normal (N) with the solid lines giving the probability ( >33%) of this more likely category (above, below, or near)."
    two = "The shading on the temperature map depicts the most favored category, either above-normal (A) or below-normal (B) with the solid lines giving the probability ( >50%) of this more likely category (above or below)."
    assert category_definition_from_page("<p>" + three + "</p>") == three
    assert category_definition_from_page("<p>" + two + "</p>") == two
    assert category_definition_from_page("<!--" + two + "--><p>" + three + "</p>") == three
    assert category_definition_from_page("These are three category outlooks.") == "See official legend"
    assert category_definition_from_page("The shading on the precipitation map depicts the most favored category, above-median or below-median.") == "See official legend"
    page = "Valid: 01 Jan 2026 to 14 Jan 2026<br>Updated: 17 Dec 2025<p>" + three + "</p>"
    result = parse_outlook(page, "Weeks 3–4", "https://example.invalid", "https://example.invalid/map.gif")
    assert result["category_definition"] == three
    assert "median categories" not in result["methodology"]

"""Offline tests use explicit unit fixtures; live app data is always downloaded."""

from datetime import datetime
import math

import pandas as pd
import pytest

from data_sources.eia import parse_series_frame, storage_context


def price_frame(values):
    return pd.DataFrame([
        ["Back to Contents", "Daily prices"],
        ["Sourcekey", "RNGWHHD"],
        ["Date", "Henry Hub Natural Gas Spot Price (Dollars per Million Btu)"],
        *values,
    ])


def parse_price(frame):
    return parse_series_frame(
        frame, series_key="RNGWHHD", value_key="price_usd_mmbtu",
        unit_text="Dollars per Million Btu",
    )


def test_parse_omits_missing_prices_without_filling_holidays():
    frame = price_frame([
        [datetime(2026, 9, 9), 2.81],
        [datetime(2026, 9, 7), math.nan],
        [datetime(2026, 9, 8), "2.90"],
        [datetime(2026, 9, 10), "NA"],
        [pd.NaT, 100],
    ])
    assert parse_price(frame) == [
        {"date": "2026-09-08", "price_usd_mmbtu": 2.90},
        {"date": "2026-09-09", "price_usd_mmbtu": 2.81},
    ]


def test_parser_requires_expected_source_and_units():
    frame = price_frame([[datetime(2026, 9, 9), 2.81]])
    frame.iloc[1, 1] = "WRONG_SERIES"
    with pytest.raises(ValueError, match="expected series"):
        parse_price(frame)
    frame.iloc[1, 1] = "RNGWHHD"
    frame.iloc[2, 1] = "Cents per therm"
    with pytest.raises(ValueError, match="expected units"):
        parse_price(frame)


def test_conflicting_duplicate_and_infinite_values_fail():
    with pytest.raises(ValueError, match="Conflicting"):
        parse_price(price_frame([[datetime(2026, 9, 9), 2.81], [datetime(2026, 9, 9), 2.90]]))
    with pytest.raises(ValueError, match="Nonfinite"):
        parse_price(price_frame([[datetime(2026, 9, 9), float("inf")]]))


def test_seasonal_comparison_excludes_current_year_and_keeps_audit_dates():
    rows = [{"date": f"{year}-09-04", "storage_bcf": 1000 + (year - 2021) * 100}
            for year in range(2021, 2027)]
    rows.append({"date": "2026-08-28", "storage_bcf": 1450})
    latest = storage_context(rows)[-1]
    assert latest["comparison_years"] == [2021, 2022, 2023, 2024, 2025]
    assert latest["five_year_avg"] == 1200
    assert latest["five_year_min"] == 1000
    assert latest["five_year_max"] == 1400
    assert latest["surplus_bcf"] == 300
    assert latest["surplus_pct"] == 25
    assert latest["weekly_change_bcf"] == 50
    assert all(row["date"] < "2026" for row in latest["comparison_observations"])


def test_missing_baseline_year_does_not_silently_use_four_years():
    rows = [{"date": f"{year}-09-04", "storage_bcf": 3000}
            for year in (2021, 2022, 2024, 2025, 2026)]
    latest = storage_context(rows)[-1]
    assert latest["comparison_sample_count"] == 4
    assert latest["five_year_avg"] is None
    assert latest["five_year_min"] is None
    assert latest["surplus_bcf"] is None


def test_gap_does_not_become_a_weekly_injection():
    rows = [{"date": "2026-08-21", "storage_bcf": 3184},
            {"date": "2026-09-04", "storage_bcf": 3254}]
    assert storage_context(rows)[-1]["weekly_change_bcf"] is None


def test_leap_day_and_nearest_date_tie_are_deterministic():
    rows = [{"date": f"{year}-02-28", "storage_bcf": 1500}
            for year in range(2019, 2024)]
    rows.extend([{"date": "2023-02-27", "storage_bcf": 1200},
                 {"date": "2023-03-01", "storage_bcf": 2000},
                 {"date": "2024-02-29", "storage_bcf": 1600}])
    latest = storage_context(rows)[-1]
    assert latest["comparison_sample_count"] == 5
    assert latest["five_year_avg"] == 1500
    assert latest["comparison_observations"][-1]["date"] == "2023-02-28"
    # Without the exact anniversary, equally distant dates choose the earlier one.
    rows = [row for row in rows if row["date"] != "2023-02-28"]
    latest = storage_context(rows)[-1]
    assert latest["comparison_observations"][-1]["date"] == "2023-02-27"


def test_far_away_observation_cannot_stand_in_for_seasonal_week():
    rows = [{"date": f"{year}-09-04", "storage_bcf": 3000}
            for year in range(2021, 2027)]
    rows[0]["date"] = "2021-08-01"
    assert storage_context(rows)[-1]["five_year_avg"] is None

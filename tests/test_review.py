"""Regression checks for missing data, calendar joins, and atomic snapshots."""

import sqlite3

import numpy as np
import pandas as pd
import pytest

from models.hdd import regional_frame, compare_forecasts
from models.gas_demand import demand_impact
from models.signals import signal_table, eastern_risk, vortex_risk
from storage.database import Database


REGIONS = [{"name": "Northeast", "weight": 1.0}]


def observation(day="2026-01-01", temp=35, normal=10):
    return {"date": day, "region": "Northeast", "temp_f": temp, "normal_hdd": normal}


def test_missing_dates_cannot_disappear_during_national_aggregation():
    with pytest.raises(ValueError, match="[Dd]ate"):
        regional_frame([observation(pd.NaT)], REGIONS)


def test_infinite_climatology_is_rejected_instead_of_entering_demand_model():
    with pytest.raises(ValueError, match="[Nn]ormal|finite"):
        regional_frame([observation(normal=np.inf)], REGIONS)


def test_empty_signal_is_unavailable_not_a_neutral_weather_forecast():
    table, score, label, coverage = signal_table()
    assert label == "Unavailable"
    assert coverage == 0
    assert table.Status.eq("Abstains").all()


@pytest.mark.parametrize("days", [
    ["2026-01-01", "2026-01-02"],
    ["2026-01-01", "2026-01-03", "2026-01-05"],
])
def test_eastern_risk_requires_three_consecutive_days(days):
    frame = regional_frame([observation(day) for day in days], REGIONS)
    label, _ = eastern_risk(frame)
    assert label == "Unavailable"


def test_eastern_risk_uses_a_complete_three_day_window_when_one_exists():
    days = ["2026-01-01", "2026-01-03", "2026-01-04", "2026-01-05"]
    frame = regional_frame([observation(day) for day in days], REGIONS)
    label, explanation = eastern_risk(frame)
    assert label == "High"
    assert "+20.0" in explanation


@pytest.mark.parametrize("wind", [float("inf"), float("-inf")])
def test_nonfinite_stratospheric_wind_cannot_produce_a_risk_classification(wind):
    label, _ = vortex_risk({"rows": [{"date": "2026-01-01", "u10_ms": wind}]})
    assert label == "Unavailable"


def test_daily_demand_vector_cannot_silently_be_a_region_by_day_matrix():
    with pytest.raises(ValueError, match="daily|dimensional|vector"):
        demand_impact([[1, 2], [3, 4]], 0.8)


def test_leap_day_comparison_uses_the_exact_valid_date():
    before = regional_frame([
        observation("2024-02-28", temp=0), observation("2024-02-29", temp=35)
    ], REGIONS)
    after = regional_frame([
        observation("2024-02-29", temp=30), observation("2024-03-01", temp=60)
    ], REGIONS)
    compared = compare_forecasts(after, before)
    assert compared.date.tolist() == ["2024-02-29"]
    assert compared.weighted_change.sum() == 5


def test_failed_audit_insert_rolls_back_entire_snapshot_transaction(tmp_path):
    db = Database(tmp_path / "atomic.sqlite3")
    first = db.save("gfs", {"model_run": "2026-01-01T00:00:00Z", "value": 1})
    with db.connect() as connection:
        connection.execute("""
            CREATE TRIGGER reject_attempt BEFORE INSERT ON attempts
            BEGIN SELECT RAISE(ABORT, 'deliberate test failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="deliberate test failure"):
        db.save("gfs", {"model_run": "2026-01-02T00:00:00Z", "value": 2})
    assert len(db.history()) == 1
    assert db.latest("gfs")["id"] == first
    assert db.snapshot(first)["payload"]["value"] == 1


def test_model_cycle_timezones_normalize_before_distinct_run_comparison(tmp_path):
    db = Database(tmp_path / "timezones.sqlite3")
    first = db.save("gfs", {"model_run": "2026-01-01T18:00:00Z"})
    db.save("gfs", {"model_run": "2026-01-02T00:00:00Z"})
    db.save("gfs", {"model_run": "2026-01-01T18:00:00-06:00"})
    assert db.comparison(db.latest("gfs"))["id"] == first


def test_24hour_comparison_tolerance_boundary_is_six_hours(tmp_path):
    db = Database(tmp_path / "boundary.sqlite3")
    old = db.save("gfs", {"model_run": "2026-01-01T00:00:00Z"})
    db.save("gfs", {"model_run": "2026-01-02T06:00:00Z"})
    assert db.comparison(db.latest("gfs"), 24)["id"] == old
    db.save("gfs", {"model_run": "2026-01-02T12:00:00Z"})
    assert db.comparison(db.latest("gfs"), 24) is None
